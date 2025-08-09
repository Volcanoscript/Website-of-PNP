import os
import json
import time
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path

import requests
from flask import (
    Flask, render_template, request, redirect, url_for, session, jsonify, abort, flash
)

# -------------------------
# CONFIG
# -------------------------
APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "data.json"
AVATAR_TTL = 60 * 60  # 1 hour
AVATAR_SIZE = os.getenv("AVATAR_SIZE", "150x150")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "PNP2025")
SECRET_KEY = os.getenv("SECRET_KEY", None) or os.urandom(24)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY

# -------------------------
# PNP Rank Order (lowest -> highest)
# The index is used in stored members as rank_index.
# -------------------------
PNP_RANKS = [
    # PNCOs (lower)
    "Patrolman/Patrolwoman",
    "Police Corporal",
    "Police Staff Sergeant",
    "Police Master Sergeant",
    "Police Senior Master Sergeant",
    "Police Chief Master Sergeant",
    "Police Executive Master Sergeant",
    # PCOs (higher)
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

# -------------------------
# Simple file-based storage
# -------------------------
LOCK = threading.Lock()


def read_data():
    if not DATA_FILE.exists():
        # create with empty structure
        DATA_FILE.write_text(json.dumps({"members": [], "logs": []}, indent=2))
    with LOCK:
        return json.loads(DATA_FILE.read_text())


def write_data(data):
    with LOCK:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(DATA_FILE)


# -------------------------
# Avatar cache (in-memory)
# -------------------------
avatar_cache = {}
avatar_lock = threading.Lock()


def avatar_get(username):
    key = (username or "").lower()
    now = time.time()
    with avatar_lock:
        v = avatar_cache.get(key)
        if v and v["expiry"] > now:
            return v["url"]
    return None


def avatar_set(username, url):
    key = (username or "").lower()
    with avatar_lock:
        avatar_cache[key] = {"url": url, "expiry": time.time() + AVATAR_TTL}


def avatar_cleaner():
    while True:
        time.sleep(300)
        now = time.time()
        with avatar_lock:
            remove = [k for k, v in avatar_cache.items() if v["expiry"] <= now]
            for k in remove:
                del avatar_cache[k]


threading.Thread(target=avatar_cleaner, daemon=True).start()


# -------------------------
# Roblox helpers
# -------------------------
def get_roblox_userid(username):
    """Resolve Roblox username -> userId (int) or None."""
    if not username:
        return None
    try:
        url = "https://users.roblox.com/v1/usernames/users"
        resp = requests.post(url, json={"usernames": [username], "excludeBannedUsers": False}, timeout=6)
        resp.raise_for_status()
        j = resp.json()
        if j.get("data") and len(j["data"]) > 0:
            return j["data"][0].get("id")
    except Exception:
        return None
    return None


def get_roblox_avatar(username):
    """Return live avatar image URL for username or None."""
    # check cache
    c = avatar_get(username)
    if c is not None:
        return c

    uid = get_roblox_userid(username)
    if not uid:
        avatar_set(username, None)
        return None

    # Avatar thumbnail endpoint
    url = (
        f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
        f"?userIds={uid}&size={AVATAR_SIZE}&format=Png&isCircular=true"
    )
    # No need to call thumbnails API for imageUrl field - thumbnails endpoint returns JSON
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        j = resp.json()
        if j.get("data") and len(j["data"]) > 0:
            img = j["data"][0].get("imageUrl")
            avatar_set(username, img)
            return img
    except Exception:
        avatar_set(username, None)
        return None
    avatar_set(username, None)
    return None


# -------------------------
# Auth helpers
# -------------------------
def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return func(*args, **kwargs)
    return wrapper


# -------------------------
# Utility: log admin action in data.json
# -------------------------
def log_action(admin, action, details=""):
    data = read_data()
    data.setdefault("logs", [])
    data["logs"].insert(0, {
        "at": datetime.utcnow().isoformat(),
        "admin": admin,
        "action": action,
        "details": details
    })
    # keep logs length sane
    data["logs"] = data["logs"][:500]
    write_data(data)


# -------------------------
# ROUTES
# -------------------------
@app.route("/", methods=["GET"])
def roster_view():
    data = read_data()
    members = data.get("members", [])
    # attach rank name and avatar
    rendered = []
    for m in members:
        rank_index = int(m.get("rank_index", 0))
        rendered.append({
            "id": m.get("id"),
            "username": m.get("username"),
            "rank_index": rank_index,
            "rank": PNP_RANKS[rank_index] if 0 <= rank_index < len(PNP_RANKS) else "Unknown",
            "avatar": get_roblox_avatar(m.get("username")) or None,
            "created_at": m.get("created_at")
        })
    return render_template(
        "roster.html",
        members=rendered,
        ranks=list(enumerate(PNP_RANKS)),
        is_admin=bool(session.get("is_admin")),
        logs=data.get("logs", [])
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        form_user = request.form.get("username", "").strip()
        form_pass = request.form.get("password", "")
        if form_user == ADMIN_USERNAME and form_pass == ADMIN_PASSWORD:
            session["is_admin"] = True
            session["admin_user"] = form_user
            log_action(form_user, "login", "admin logged in")
            next_url = request.args.get("next") or url_for("roster_view")
            return redirect(next_url)
        else:
            flash("Invalid credentials", "error")
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    admin = session.get("admin_user", "unknown")
    session.pop("is_admin", None)
    session.pop("admin_user", None)
    log_action(admin, "logout", "admin logged out")
    return redirect(url_for("roster_view"))


@app.route("/add", methods=["POST"])
@admin_required
def add_member():
    username = request.form.get("username", "").strip()
    try:
        rank_index = int(request.form.get("rank_index", 0))
    except Exception:
        rank_index = 0
    if not username:
        return redirect(url_for("roster_view"))

    data = read_data()
    members = data.setdefault("members", [])

    # enforce uniqueness by username (case-insensitive)
    if any(m["username"].lower() == username.lower() for m in members):
        flash("Username already exists", "error")
        return redirect(url_for("roster_view"))

    new_id = max((m.get("id", 0) for m in members), default=0) + 1
    now = datetime.utcnow().isoformat()
    members.append({
        "id": new_id,
        "username": username,
        "rank_index": int(max(0, min(rank_index, len(PNP_RANKS)-1))),
        "created_at": now
    })
    write_data(data)
    log_action(session.get("admin_user", "admin"), "add", f"{username} -> {PNP_RANKS[rank_index]}")
    # prefetch avatar in background
    threading.Thread(target=get_roblox_avatar, args=(username,), daemon=True).start()
    return redirect(url_for("roster_view"))


@app.route("/delete/<int:member_id>", methods=["POST"])
@admin_required
def delete_member(member_id):
    data = read_data()
    members = data.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        flash("Member not found", "error")
        return redirect(url_for("roster_view"))
    members = [x for x in members if int(x.get("id")) != int(member_id)]
    data["members"] = members
    write_data(data)
    log_action(session.get("admin_user", "admin"), "delete", m.get("username"))
    return redirect(url_for("roster_view"))


@app.route("/promote/<int:member_id>", methods=["POST"])
@admin_required
def promote_member(member_id):
    data = read_data()
    members = data.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        flash("Member not found", "error")
        return redirect(url_for("roster_view"))
    cur = int(m.get("rank_index", 0))
    if cur <= 0:
        flash("Already highest rank", "info")
        return redirect(url_for("roster_view"))
    m["rank_index"] = cur - 1
    write_data(data)
    log_action(session.get("admin_user", "admin"), "promote", f"{m.get('username')} -> {PNP_RANKS[m['rank_index']]}")
    return redirect(url_for("roster_view"))


@app.route("/demote/<int:member_id>", methods=["POST"])
@admin_required
def demote_member(member_id):
    data = read_data()
    members = data.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        flash("Member not found", "error")
        return redirect(url_for("roster_view"))
    cur = int(m.get("rank_index", 0))
    if cur >= len(PNP_RANKS) - 1:
        flash("Already lowest rank", "info")
        return redirect(url_for("roster_view"))
    m["rank_index"] = cur + 1
    write_data(data)
    log_action(session.get("admin_user", "admin"), "demote", f"{m.get('username')} -> {PNP_RANKS[m['rank_index']]}")
    return redirect(url_for("roster_view"))


@app.route("/api/roster")
def api_roster():
    data = read_data()
    out = []
    for m in data.get("members", []):
        out.append({
            "id": m.get("id"),
            "username": m.get("username"),
            "rank_index": m.get("rank_index"),
            "rank": PNP_RANKS[int(m.get("rank_index", 0))] if 0 <= int(m.get("rank_index", 0)) < len(PNP_RANKS) else "Unknown",
            "avatar": get_roblox_avatar(m.get("username")),
            "created_at": m.get("created_at")
        })
    return jsonify(out)


# -------------------------
# Boot: ensure data file exists and seed example if empty
# -------------------------
with app.app_context():
    if not DATA_FILE.exists():
        write_data({"members": [], "logs": []})
    d = read_data()
    if not d.get("members"):
        now = datetime.utcnow().isoformat()
        d["members"] = [
            {"id": 1, "username": "Roblox", "rank_index": 11, "created_at": now},
            {"id": 2, "username": "Builderman", "rank_index": 8, "created_at": now}
        ]
        write_data(d)

# -------------------------
# Run dev server
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("Starting app on port", port, "admin:", ADMIN_USERNAME)
    app.run(host="0.0.0.0", port=port)
