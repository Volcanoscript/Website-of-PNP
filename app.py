# app.py
"""
Single-file Flask app for Render deployment.

Features:
- Single Python file (no external templates)
- Admin login (default username: admin, password: PNP2025; can be overridden by env vars)
- Full PNP rank list (PNCO + PCO) in the order you requested
- Add / Promote / Demote / Delete members (by numeric id)
- Persistent storage to `players.json` (auto-created in the app directory)
- Live Roblox avatar fetching (username -> userid -> thumbnail) with in-memory cache
- Admin activity logs saved inside players.json
- UI (HTML/CSS/JS) embedded inside the file
- Run with `python app.py` or with Gunicorn via `gunicorn app:app`
"""

import os
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

import requests
from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)

# ---------------- Configuration ----------------
APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "players.json"
AVATAR_TTL = int(os.getenv("AVATAR_TTL", 60 * 60))  # seconds, default 1 hour
AVATAR_CLEAN_INTERVAL = int(os.getenv("AVATAR_CLEAN_INTERVAL", 300))  # seconds
AVATAR_SIZE = os.getenv("AVATAR_SIZE", "150x150")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "PNP2025")
SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24)
PORT = int(os.getenv("PORT", 5000))

# PNP ranks (lowest -> highest) EXACT order provided by you
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

# ---------------- Flask app ----------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---------------- Persistence helpers ----------------
_data_lock = threading.Lock()


def ensure_datafile():
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"members": [], "logs": []}, indent=2))


def read_data():
    ensure_datafile()
    with _data_lock:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def write_data(d):
    with _data_lock:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)


# ---------------- Avatar cache ----------------
_avatar_cache = {}
_avatar_lock = threading.Lock()


def avatar_get(username):
    key = (username or "").lower()
    now = time.time()
    with _avatar_lock:
        v = _avatar_cache.get(key)
        if v and v["expiry"] > now:
            return v["url"]
    return None


def avatar_set(username, url):
    key = (username or "").lower()
    with _avatar_lock:
        _avatar_cache[key] = {"url": url, "expiry": time.time() + AVATAR_TTL}


def avatar_cleaner():
    while True:
        time.sleep(AVATAR_CLEAN_INTERVAL)
        now = time.time()
        with _avatar_lock:
            to_del = [k for k, v in _avatar_cache.items() if v["expiry"] <= now]
            for k in to_del:
                del _avatar_cache[k]


# start cleaner thread
threading.Thread(target=avatar_cleaner, daemon=True).start()

# ---------------- Roblox helpers ----------------
ROBLOX_USERNAME_ENDPOINT = "https://users.roblox.com/v1/usernames/users"
ROBLOX_THUMBNAIL_ENDPOINT = "https://thumbnails.roblox.com/v1/users/avatar-headshot"


def get_roblox_userid(username):
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
        if j.get("data") and len(j["data"]) > 0:
            return j["data"][0].get("id")
    except Exception:
        return None
    return None


def get_roblox_avatar(username, size=AVATAR_SIZE):
    # cached (can cache None)
    cached = avatar_get(username)
    if cached is not None:
        return cached
    uid = get_roblox_userid(username)
    if not uid:
        avatar_set(username, None)
        return None
    try:
        url = f"{ROBLOX_THUMBNAIL_ENDPOINT}?userIds={uid}&size={size}&format=Png&isCircular=true"
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


# ---------------- Auth & logging ----------------
def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)

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


