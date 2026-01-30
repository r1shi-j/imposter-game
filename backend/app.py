from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

players = {}
host_sid = None
game_started = False

@app.route("/")
def home():
    return {"message": "Socket.IO backend alive 🚀"}

@socketio.on("connect")
def handle_connect():
    global host_sid
    if host_sid is None:
        host_sid = request.sid
        socketio.emit("host_update", {"host": True})
    else:
        socketio.emit("host_update", {"host": False}, to=request.sid)

    print("Client connected")

@socketio.on("join")
def handle_join(data):
    name = data["name"]
    players[request.sid] = name

    socketio.emit("players_update", list(players.values()))
    print(f"{name} joined")

@socketio.on("disconnect")
def handle_disconnect():
    global host_sid
    name = players.pop(request.sid, None)

    if request.sid == host_sid:
        host_sid = None
        game_started = False

    socketio.emit("players_update", list(players.values()))

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