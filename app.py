#!/usr/bin/env python3
"""
PPNP roster single-file app.py
- All PNP ranks included
- Roblox avatars by username
- Admin (add/edit/delete/promote/demote)
- Persist to data.json
- Uses PORT env var; binds 0.0.0.0
- Auto-installs flask & requests if missing
"""

import os, sys, subprocess, json, uuid, datetime
from functools import wraps

# Auto-install dependencies if missing
for pkg in ("flask", "requests"):
    try:
        __import__(pkg)
    except ImportError:
        print(f"Installing missing package: {pkg}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify
import requests

# ---------- Config ----------
PORT = int(os.environ.get("PORT", os.environ.get("RENDER_PORT", 5000)))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "PNP2025")
SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(24).hex())
DATA_FILE = os.environ.get("DATA_FILE", "data.json")
ROBLOX_TIMEOUT = 6

# ---------- PNP ranks (ordered highest -> lowest) with shortcodes ----------
PNP_RANKS = [
    ("Police General", "PGen"),
    ("Police Lieutenant General", "PLtGen"),
    ("Police Major General", "PMajGen"),
    ("Police Brigadier General", "PBrigGen"),
    ("Police Colonel", "PCOL"),
    ("Police Lieutenant Colonel", "PLtCol"),
    ("Police Major", "PMaj"),
    ("Police Captain", "PCpt"),
    ("Police Lieutenant", "PLt"),
    ("Police Executive Master Sergeant", "PEMS"),
    ("Police Chief Master Sergeant", "PCMS"),
    ("Police Senior Master Sergeant", "PSMS"),
    ("Police Master Sergeant", "PMSg"),
    ("Police Staff Sergeant", "PSSg"),
    ("Police Corporal", "PCpl"),
    ("Patrolman", "Patrolman"),
    ("Patrolwoman", "Patrolwoman")
]
RANK_NAMES = [r[0] for r in PNP_RANKS]

def rank_index(rank_name):
    try:
        return RANK_NAMES.index(rank_name)
    except ValueError:
        return len(RANK_NAMES)

# ---------- App ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# ---------- Persistence ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        # create default with example users similar to your screenshot
        sample = [
            {"id": str(uuid.uuid4()), "username": "Courkid123", "display_name": "", "rank": "Police Chief Master Sergeant", "avatar_url": "", "created_at": datetime.datetime.utcnow().isoformat()},
            {"id": str(uuid.uuid4()), "username": "SquadLeader59", "display_name": "", "rank": "Police Staff Sergeant", "avatar_url": "", "created_at": datetime.datetime.utcnow().isoformat()},
            {"id": str(uuid.uuid4()), "username": "BuliderMaster", "display_name": "", "rank": "Police Master Sergeant", "avatar_url": "", "created_at": datetime.datetime.utcnow().isoformat()},
            {"id": str(uuid.uuid4()), "username": "OfficerRamos", "display_name": "", "rank": "Police Captain", "avatar_url": "", "created_at": datetime.datetime.utcnow().isoformat()},
        ]
        save_data(sample)
        return sample
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Failed loading data:", e)
        return []

def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)

# ---------- Roblox avatar helpers ----------
def fetch_user_id(username):
    try:
        if not username: return None
        u = requests.utils.requote_uri(username)
        r = requests.get(f"https://api.roblox.com/users/get-by-username?username={u}", timeout=ROBLOX_TIMEOUT)
        if r.status_code != 200:
            return None
        j = r.json()
        return j.get("Id") or j.get("id")
    except Exception:
        return None

def fetch_avatar_url_by_username(username):
    try:
        user_id = fetch_user_id(username)
        if not user_id:
            return ""
        t = requests.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false", timeout=ROBLOX_TIMEOUT)
        if t.status_code != 200:
            return ""
        tj = t.json()
        if "data" in tj and tj["data"] and tj["data"][0].get("imageUrl"):
            return tj["data"][0]["imageUrl"]
    except Exception:
        return ""
    return ""

# ---------- Auth decorator ----------
def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped

