from flask import Flask, request
from flask_cors import CORS
from flask_socketio import SocketIO
import random
import uuid

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")  # async_mode="eventlet"

players = {}  # player_id: {"sid": socket_id, "name": player_name}
HOST_PASSWORD = "RJANS"
host_sid = None
host_player_id = None
game_started = False
session_active = False

@app.route("/")
def home():
    return {"message": "Socket.IO backend alive 🚀"}

@socketio.on("connect")
def handle_connect():
    print("Client connected", request.sid)
    # On connect, no player assigned yet. Player must join to get player_id.

@socketio.on("disconnect")
def handle_disconnect():
    global host_sid, host_player_id, game_started, session_active

    # Find player_id by sid
    disconnected_player_id = None
    for pid, pdata in players.items():
        if pdata["sid"] == request.sid:
            disconnected_player_id = pid
            break

    if disconnected_player_id is not None:
        # Mark player as disconnected by setting sid to None, but keep player in players dict
        players[disconnected_player_id]["sid"] = None
        print(f"Player {players[disconnected_player_id]['name']} disconnected (player_id: {disconnected_player_id})")

        # If host disconnected, keep host_sid None but session_active remains until end_session or host returns
        if host_sid == request.sid:
            host_sid = None

    socketio.emit("players_update", get_active_players())

@socketio.on("host_login")
def host_login(data):
    global host_sid, host_player_id, session_active, game_started

    if host_sid is not None:
        socketio.emit(
            "host_login_result",
            {"success": False, "error": "Host already assigned"},
            to=request.sid
        )
        return

    if data.get("password") == HOST_PASSWORD:
        host_sid = request.sid
        session_active = True
        game_started = False
        # Create a host player_id and add to players if not present
        host_player_id = str(uuid.uuid4())
        players[host_player_id] = {"sid": request.sid, "name": "Host"}
        socketio.emit("host_login_result", {"success": True, "player_id": host_player_id}, to=request.sid)
        socketio.emit("session_active", True)
        socketio.emit("players_update", get_active_players())
    else:
        socketio.emit("host_login_result", {"success": False}, to=request.sid)

@socketio.on("join")
def handle_join(data):
    global session_active

    if not session_active:
        socketio.emit("join_result", {"success": False, "error": "Session not active"}, to=request.sid)
        return

    name = data.get("name")
    if not name:
        socketio.emit("join_result", {"success": False, "error": "Name required"}, to=request.sid)
        return

    # Check if player already joined with this sid (reconnect)
    existing_player_id = None
    for pid, pdata in players.items():
        if pdata["sid"] == request.sid:
            existing_player_id = pid
            break

    if existing_player_id is not None:
        # Already joined, send player_id back
        socketio.emit("join_result", {"success": True, "player_id": existing_player_id}, to=request.sid)
        return

    # Check if player with same name exists but disconnected (refresh-safe)
    rejoin_player_id = None
    for pid, pdata in players.items():
        if pdata["name"] == name and pdata["sid"] is None:
            rejoin_player_id = pid
            break

    if rejoin_player_id:
        players[rejoin_player_id]["sid"] = request.sid
        socketio.emit("join_result", {"success": True, "player_id": rejoin_player_id}, to=request.sid)
        socketio.emit("players_update", get_active_players())
        print(f"Player {name} reconnected with player_id {rejoin_player_id}")
        return

    # New player join
    player_id = str(uuid.uuid4())
    players[player_id] = {"sid": request.sid, "name": name}
    socketio.emit("join_result", {"success": True, "player_id": player_id}, to=request.sid)
    socketio.emit("players_update", get_active_players())
    print(f"{name} joined with player_id {player_id}")

@socketio.on("leave")
def handle_leave(data):
    player_id = data.get("player_id")
    if player_id and player_id in players:
        # Remove player entirely
        player_name = players[player_id]["name"]
        del players[player_id]
        socketio.emit("players_update", get_active_players())
        print(f"Player {player_name} left and removed (player_id: {player_id})")

@socketio.on("kick")
def handle_kick(data):
    global players
    if request.sid != host_sid:
        return  # only host can kick

    player_id = data.get("player_id")
    if player_id and player_id in players:
        kicked_name = players[player_id]["name"]
        # Remove player
        del players[player_id]
        socketio.emit("players_update", get_active_players())
        socketio.emit("kicked", {"player_id": player_id})  # broadcast kick event
        print(f"Player {kicked_name} kicked by host")

@socketio.on("start_game")
def start_game():
    global game_started

    if request.sid != host_sid:
        return  # ignore non-host

    if game_started:
        return

    if len(players) < 2:
        socketio.emit("error", {"error": "Not enough players to start the game"}, to=host_sid)
        return

    game_started = True

    # Choose impostor from players with connected sid (active players)
    active_player_ids = [pid for pid, pdata in players.items() if pdata["sid"]]
    impostor_pid = random.choice(active_player_ids)

    for pid, pdata in players.items():
        role = "impostor" if pid == impostor_pid else "crew"
        if pdata["sid"]:
            socketio.emit("role", {"role": role}, to=pdata["sid"])

    socketio.emit("game_started")

@socketio.on("end_session")
def end_session():
    global session_active, game_started, host_sid, host_player_id, players

    if request.sid != host_sid:
        return  # only host can end session

    session_active = False
    game_started = False
    host_sid = None
    host_player_id = None
    players.clear()

    socketio.emit("session_active", False)
    socketio.emit("players_update", [])
    print("Session ended by host")

def get_active_players():
    # Return list of dicts with player_id and name for players with sid != None
    return [{"player_id": pid, "name": pdata["name"]} for pid, pdata in players.items() if pdata["sid"] is not None]

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)