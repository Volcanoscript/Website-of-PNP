from flask import Flask, request, jsonify
from flask_cors import CORS
import datetime

app = Flask(__name__)
CORS(app)

# Example in-memory data store
data = {
    "logs": []
}

@app.route("/")
def home():
    return "Welcome to the PNP Website API! 🚀"

@app.route("/logs", methods=["GET"])
def get_logs():
    return jsonify(data["logs"])

@app.route("/logs", methods=["POST"])
def add_log():
    log_entry = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "message": request.json.get("message", "No message provided")
    }
    data["logs"].insert(0, log_entry)
    return jsonify({"status": "success", "log": log_entry}), 201

if __name__ == "__main__":
    # Render requires binding to 0.0.0.0 with a port
    app.run(host="0.0.0.0", port=5000, debug=True)
