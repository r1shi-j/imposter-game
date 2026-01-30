from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

players = {}
HOST_PASSWORD = "RJANS"
host_sid = None
game_started = False

@app.route("/")
def home():
    return {"message": "Socket.IO backend alive 🚀"}

@socketio.on("connect")
def handle_connect():
    print("Client connected", request.sid)

@socketio.on("disconnect")
def handle_disconnect():
    global host_sid, game_started

    players.pop(request.sid, None)

    if request.sid == host_sid:
        host_sid = None
        game_started = False

    socketio.emit("players_update", list(players.values()))

@socketio.on("host_login")
def host_login(data):
    global host_sid

    if host_sid is not None:
        socketio.emit(
            "host_login_result",
            {"success": False, "error": "Host already assigned"},
            to=request.sid
        )
        return

    if data.get("password") == HOST_PASSWORD:
        host_sid = request.sid
        socketio.emit("host_login_result", {"success": True}, to=request.sid)
    else:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)

@socketio.on("join")
def handle_join(data):
    name = data["name"]
    players[request.sid] = name

    socketio.emit("players_update", list(players.values()))
    print(f"{name} joined")

@socketio.on("start_game")
def start_game():
    global game_started

    if request.sid != host_sid:
        return  # ignore non-host

    if game_started:
        return

    game_started = True

    impostor_sid = random.choice(list(players.keys()))

    for sid in players:
        role = "impostor" if sid == impostor_sid else "crew"
        socketio.emit("role", {"role": role}, to=sid)

    socketio.emit("game_started")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)