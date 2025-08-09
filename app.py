import os
import uuid
import datetime
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# PNP Rank hierarchy (highest to lowest)
PNP_RANKS = [
    "Police General",
    "Police Lieutenant General",
    "Police Major General",
    "Police Brigadier General",
    "Police Colonel",
    "Police Lieutenant Colonel",
    "Police Major",
    "Police Captain",
    "Police Lieutenant",
    "Police Executive Master Sergeant",
    "Police Chief Master Sergeant",
    "Police Senior Master Sergeant",
    "Police Master Sergeant",
    "Police Staff Sergeant",
    "Police Corporal",
    "Patrolman"
]

# Initial sample roster
roster = []

# Function to get Roblox avatar URL from username
def get_roblox_avatar(username):
    try:
        # Get user ID from Roblox API
        user_res = requests.get(f"https://api.roblox.com/users/get-by-username?username={username}")
        user_data = user_res.json()
        if "Id" not in user_data or user_data["Id"] == -1:
            return ""

        user_id = user_data["Id"]

        # Get avatar thumbnail
        avatar_res = requests.get(
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
            f"?userIds={user_id}&size=150x150&format=Png&isCircular=false"
        )
        avatar_data = avatar_res.json()
        if avatar_data.get("data") and len(avatar_data["data"]) > 0:
            return avatar_data["data"][0]["imageUrl"]
        return ""
    except Exception:
        return ""

@app.route("/")
def home():
    return jsonify({"message": "PNP Roster API Running"}), 200

@app.route("/roster", methods=["GET"])
def get_roster():
    sorted_roster = sorted(
        roster,
        key=lambda x: PNP_RANKS.index(x["rank"]) if x["rank"] in PNP_RANKS else len(PNP_RANKS)
    )
    for idx, officer in enumerate(sorted_roster, start=1):
        officer["position"] = idx
    return jsonify(sorted_roster), 200

@app.route("/roster", methods=["POST"])
def add_officer():
    data = request.json
    if not data or "username" not in data or "rank" not in data:
        return jsonify({"error": "Username and rank are required"}), 400
    if data["rank"] not in PNP_RANKS:
        return jsonify({"error": "Invalid rank"}), 400

    avatar_url = get_roblox_avatar(data["username"])

    new_officer = {
        "id": str(uuid.uuid4()),
        "username": data["username"],
        "display_name": data.get("display_name", ""),
        "rank": data["rank"],
        "avatar_url": avatar_url,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat()
    }
    roster.append(new_officer)
    return jsonify(new_officer), 201

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
