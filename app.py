from flask import Flask, render_template_string, request, redirect, url_for, session
import json
import requests
import os

app = Flask(__name__)
app.secret_key = "super_secret_key_here"

DATA_FILE = "data.json"
ADMIN_PASSWORD = "PNP2025"

# HTML Template
template = """
<!DOCTYPE html>
<html>
<head>
    <title>Probisya Roleplay City</title>
    <style>
        body { font-family: Arial; background: #111; color: white; text-align: center; }
        .member { display: inline-block; background: #222; padding: 15px; margin: 10px; border-radius: 10px; }
        img { border-radius: 50%; }
        input, button { padding: 5px; margin: 5px; }
    </style>
</head>
<body>
    {% if not session.get('admin') %}
        <h2>Admin Login</h2>
        <form method="POST" action="{{ url_for('login') }}">
            <input type="password" name="password" placeholder="Enter password" required>
            <button type="submit">Login</button>
        </form>
    {% else %}
        <h1>Probisya Roleplay City — Roster</h1>
        <form method="POST" action="{{ url_for('add_member') }}">
            <input type="text" name="username" placeholder="Roblox username" required>
            <input type="text" name="rank" placeholder="Rank" required>
            <button type="submit">Add</button>
        </form>
        <div>
            {% for member in roster %}
                <div class="member">
                    <img src="{{ member.avatar }}" width="150" height="150"><br>
                    <b>{{ member.rank }}</b><br>
                    {{ member.username }}<br>
                    <a href="{{ url_for('delete_member', username=member.username) }}" style="color:red;">Delete</a>
                </div>
            {% endfor %}
        </div>
    {% endif %}
</body>
</html>
"""

# Load data
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump([], f)
    with open(DATA_FILE) as f:
        return json.load(f)

# Save data
def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Get Roblox userId
def get_user_id(username):
    url = f"https://api.roblox.com/users/get-by-username?username={username}"
    r = requests.get(url)
    data = r.json()
    return data.get("Id")

# Get Roblox avatar
def get_avatar(user_id):
    return f"https://www.roblox.com/headshot-thumbnail/image?userId={user_id}&width=150&height=150&format=png"

@app.route("/", methods=["GET"])
def home():
    roster = load_data()
    return render_template_string(template, roster=roster, session=session)

@app.route("/login", methods=["POST"])
def login():
    if request.form["password"] == ADMIN_PASSWORD:
        session["admin"] = True
    return redirect(url_for("home"))

@app.route("/add", methods=["POST"])
def add_member():
    if not session.get("admin"):
        return redirect(url_for("home"))

    username = request.form["username"]
    rank = request.form["rank"]

    user_id = get_user_id(username)
    if user_id:
        avatar = get_avatar(user_id)
        roster = load_data()
        roster.append({"username": username, "rank": rank, "avatar": avatar})
        save_data(roster)

    return redirect(url_for("home"))

@app.route("/delete/<username>")
def delete_member(username):
    if not session.get("admin"):
        return redirect(url_for("home"))

    roster = load_data()
    roster = [m for m in roster if m["username"] != username]
    save_data(roster)
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
