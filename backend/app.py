from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random
import uuid
import threading
import time
import json
import os
import bcrypt
from dotenv import load_dotenv

load_dotenv()
HOST_PASSWORD_HASH = os.getenv("HOST_PASSWORD_HASH")

MASTER_WORDS = [
"Sunflower","Fruits","Camera","Liquid","Book","Ocean","Apple","Planet","Baby","Pail",
"Cabbage","Towel","Eyeglasses","Pumpkins","Tree","Breakfast","Stairs","White","Stirrup","Beach",
"Berries","Lemurs","Knife","Dessert","Winter","Flames","Gymnastics","Wedding","Skates","Pipe",
"Peony","Storm","Chocolate","Pineapple","Cloud","Glass","Strawberry","Mushrooms","Broccoli","Sun",
"Straw","Figurines","Scarf","Thought","Wallet","Hedgehog","Window","Vitamins","Spices","Groundnut",
"Equilibrium","Door","Nebula","Banana","Smile","Wheel","Tea","Bear","Nautilus","Tuber",
"Lavender","Snow","Castle","Police","Knowledge","Pizza","Ink","Bed","Selfie","Strings",
"Eclipse","Letter","Tin","Embers","Balloon","Foot","Caviar","Buffet","Bunker","Rock",
"Antennas","Blueberries","Porcelain","Spirit","Apple","Canyon","Taxicab","Reptile","Shadow","Overall",
"Crown","Atmosphere","Insulator","Show","One","Mammal","Pieces","Hay","Reflection","Water",
"Bench","Firewood","Fuel","Wind","Persimmon","Bird","Tarmac","Small","Airport","Baptism",
"Cat","Team","Sheep","Frost","Speed","Instrument","Number","Sloth","Fork","Honeymoon",
"Wheelbarrow","Grooming","Feeding","Geometry","Trail","Lighthouse","Canvas","Relaxation","Silhouette","Slope",
"Pink","Vacation","Peel","Scales","Compass","Time","Net","Cushions","Basket","Memories",
"Plastic","Fish","Diamond","Precious","Cheese","Seahorse","Sack","Finger","Laser","Salt",
"Eyebrow","Syrup","Tomatoes","Buddhism","Sandwich","Juice","Policeman","Sprinkler","Hotel","Hobby",
"Strawberry","Kiss","Feet","Waist","Candle","Trumpet","Pond","Exotic","Landmark","Green",
"Bridge","Clothes","Root","Flatiron","Artichoke","Fountain","Atlas","Christmas","Eiffel","Artist",
"Supplies","Dragonfly","Pendulum","Book","Gift","Vanilla","Egypt","Horse","Two","Mustard",
"Puppy","Purée","Rust","Stripes","Stick","Programming","City","Structure","Heart","Result",
"Dragon","Potter","Predator","Western","Sky","Roof","Indoor","Bite","Spiral","Ornithology",
"Nest","Carbohydrate","Twin","Wings","Grass","Seeds","Chair","Corset","Signs","Fruit",
"Honeycomb","Face","Chain","Sweet","Stunt","Back","Agriculture","Beans","Sauce","Knitting",
"Waves","Fur","Transparency","Aerial","Square","Tail","Ferns","Enclosure","Cake","White",
"Tombstone","Dress","Windy","Poppy","Bread","Turret","Dough","Studio","Tasting","Curls",
"Crossed","Lettuce","Leaves","Duck","Organ","Inheritance","Latitude","Dots","Pollution","Eye",
"Lid","Hand","Game","Toxic","Vinyl","Plate","Damages","Elements","Open","Repair",
"Sushi","Autumn","Sun","Tree","Asian","Kitchen","Tamarind","Poultry","Cage","Chess",
"Headphones","Apartment","Pump","Shoes","Promise","Puppet","Quinoa","Teeth","Pillars","Bear",
"Cap","Baby","Lemon","Floor","Mask","Beverage","Almonds","Vinegar","Prayer","Scavenger",
"Preserve","Butter","Look","Hero","Music","Harvesting","Stroller","Cheese","Bus","Cartoons",
"Shoes","Scent","Ring","Bracelet","Owl","Aisle","Fishing","Tooth","Ivory","Ball",
"Hunter","Camel","Beanie","Wool","Horizon","Empty","Sandal","Gloves","Egg","Balloon",
"Elephant","Chips","Skin","Crystal","Train","Belief","Pasta","Shed","Whiskers","Roof",
"Florist","Kitchen","Stalactite","Apple","Russia","Cherry","Door","Tomato","Packaging","Bakery",
"Temperature","Hair","Souvenirs","Pouring","Fog","Champagne","Fig","Harp","Surf","Rice",
"Archive","Macaron","Insect","Solo","Horse","Ribs","Longship","Rodent","Thinking","England",
"Carrot","Pocket","Gnome","Olive","Capacitor","Farm","Childhood","Copper","Cross","Kitchen",
"Danger","Future","Mane","Gymnastics","Pattern","Probability","Professional","Moon","Hat","Graffiti",
"Cards","Shorts","Space","Star","Music","Takeoff","Surface","Bird","Tradition","Visor"
]
WORDS_FILE = "backend/words.json"
RESET_THRESHOLD = 200

