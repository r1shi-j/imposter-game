from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random
import uuid
import threading
import time

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

HOST_PASSWORD = "1"
MINIMUM_PLAYERS=2
DEFAULT_DURATION=3
WORDS = ["suntanning", "airport", "classroom"]

players = {}   # player_id -> {sid, name}
host_token = None
host_sid = None
state = "waiting"  # waiting | lobby | game | voting | leaderboard
round_minutes = DEFAULT_DURATION
roles = {}  # player_id -> "impostor" | "crew"
votes = {}        # voter_pid -> voted_pid
scores = {}       # player_id -> points
leaderboard = []  # list of {name, score} for display
current_word = None
round_end_time = None
timer_thread = None


def get_player_by_sid(sid):
    for pid, p in players.items():
        if p["sid"] == sid:
            return pid
    return None


def emit_state():
    remaining = 0
    time_remaining = None

    if state == "voting":
        remaining = len(players) - len(votes)

    if state == "game" and round_end_time:
        time_remaining = max(0, int(round_end_time - time.time()))

    emit_data = {
        "state": state,
        "hostExists": host_token is not None,
        "roundMinutes": round_minutes,
        "remainingVotes": remaining,
        "timeRemaining": time_remaining
    }

    # Include leaderboard data when in leaderboard state
    if state == "leaderboard":
        emit_data["leaderboard"] = leaderboard

    socketio.emit("state_update", emit_data)


def emit_players():
    socketio.emit("players_update", {
        "players": [
            {
                "player_id": pid,
                "name": p["name"]
            }
            for pid, p in players.items()
            if p["sid"] is not None and p["name"] is not None
        ]
    })


# --- Timer logic ---
def start_round_timer():
    global state, round_end_time

    duration = round_minutes * 60
    round_end_time = time.time() + duration

    while state == "game":
        remaining = int(round_end_time - time.time())
        if remaining <= 0:
            break
        socketio.emit("state_update", {
            "state": "game",
            "hostExists": host_token is not None,
            "roundMinutes": round_minutes,
            "timeRemaining": remaining
        })
        time.sleep(1)

    if state == "game":
        transition_to_voting()


def transition_to_voting():
    global state, votes
    votes.clear()
    state = "voting"
    emit_state()
    emit_players()   # <-- CRITICAL: force player list refresh for voting


@socketio.on("connect")
def connect():
    token = request.args.get("token")
    pid = request.args.get("playerId")

    is_host = token is not None and token == host_token

    if is_host:
        global host_sid
        host_sid = request.sid

    if pid in players:
        players[pid]["sid"] = request.sid
        has_joined = True
    else:
        has_joined = False

    socketio.emit("identity_update", {
        "isHost": is_host,
        "hasJoined": has_joined,
        "playerId": pid
    }, to=request.sid)

    emit_state()
    emit_players()


@socketio.on("disconnect")
def disconnect():
    for p in players.values():
        if p["sid"] == request.sid:
            p["sid"] = None
    pid = get_player_by_sid(request.sid)
    if pid and pid in votes:
        del votes[pid]
    emit_players()


@socketio.on("host_login")
def host_login(data):
    global host_token, host_sid, state

    if host_token is not None:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)
        return

    if data.get("password") != HOST_PASSWORD:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)
        return

    host_token = str(uuid.uuid4())
    host_sid = request.sid
    state = "lobby"

    socketio.emit("host_login_result", {
        "success": True,
        "token": host_token
    }, to=request.sid)

    emit_state()


@socketio.on("join")
def join(data):
    global players

    pid = data.get("playerId")

    # restore existing player
    if pid in players:
        players[pid]["sid"] = request.sid
        socketio.emit("join_result", {
            "success": True,
            "playerId": pid
        }, to=request.sid)
        # If joining mid-game, force crew role
        if state == "game":
            roles[pid] = "crew"
            socketio.emit(
                "role",
                {"role": "crew", "word": current_word},
                to=request.sid
            )
        emit_players()
        emit_state()
        return

    if state == "waiting":
        socketio.emit("join_result", {"success": False}, to=request.sid)
        return

    name = data.get("name")

    if not name:
        socketio.emit("join_result", {"success": False}, to=request.sid)
        return

    pid = str(uuid.uuid4())
    players[pid] = {
        "sid": request.sid,
        "name": name
    }

    socketio.emit("join_result", {
        "success": True,
        "playerId": pid,
        "state": state,
        "isHost": False
    }, to=request.sid)

    # If joining mid-game, force crew role
    if state == "game":
        roles[pid] = "crew"
        socketio.emit(
            "role",
            {"role": "crew", "word": current_word},
            to=request.sid
        )

    emit_players()
    emit_state()


@socketio.on("leave")
def leave():
    # Find player by sid and remove
    pid_to_remove = None
    for pid, p in players.items():
        if p["sid"] == request.sid:
            pid_to_remove = pid
            break
    if pid_to_remove:
        del players[pid_to_remove]
        emit_players()
        emit_state()


