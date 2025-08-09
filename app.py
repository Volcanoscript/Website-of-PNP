from flask import Flask, request, redirect, url_for, render_template_string
import requests

app = Flask(__name__)

# Simple in-memory rank storage
users = {}
ADMIN_PASSWORD = "PNP2025"

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>PNP Admin Panel</title>
</head>
<body style="font-family: Arial; text-align: center;">
    <h1>PNP Admin Panel</h1>

    {% if not logged_in %}
        <form method="post" action="/login">
            <input type="password" name="password" placeholder="Enter Admin Password">
            <button type="submit">Login</button>
        </form>
    {% else %}
        <h2>Welcome, Admin!</h2>
        <form method="post" action="/add_user">
            <input type="text" name="username" placeholder="Roblox Username" required>
            <select name="rank">
                <option value="Patrol">Patrol</option>
                <option value="Sergeant">Sergeant</option>
                <option value="Captain">Captain</option>
            </select>
            <button type="submit">Add User</button>
        </form>
        
        <h3>Current Members</h3>
        <table border="1" style="margin: auto;">
            <tr><th>Avatar</th><th>Username</th><th>Rank</th><th>Actions</th></tr>
            {% for username, rank in users.items() %}
            <tr>
                <td><img src="{{ avatars[username] }}" width="100"></td>
                <td>{{ username }}</td>
                <td>{{ rank }}</td>
                <td>
                    <a href="/promote/{{ username }}">Promote</a> | 
                    <a href="/demote/{{ username }}">Demote</a>
                </td>
            </tr>
            {% endfor %}
        </table>
        <br>
        <a href="/logout">Logout</a>
    {% endif %}
</body>
</html>
"""

# Session simulation
session_state = {"logged_in": False}

def get_roblox_avatar(username):
    try:
        resp = requests.get(f"https://api.roblox.com/users/get-by-username?username={username}").json()
        if "Id" in resp:
            user_id = resp["Id"]
            avatar_url = f"https://www.roblox.com/headshot-thumbnail/image?userId={user_id}&width=150&height=150&format=png"
            return avatar_url
    except:
        pass
    return "https://via.placeholder.com/150"

@app.route("/")
def home():
    avatars = {u: get_roblox_avatar(u) for u in users}
    return render_template_string(HTML_TEMPLATE, logged_in=session_state["logged_in"], users=users, avatars=avatars)

@app.route("/login", methods=["POST"])
def login():
    if request.form.get("password") == ADMIN_PASSWORD:
        session_state["logged_in"] = True
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session_state["logged_in"] = False
    return redirect(url_for("home"))

@app.route("/add_user", methods=["POST"])
def add_user():
    if session_state["logged_in"]:
        username = request.form.get("username")
        rank = request.form.get("rank")
        if username:
            users[username] = rank
    return redirect(url_for("home"))

@app.route("/promote/<username>")
def promote(username):
    ranks = ["Patrol", "Sergeant", "Captain"]
    if username in users:
        current_rank = users[username]
        if current_rank in ranks and ranks.index(current_rank) < len(ranks) - 1:
            users[username] = ranks[ranks.index(current_rank) + 1]
    return redirect(url_for("home"))

@app.route("/demote/<username>")
def demote(username):
    ranks = ["Patrol", "Sergeant", "Captain"]
    if username in users:
        current_rank = users[username]
        if current_rank in ranks and ranks.index(current_rank) > 0:
            users[username] = ranks[ranks.index(current_rank) - 1]
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
