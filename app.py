import os
import requests
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "change-me")

# Full rank list (lowest -> highest)
RANKS = [
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

# In-memory store: username -> {"rank": rank, "avatar": url}
players = {}


# ---------- Roblox helpers ----------
def get_roblox_userid(username):
    """Resolve username -> numeric id using users.roblox.com."""
    if not username:
        return None
    try:
        url = "https://users.roblox.com/v1/usernames/users"
        resp = requests.post(url, json={"usernames": [username], "excludeBannedUsers": False}, timeout=6)
        resp.raise_for_status()
        j = resp.json()
        if j.get("data"):
            return j["data"][0].get("id")
    except Exception:
        return None
    return None


def get_roblox_avatar_url(user_id, size="150x150"):
    """Return headshot avatar URL from thumbnails.roblox.com or None."""
    if not user_id:
        return None
    try:
        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size={size}&format=Png&isCircular=true"
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        j = resp.json()
        if j.get("data") and len(j["data"]) > 0:
            return j["data"][0].get("imageUrl")
    except Exception:
        return None
    return None


# ---------- routes ----------
@app.route("/")
def index():
    # players is a dict: username -> {rank, avatar}
    return render_template("index.html", players=players, ranks=RANKS)


@app.route("/add_player", methods=["POST"])
def add_player():
    username = (request.form.get("username") or "").strip()
    rank = request.form.get("rank") or RANKS[0]
    if not username:
        flash("Username is required.", "error")
        return redirect(url_for("index"))

    if username.lower() in (u.lower() for u in players.keys()):
        flash("Player already exists.", "error")
        return redirect(url_for("index"))

    user_id = get_roblox_userid(username)
    if not user_id:
        flash("Roblox user not found (check username).", "error")
        return redirect(url_for("index"))

    avatar = get_roblox_avatar_url(user_id)
    players[username] = {"rank": rank, "avatar": avatar}
    flash(f"Added {username} as {rank}.", "success")
    return redirect(url_for("index"))


@app.route("/promote", methods=["POST"])
def promote():
    username = (request.form.get("username") or "").strip()
    if username not in players:
        flash("Player not found.", "error")
        return redirect(url_for("index"))
    cur = players[username]["rank"]
    try:
        idx = RANKS.index(cur)
    except ValueError:
        idx = 0
    # promote toward higher index? You defined lowest->highest; promote moves up the list index+1
    if idx < len(RANKS) - 1:
        players[username]["rank"] = RANKS[idx + 1]
        flash(f"Promoted {username} to {players[username]['rank']}.", "success")
    else:
        flash("Already at highest rank.", "info")
    return redirect(url_for("index"))


@app.route("/demote", methods=["POST"])
def demote():
    username = (request.form.get("username") or "").strip()
    if username not in players:
        flash("Player not found.", "error")
        return redirect(url_for("index"))
    cur = players[username]["rank"]
    try:
        idx = RANKS.index(cur)
    except ValueError:
        idx = 0
    if idx > 0:
        players[username]["rank"] = RANKS[idx - 1]
        flash(f"Demoted {username} to {players[username]['rank']}.", "success")
    else:
        flash("Already at lowest rank.", "info")
    return redirect(url_for("index"))


@app.route("/delete", methods=["POST"])
def delete():
    username = (request.form.get("username") or "").strip()
    if username in players:
        del players[username]
        flash(f"Deleted {username}.", "success")
    else:
        flash("Player not found.", "error")
    return redirect(url_for("index"))


# run
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    # app.run must be last line
    app.run(host="0.0.0.0", port=port, debug=False)
