# app.py
"""
Single-file PNP roster app ready for Render.com.

Features:
- Admin login (admin / PNP2025 by default)
- Add / Promote / Demote / Delete members
- Persistent storage to players.json (members + logs)
- Live Roblox avatar thumbnails (cached)
- All HTML embedded (no external templates)
"""

import os
import json
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps

import requests
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    render_template_string,
    jsonify,
)

# ---------- Configuration ----------
APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "players.json"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "PNP2025")
SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24)
PORT = int(os.getenv("PORT", 5000))

AVATAR_TTL = int(os.getenv("AVATAR_TTL", 60 * 60))  # seconds
AVATAR_CLEAN_INTERVAL = int(os.getenv("AVATAR_CLEAN_INTERVAL", 300))  # seconds
AVATAR_SIZE = os.getenv("AVATAR_SIZE", "150x150")

# PNP ranks (lowest -> highest) — exact list you provided
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

# Roblox endpoints (users -> thumbnails)
ROBLOX_USERNAME_ENDPOINT = "https://users.roblox.com/v1/usernames/users"
ROBLOX_THUMBNAIL_ENDPOINT = "https://thumbnails.roblox.com/v1/users/avatar-headshot"

# ---------- Flask app ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---------- Safe file persistence ----------
_lock = threading.Lock()


def ensure_datafile():
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"members": [], "logs": []}, indent=2), encoding="utf-8")


def read_data():
    ensure_datafile()
    with _lock:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def write_data(data):
    # atomic replace
    with _lock:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)


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
    """Return Roblox user id or None."""
    if not username:
        return None
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
    """Return avatar headshot URL or None. Uses cache to reduce API calls."""
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


# ---------- Auth & Logging ----------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return wrapper


def log_action(admin, action, details=""):
    d = read_data()
    logs = d.setdefault("logs", [])
    logs.insert(
        0,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "admin": admin,
            "action": action,
            "details": details,
        },
    )
    d["logs"] = logs[:500]
    write_data(d)


# ---------- HTML (embedded) ----------
MAIN_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PNP Roster</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family: Arial, Helvetica, sans-serif;background:#0b0b0b;color:#eee;margin:12px}
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

    <div style="margin-top:16px;color:#888">Data persisted in <code>players.json</code>. Avatars fetched from Roblox and cached for {{ avatar_ttl }} seconds.</div>
  </div>
