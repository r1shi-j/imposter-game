from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random
import uuid

app = Flask(__name__)
CORS(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

HOST_PASSWORD = "RJANS"

# ---- Global state ----
players = {}  # player_id -> { "sid": str | None, "name": str }
host_player_id = None   # persistent host identity
session_state = "waiting"  # waiting | lobby | game


@app.route("/")
def home():
    return {"message": "Socket.IO backend alive 🚀"}


# ---- Helpers ----
def emit_state():
    socketio.emit("state_update", {"state": session_state})


def emit_players():
    socketio.emit("players_update", {
        "players": [
            {"player_id": pid, "name": p["name"]}
            for pid, p in players.items()
            if p["sid"] is not None
        ]
    })


def reset_session():
    global players, host_player_id, session_state
    players.clear()
    host_player_id = None
    session_state = "waiting"
    emit_state()
    emit_players()


# ---- Socket events ----
@socketio.on("connect")
def handle_connect():
    emit_state()
    emit_players()


@socketio.on("disconnect")
def handle_disconnect():
    for pid, pdata in players.items():
        if pdata["sid"] == request.sid:
            pdata["sid"] = None
            print(f"{pdata['name']} disconnected")
            break
    emit_players()


@socketio.on("host_login")
def host_login(data):
    global host_player_id, session_state

    if host_player_id is not None:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)
        return

    if data.get("password") != HOST_PASSWORD:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)
        return

    host_player_id = str(uuid.uuid4())
    players[host_player_id] = {
        "sid": request.sid,
        "name": "Host"
    }

    session_state = "lobby"

    socketio.emit(
        "host_login_result",
        {"success": True, "player_id": host_player_id},
        to=request.sid
    )

    emit_state()
    emit_players()


@socketio.on("reclaim_host")
def reclaim_host(data):
    global host_player_id

    pid = data.get("playerId")
    if pid and pid == host_player_id and pid in players:
        players[pid]["sid"] = request.sid
        socketio.emit("host_login_result", {"success": True}, to=request.sid)
        emit_players()


@socketio.on("join")
def join(data):
    if session_state == "waiting":
        socketio.emit("join_result", {"success": False}, to=request.sid)
        return

    name = data.get("name")
    if not name:
        return

    # Reconnect by name
    for pid, pdata in players.items():
        if pdata["name"] == name and pdata["sid"] is None:
            pdata["sid"] = request.sid
            socketio.emit("join_result", {"success": True, "player_id": pid}, to=request.sid)
            emit_players()
            return

    # New player
    pid = str(uuid.uuid4())
    players[pid] = {"sid": request.sid, "name": name}
    socketio.emit("join_result", {"success": True, "player_id": pid}, to=request.sid)
    emit_players()


@socketio.on("leave")
def leave(data):
    pid = data.get("player_id")
    if pid in players:
        del players[pid]
        emit_players()


@socketio.on("kick")
def kick(data):
    if host_player_id is None or players.get(host_player_id, {}).get("sid") != request.sid:
        return

    pid = data.get("player_id")
    if pid in players:
        del players[pid]
        socketio.emit("kicked", {"player_id": pid})
        emit_players()


@socketio.on("start_game")
def start_game():
    global session_state

    if host_player_id is None or players.get(host_player_id, {}).get("sid") != request.sid:
        return

    if session_state != "lobby":
        return

    active_players = [
        pid for pid, p in players.items() if p["sid"] is not None
    ]

    if len(active_players) < 2:
        return

    session_state = "game"
    emit_state()

    impostor = random.choice(active_players)

    for pid, pdata in players.items():
        if pdata["sid"] is None:
            continue
        role = "impostor" if pid == impostor else "crew"
        socketio.emit("role", {"role": role}, to=pdata["sid"])


@socketio.on("end_session")
def end_session():
    if host_player_id is None or players.get(host_player_id, {}).get("sid") != request.sid:
        return
    reset_session()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)