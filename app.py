# app.py
# Full PNP admin roster app (single-file backend)
# - Uses your existing templates (unchanged) via render_template()
# - SQLite storage: pnp.db
# - Admin login, add/promote/demote/delete, admin logs
# - Live Roblox avatar thumbnails with caching
# - Safe, defensive (meant to avoid Render 502s)
# Run: python app.py (dev) or gunicorn app:app (Render)

import os
import sqlite3
import time
import threading
from functools import wraps
from datetime import datetime
from flask import Flask, g, request, redirect, url_for, session, render_template, jsonify, abort
import requests
from werkzeug.security import generate_password_hash, check_password_hash

# ---- CONFIG ----
DB_PATH = os.getenv("DB_PATH", "pnp.db")
PORT = int(os.getenv("PORT", 5000))
SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
# IMPORTANT: change ADMIN_PASSWORD on Render to a strong secret
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "PNP2025")
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

# Avatar caching
AVATAR_TTL = 60 * 60  # seconds
AVATAR_SIZE = os.getenv("AVATAR_SIZE", "150x150")
avatar_cache = {}
avatar_lock = threading.Lock()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY
app.config["DATABASE"] = DB_PATH

# ---- PNP ranks (ordered highest -> lowest). Edit if you want. ----
PNP_RANKS = [
    "Police Director General (PDG)",
    "Police Deputy Director General (PDDG)",
    "Police Chief (PC)",
    "Police Deputy Chief (PDC)",
    "Police Colonel (PCol)",
    "Police Lieutenant Colonel (PLCol)",
    "Police Major (PMaj)",
    "Police Captain (PCpt)",
    "Police Lieutenant (PLt)",
    "Police Master Sergeant (PMSg)",
    "Police Staff Sergeant (PSSg)",
    "Police Sergeant (PSg)",
    "Police Corporal (PCpl)",
    "Police Patrolman (PPat)",
    "Police Recruit (PRec)"
]

# -------------------------
# Avatar cache helpers
# -------------------------
def avatar_get(username):
    key = (username or "").lower()
    now = time.time()
    with avatar_lock:
        v = avatar_cache.get(key)
        if v and v[1] > now:
            return v[0]
    return None

def avatar_set(username, url):
    key = (username or "").lower()
    expiry = time.time() + AVATAR_TTL
    with avatar_lock:
        avatar_cache[key] = (url, expiry)

def avatar_cleaner():
    while True:
        time.sleep(300)
        now = time.time()
        with avatar_lock:
            to_remove = [k for k, v in avatar_cache.items() if v[1] <= now]
            for k in to_remove:
                del avatar_cache[k]

threading.Thread(target=avatar_cleaner, daemon=True).start()

# -------------------------
# Roblox thumbnail function (safe)
# -------------------------
def fetch_roblox_avatar(username):
    if not username:
        return None
    # return cached if available
    c = avatar_get(username)
    if c is not None:
        return c
    try:
        resp = requests.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=6
        )
        resp.raise_for_status()
        j = resp.json()
        if j.get("data") and len(j["data"]) > 0:
            uid = j["data"][0].get("id")
            if uid:
                url = (
                    f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
                    f"?userIds={uid}&size={AVATAR_SIZE}&format=Png&isCircular=true"
                )
                avatar_set(username, url)
                return url
    except Exception:
        # network/API failure => cache None for short period
        avatar_set(username, None)
        return None
    avatar_set(username, None)
    return None

