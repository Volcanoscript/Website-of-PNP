from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Example in-memory storage
data_store = {
    "logs": [],
    "avatars": {}
}

# Root endpoint
@app.route("/")
def home():
    return jsonify({"message": "Server is running!"})

# Admin tool: view logs
@app.route("/admin/logs", methods=["GET"])
def get_logs():
    return jsonify(data_store["logs"])

# Admin tool: add a log entry
@app.route("/admin/logs", methods=["POST"])
def add_log():
    entry = request.json
    data_store["logs"].insert(0, entry)
    return jsonify({"status": "Log added"}), 201

# Avatar upload/live data simulation
@app.route("/avatar/<username>", methods=["POST"])
def update_avatar(username):
    avatar_data = request.json.get("avatar")
    data_store["avatars"][username] = avatar_data
    return jsonify({"status": f"Avatar updated for {username}"}), 200

@app.route("/avatar/<username>", methods=["GET"])
def get_avatar(username):
    avatar_data = data_store["avatars"].get(username)
    if avatar_data:
        return jsonify({"username": username, "avatar": avatar_data})
    return jsonify({"error": "Avatar not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
