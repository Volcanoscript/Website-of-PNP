# app.py
"""
All-in-one PNP roster app (single file)

Features:
- PostgreSQL persistent storage (via DATABASE_URL env var) OR fallback to players.json if no DB set
- Admin login UI (default admin / PNP2025)
- Add / Promote / Demote / Delete members
- Logs
- /get_ranks leaderboard page with Roblox avatar thumbnails (cached)
- /api/roster JSON endpoint
"""

import os
import time
import threading
import json
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps

import requests
import psycopg2
import psycopg2.extras
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string,
    session,
    jsonify,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- Config ----------
APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "players.json"

PORT = int(os.getenv("PORT", 5000))
SECRET_KEY = os.getenv("postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/pnp_website_database") or os.urandom(24).hex()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_DB = bool(DATABASE_URL)

ADMIN_USERNAME_DEFAULT = "admin"
ADMIN_PASSWORD_DEFAULT = "PNP2025"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", ADMIN_USERNAME_DEFAULT)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", ADMIN_PASSWORD_DEFAULT)

AVATAR_TTL = int(os.getenv("AVATAR_TTL", 60 * 60))  # 1 hour cache
AVATAR_CLEAN_INTERVAL = int(os.getenv("AVATAR_CLEAN_INTERVAL", 300))  # cleanup every 5 min
AVATAR_SIZE = os.getenv("AVATAR_SIZE", "150x150")

# PNP ranks (lowest -> highest)
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
    "Police General",
]

# Roblox endpoints
ROBLOX_USERNAME_ENDPOINT = "https://users.roblox.com/v1/usernames/users"
ROBLOX_THUMBNAIL_ENDPOINT = "https://thumbnails.roblox.com/v1/users/avatar-headshot"