MINIMUM_PLAYERS=3
DEFAULT_DURATION=3
MAX_DURATION=5
DISCONNECT_GRACE_SECONDS = 5

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

players = {}        # player_id -> {sid, name}
player_names = {}   # player_id -> name (persists even after player leaves)
host_token = None
host_sid = None
state = "waiting"   # waiting | lobby | game | voting | leaderboard
roles = {}          # player_id -> "impostor" | "crew"
votes = {}          # voter_pid -> voted_pid
scores = {}         # player_id -> points
leaderboard = []    # list of {name, score} for display
current_word = None
round_end_time = None
timer_thread = None
# Timer controls
round_minutes = DEFAULT_DURATION
round_length_seconds = DEFAULT_DURATION * 60
timer_paused = False
paused_remaining = None


def load_words():
    # If file doesn't exist, create it
    if not os.path.exists(WORDS_FILE):
        reset_words_file()

    with open(WORDS_FILE, "r") as f:
        words = json.load(f)

    # Auto reset if pool too small
    if len(words) < RESET_THRESHOLD:
        reset_words_file()
        words = MASTER_WORDS.copy()

    return words


def reset_words_file():
    with open(WORDS_FILE, "w") as f:
        json.dump(MASTER_WORDS, f)


def remove_word(word):
    words = load_words()

    if word in words:
        words.remove(word)

        with open(WORDS_FILE, "w") as f:
            json.dump(words, f)


def get_random_word():
    words = load_words()

    word = random.choice(words)

    remove_word(word)

    return word


def active_player_ids():
    """Return list of currently connected player IDs."""
    return [pid for pid, p in players.items() if p["sid"] is not None]


def active_players():
    """Return dict of active players only."""
    return {pid: p for pid, p in players.items() if p["sid"] is not None}


def get_player_by_sid(sid):
    for pid, p in players.items():
        if p["sid"] == sid:
            return pid
    return None


def active_player_count():
    # Return number of active players (sid is not None).
    return len([p for p in players.values() if p["sid"] is not None])


def reset_to_lobby(reason=None):
    # Reset the game to lobby without awarding scores. Broadcast reason if provided.
    global state, roles, votes, current_word
    state = "lobby"
    roles.clear()
    votes.clear()
    current_word = None
    if reason:
        socketio.emit("game_ended", {"reason": reason})
    request_state_sync()


def emit_state():
    remaining = 0
    time_remaining = None

    if state == "voting":
        # Only count active players (sid is not None) for voting
        # remaining = active_player_count() - len(votes)
        remaining = len([pid for pid in active_player_ids() if pid not in votes])

    if state == "game" and round_end_time:
        time_remaining = max(0, int(round_end_time - time.time()))

    emit_data = {
        "state": state,
        "hostExists": host_token is not None,
        "roundMinutes": round_minutes,
        "roundLengthSeconds": round_length_seconds,
        "remainingVotes": remaining,
        "timeRemaining": time_remaining,
        "timerPaused": timer_paused,
        "pausedRemaining": paused_remaining,
        "disconnect_time": None
    }

    # Include leaderboard data when in leaderboard state
    if state == "leaderboard":
        emit_data["leaderboard"] = leaderboard
    emit_data["canContinue"] = active_player_count() >= MINIMUM_PLAYERS

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


def enforce_min_players_with_grace():
    now = time.time()

    # If anyone disconnected recently, wait
    for p in players.values():
        if p.get("disconnect_time"):
            if now - p["disconnect_time"] < DISCONNECT_GRACE_SECONDS:
                return  # still waiting for possible rejoin

    if state in ("game", "voting", "leaderboard"):
        if active_player_count() < MINIMUM_PLAYERS:
            reset_to_lobby("Not enough players - game ended")