</body>
</html>
"""

# ---------- Routes ----------


@app.route("/")
def index():
    d = read_data()
    members = []
    for m in d.get("members", []):
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
    return render_template_string(
        MAIN_HTML,
        members=members,
        ranks=PNP_RANKS,
        is_admin=bool(session.get("is_admin")),
        admin_user=session.get("admin_user"),
        logs=d.get("logs", []),
        avatar_ttl=AVATAR_TTL,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password", "")
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session["is_admin"] = True
            session["admin_user"] = u
            log_action(u, "login", "admin logged in")
            return redirect(request.args.get("next") or url_for("index"))
        return (
            "<div style='padding:20px'>Invalid credentials. <a href='/'>Back</a></div>",
            401,
        )
    return (
        "<div style='max-width:420px;margin:40px auto;padding:20px;background:#0d0d0d;border-radius:8px;color:#fff'>"
        "<h2>Admin Login</h2>"
        "<form method='post'>"
        "<input name='username' placeholder='username' required style='width:100%;padding:8px;margin:6px 0'>"
        "<input name='password' type='password' placeholder='password' required style='width:100%;padding:8px;margin:6px 0'>"
        "<button style='padding:8px 12px'>Login</button>"
        "</form></div>"
    )


@app.route("/logout")
def logout():
    admin = session.get("admin_user", "unknown")
    session.pop("is_admin", None)
    session.pop("admin_user", None)
    log_action(admin, "logout", "admin logged out")
    return redirect(url_for("index"))


@app.route("/add", methods=["POST"])
@admin_required
def add_member():
    username = (request.form.get("username") or "").strip()
    try:
        rank_index = int(request.form.get("rank_index", 0))
    except Exception:
        rank_index = 0
    if not username:
        return redirect(url_for("index"))
    d = read_data()
    members = d.setdefault("members", [])
    if any(x["username"].lower() == username.lower() for x in members):
        return redirect(url_for("index"))
    new_id = max((m.get("id", 0) for m in members), default=0) + 1
    now = datetime.now(timezone.utc).isoformat()
    members.append(
        {"id": new_id, "username": username, "rank_index": max(0, min(rank_index, len(PNP_RANKS) - 1)), "created_at": now}
    )
    write_data(d)
    log_action(session.get("admin_user", "admin"), "add", f"{username} -> {PNP_RANKS[rank_index]}")
    threading.Thread(target=get_roblox_avatar, args=(username,), daemon=True).start()
    return redirect(url_for("index"))


@app.route("/delete/<int:member_id>", methods=["POST"])
@admin_required
def delete_member(member_id):
    d = read_data()
    members = d.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        return redirect(url_for("index"))
    members = [x for x in members if int(x.get("id")) != int(member_id)]
    d["members"] = members
    write_data(d)
    log_action(session.get("admin_user", "admin"), "delete", m.get("username"))
    return redirect(url_for("index"))


@app.route("/promote/<int:member_id>", methods=["POST"])
@admin_required
def promote_member(member_id):
    d = read_data()
    members = d.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        return redirect(url_for("index"))
    cur = int(m.get("rank_index", 0))
    if cur < len(PNP_RANKS) - 1:
        m["rank_index"] = cur + 1
        write_data(d)
        log_action(session.get("admin_user", "admin"), "promote", f"{m.get('username')} -> {PNP_RANKS[m['rank_index']]}")
    return redirect(url_for("index"))


@app.route("/demote/<int:member_id>", methods=["POST"])
@admin_required
def demote_member(member_id):
    d = read_data()
    members = d.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        return redirect(url_for("index"))
    cur = int(m.get("rank_index", 0))
    if cur > 0:
        m["rank_index"] = cur - 1
        write_data(d)
        log_action(session.get("admin_user", "admin"), "demote", f"{m.get('username')} -> {PNP_RANKS[m['rank_index']]}")
    return redirect(url_for("index"))


@app.route("/api/roster")
def api_roster():
    d = read_data()
    out = []
    for m in d.get("members", []):
        ri = int(m.get("rank_index", 0))
        out.append(
            {
                "id": m.get("id"),
                "username": m.get("username"),
                "rank_index": ri,
                "rank": PNP_RANKS[ri] if 0 <= ri < len(PNP_RANKS) else "Unknown",
                "avatar": get_roblox_avatar(m.get("username")),
                "created_at": m.get("created_at"),
            }
        )
    return jsonify(out)


# ---------- initial seed ----------
with app.app_context():
    ensure_datafile()
    d = read_data()
    if not d.get("members"):
        now = datetime.now(timezone.utc).isoformat()
        d["members"] = [{"id": 1, "username": "Roblox", "rank_index": 11, "created_at": now}]
        write_data(d)

# ---------- run ----------
if __name__ == "__main__":
    print(f"Starting app on 0.0.0.0:{PORT} (admin: {ADMIN_USERNAME})")
    # For Render prefer start command: "gunicorn app:app"
    app.run(host="0.0.0.0", port=PORT, debug=False)        CREATE TABLE IF NOT EXISTS members (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            rank_index INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            at TIMESTAMP WITH TIME ZONE NOT NULL,
            admin TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT
        );
        """,
    ]
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for q in sql:
                    cur.execute(q)
    finally:
        conn.close()

def get_admin_record():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, username FROM admins LIMIT 1;")
            return cur.fetchone()
    finally:
        conn.close()

