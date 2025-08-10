# app.py
"""
Single-file PNP roster app (Flask) with PostgreSQL backend + Roblox avatar thumbnails.
Drop this file into your Render service. Ensure `psycopg2-binary` is in requirements.txt.
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
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

# Try to import psycopg2 (psycopg2-binary recommended in requirements.txt)
try:
    import psycopg2
    import psycopg2.extras
except Exception as e:
    raise RuntimeError(
        "psycopg2 is required. Add `psycopg2-binary` to requirements.txt and redeploy. "
        "Original error: " + str(e)
    )

# ---------- Config ----------
APP_DIR = Path(__file__).parent
PORT = int(os.getenv("PORT", 10000))
SECRET_KEY = os.getenv("SECRET_KEY") or "change_this_to_a_secret_please"
SESSION_COOKIE_NAME = "pnp_session"

# Use provided DB URL or env var DATABASE_URL
DEFAULT_DB_URL = (
    "postgresql://pnp_website_database_user:"
    "JgSW6mMvhBVernIALTJpR296LMPIlme9@"
    "dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/"
    "pnp_website_database"
)
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

# Admin defaults (can be overridden by creating an admin in /setup or via env vars)
ADMIN_USERNAME_DEFAULT = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_DEFAULT = os.getenv("ADMIN_PASSWORD", "PNP2025")

# Avatar caching
AVATAR_TTL = int(os.getenv("AVATAR_TTL", 60 * 60))  # 1 hour
AVATAR_CLEAN_INTERVAL = int(os.getenv("AVATAR_CLEAN_INTERVAL", 300))
AVATAR_SIZE = os.getenv("AVATAR_SIZE", "150x150")

# PNP ranks (lowest -> highest) — exact list
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
app.config["SESSION_COOKIE_NAME"] = SESSION_COOKIE_NAME

# ---------- DB helpers ----------
def get_conn():
    """Return a new connection. Caller should close it (or use context manager)."""
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def ensure_schema():
    """Create tables if they don't exist."""
    sql = [
        """
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS members (
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
    print(f"Starting app on 0.0.0.0:{PORT} using DB: {DATABASE_URL}")
    app.run(host="0.0.0.0", port=PORT, debug=False)            );
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