def start_round_timer():
    global state, round_end_time
    global timer_paused, paused_remaining

    duration = round_length_seconds
    round_end_time = time.time() + duration

    while state == "game":
        if timer_paused:
            # While paused, report pausedRemaining
            socketio.emit("state_update", {
                "state": "game",
                "hostExists": host_token is not None,
                "roundMinutes": round_minutes,
                "timeRemaining": paused_remaining,
                "timerPaused": True,
                "pausedRemaining": paused_remaining
            })
            time.sleep(1)
            continue

        remaining = int(round_end_time - time.time())
        if remaining <= 0:
            break
        socketio.emit("state_update", {
            "state": "game",
            "hostExists": host_token is not None,
            "roundMinutes": round_minutes,
            "timeRemaining": remaining,
            "timerPaused": False
        })
        time.sleep(1)

    if state == "game":
        transition_to_voting()


def transition_to_voting():
    global state, votes
    votes.clear()
    state = "voting"
    request_state_sync()


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
        players[pid].pop("disconnect_time", None)
        has_joined = True
    else:
        has_joined = False

    socketio.emit("identity_update", {
        "isHost": is_host,
        "hasJoined": has_joined,
        "playerId": pid
    }, to=request.sid)

    request_state_sync()


@socketio.on("disconnect")
def disconnect():
    # On disconnect (page refresh, network drop), just mark player as disconnected
    # Don't broadcast leave messages or remove them
    # They can rejoin with same playerId
    pid = get_player_by_sid(request.sid)
    if not pid: return
    players[pid]["sid"] = None
    players[pid]["disconnect_time"] = time.time()
    emit_state()
    # Start a delayed enforcement check after grace period
    if state in ("voting", "leaderboard"): return
    def delayed_enforce():
        time.sleep(DISCONNECT_GRACE_SECONDS)
        # If player is still disconnected, enforce minimum player rules
        player = players.get(pid)
        if player and player.get("sid") is None:
            enforce_min_players_with_grace()
            request_state_sync()

    threading.Thread(target=delayed_enforce, daemon=True).start()


@socketio.on("host_login")
def host_login(data):
    global host_token, host_sid, state

    if host_token is not None:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)
        return

    if not bcrypt.checkpw(data.get("password", "").encode(), HOST_PASSWORD_HASH.encode()):
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
    name = data.get("name")

    # restore existing player
    if pid in players:
        was_disconnected = players[pid]["sid"] is None

        # Update name if they provided a new one and it's valid
        new_name = data.get("name")
        if new_name:
            # Check if name is already taken by ANOTHER active player
            name_taken = False
            for other_pid, player_data in players.items():
                if other_pid != pid and player_data["name"] == new_name and player_data["sid"] is not None:
                    name_taken = True
                    break
            
            if not name_taken:
                players[pid]["name"] = new_name
                player_names[pid] = new_name
        
        players[pid]["sid"] = request.sid
        players[pid].pop("disconnect_time", None)
        socketio.emit("join_result", {
            "success": True,
            "playerId": pid
        }, to=request.sid)

        if was_disconnected:
            socketio.emit(
                "player_joined",
                {"name": players[pid]["name"]},
                skip_sid=request.sid
            )
            
        # If joining mid-game, force crew role
        if state == "game":
            roles[pid] = "crew"
            socketio.emit(
                "role",
                {"role": "crew", "word": current_word},
                to=request.sid
            )
        
        # If in leaderboard state, rebuild it with updated name
        if state == "leaderboard":
            global leaderboard
            leaderboard = [
                {
                    "name": player_names.get(p_id, "Unknown"),
                    "score": scores[p_id]
                }
                for p_id in scores
                if p_id in player_names
            ]
            leaderboard.sort(key=lambda x: x["score"], reverse=True)
        
        request_state_sync()
        enforce_min_players_with_grace()
        return

    if state == "waiting":
        socketio.emit("join_result", {"success": False}, to=request.sid)
        return

    if not name:
        socketio.emit("join_result", {"success": False}, to=request.sid)
        return

    # Check if name is already taken by another active player
    for other_pid, player_data in players.items():
        if other_pid != pid and player_data["name"] == name and player_data["sid"] is not None:
            socketio.emit("join_result", {"success": False}, to=request.sid)
            return

    pid = str(uuid.uuid4())
    players[pid] = {
        "sid": request.sid,
        "name": name
    }
    player_names[pid] = name  # Persist name for this session

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

    # Broadcast join message to all OTHER players
    socketio.emit("player_joined", {"name": name}, skip_sid=request.sid)

    request_state_sync()


