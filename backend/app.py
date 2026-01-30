from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random
import uuid

app = Flask(__name__)
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

HOST_PASSWORD = "RJANS"

players = {}   # player_id -> {sid, name}
host_token = None
host_sid = None
state = "waiting"  # waiting | lobby | game


def get_player_by_sid(sid):
    for pid, p in players.items():
        if p["sid"] == sid:
            return pid
    return None


def emit_state():
    socketio.emit("state_update", {
        "state": state,
        "hostExists": host_token is not None
    })


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
        "hasJoined": has_joined
    }, to=request.sid)

    emit_state()
    emit_players()


@socketio.on("disconnect")
def disconnect():
    for p in players.values():
        if p["sid"] == request.sid:
            p["sid"] = None
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
    if pid in players:
        players[pid]["sid"] = request.sid
        socketio.emit("join_result", {
            "success": True,
            "playerId": pid,
            "state": state,
            "isHost": False,
            "restored": True
        }, to=request.sid)
        emit_players()
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

    emit_players()


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
    global state
    if request.sid != host_sid:
        return
    # host must be a player
    if get_player_by_sid(request.sid) is None:
        return
    # minimum 3 players
    if len(players) < 3:
        return
    state = "game"
    emit_state()


@socketio.on("end_session")
def end_session():
    global players, host_token, host_sid, state
    if request.sid == host_sid:
        players.clear()
        host_token = None
        host_sid = None
        state = "waiting"
        emit_state()
        emit_players()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)