# ---------- Flask app ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---------- DB helpers ----------
def get_conn():
    if not USE_DB:
        return None
    # psycopg2 accepts DATABASE_URL directly
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    if not USE_DB:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                rank_index INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL
            );
            """
            )
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            """
            )
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                at TIMESTAMPTZ NOT NULL,
                admin TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT
            );
            """
            )
        conn.commit()


# ---------- File fallback helpers (if no DB) ----------
# Thread lock for file I/O
_file_lock = threading.Lock()


def ensure_datafile():
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"admin": None, "members": [], "logs": []}, indent=2), encoding="utf-8")


def read_datafile():
    ensure_datafile()
    with _file_lock:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def write_datafile(d):
    with _file_lock:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)


# ---------- Choose persistence layer functions ----------
if USE_DB:
    init_db()

    def get_admin_record():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username, password_hash FROM admins LIMIT 1")
                return cur.fetchone()

    def create_admin_record(username, raw_password):
        h = generate_password_hash(raw_password)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO admins (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash",
                    (username, h),
                )
            conn.commit()

    def verify_admin_record(username, raw_password):
        rec = None
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM admins WHERE username = %s", (username,))
                rec = cur.fetchone()
        if not rec:
            return False
        return check_password_hash(rec["password_hash"], raw_password)

    def get_members_list():
        out = []
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, rank_index, created_at FROM members ORDER BY id")
                rows = cur.fetchall()
                for r in rows:
                    out.append(
                        {
                            "id": r["id"],
                            "username": r["username"],
                            "rank_index": int(r["rank_index"]),
                            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        }
                    )
        return out

    def add_member(username, rank_index=0):
        now = datetime.now(timezone.utc)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO members (username, rank_index, created_at) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING RETURNING id",
                    (username, int(rank_index), now),
                )
                conn.commit()

    def delete_member(member_id):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM members WHERE id = %s", (int(member_id),))
                changed = cur.rowcount
                conn.commit()
        return bool(changed)

    def change_member_rank(member_id, delta):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT rank_index FROM members WHERE id = %s", (int(member_id),))
                r = cur.fetchone()
                if not r:
                    return False
                new = max(0, min(len(PNP_RANKS) - 1, int(r["rank_index"]) + int(delta)))
                cur.execute("UPDATE members SET rank_index = %s WHERE id = %s", (new, int(member_id)))
                conn.commit()
        return True

    def log_action(admin, action, details=""):
        now = datetime.now(timezone.utc)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO logs (at, admin, action, details) VALUES (%s, %s, %s, %s)",
                    (now, admin, action, details),
                )
                conn.commit()

    def get_logs(limit=200):
        out = []
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT at, admin, action, details FROM logs ORDER BY id DESC LIMIT %s", (int(limit),))
                rows = cur.fetchall()
                for r in rows:
                    out.append({"at": r["at"].isoformat(), "admin": r["admin"], "action": r["action"], "details": r["details"]})
        return out

else:
    # File-based functions (fallback)
    def get_admin_record():
        d = read_datafile()
        return d.get("admin")

    def create_admin_record(username, raw_password):
        d = read_datafile()
        d["admin"] = {"username": username, "password_hash": generate_password_hash(raw_password)}
        write_datafile(d)

    def verify_admin_record(username, raw_password):
        d = read_datafile()
        adm = d.get("admin")
        if not adm:
            return False
        return adm.get("username") == username and check_password_hash(adm.get("password_hash", ""), raw_password)

    def get_members_list():
        d = read_datafile()
        return d.get("members", [])

    def add_member(username, rank_index=0):
        d = read_datafile()
        members = d.setdefault("members", [])
        if any(m.get("username", "").lower() == username.lower() for m in members):
            return
        new_id = max((m.get("id", 0) for m in members), default=0) + 1
        now = datetime.now(timezone.utc).isoformat()
        members.append({"id": new_id, "username": username, "rank_index": int(rank_index), "created_at": now})
        write_datafile(d)

    def delete_member(member_id):
        d = read_datafile()
        members = d.get("members", [])
        before = len(members)
        d["members"] = [m for m in members if int(m.get("id")) != int(member_id)]
        write_datafile(d)
        return len(d["members"]) < before

    def change_member_rank(member_id, delta):
        d = read_datafile()
        members = d.get("members", [])
        for m in members:
            if int(m.get("id")) == int(member_id):
                ri = max(0, min(len(PNP_RANKS) - 1, int(m.get("rank_index", 0)) + int(delta)))
                m["rank_index"] = ri
                write_datafile(d)
                return True
        return False

    def log_action(admin, action, details=""):
        d = read_datafile()
        logs = d.setdefault("logs", [])
        logs.insert(0, {"at": datetime.now(timezone.utc).isoformat(), "admin": admin, "action": action, "details": details})
        d["logs"] = logs[:500]
        write_datafile(d)

    def get_logs(limit=200):
        d = read_datafile()
        return d.get("logs", [])[:limit]


# ---------- Avatar cache ----------
_avatar_cache = {}
_avatar_lock = threading.Lock()


def avatar_get_cached(username):
    if not username:
        return None
    key = username.lower()
    now = time.time()
    with _avatar_lock:
        entry = _avatar_cache.get(key)
        if entry and entry["expiry"] > now:
            return entry["url"]
    return None


def avatar_set_cached(username, url):
    key = (username or "").lower()
    with _avatar_lock:
        _avatar_cache[key] = {"url": url, "expiry": time.time() + AVATAR_TTL}


def _avatar_cleaner_loop():
    while True:
        time.sleep(AVATAR_CLEAN_INTERVAL)
        now = time.time()
        with _avatar_lock:
            to_del = [k for k, v in _avatar_cache.items() if v["expiry"] <= now]
            for k in to_del:
                del _avatar_cache[k]


threading.Thread(target=_avatar_cleaner_loop, daemon=True).start()


# ---------- Roblox helpers ----------
def get_roblox_userid(username):
    try:
        resp = requests.post(
            ROBLOX_USERNAME_ENDPOINT,
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=6,
        )
        resp.raise_for_status()
        j = resp.json()
        data = j.get("data") or []
        if data:
            return data[0].get("id")
    except Exception:
        return None
    return None


def get_roblox_avatar(username, size=AVATAR_SIZE):
    if not username:
        return None
    cached = avatar_get_cached(username)
    if cached is not None:
        return cached
    uid = get_roblox_userid(username)
    if not uid:
        avatar_set_cached(username, None)
        return None
    try:
        url = f"{ROBLOX_THUMBNAIL_ENDPOINT}?userIds={uid}&size={size}&format=Png&isCircular=true"
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        j = resp.json()
        data = j.get("data") or []
        if data and data[0].get("imageUrl"):
            img = data[0]["imageUrl"]
            avatar_set_cached(username, img)
            return img
    except Exception:
        avatar_set_cached(username, None)
        return None
    avatar_set_cached(username, None)
    return None


# ---------- Auth decorator ----------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return wrapper


# ---------- HTML templates (embedded) ----------
INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PNP Roster</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family:Arial,Helvetica,sans-serif;background:#0b0b0b;color:#eee;margin:12px}
    .wrap{max-width:1000px;margin:0 auto}
    header{display:flex;justify-content:space-between;align-items:center}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-top:14px}
    .card{background:#111;padding:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.03);display:flex;gap:12px;align-items:center}
    .avatar{width:72px;height:72px;border-radius:8px;overflow:hidden;background:#000}
    .avatar img{width:100%;height:100%;object-fit:cover}
    .meta{flex:1}
    .rank{color:#ffd54b;font-weight:700}
    .muted{color:#9aa}
    .controls form{display:inline}
    .btn{padding:6px 10px;border-radius:6px;border:0;cursor:pointer;margin-left:6px}
    .btn-danger{background:#d33;color:#fff}
    input, select{padding:8px;border-radius:6px;border:1px solid #222;background:#0c0c0c;color:#fff}
    .panel{margin-top:16px;padding:12px;border-radius:8px;background:#0d0d0d}
    a{color:#8ec5ff}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>PNP Roster</h1>
        <div class="muted">Members: {{ members|length }}</div>
      </div>
      <div>
        {% if is_admin %}
          <div>Admin: <strong>{{ admin_user }}</strong> — <a href="{{ url_for('logout') }}">Logout</a></div>
        {% else %}
          <div><a href="{{ url_for('login') }}">Admin Login</a></div>
        {% endif %}
      </div>
    </header>

    <div class="grid">
      {% for m in members %}
      <div class="card">
        <div class="avatar">
          {% if m.avatar %}
            <img src="{{ m.avatar }}" alt="avatar">
          {% else %}
            <img src="https://via.placeholder.com/150x150.png?text=No+Avatar" alt="no avatar">
          {% endif %}
        </div>
        <div class="meta">
          <div class="rank">{{ m.rank }}</div>
          <div><strong>{{ m.username }}</strong></div>
          <div class="muted">Joined: {{ m.created_at }}</div>
        </div>
        {% if is_admin %}
        <div class="controls">
          <form method="post" action="{{ url_for('promote_member', member_id=m.id) }}">
            <button class="btn" type="submit">Promote</button>
          </form>
          <form method="post" action="{{ url_for('demote_member', member_id=m.id) }}">
            <button class="btn" type="submit">Demote</button>
          </form>
          <form method="post" action="{{ url_for('delete_member', member_id=m.id) }}" onsubmit="return confirm('Delete {{ m.username }}?')">
            <button class="btn btn-danger" type="submit">Delete</button>
          </form>
        </div>
        {% endif %}
      </div>
      {% endfor %}
    </div>

    {% if is_admin %}
    <section class="panel">
      <h3>Add member</h3>
      <form method="post" action="{{ url_for('add_member') }}">
        <input name="username" placeholder="Roblox username" required>
        <select name="rank_index">
          {% for r in ranks %}
            <option value="{{ loop.index0 }}">{{ r }}</option>
          {% endfor %}
        </select>
        <button class="btn" type="submit">Add</button>
      </form>
    </section>

    <section class="panel">
      <h3>Admin logs (latest)</h3>
      <div style="max-height:220px;overflow:auto">
        {% for log in logs %}
          <div style="padding:8px;border-bottom:1px solid rgba(255,255,255,0.03);font-size:13px;color:#9aa">
            <strong>{{ log.at }}</strong> — <em>{{ log.admin }}</em> — {{ log.action }}{% if log.details %} — {{ log.details }}{% endif %}
          </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    <div style="margin-top:16px;color:#888">Data persisted in {{ persistence }}. Avatars fetched from Roblox and cached for {{ avatar_ttl }} seconds. <a href="{{ url_for('get_ranks') }}">Public leaderboard</a> • <a href="{{ url_for('api_roster') }}">API (JSON)</a></div>
  </div>
</body>
</html>
"""