# -------------------------
# Database helpers
# -------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = sqlite3.connect(app.config["DATABASE"], timeout=30, check_same_thread=False)
        db.row_factory = sqlite3.Row
        g._database = db
    return db

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            rank_index INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            admin TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT
        )
    """)
    db.commit()

@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# -------------------------
# CRUD + logging
# -------------------------
def query_members():
    db = get_db()
    cur = db.execute("SELECT * FROM members ORDER BY rank_index ASC, username COLLATE NOCASE ASC")
    return [dict(r) for r in cur.fetchall()]

def add_member_db(username, rank_index):
    db = get_db()
    now = datetime.utcnow().isoformat()
    try:
        db.execute("INSERT INTO members (username, rank_index, created_at) VALUES (?, ?, ?)",
                   (username, int(rank_index), now))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def delete_member_db(member_id):
    db = get_db()
    db.execute("DELETE FROM members WHERE id = ?", (member_id,))
    db.commit()

def update_member_rank_db(member_id, new_rank_index):
    db = get_db()
    db.execute("UPDATE members SET rank_index = ? WHERE id = ?", (int(new_rank_index), member_id))
    db.commit()

def get_member_db(member_id):
    db = get_db()
    cur = db.execute("SELECT * FROM members WHERE id = ?", (member_id,))
    r = cur.fetchone()
    return dict(r) if r else None

def get_member_by_username(username):
    db = get_db()
    cur = db.execute("SELECT * FROM members WHERE username = ?", (username,))
    r = cur.fetchone()
    return dict(r) if r else None

def log_admin(admin, action, details=""):
    db = get_db()
    at = datetime.utcnow().isoformat()
    db.execute("INSERT INTO admin_logs (at, admin, action, details) VALUES (?, ?, ?, ?)",
               (at, admin, action, details))
    db.commit()

def query_logs(limit=200):
    db = get_db()
    cur = db.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]

# -------------------------
# Auth decorator
# -------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

# -------------------------
# Seed minimal data if empty (safe)
# -------------------------
def seed_if_empty():
    db = get_db()
    cur = db.execute("SELECT COUNT(*) c FROM members")
    c = cur.fetchone()["c"]
    if c == 0:
        now = datetime.utcnow().isoformat()
        samples = [
            ("Roblox", 2),
            ("Builderman", 5),
            ("Stickmasterluke", 7),
        ]
        for u, ri in samples:
            try:
                db.execute("INSERT INTO members (username, rank_index, created_at) VALUES (?, ?, ?)",
                           (u, ri, now))
            except Exception:
                pass
        db.commit()

# -------------------------
# Views (do NOT change your templates on disk)
# -------------------------
@app.route("/")
def home():
    # Fetch DB members and attach avatars (cached)
    members_raw = query_members()
    members = []
    for m in members_raw:
        avatar = fetch_roblox_avatar(m["username"])
        members.append({
            "id": m["id"],
            "username": m["username"],
            "rank_index": m["rank_index"],
            "rank": PNP_RANKS[m["rank_index"]] if 0 <= m["rank_index"] < len(PNP_RANKS) else "Unknown",
            "avatar": avatar,
            "created_at": m["created_at"][:19].replace("T", " ")
        })

    # Render your existing template called roster.html (do not change UI).
    # If you named it differently, change the filename below to match your file.
    return render_template(
        "roster.html",
        members=members,
        is_admin=bool(session.get("admin_logged_in")),
        ranks=list(enumerate(PNP_RANKS)),
        logs=query_logs(200) if session.get("admin_logged_in") else [],
        error=None
    )

# Login page - renders your existing login.html (unchanged)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        # Accept correct username + matching password
        if u == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, p) or (u == ADMIN_USERNAME and p == ADMIN_PASSWORD):
            session["admin_logged_in"] = True
            session["admin_user"] = u
            log_admin(u, "login", "admin logged in")
            next_url = request.args.get("next") or url_for("home")
            return redirect(next_url)
        else:
            # render same login.html with error variable available (template unchanged unless it uses error)
            return render_template("login.html", error="Invalid credentials")
    # GET
    return render_template("login.html")

@app.route("/logout")
def logout():
    admin = session.get("admin_user", "unknown")
    session.pop("admin_logged_in", None)
    session.pop("admin_user", None)
    log_admin(admin, "logout", "admin logged out")
    return redirect(url_for("home"))

# Admin actions (endpoints). These POST handlers do not change your UI files.
@app.route("/admin/add", methods=["POST"])
@admin_required
def add_member():
    username = request.form.get("username", "").strip()
    try:
        rank_index = int(request.form.get("rank_index", 0))
    except Exception:
        rank_index = 0
    if not username:
        return redirect(url_for("home"))
    if get_member_by_username(username):
        log_admin(session.get("admin_user", "admin"), "add_failed", f"{username} already exists")
        return redirect(url_for("home"))
    ok = add_member_db(username, rank_index)
    if ok:
        log_admin(session.get("admin_user", "admin"), "add", f"{username} -> {PNP_RANKS[rank_index]}")
    else:
        log_admin(session.get("admin_user", "admin"), "add_failed", username)
    return redirect(url_for("home"))

@app.route("/admin/delete/<int:member_id>", methods=["POST"])
@admin_required
def delete_member(member_id):
    m = get_member_db(member_id)
    if not m:
        return redirect(url_for("home"))
    delete_member_db(member_id)
    log_admin(session.get("admin_user", "admin"), "delete", m["username"])
    return redirect(url_for("home"))

@app.route("/admin/promote/<int:member_id>", methods=["POST"])
@admin_required
def promote(member_id):
    m = get_member_db(member_id)
    if not m:
        return redirect(url_for("home"))
    cur = m["rank_index"]
    new_rank = max(0, cur - 1)
    if new_rank != cur:
        update_member_rank_db(member_id, new_rank)
        log_admin(session.get("admin_user", "admin"), "promote", f"{m['username']} {PNP_RANKS[cur]} -> {PNP_RANKS[new_rank]}")
    return redirect(url_for("home"))

@app.route("/admin/demote/<int:member_id>", methods=["POST"])
@admin_required
def demote(member_id):
    m = get_member_db(member_id)
    if not m:
        return redirect(url_for("home"))
    cur = m["rank_index"]
    new_rank = min(len(PNP_RANKS)-1, cur + 1)
    if new_rank != cur:
        update_member_rank_db(member_id, new_rank)
        log_admin(session.get("admin_user", "admin"), "demote", f"{m['username']} {PNP_RANKS[cur]} -> {PNP_RANKS[new_rank]}")
    return redirect(url_for("home"))

# Optional API endpoint: return JSON roster
@app.route("/api/roster")
def api_roster():
    members_raw = query_members()
    out = []
    for m in members_raw:
        out.append({
            "id": m["id"],
            "username": m["username"],
            "rank_index": m["rank_index"],
            "rank": PNP_RANKS[m["rank_index"]] if 0 <= m["rank_index"] < len(PNP_RANKS) else "Unknown",
            "avatar": fetch_roblox_avatar(m["username"]),
            "created_at": m["created_at"]
        })
    return jsonify(out)

# Initialize DB and seed
with app.app_context():
    init_db()
    seed_if_empty()

# Run (dev)
if __name__ == "__main__":
    print(f"Starting on 0.0.0.0:{PORT} — admin: {ADMIN_USERNAME}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