# ---------------- Single-file UI template ----------------
SITE_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PROBISYA — PNP Roster</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    :root{--bg:#070708;--card:#111213;--muted:rgba(255,255,255,0.6);--accent:#ffd54b}
    body{background:linear-gradient(#040405,#0b0b0b);color:#fff;font-family:Arial;margin:18px}
    .wrap{max-width:980px;margin:0 auto}
    header{display:flex;justify-content:space-between;align-items:center}
    h1{margin:0 0 12px 0}
    .muted{color:var(--muted)}
    .search input{padding:10px;border-radius:10px;border:0;background:#111;color:#ddd;width:260px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin-top:14px}
    .card{display:flex;gap:14px;align-items:center;padding:12px;border-radius:12px;background:linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0.01));border:1px solid rgba(255,255,255,0.03)}
    .avatar{width:72px;height:72px;border-radius:10px;overflow:hidden;background:#000;flex:0 0 72px}
    .avatar img{width:100%;height:100%;object-fit:cover;display:block}
    .avatar-placeholder{width:72px;height:72px;background:#181818;border-radius:8px}
    .meta{flex:1;min-width:0}
    .rank{color:var(--accent);font-weight:700;margin-bottom:6px}
    .username{font-weight:600}
    .small{color:var(--muted);font-size:13px;margin-top:6px}
    .controls{display:flex;gap:8px;flex-direction:column}
    .btn{padding:8px;border-radius:8px;border:0;cursor:pointer;font-weight:700}
    .btn-primary{background:var(--accent);color:#111}
    .btn-ghost{background:transparent;border:1px solid rgba(255,255,255,0.06);color:#fff}
    .danger{background:#ff4d4f;color:#fff}
    .panel{margin-top:18px;padding:12px;border-radius:10px;background:#0d0d0d;border:1px solid rgba(255,255,255,0.03)}
    .box{max-width:360px;margin:80px auto;padding:18px;background:#0f0f0f;border-radius:10px}
    .err{color:#ff7b7b;margin-bottom:8px}
    .log-item{padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.02);font-size:13px;color:var(--muted)}
    .inline{display:inline}
    input, select { padding:8px; border-radius:6px; border:1px solid #222; background:#0b0b0b; color:#fff; margin-right:6px; }
    form.inline { display:inline; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>PROBISYA — PNP Roster</h1>
        <div class="muted">Members: {{ members|length }}</div>
      </div>
      <div>
        <div class="search">
          <input id="q" placeholder="Search username or rank..." oninput="filter()" />
        </div>
        {% if is_admin %}
          <div style="margin-top:8px"><a href="{{ url_for('logout') }}" class="btn btn-ghost">Logout</a></div>
        {% else %}
          <div style="margin-top:8px"><a href="{{ url_for('login') }}" class="btn btn-ghost">Admin Login</a></div>
        {% endif %}
      </div>
    </header>

    <div class="grid" id="list">
      {% for m in members %}
        <div class="card" data-username="{{ m.username|lower }}" data-rank="{{ m.rank|lower }}">
          <div class="avatar">
            {% if m.avatar %}
              <img src="{{ m.avatar }}" alt="avatar">
            {% else %}
              <div class="avatar-placeholder"></div>
            {% endif %}
          </div>

          <div class="meta">
            <div class="rank">{{ m.rank }}</div>
            <div class="username">{{ m.username }}</div>
            <div class="small">Joined: {{ m.created_at }}</div>
          </div>

          {% if is_admin %}
            <div class="controls">
              <form class="inline" method="post" action="{{ url_for('promote_member', member_id=m.id) }}">
                <button class="btn btn-primary" type="submit">Promote</button>
              </form>
              <form class="inline" method="post" action="{{ url_for('demote_member', member_id=m.id) }}">
                <button class="btn btn-ghost" type="submit">Demote</button>
              </form>
              <form class="inline" method="post" action="{{ url_for('delete_member', member_id=m.id) }}" onsubmit="return confirm('Delete {{ m.username }}?')">
                <button class="btn danger" type="submit">Delete</button>
              </form>
            </div>
          {% endif %}
        </div>
      {% endfor %}
    </div>

    {% if is_admin %}
    <section class="panel">
      <h3>Add new member</h3>
      <form method="post" action="{{ url_for('add_member') }}">
        <input name="username" placeholder="Roblox username" required>
        <select name="rank_index">
          {% for idx, r in enumerate(ranks) %}
            <option value="{{ idx }}">{{ r }}</option>
          {% endfor %}
        </select>
        <button class="btn btn-primary" type="submit">Add member</button>
      </form>
    </section>

    <section class="panel" style="margin-top:12px">
      <h3>Admin activity (latest)</h3>
      <div style="max-height:240px;overflow:auto">
        {% for log in logs %}
          <div class="log-item"><strong>{{ log.at }}</strong> — <em>{{ log.admin }}</em> — {{ log.action }} {{ log.details and (' - ' ~ log.details) or '' }}</div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    <div style="margin-top:18px;color:#999">Note: avatars fetched from Roblox. Data saved in <code>players.json</code>.</div>
  </div>

<script>
function filter(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  document.querySelectorAll('#list .card').forEach(el=>{
    const uname = el.dataset.username || '';
    const rank = el.dataset.rank || '';
    el.style.display = (uname.includes(q) || rank.includes(q)) ? 'flex' : 'none';
  });
}
</script>
</body>
</html>
"""

# ---------------- Routes ----------------
@app.route("/")
def index():
    d = read_data()
    members_raw = d.get("members", [])
    members = []
    for m in members_raw:
        ri = int(m.get("rank_index", 0))
        members.append(
            {
                "id": int(m.get("id")),
                "username": m.get("username"),
                "rank_index": ri,
                "rank": PNP_RANKS[ri] if 0 <= ri < len(PNP_RANKS) else "Unknown",
                "avatar": get_roblox_avatar(m.get("username")) or None,
                "created_at": m.get("created_at"),
            }
        )
    return render_template_string(
        SITE_HTML,
        members=members,
        ranks=PNP_RANKS,
        is_admin=bool(session.get("is_admin")),
        logs=d.get("logs", []),
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
        flash("Invalid credentials", "error")
        return render_template_string(
            "<div style='max-width:420px;margin:40px auto;padding:20px;background:#0f0f0f;border-radius:8px;color:#fff'>"
            "<p style='color:#ff7b7b'>Invalid credentials</p><p><a href='{{ url_for(\"index\") }}'>Back</a></p></div>"
        )
    return render_template_string(
        "<div style='max-width:420px;margin:40px auto;padding:20px;background:#0f0f0f;border-radius:8px;color:#fff'>"
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
        flash("Username required", "error")
        return redirect(url_for("index"))
    d = read_data()
    members = d.setdefault("members", [])
    if any(x["username"].lower() == username.lower() for x in members):
        flash("Username already exists", "error")
        return redirect(url_for("index"))
    new_id = max((m.get("id", 0) for m in members), default=0) + 1
    now = datetime.now(timezone.utc).isoformat()
    members.append(
        {
            "id": new_id,
            "username": username,
            "rank_index": max(0, min(rank_index, len(PNP_RANKS) - 1)),
            "created_at": now,
        }
    )
    write_data(d)
    log_action(session.get("admin_user", "admin"), "add", f"{username} -> {PNP_RANKS[rank_index]}")
    # fetch avatar async so UI isn't blocked
    threading.Thread(target=get_roblox_avatar, args=(username,), daemon=True).start()
    return redirect(url_for("index"))


@app.route("/delete/<int:member_id>", methods=["POST"])
@admin_required
def delete_member(member_id):
    d = read_data()
    members = d.get("members", [])
    m = next((x for x in members if int(x.get("id")) == int(member_id)), None)
    if not m:
        flash("Member not found", "error")
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
        flash("Member not found", "error")
        return redirect(url_for("index"))
    cur = int(m.get("rank_index", 0))
    if cur >= len(PNP_RANKS) - 1:
        flash("Already at highest rank", "info")
        return redirect(url_for("index"))
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
        flash("Member not found", "error")
        return redirect(url_for("index"))
    cur = int(m.get("rank_index", 0))
    if cur <= 0:
        flash("Already at lowest rank", "info")
        return redirect(url_for("index"))
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


# ---------------- seed default data if empty ----------------
with app.app_context():
    ensure_datafile()
    d = read_data()
    if not d.get("members"):
        now = datetime.now(timezone.utc).isoformat()
        d["members"] = [{"id": 1, "username": "Roblox", "rank_index": 11, "created_at": now}]
        write_data(d)

# ---------------- run ----------------
if __name__ == "__main__":
    print(f"Starting app on 0.0.0.0:{PORT} (admin: {ADMIN_USERNAME})")
    # If deploying on Render, prefer running via gunicorn: `gunicorn app:app`
    app.run(host="0.0.0.0", port=PORT, debug=False)
