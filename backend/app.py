from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

players = {}

@app.route("/")
def home():
    return {"message": "Socket.IO backend alive 🚀"}

@socketio.on("connect")
def handle_connect():
    print("A client connected")

@socketio.on("join")
def handle_join(data):
    name = data["name"]
    players[request.sid] = name

    socketio.emit("players_update", list(players.values()))
    print(f"{name} joined")

@socketio.on("disconnect")
def handle_disconnect():
    name = players.pop(request.sid, None)
    socketio.emit("players_update", list(players.values()))

    if name:
        print(f"{name} left")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)