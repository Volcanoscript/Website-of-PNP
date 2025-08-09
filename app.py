#!/usr/bin/env python3
import os
import uuid
import json
import datetime
import requests
from functools import wraps
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify
from flask_cors import CORS

# ---------- Config ----------
PORT = int(os.environ.get("PORT", 5000))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "PNP2025")
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_secret")
DATA_FILE = os.environ.get("DATA_FILE", "data.json")
ROBLOX_TIMEOUT = 6  # seconds

# ---------- PNP ranks (highest -> lowest) with shortcodes ----------
PNP_RANKS = [
    ("Police General", "PGen"),
    ("Police Lieutenant General", "PLtGen"),
    ("Police Major General", "PMajGen"),
    ("Police Brigadier General", "PBrigGen"),
    ("Police Colonel", "PCol"),
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
    ("Patrolwoman", "Patrolwoman"),
]

RANK_NAMES = [r[0] for r in PNP_RANKS]
RANK_CODES = {r[0]: r[1] for r in PNP_RANKS}


# ---------- Flask app ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app)


# ---------- Persistence ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        # create file with sample members
        sample = [
            {
                "id": str(uuid.uuid4()),
                "username": "Courkid123",
                "display_name": "",
                "rank": "Police Chief Master Sergeant",
                "avatar_url": "",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "username": "SquadLeader59",
                "display_name": "",
                "rank": "Police Staff Sergeant",
                "avatar_url": "",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        ]
        save_data(sample)
        return sample
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


# ---------- Roblox avatar helpers ----------
def fetch_user_id(username: str):
    if not username:
        return None
    try:
        q = requests.utils.requote_uri(username)
        r = requests.get(f"https://api.roblox.com/users/get-by-username?username={q}", timeout=ROBLOX_TIMEOUT)
        if r.status_code != 200:
            return None
        j = r.json()
        return j.get("Id") or j.get("id")
    except Exception:
        return None


def fetch_avatar_by_userid(user_id):
    try:
        if not user_id:
            return ""
        r = requests.get(
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false",
            timeout=ROBLOX_TIMEOUT,
        )
        if r.status_code != 200:
            return ""
        j = r.json()
        if "data" in j and j["data"] and j["data"][0].get("imageUrl"):
            return j["data"][0]["imageUrl"]
    except Exception:
        return ""
    return ""


def fetch_avatar_by_username(username: str):
    uid = fetch_user_id(username)
    if not uid:
        return ""
    return fetch_avatar_by_userid(uid)


# ---------- Helpers ----------
def find_member(data, member_id):
    for m in data:
        if m.get("id") == member_id:
            return m
    return None


def rank_index(rank_name):
    try:
        return RANK_NAMES.index(rank_name)
    except ValueError:
        return len(RANK_NAMES)


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


# ---------- Templates (inline) ----------
INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PPNP Roster</title>
<style>
:root{--bg:#06101a;--card:#0b1217;--accent:#f5c153;--muted:#9aa6b0}
body{margin:0;font-family:Inter,system-ui,Arial;background:var(--bg);color:#e6eef8}
.container{max-width:1000px;margin:20px auto;padding:18px}
h1{text-align:center;margin:8px 0 18px;font-size:28px}
.search{display:block;width:100%;padding:12px;border-radius:12px;border:none;background:#0b1419;color:#e6eef8;font-size:16px;box-sizing:border-box}
.grid{display:grid;grid-template-columns:1fr;gap:12px;margin-top:14px}
.card{background:linear-gradient(180deg,#0f1720,#0b1217);padding:12px;border-radius:10px;display:flex;align-items:center;gap:12px;border:1px solid rgba(255,255,255,0.02)}
.avatar{width:84px;height:84px;border-radius:10px;overflow:hidden;background:#07121b;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.avatar img{width:100%;height:100%;object-fit:cover}
.info{flex:1}
.role{color:var(--accent);font-weight:700;font-size:18px}
.username{color:#fff;font-size:16px;margin-top:6px}
.actions{display:flex;flex-direction:column;gap:8px;margin-left:auto}
.btn{padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03);background:transparent;color:#e6eef8}
.btn.danger{background:#b91c1c;color:#fff;border:none}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
select,input,button{background:#07121b;color:#e6eef8;border:1px solid rgba(255,255,255,0.03);padding:8px;border-radius:8px}
.footer{margin-top:14px;color:var(--muted);font-size:13px}
@media(min-width:720px){.grid{grid-template-columns:repeat(2,1fr)}}
</style>
</head><body>
<div class="container">
  <h1>PROBISYA ROLEPLAY CITY — <span style="color:var(--accent)">PNP ROSTER</span></h1>
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="flex:1;margin-right:12px"><input id="q" class="search" placeholder="Search rank, username... (type to filter)"></div>
    <div>
      {% if is_admin %}
        <form method="post" action="/logout" style="display:inline"><button class="btn">Logout</button></form>
      {% else %}
        <a href="/login"><button class="btn">Admin Login</button></a>
      {% endif %}
    </div>
  </div>

  {% if is_admin %}
  <form method="post" action="/add" class="controls" style="margin-top:12px">
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
    {% for rank in rank_order %}
      <div style="font-weight:700;color:#9aa6b0;margin-top:6px">{{ loop.index }}. {{ rank }} — ({{ counts[rank]|default(0) }})</div>
      {% if grouped[rank] %}
        {% for m in grouped[rank] %}
        <div class="card" data-username="{{ m.username|lower }}" data-rank="{{ m.rank|lower }}" data-display="{{ (m.display_name or '')|lower }}">
          <div class="avatar">
            {% if m.avatar_url %}
              <img src="{{ m.avatar_url }}" alt="">
            {% else %}
              <div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#000;background:var(--accent);font-weight:700">{{ (m.display_name or m.username)[:2] }}</div>
            {% endif %}
          </div>
          <div class="info">
            <div class="role">{{ m.rank }} <small style="color:#9aa6b0">({{ rank_codes[m.rank] if m.rank in rank_codes else '' }})</small></div>
            <div class="username">{{ m.display_name or m.username }}</div>
            <div style="color:#9aa6b0;font-size:12px;margin-top:6px">Added: {{ m.created_at }}</div>
          </div>
          <div class="actions">
            {% if is_admin %}
              <form method="post" action="/promote/{{ m.id }}"><button class="btn" type="submit">Promote</button></form>
              <form method="post" action="/demote/{{ m.id }}"><button class="btn" type="submit">Demote</button></form>
              <form method="post" action="/edit/{{ m.id }}"><button class="btn" onclick="return editPrompt('{{ m.id }}')">Edit</button></form>
              <form method="post" action="/delete/{{ m.id }}" onsubmit="return confirm('Delete this member?')"><button class="btn danger" type="submit">Delete</button></form>
            {% else %}
              <div style="color:#9aa6b0;font-size:13px">—</div>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      {% else %}
        <div style="color:#5b6970;padding:8px 0 12px">No members for this rank.</div>
      {% endif %}
    {% endfor %}
  </div>

  <div class="footer">Data file: <code>{{ data_file }}</code></div>
</div>

<script>
document.getElementById('q').addEventListener('input', () => {
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('#grid .card').forEach(card=>{
    const u = card.getAttribute('data-username')||'';
    const r = card.getAttribute('data-rank')||'';
    const d = card.getAttribute('data-display')||'';
    card.style.display = (u.includes(q) || r.includes(q) || d.includes(q))? '' : 'none';
  });
});
function editPrompt(id){
  const newDisplay = prompt("New display name (leave blank to keep):");
  if(newDisplay===null) return false;
  const newUsername = prompt("New Roblox username (leave blank to keep):");
  if(newUsername===null) return false;
  const newRank = prompt("New rank (leave blank to keep):");
  if(newRank===null) return false;
  const f=document.createElement('form'); f.method='POST'; f.action='/edit/'+id;
  const add=(n,v)=>{ const i=document.createElement('input'); i.type='hidden'; i.name=n; i.value=v; f.appendChild(i); };
  add('display_name', newDisplay); add('username', newUsername); add('rank', newRank);
  document.body.appendChild(f); f.submit(); return false;
}
</script>
</body></html>
"""

LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin Login</title>
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
  <div style="color:#9ca3af;font-size:13px;margin-top:10px">Default: admin / PNP2025 (change via env vars)</div>
</div>
</body></html>"""


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    # load and attempt to fill missing avatars (once)
    data = load_data()
    updated = False
    for m in data:
        if m.get("username") and not m.get("avatar_url"):
            url = fetch_avatar_by_username(m["username"])
            if url:
                m["avatar_url"] = url
                updated = True
    if updated:
        save_data(data)

    # group by rank preserving PNP order
    grouped = {r: [] for r in RANK_NAMES}
    for m in data:
        grouped.setdefault(m.get("rank"), []).append(m)

    # sort each group's members by created_at
    for k in grouped:
        grouped[k] = sorted(grouped[k], key=lambda x: x.get("created_at", ""))

    # counts
    counts = {r: len(grouped.get(r, [])) for r in RANK_NAMES}

    return render_template_string(
        INDEX_HTML,
        ranks=PNP_RANKS,
        rank_order=RANK_NAMES,
        grouped=grouped,
        counts=counts,
        is_admin=bool(session.get("admin")),
        data_file=DATA_FILE,
        rank_codes=RANK_CODES,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
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
@admin_required
def add_member():
    username = (request.form.get("username") or "").strip()
    display_name = (request.form.get("display_name") or "").strip()
    rank = (request.form.get("rank") or "").strip()
    if not rank:
        return "Rank required", 400
    avatar_url = fetch_avatar_by_username(username) if username else ""
    member = {
        "id": str(uuid.uuid4()),
        "rank": rank,
        "display_name": display_name,
        "username": username,
        "avatar_url": avatar_url,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    data = load_data()
    data.append(member)
    save_data(data)
    return redirect(url_for("index"))


@app.route("/edit/<member_id>", methods=["POST"])
@admin_required
def edit_member(member_id):
    data = load_data()
    m = find_member(data, member_id)
    if not m:
        return "Not found", 404
    new_display = request.form.get("display_name")
    new_username = request.form.get("username")
    new_rank = request.form.get("rank")
    if new_display and new_display.strip():
        m["display_name"] = new_display.strip()
    if new_rank and new_rank.strip():
        m["rank"] = new_rank.strip()
    if new_username and new_username.strip() and new_username.strip() != m.get("username"):
        m["username"] = new_username.strip()
        m["avatar_url"] = fetch_avatar_by_username(m["username"])
    save_data(data)
    return redirect(url_for("index"))


@app.route("/delete/<member_id>", methods=["POST"])
@admin_required
def delete_member(member_id):
    data = load_data()
    new = [x for x in data if x.get("id") != member_id]
    if len(new) == len(data):
        return "Not found", 404
    save_data(new)
    return redirect(url_for("index"))


@app.route("/promote/<member_id>", methods=["POST"])
@admin_required
def promote_member(member_id):
    data = load_data()
    m = find_member(data, member_id)
    if not m:
        return "Not found", 404
    idx = rank_index(m.get("rank"))
    if idx > 0:
        m["rank"] = RANK_NAMES[idx - 1]
        save_data(data)
    return redirect(url_for("index"))


@app.route("/demote/<member_id>", methods=["POST"])
@admin_required
def demote_member(member_id):
    data = load_data()
    m = find_member(data, member_id)
    if not m:
        return "Not found", 404
    idx = rank_index(m.get("rank"))
    if idx < len(RANK_NAMES) - 1:
        m["rank"] = RANK_NAMES[idx + 1]
        save_data(data)
    return redirect(url_for("index"))


@app.route("/api/roster", methods=["GET"])
def api_roster():
    return jsonify(load_data())


# ---------- Run ----------
if __name__ == "__main__":
    # fill missing avatars on first start (non-blocking simple approach)
    data_now = load_data()
    updated = False
    for m in data_now:
        if not m.get("avatar_url") and m.get("username"):
            url = fetch_avatar_by_username(m["username"])
            if url:
                m["avatar_url"] = url
                updated = True
    if updated:
        save_data(data_now)

    print(f"Starting PPNP roster on port {PORT} (admin: {ADMIN_USER})")
    app.run(host="0.0.0.0", port=PORT)