LOGIN_HTML = r"""
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Admin Login</title>
<style>body{background:#0b0b0b;color:#fff;font-family:Arial;padding:20px}form{max-width:400px;margin:auto;background:#111;padding:20px;border-radius:8px}</style>
</head>
<body>
  <form method="post">
    <h2>Admin Login</h2>
    <input name="username" placeholder="username" required style="width:100%;padding:8px;margin:8px 0">
    <input name="password" type="password" placeholder="password" required style="width:100%;padding:8px;margin:8px 0">
    <button style="padding:8px 12px">Login</button>
  </form>
</body>
</html>
"""

LEADERBOARD_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PNP Leaderboard</title>
  <style>
    body{font-family:Arial;background:#f6f8fb;color:#111;padding:24px}
    .card{max-width:800px;margin:18px auto;padding:20px;border-radius:10px;background:#fff;box-shadow:0 6px 18px rgba(0,0,0,0.06)}
    .player{display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #eee}
    .player:last-child{border-bottom:0}
    .avatar{width:64px;height:64px;border-radius:8px;margin-right:12px;overflow:hidden}
    .avatar img{width:100%;height:100%;object-fit:cover}
    .meta{flex:1}
    .rank{color:#666;font-size:14px}
    h1{text-align:center;margin-bottom:12px}
  </style>
</head>
<body>
  <div class="card">
    <h1>PNP Leaderboard</h1>
    {% for p in players %}
      <div class="player">
        <div class="avatar"><img src="{{ p.avatar or placeholder }}" alt="avatar"></div>
        <div class="meta">
          <div><strong>{{ p.username }}</strong></div>
          <div class="rank">{{ p.rank }}</div>
        </div>
      </div>
    {% endfor %}
    {% if not players %}
      <div style="text-align:center;color:#666">No members yet</div>
    {% endif %}
  </div>
</body>
</html>
"""

# ---------- Routes ----------
@app.route("/")
def index():
    members_raw = get_members_list()
    members = []
    for m in members_raw:
        ri = int(m.get("rank_index", 0))
        members.append(
            {
                "id": int(m.get("id")),
                "username": m.get("username"),
                "rank_index": ri,
                "rank": PNP_RANKS[ri] if 0 <= ri < len(PNP_RANKS) else "Unknown",
                "avatar": get_roblox_avatar(m.get("username")),
                "created_at": m.get("created_at"),
            }
        )
    logs = get_logs(200)
    persistence = "PostgreSQL" if USE_DB else f"players.json (file fallback)"
    return render_template_string(
        INDEX_HTML,
        members=members,
        ranks=PNP_RANKS,
        is_admin=bool(session.get("is_admin")),
        admin_user=session.get("admin_user"),
        logs=logs,
        avatar_ttl=AVATAR_TTL,
        persistence=persistence,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    # login page
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = re
