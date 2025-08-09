from flask import Flask, request, redirect, url_for, session
import requests

app = Flask(__name__)
app.secret_key = "super-secret-key"

# Admin login credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "PNP2025"

# Store players and ranks in memory
players = {}

# PNP rank structure
PNP_RANKS = [
    "Patrolman/Patrolwoman",
    "Police Corporal",
    "Police Staff Sergeant",
    "Police Master Sergeant",
    "Police Senior Master Sergeant",
    "Police Chief Master Sergeant",
    "Police Executive Master Sergeant",
    "Police Lieutenant",
    "Police Captain",
    "Police Major",
    "Police Lieutenant Colonel",
    "Police Colonel",
    "Police Brigadier General",
    "Police Major General",
    "Police Lieutenant General",
    "Police General"
]

# Get Roblox avatar URL
def get_roblox_avatar(username):
    try:
        user_info = requests.get(f"https://api.roblox.com/users/get-by-username?username={username}").json()
        if "Id" in user_info:
            user_id = user_info["Id"]
            avatar_url = f"https://www.roblox.com/headshot-thumbnail/image?userId={user_id}&width=150&height=150&format=png"
            return avatar_url
    except:
        pass
    return "https://upload.wikimedia.org/wikipedia/commons/a/ac/No_image_available.svg"

# Login page
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("dashboard"))
        else:
            return "<h3>Invalid credentials</h3>" + login_form()

    return login_form()

def login_form():
    return """
    <h2>PNP Admin Login</h2>
    <form method='POST'>
        <input type='text' name='username' placeholder='Username' required><br><br>
        <input type='password' name='password' placeholder='Password' required><br><br>
        <button type='submit'>Login</button>
    </form>
    """

# Dashboard
@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))

    html = "<h2>PNP Rank Management</h2>"
    html += "<a href='/logout'>Logout</a><br><br>"
    html += "<form method='POST' action='/add'>"
    html += "Roblox Username: <input type='text' name='username' required> "
    html += "<button type='submit'>Add Player</button></form><br>"

    for name, rank_index in players.items():
        avatar = get_roblox_avatar(name)
        rank = PNP_RANKS[rank_index]
        html += f"<div style='margin-bottom:10px;'>"
        html += f"<img src='{avatar}' alt='Avatar' width='50' height='50'> "
        html += f"<b>{name}</b> - {rank} "
        html += f"<a href='/promote/{name}'>Promote</a> "
        html += f"<a href='/demote/{name}'>Demote</a> "
        html += f"<a href='/delete/{name}'>Delete</a>"
        html += "</div>"

    return html

# Add player
@app.route("/add", methods=["POST"])
def add():
    if not session.get("admin"):
        return redirect(url_for("login"))

    username = request.form.get("username")
    if username not in players:
        players[username] = 0
    return redirect(url_for("dashboard"))

# Promote player
@app.route("/promote/<username>")
def promote(username):
    if not session.get("admin"):
        return redirect(url_for("login"))

    if username in players and players[username] < len(PNP_RANKS) - 1:
        players[username] += 1
    return redirect(url_for("dashboard"))

# Demote player
@app.route("/demote/<username>")
def demote(username):
    if not session.get("admin"):
        return redirect(url_for("login"))

    if username in players and players[username] > 0:
        players[username] -= 1
    return redirect(url_for("dashboard"))

# Delete player
@app.route("/delete/<username>")
def delete(username):
    if not session.get("admin"):
        return redirect(url_for("login"))

    if username in players:
        del players[username]
    return redirect(url_for("dashboard"))

# Logout
@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