# ---------- Templates ----------
INDEX_HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PROBISYA ROLEPLAY CITY — PNP ROSTER</title>
<style>
:root{--bg:#06101a;--card:#0b1217;--accent:#f5c153;--muted:#9aa6b0}
body{margin:0;font-family:Inter,system-ui,Arial;background:var(--bg);color:#e6eef8}
.container{max-width:1000px;margin:20px auto;padding:18px}
h1{text-align:center;margin:8px 0 18px;font-size:32px}
.search{display:block;width:100%;padding:14px;border-radius:14px;border:none;background:#0b1419;color:#e6eef8;font-size:18px;box-sizing:border-box}
.grid{display:grid;grid-template-columns:1fr;gap:14px;margin-top:18px}
.card{background:linear-gradient(180deg,#0f1720,#0b1217);padding:14px;border-radius:12px;display:flex;align-items:center;gap:14px;border:1px solid rgba(255,255,255,0.02)}
.avatar{width:84px;height:84px;border-radius:10px;background:#07121b;flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center}
.avatar img{width:100%;height:100%;object-fit:cover;display:block}
.info{flex:1}
.role{color:var(--accent);font-weight:700;font-size:20px}
.username{color:#fff;font-size:18px;margin-top:6px}
.actions{display:flex;flex-direction:column;gap:8px;margin-left:auto}
.btn{padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03);background:transparent;color:#e6eef8}
.btn.danger{background:#b91c1c;color:#fff;border:none}
.footer{margin-top:14px;color:var(--muted);font-size:13px}
.header-row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.controls{display:flex;gap:8px;align-items:center}
.form-inline{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
select,input,button{background:#07121b;color:#e6eef8;border:1px solid rgba(255,255,255,0.03);padding:8px;border-radius:8px}
@media(min-width:720px){.grid{grid-template-columns:1fr 1fr}}
</style>
</head><body>
<div class="container">
  <div class="header-row">
    <h1>PROBISYA ROLEPLAY CITY — <span style="color:var(--accent)">PNP ROSTER</span></h1>
    <div>
      {% if is_admin %}
        <form method="post" action="/logout" style="display:inline"><button class="btn">Logout</button></form>
      {% else %}
        <a href="/login"><button class="btn">Admin Login</button></a>
      {% endif %}
    </div>
  </div>

  <input id="q" oninput="filterCards()" class="search" placeholder="Search">

  {% if is_admin %}
  <form method="post" action="/add" class="form-inline" style="margin-top:12px">
    <select name="rank" required>
      {% for r,code in ranks %}
        <option value="{{ r }}">{{ r }} ({{ code }})</option>
      {% endfor %}
    </select>
    <input name="username" placeholder="Roblox username (exact)">
    <input name="display_name" placeholder="Display name (optional)">
    <button type="submit" class="btn">Add Member</button>
  </form>
  {% endif %}

  <div id="grid" class="grid">
    {% for rank, members in grouped.items() %}
      {% if members %}
        {% for m in members %}
        <div class="card" data-username="{{ m.username|lower }}" data-rank="{{ m.rank|lower }}" data-display="{{ (m.display_name or '')|lower }}">
          <div class="avatar">
            {% if m.avatar_url %}
              <img src="{{ m.avatar_url }}" alt="">
            {% else %}
              <div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#000;background:var(--accent);font-weight:700">{{ (m.display_name or m.username)[:2] }}</div>
            {% endif %}
          </div>
          <div class="info">
            <div class="role">{{ m.rank }} ({{ rank_codes[m.rank] }})</div>
            <div class="username">{{ m.display_name or m.username }}</div>
            <div style="color:var(--muted);font-size:12px;margin-top:6px">Added: {{ m.created_at }}</div>
          </div>
          <div class="actions">
            {% if is_admin %}
              <form method="post" action="/promote/{{ m.id }}"><button class="btn" type="submit">Promote</button></form>
              <form method="post" action="/demote/{{ m.id }}"><button class="btn" type="submit">Demote</button></form>
              <form method="post" action="/edit/{{ m.id }}"><button class="btn" onclick="return editPrompt('{{ m.id }}')">Edit</button></form>
              <form method="post" action="/delete/{{ m.id }}" onsubmit="return confirm('Delete this member?')"><button class="btn danger" type="submit">Delete</button></form>
            {% else %}
              <div style="color:var(--muted);font-size:13px">—</div>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      {% endif %}
    {% endfor %}
  </div>

  <div class="footer">Data file: <code>{{ data_file }}</code></div>
</div>

<script>
function filterCards(){
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('#grid .card').forEach(card=>{
    const u = card.getAttribute('data-username')||'';
    const r = card.getAttribute('data-rank')||'';
    const d = card.getAttribute('data-display')||'';
    card.style.display = (u.includes(q) || r.includes(q) || d.includes(q))? '' : 'none';
  });
}
function editPrompt(id){
  const newDisplay = prompt("New display name (leave blank to keep):");
  if(newDisplay === null) return false;
  const newUsername = prompt("New Roblox username (leave blank to keep):");
  if(newUsername === null) return false;
  const newRank = prompt("New rank (leave blank to keep):");
  if(newRank === null) return false;
  const f = document.createElement('form'); f.method='POST'; f.action='/edit/'+id;
  const add=(n,v)=>{ const i=document.createElement('input'); i.type='hidden'; i.name=n; i.value=v; f.appendChild(i); };
  add('display_name', newDisplay); add('username', newUsername); add('rank', newRank);
  document.body.appendChild(f); f.submit();
  return false;
}
</script>
</body></html>
"""

LOGIN_HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin Login</title>
<style>
body{font-family:Inter,Arial,system-ui;background:#071023;color:#e6eef8;display:flex;align-items:center;justify-content:center;height:100vh}
.box{background:#0b1220;padding:22px;border-radius:8px;width:360px}
input{width:100%;padding:10px;margin:8px 0;border-radius:6px;border:1px solid rgba(255,255,255,0.05);background:#06121b;color:#e6eef8}
button{width:100%;padding:10px;border-radius:6px;border:none;background:#f59e0b;color:#071023;font-weight:700}
.error{color:#fca5a5;margin-bottom:8px}
</style>
</head><body>
<div class="box">
  <h3 style="margin:0 0 8px">Admin login</h3>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="post">
    <input name="username" placeholder="username" required value="{{ username or '' }}" />
    <input name="password" type="password" placeholder="password" required />
    <button type="submit">Login</button>
  </form>
  <div style="color:#9ca3af;font-size:13px;margin-top:8px">Default admin / PNP2025</div>
</div>
</body></html>
"""

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    data = load_data()
    # group members by rank in PNP order (include empty ranks)
    grouped = {r: [] for r in RANK_NAMES}
    for m in data:
        grouped.setdefault(m.get("rank"), []).append(m)
    # ensure every rank exists as key and sort members by created_at
    for r in list(grouped.keys()):
        grouped[r] = sorted(grouped[r], key=lambda x: x.get("created_at", ""))
    # create rank codes map
    rank_codes = {name: code for (name, code) in PNP_RANKS}
    return render_template_string(INDEX_HTML, roster=data, grouped=grouped, ranks=PNP_RANKS, is_admin=bool(session.get("admin")), data_file=DATA_FILE, rank_codes=rank_codes)

@app.route("/login", methods=["GET","POST"])
def login():
    err = None
    if request.method == "POST":
        u = request.form.get("username","")
        p = request.form.get("password","")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("index"))
        err = "Invalid credentials"
    return render_template_string(LOGIN_HTML, error=err, username=ADMIN_USER)

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))

@app.route("/add", methods=["POST"])
def add_member():
    if not session.get("admin"):
        return "Admin required", 403
    username = (request.form.get("username") or "").strip()
    display_name = (request.form.get("display_name") or "").strip()
    rank = (request.form.get("rank") or "").strip()
    if not rank:
        return "Rank required", 400
    avatar_url = fetch_avatar_url_by_username(username) if username else ""
    member = {"id": str(uuid.uuid4()), "rank": rank, "display_name": display_name, "username": username, "avatar_url": avatar_url, "created_at": datetime.datetime.utcnow().isoformat()}
    data = load_data(); data.append(member); save_data(data)
    return redirect(url_for("index"))

@app.route("/edit/<member_id>", methods=["POST"])
def edit_member(member_id):
    if not session.get("admin"):
        return "Admin required", 403
    data = load_data(); m = find_member(data, member_id)
    if not m:
        return "Not found", 404
    new_display = request.form.get("display_name")
    new_username = request.form.get("username")
    new_rank = request.form.get("rank")
    if new_display is not None and new_display.strip() != "":
        m["display_name"] = new_display.strip()
    if new_rank is not None and new_rank.strip() != "":
        m["rank"] = new_rank.strip()
    if new_username is not None and new_username.strip() != "" and new_username.strip() != m.get("username"):
        m["username"] = new_username.strip()
        m["avatar_url"] = fetch_avatar_url_by_username(m["username"])
    save_data(data)
    return redirect(url_for("index"))

@app.route("/delete/<member_id>", methods=["POST"])
def delete_member(member_id):
    if not session.get("admin"):
        return "Admin required", 403
    data = load_data(); new = [x for x in data if x.get("id") != member_id]
    if len(new) == len(data):
        return "Not found", 404
    save_data(new)
    return redirect(url_for("index"))

@app.route("/promote/<member_id>", methods=["POST"])
def promote_member(member_id):
    if not session.get("admin"):
        return "Admin required", 403
    data = load_data(); m = find_member(data, member_id)
    if not m:
        return "Not found", 404
    idx = rank_index(m.get("rank"))
    if idx > 0:
        m["rank"] = RANK_NAMES[idx-1]
        save_data(data)
    return redirect(url_for("index"))

@app.route("/demote/<member_id>", methods=["POST"])
def demote_member(member_id):
    if not session.get("admin"):
        return "Admin required", 403
    data = load_data(); m = find_member(data, member_id)
    if not m:
        return "Not found", 404
    idx = rank_index(m.get("rank"))
    if idx < len(RANK_NAMES)-1:
        m["rank"] = RANK_NAMES[idx+1]
        save_data(data)
    return redirect(url_for("index"))

@app.route("/api/roster", methods=["GET"])
def api_roster():
    return jsonify(load_data())

# ---------- Start ----------
if __name__ == "__main__":
    print(f"Starting PPNP roster on port {PORT} (admin: {ADMIN_USER})")
    # Ensure data avatars are filled (non-blocking)
    data_now = load_data()
    updated = False
    for m in data_now:
        if not m.get("avatar_url") and m.get("username"):
            url = fetch_avatar_url_by_username(m["username"])
            if url:
                m["avatar_url"] = url
                updated = True
    if updated:
        save_data(data_now)
    app.run(host="0.0.0.0", port=PORT)