@socketio.on("leave")
def leave(data=None):
    global state, roles, votes, current_word
    
    data = data or {}

    # Determine who is being removed
    target_pid = data.get("playerId")

    # Case 1: host removing someone else
    if target_pid:
        if request.sid != host_sid:
            return  # only host can remove others
        if host_sid == players.get(target_pid)["sid"]:
            socketio.emit("host_powerful", {})
            return
        if target_pid not in players:
            return
    else:
        # Case 2: player leaving themselves
        target_pid = get_player_by_sid(request.sid)
        if not target_pid:
            return

    player = players.get(target_pid)
    if not player:
        return

    player_name = player.get("name", "Unknown")
    is_impostor = roles.get(target_pid) == "impostor"
    is_kicked = data.get("playerId") is not None and request.sid == host_sid

    # Notify the removed player if they are connected
    if player["sid"]:
        socketio.emit("leave_success", { "kicked": is_kicked }, to=player["sid"])

    # Remove votes involving this player
    votes.pop(target_pid, None)
    votes = {
        voter: voted
        for voter, voted in votes.items()
        if voted != target_pid
    }
    
    # If impostor leaves during game state, broadcast and reset to lobby
    if is_impostor and state == "game":
        # Remove from players dict since game must reset
        del players[target_pid]
        
        # Reset game state
        state = "lobby"
        roles.clear()
        votes.clear()
        current_word = None
        
        # Broadcast to all OTHER clients that impostor left
        socketio.emit("impostor_left", {"name": player_name, "kicked": is_kicked}, skip_sid=request.sid)
        
        request_state_sync()
    else:
        # Normal leave - keep player in dict but set sid to None
        # This allows them to rejoin with same playerId and merge scores
        players[target_pid]["sid"] = None
        
        # Broadcast appropriate message based on game state
        if state == "game":
            socketio.emit("non_impostor_left", {"name": player_name, "kicked": is_kicked}, skip_sid=request.sid)
        else:
            socketio.emit("player_left", {"name": player_name, "kicked": is_kicked}, skip_sid=request.sid)
        
        request_state_sync()
        enforce_min_players_with_grace()


@socketio.on("return_to_lobby")
def return_to_lobby():
    # Only allow if game is currently showing leaderboard and cannot continue
    if state != "leaderboard":
        return

    if active_player_count() >= MINIMUM_PLAYERS:
        return

    # Do NOT remove player, just reset game state
    reset_to_lobby("Returned to lobby")


@socketio.on("start_game")
def start_game():
    new_game(True)


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


@socketio.on("reveal_results")
def reveal_results():
    global state, scores

    if request.sid != host_sid:
        return

    if state != "voting":
        return

    # Only require votes from active players (sid is not None)
    required_votes = len([
        pid for pid, p in players.items()
        if p["sid"] is not None
    ])

    if len(votes) < required_votes:
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

    # If impostor left the game, we can't score - abort reveal
    if impostor_pid not in players:
        return

    # Score the impostor: +1 for each incorrect vote FROM NON-IMPOSTORS
    incorrect_votes = 0
    for voter_pid, voted_pid in votes.items():
        # Only count votes from players still in the game
        if voter_pid not in players:
            continue
        if str(voter_pid) != str(impostor_pid) and str(voted_pid) != str(impostor_pid):
            incorrect_votes += 1
    scores[impostor_pid] += incorrect_votes

    # Score the crew: +1 if they voted correctly (and they're not the impostor)
    # Count correct votes from non-impostor players and award them
    num_correct = 0
    for voter_pid, voted_pid in votes.items():
        try:
            # Only process if voter still in game
            if voter_pid not in players:
                continue
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

    # Build leaderboard data - include all players with scores, even if they left
    global leaderboard
    leaderboard = [
        {
            "name": player_names.get(pid, "Unknown"),
            "score": scores[pid]
        }
        for pid in scores
        if pid in player_names
    ]
    leaderboard.sort(key=lambda x: x["score"], reverse=True)

    # Number of active non-impostor players (possible voters excluding impostor)
    num_possible = max(0, active_player_count() - 1)  # -1 for the impostor

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


