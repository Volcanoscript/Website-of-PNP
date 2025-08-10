
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
    app.run(host="0.0.0.0", port=PORT, debug=False)

# ----------- database -------------
import os
import psycopg2

# Get the DATABASE_URL from environment variables
DATABASE_URL = os.environ.get("postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/pnp_website_database")

if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable is not set")

# Connect to the external PostgreSQL database using the URL
conn = psycopg2.connect(DATABASE_URL)

# Now you can use `conn` to work with your database

