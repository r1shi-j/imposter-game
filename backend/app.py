from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

@app.route("/")
def home():
    return {"message": "Socket.IO backend alive 🚀"}

@socketio.on("connect")
def handle_connect():
    print("A client connected")

@socketio.on("disconnect")
def handle_disconnect():
    print("A client disconnected")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)