@socketio.on("adjust_time")
def adjust_time(data):
    global round_end_time, timer_paused, paused_remaining
    if request.sid != host_sid:
        return
    if state != "game":
        return
    try:
        delta = int(data.get("delta", 0))
    except Exception:
        return

    MAX_SECONDS = MAX_DURATION * 60

    if timer_paused:
        current = paused_remaining if paused_remaining is not None else 0
        new_remaining = max(0, min(MAX_SECONDS, current + delta))
        paused_remaining = new_remaining
        if new_remaining == 0:
            transition_to_voting()
        else:
            emit_state()
        return

    # not paused
    if round_end_time is None:
        return
    current = max(0, int(round_end_time - time.time()))
    new_remaining = max(0, min(MAX_SECONDS, current + delta))
    if new_remaining == 0:
        transition_to_voting()
        return
    round_end_time = time.time() + new_remaining
    emit_state()


@socketio.on("toggle_pause")
def toggle_pause():
    global timer_paused, paused_remaining, round_end_time
    if request.sid != host_sid:
        return
    if state != "game":
        return

    if not timer_paused:
        # pause now
        if round_end_time is None:
            return
        paused_remaining = max(0, int(round_end_time - time.time()))
        timer_paused = True
        emit_state()
    else:
        # resume
        if paused_remaining is None:
            return
        round_end_time = time.time() + paused_remaining
        timer_paused = False
        paused_remaining = None
        emit_state()


@socketio.on("set_round_minutes")
def set_round_minutes(data):
    global round_minutes
    if request.sid != host_sid:
        return
    mins = int(data.get("minutes", 3))
    # store as minutes for backward compat but also update seconds
    round_minutes = max(1, min(MAX_DURATION, mins))
    global round_length_seconds
    round_length_seconds = round_minutes * 60
    emit_state()


@socketio.on("set_round_seconds")
def set_round_seconds(data):
    global round_length_seconds, round_minutes
    if request.sid != host_sid:
        return
    try:
        secs = int(data.get("seconds", DEFAULT_DURATION * 60))
    except Exception:
        return
    secs = max(0, min(MAX_DURATION * 60, secs))
    round_length_seconds = secs
    # update minutes summary
    round_minutes = max(1, min(MAX_DURATION, int((round_length_seconds + 59) / 60)))
    emit_state()


@socketio.on("end_session")
def end_session():
    global players, player_names, host_token, host_sid, state, roles, round_minutes, current_word, scores, leaderboard
    if request.sid == host_sid:
        players.clear()
        player_names.clear()
        votes.clear()
        host_token = None
        host_sid = None
        state = "waiting"
        roles.clear()
        round_minutes = DEFAULT_DURATION
        current_word = None
        scores.clear()
        leaderboard = []
        request_state_sync()


@socketio.on("next_round")
def next_round():
    new_game(False)


def new_game(is_initial):
    global state, roles, current_word, timer_thread

    if request.sid != host_sid:
        return
    
    if is_initial:
        host_pid = get_player_by_sid(request.sid)
        if host_pid is None:
            return

        if len(players) < MINIMUM_PLAYERS:
            return
    else:
        if state not in ("lobby", "leaderboard"):
            return

    votes.clear()
    state = "game"

    timer_thread = threading.Thread(target=start_round_timer, daemon=True)
    timer_thread.start()

    roles = {}
    current_word = get_random_word()

    # Only pick impostor from active players (sid is not None)
    active_pids = active_player_ids()
    if not active_pids:
        return
    impostor_pid = random.choice(active_pids)

    for pid in players:
        roles[pid] = "impostor" if pid == impostor_pid else "crew"

    if not is_initial:
        # Emit signal that next round has started
        socketio.emit("next_round_started", {})

    for pid, role in roles.items():
        sid = players[pid]["sid"]
        if sid:
            if role == "impostor":
                socketio.emit("role", {"role": "impostor"}, to=sid)
            else:
                socketio.emit("role", {"role": "crew", "word": current_word}, to=sid)
    
    emit_state()


@socketio.on("request_state_sync")
def request_state_sync():
    emit_state()
    emit_players()


if __name__ == "__main__":
    # TODO: add chat feature
    # TODO: add CSS
    socketio.run(app, host="0.0.0.0", port=5001)