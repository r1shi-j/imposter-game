from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # allows frontend to talk to backend

@app.route("/")
def home():
    return jsonify(message="Backend is alive 🚀")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)