@socketio.on("start_game")
def start_game():
    global state, roles, current_word

    if request.sid != host_sid:
        return

    host_pid = get_player_by_sid(request.sid)
    if host_pid is None:
        return

    if len(players) < MINIMUM_PLAYERS:
        return

    votes.clear()
    state = "game"
    emit_state()

    global timer_thread
    timer_thread = threading.Thread(target=start_round_timer, daemon=True)
    timer_thread.start()

    roles = {}
    current_word = random.choice(WORDS)

    impostor_pid = random.choice(list(players.keys()))

    for pid in players:
        roles[pid] = "impostor" if pid == impostor_pid else "crew"

    for pid, role in roles.items():
        sid = players[pid]["sid"]
        if sid:
            if role == "impostor":
                socketio.emit("role", {"role": "impostor"}, to=sid)
            else:
                socketio.emit(
                    "role",
                    {"role": "crew", "word": current_word},
                    to=sid
                )


# Voting phase logic
@socketio.on("cast_vote")
def cast_vote(data):
    global votes

    if state != "voting":
        return

    voter_pid = get_player_by_sid(request.sid)
    voted_pid = data.get("voted")

    if voter_pid is None:
        return

    # cannot vote for yourself
    if voter_pid == voted_pid:
        return

    # overwrite allowed
    votes[voter_pid] = voted_pid
    emit_state()


def compute_results():
    # count votes
    tally = {}
    for voted in votes.values():
        tally[voted] = tally.get(voted, 0) + 1

    if not tally:
        return None

    voted_out = max(tally.items(), key=lambda x: x[1])[0]

    impostor_pid = None
    for pid, role in roles.items():
        if role == "impostor":
            impostor_pid = pid
            break

    return {
        "votedOut": voted_out,
        "impostor": impostor_pid,
        "correct": voted_out == impostor_pid
    }


@socketio.on("reveal_results")
def reveal_results():
    global state, scores

    if request.sid != host_sid:
        return

    if state != "voting":
        return

    if len(votes) < len(players):
        return

    result = compute_results()
    if not result:
        return

    impostor_pid = result["impostor"]
    voted_out_pid = result["votedOut"]

    # Initialize scores if needed
    for pid in players:
        if pid not in scores:
            scores[pid] = 0

    # Score the impostor: +1 for each incorrect vote FROM NON-IMPOSTORS
    incorrect_votes = 0
    for voter_pid, voted_pid in votes.items():
        if str(voter_pid) != str(impostor_pid) and str(voted_pid) != str(impostor_pid):
            incorrect_votes += 1
    scores[impostor_pid] += incorrect_votes

    # Score the crew: +1 if they voted correctly (and they're not the impostor)
    # Count correct votes from non-impostor players and award them
    num_correct = 0
    for voter_pid, voted_pid in votes.items():
        try:
            if str(voter_pid) == str(impostor_pid):
                # ignore impostor's own vote for scoring
                continue
            if str(voted_pid) == str(impostor_pid):
                # only count if voter is a known player
                if voter_pid in players:
                    scores[voter_pid] += 1
                    num_correct += 1
        except Exception:
            continue

    # Build leaderboard data
    global leaderboard
    leaderboard = [
        {
            "name": players[pid]["name"],
            "score": scores[pid]
        }
        for pid in players
        if pid in scores
    ]
    leaderboard.sort(key=lambda x: x["score"], reverse=True)

    # Number of non-impostor players (possible voters excluding impostor)
    num_possible = sum(1 for pid in players if str(pid) != str(impostor_pid))

    # Debug: log votes and counts
    print(f"reveal_results: votes={votes}, impostor={impostor_pid}, num_correct={num_correct}, num_possible={num_possible}")

    socketio.emit("round_result", {
        "votedOut": players[voted_out_pid]["name"],
        "votedOutId": voted_out_pid,
        "impostor": players[impostor_pid]["name"],
        "impostorId": impostor_pid,
        "correct": result["correct"],
        "leaderboard": leaderboard,
        "numCorrect": num_correct,
        "numPossible": num_possible
    })

    state = "leaderboard"
    emit_state()


@socketio.on("set_round_minutes")
def set_round_minutes(data):
    global round_minutes
    if request.sid != host_sid:
        return
    mins = int(data.get("minutes", 3))
    round_minutes = max(1, min(5, mins))
    emit_state()


@socketio.on("end_session")
def end_session():
    global players, host_token, host_sid, state, roles, round_minutes, current_word, scores, leaderboard
    if request.sid == host_sid:
        players.clear()
        votes.clear()
        host_token = None
        host_sid = None
        state = "waiting"
        roles.clear()
        round_minutes = DEFAULT_DURATION
        current_word = None
        scores.clear()
        leaderboard = []
        emit_state()
        emit_players()


@socketio.on("next_round")
def next_round():
    global state, roles, current_word

    if request.sid != host_sid:
        return

    if state not in ("lobby", "leaderboard"):
        return

    votes.clear()
    state = "game"
    emit_state()

    global timer_thread
    timer_thread = threading.Thread(target=start_round_timer, daemon=True)
    timer_thread.start()

    roles = {}
    current_word = random.choice(WORDS)

    impostor_pid = random.choice(list(players.keys()))

    for pid in players:
        roles[pid] = "impostor" if pid == impostor_pid else "crew"

    # Emit signal that next round has started
    socketio.emit("next_round_started", {})

    for pid, role in roles.items():
        sid = players[pid]["sid"]
        if sid:
            if role == "impostor":
                socketio.emit("role", {"role": "impostor"}, to=sid)
            else:
                socketio.emit(
                    "role",
                    {"role": "crew", "word": current_word},
                    to=sid
                )


@socketio.on("request_state_sync")
def request_state_sync():
    emit_state()
    emit_players()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)