def create_admin(username, raw_password):
    h = generate_password_hash(raw_password)
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO admins (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING;", (username, h))
    finally:
        conn.close()

def verify_admin(username, password):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM admins WHERE username = %s LIMIT 1;", (username,))
            r = cur.fetchone()
            if not r:
                return False
            return check_password_hash(r[0], password)
    finally:
        conn.close()

def add_member_db(username, rank_index=0):
    now = datetime.now(timezone.utc)
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO members (username, rank_index, created_at) VALUES (%s, %s, %s)", (username, rank_index, now))
    finally:
        conn.close()

def list_members_db():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, username, rank_index, created_at FROM members ORDER BY id;")
            return cur.fetchall()
    finally:
        conn.close()

def delete_member_db(member_id):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM members WHERE id = %s;", (member_id,))
                return cur.rowcount > 0
    finally:
        conn.close()

def change_rank_db(member_id, delta):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT rank_index FROM members WHERE id = %s LIMIT 1;", (member_id,))
                r = cur.fetchone()
                if not r:
                    return False
                newri = max(0, min(len(PNP_RANKS)-1, int(r[0]) + delta))
                cur.execute("UPDATE members SET rank_index = %s WHERE id = %s;", (newri, member_id))
                return True
    finally:
        conn.close()

def log_action_db(admin, action, details=""):
    now = datetime.now(timezone.utc)
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO logs (at, admin, action, details) VALUES (%s, %s, %s, %s);", (now, admin, action, details))
    finally:
        conn.close()

def get_logs_db(limit=200):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT at, admin, action, details FROM logs ORDER BY id DESC LIMIT %s;", (limit,))
            return cur.fetchall()
    finally:
        conn.close()

# Ensure DB schema on startup
ensure_schema()

# If no admin exists and env var default provided, create it
if not get_admin_record():
    # create env-defined admin or fallback default
    create_admin(ADMIN_USERNAME_DEFAULT, ADMIN_PASSWORD_DEFAULT)

# ---------- Avatar cache ----------
_avatar_cache = {}
_avatar_lock = threading.Lock()

def avatar_get_cached(username):
    if not username:
        return None
    k = username.lower()
    now = time.time()
    with _avatar_lock:
        e = _avatar_cache.get(k)
        if e and e["expiry"] > now:
            return e["url"]
    return None

def avatar_set_cached(username, url):
    k = (username or "").lower()
    with _avatar_lock:
        _avatar_cache[k] = {"url": url, "expiry": time.time() + AVATAR_TTL}

def _avatar_cleaner_loop():
    while True:
        time.sleep(AVATAR_CLEAN_INTERVAL)
        now = time.time()
        with _avatar_lock:
            to_del = [k for k,v in _avatar_cache.items() if v["expiry"] <= now]
            for k in to_del:
                del _avatar_cache[k]

threading.Thread(target=_avatar_cleaner_loop, daemon=True).start()

# Roblox helpers
def get_roblox_userid(username):
    if not username:
        return None
    try:
        resp = requests.post(ROBLOX_USERNAME_ENDPOINT, json={"usernames":[username], "excludeBannedUsers": False}, timeout=6)
        resp.raise_for_status()
        j = resp.json()
        data = j.get("data") or []
        if len(data) > 0:
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

# ---------- HTML template ----------
MAIN_HTML = r"""
<!doctype html><html><head>
<meta charset="utf-8"><title>PNP Roster</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,Helvetica,sans-serif;background:#07070a;color:#eaeaea;margin:12px}
.wrap{max-width:1000px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-top:14px}
.card{background:#111;padding:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.03);display:flex;gap:12px;align-items:center}
.avatar{width:72px;height:72px;border-radius:8px;overflow:hidden;background:#000}
.avatar img{width:100%;height:100%;object-fit:cover}
.meta{flex:1}
.rank{color:#ffd54b;font-weight:700}
.muted{color:#9aa;font-size:13px}
.controls form{display:inline}
.btn{padding:6px 10px;border-radius:6px;border:0;cursor:pointer;margin-left:6px}
.btn-danger{background:#d33;color:#fff}
input,select{padding:8px;border-radius:6px;border:1px solid #222;background:#0c0c0c;color:#fff}
.panel{margin-top:16px;padding:12px;border-radius:8px;background:#0d0d0d}
.small{font-size:13px;color:#999}
</style>
</head><body>
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
      <div class="muted small">Joined: {{ m.created_at }}</div>
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

<div style="margin-top:16px;color:#888">Data persisted in PostgreSQL. Avatars fetched from Roblox and cached for {{ avatar_ttl }} seconds.</div>
</div></body></html>
"""

# ---------- Routes ----------
@app.route("/")
def index():
    raw = list_members_db()
    members = []
    for r in raw:
        # psycopg2 DictRow or dict-like
        row = dict(r)
        ri = int(row.get("rank_index", 0))
        members.append({
            "id": int(row.get("id")),
            "username": row.get("username"),
            "rank_index": ri,
            "rank": PNP_RANKS[ri] if 0 <= ri < len(PNP_RANKS) else "Unknown",
            "avatar": get_roblox_avatar(row.get("username")),
            "created_at": row.get("created_at").astimezone(timezone.utc).isoformat() if hasattr(row.get("created_at"), "astimezone") else str(row.get("created_at")),
        })
    logs_raw = get_logs_db(200)
    logs = []
    for l in logs_raw:
        logs.append({"at": l["at"].isoformat() if hasattr(l["at"], "isoformat") else str(l["at"]), "admin": l["admin"], "action": l["action"], "details": l["details"]})
    return render_template_string(MAIN_HTML, members=members, ranks=PNP_RANKS, is_admin=bool(session.get("is_admin")), admin_user=session.get("admin_user"), logs=logs, avatar_ttl=AVATAR_TTL)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        if verify_admin(u, p):
            session["is_admin"] = True
            session["admin_user"] = u
            log_action_db(u, "login", "admin logged in")
            return redirect(request.args.get("next") or url_for("index"))
        return "<div style='padding:20px'>Invalid credentials. <a href='/'>Back</a></div>", 401
    return ("<div style='max-width:420px;margin:40px auto;padding:20px;background:#0d0d0d;border-radius:8px;color:#fff'>"
            "<h2>Admin Login</h2>"
            "<form method='post'>"
            "<input name='username' placeholder='username' required style='width:100%;padding:8px;margin:6px 0'>"
            "<input name='password' type='password' placeholder='password' required style='width:100%;padding:8px;margin:6px 0'>"
            "<button style='padding:8px 12px'>Login</button>"
            "</form></div>")

@app.route("/logout")
def logout():
    admin = session.get("admin_user", "unknown")
    session.pop("is_admin", None)
    session.pop("admin_user", None)
    log_action_db(admin, "logout", "admin logged out")
    return redirect(url_for("index"))

@app.route("/setup", methods=["GET", "POST"])
def setup():
    # One-time admin creation if none exists
    if get_admin_record():
        return "<div style='padding:20px'>Admin already exists. Remove DB record to recreate.</div>"
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        if not u or not p:
            return "<div>Username and password required</div>"
        create_admin(u, p)
        return "<div>Admin created. <a href='/login'>Login</a></div>"
    return ("<div style='max-width:420px;margin:40px auto;padding:20px;background:#0d0d0d;border-radius:8px;color:#fff'>"
            "<h2>Initial Admin Setup</h2>"
            "<form method='post'>"
            "<input name='username' placeholder='username' required style='width:100%;padding:8px;margin:6px 0'>"
            "<input name='password' type='password' placeholder='password' required style='width:100%;padding:8px;margin:6px 0'>"
            "<button style='padding:8px 12px'>Create Admin</button>"
            "</form></div>")

@app.route("/add", methods=["POST"])
@admin_required
def add_member():
    username = (request.form.get("username") or "").strip()
    try:
        rank_index = int(request.form.get("rank_index", 0))
    except Exception:
        rank_index = 0
    if not username:
        return redirect(url_for("index"))
    # avoid duplicates
    members = list_members_db()
    if any(m["username"].lower() == username.lower() for m in members):
        return redirect(url_for("index"))
    add_member_db(username, max(0, min(rank_index, len(PNP_RANKS)-1)))
    log_action_db(session.get("admin_user", "admin"), "add", f"{username} -> {PNP_RANKS[max(0, min(rank_index, len(PNP_RANKS)-1))]}")
    threading.Thread(target=get_roblox_avatar, args=(username,), daemon=True).start()
    return redirect(url_for("index"))

@app.route("/delete/<int:member_id>", methods=["POST"])
@admin_required
def delete_member(member_id):
    ok = delete_member_db(member_id)
    if ok:
        log_action_db(session.get("admin_user", "admin"), "delete", f"id:{member_id}")
    return redirect(url_for("index"))

@app.route("/promote/<int:member_id>", methods=["POST"])
@admin_required
def promote_member(member_id):
    ok = change_rank_db(member_id, +1)
    if ok:
        log_action_db(session.get("admin_user", "admin"), "promote", f"id:{member_id}")
    return redirect(url_for("index"))

@app.route("/demote/<int:member_id>", methods=["POST"])
@admin_required
def demote_member(member_id):
    ok = change_rank_db(member_id, -1)
    if ok:
        log_action_db(session.get("admin_user", "admin"), "demote", f"id:{member_id}")
    return redirect(url_for("index"))

@app.route("/api/roster")
def api_roster():
    raw = list_members_db()
    out = []
    for r in raw:
        row = dict(r)
        ri = int(row.get("rank_index", 0))
        out.append({
            "id": row.get("id"),
            "username": row.get("username"),
            "rank_index": ri,
            "rank": PNP_RANKS[ri] if 0 <= ri < len(PNP_RANKS) else "Unknown",
            "avatar": get_roblox_avatar(row.get("username")),
            "created_at": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else str(row.get("created_at")),
        })
    return jsonify(out)

# ---------- Start ----------
if __name__ == "__main__":
    print(f"Starting app on 0.0.0.0:{PORT} (admin: {ADMIN_USERNAME})")
    # For Render prefer start command: "gunicorn app:app"
    app.run(host="0.0.0.0", port=PORT, debug=False)
