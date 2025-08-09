#!/usr/bin/env python3
"""
PPNP roster app (ready to deploy)
- Admin login (default admin / PNP2025) — override via env ADMIN_USER / ADMIN_PASS
- Promote / Demote / Add / Edit / Delete
- Roblox avatar fetching by username
- Persists roster to data.json
- Uses PORT env var (Render provides it)
"""

import os, json, uuid, datetime
from functools import wraps
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify
import requests

# ---------- Config ----------
PORT = int(os.environ.get("PORT", 5000))
SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(24).hex())
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "PNP2025")
DATA_FILE = os.environ.get("DATA_FILE", "data.json")
ROBLOX_TIMEOUT = 6

# ---------- Rank ladder (ordered highest -> lowest) ----------
PNP_RANKS = [
  "Police General",
  "Police Lieutenant General",
  "Police Major General",
  "Police Brigadier General",
  "Police Colonel",
  "Police Lieutenant Colonel",
  "Police Major",
  "Police Captain",
  "Police Lieutenant",
  "Police Executive Master Sergeant",
  "Police Chief Master Sergeant",
  "Police Senior Master Sergeant",
  "Police Master Sergeant",
  "Police Staff Sergeant",
  "Police Corporal",
  "Patrolman",
  "Patrolwoman"
]

def rank_index(rank):
    try: return PNP_RANKS.index(rank)
    except: return len(PNP_RANKS)

# ---------- App ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# ---------- Persistence ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        return []
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

# create if missing
if not os.path.exists(DATA_FILE):
    save_data([])

# ---------- Roblox avatar helper ----------
def fetch_roblox_avatar(username):
    if not username: return ""
    try:
        u = requests.utils.requote_uri(username)
        r = requests.get(f"https://api.roblox.com/users/get-by-username?username={u}", timeout=ROBLOX_TIMEOUT)
        if r.status_code != 200: return ""
        j = r.json()
        user_id = j.get("Id") or j.get("id")
        if not user_id: return ""
        t = requests.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false", timeout=ROBLOX_TIMEOUT)
        if t.status_code != 200: return ""
        tj = t.json()
        if "data" in tj and tj["data"] and tj["data"][0].get("imageUrl"):
            return tj["data"][0]["imageUrl"]
    except Exception:
        return ""
    return ""

# ---------- Helpers ----------
def find_member(data, member_id):
    for m in data:
        if m.get("id") == member_id:
            return m
    return None

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
body{font-family:Inter,Arial,system-ui;background:#071023;color:#e6eef8;margin:0;padding:18px}
.wrap{max-width:1100px;margin:0 auto}
.controls{display:flex;gap:8px;align-items:center;margin:12px 0;flex-wrap:wrap}
input,select,button{padding:8px;border-radius:8px;background:#0b1220;border:1px solid rgba(255,255,255,0.03);color:#e6eef8}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:linear-gradient(180deg,#111827,#0b1220);padding:12px;border-radius:10px;display:flex;gap:12px;align-items:center}
.avatar{width:64px;height:64px;border-radius:8px;overflow:hidden;background:#06121b;flex-shrink:0}
.avatar img{width:100%;height:100%;object-fit:cover}
.role{color:#f59e0b;font-weight:700}
.actions{margin-left:auto;display:flex;flex-direction:column;gap:6px}
.small{font-size:13px;padding:6px 8px;border-radius:8px;background:transparent;border:1px solid rgba(255,255,255,0.03);color:#e6eef8}
.footer{margin-top:16px;color:#9ca3af;font-size:13px}
@media(max-width:420px){.actions{flex-direction:row}}
</style>
</head><body>
<div class="wrap">
  <header style="display:flex;justify-content:space-between;align-items:center">
    <div><h1 style="margin:0">PROBISYA ROLEPLAY CITY — <span style="color:#f59e0b">PNP ROSTER</span></h1><div style="color:#9ca3af">Admin required to modify roster</div></div>
    <div>{% if is_admin %}<form method="post" action="/logout" style="display:inline"><button class="small">Logout</button></form>{% else %}<a href="/login"><button class="small">Admin Login</button></a>{% endif %}</div>
  </header>

  <div class="controls">
    <input id="q" placeholder="Search rank, username, display name..." style="flex:1" oninput="filterItems()">
    <select id="sort" onchange="render()"><option value="rank">Sort: rank</option><option value="name">Sort: name</option><option value="username">Sort: username</option></select>
    <button onclick="fetchData()" class="small">Refresh</button>
    <button onclick="exportCSV()" class="small">Export CSV</button>
  </div>

  {% if is_admin %}
  <form method="post" action="/add" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <select name="rank" required>{% for r in ranks %}<option value="{{r}}">{{r}}</option>{% endfor %}</select>
    <input name="username" placeholder="Roblox username (exact)">
    <input name="display_name" placeholder="Display name (optional)">
    <button type="submit">Add Member</button>
  </form>
  {% endif %}

  <div id="grid" class="grid" style="margin-top:12px">
    {% for m in roster %}
    <div class="card" data-username="{{ m.username|lower }}" data-rank="{{ m.rank|lower }}" data-display="{{ (m.display_name or '')|lower }}">
      <div class="avatar">{% if m.avatar_url %}<img src="{{ m.avatar_url }}" alt="">{% else %}<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#000;background:#f59e0b;font-weight:700">{{ (m.display_name or m.username)[:2] }}</div>{% endif %}</div>
      <div style="flex:1">
        <div class="role">{{ m.rank }}</div>
        <div class="username"><strong>{{ m.display_name or m.username }}</strong><div style="color:#9ca3af;font-size:12px">{{ m.username }}</div></div>
        <div style="color:#9ca3af;font-size:12px;margin-top:6px">Added: {{ m.created_at }}</div>
      </div>
      <div class="actions">
        {% if is_admin %}
          <form method="post" action="/promote/{{ m.id }}"><button class="small" type="submit">Promote</button></form>
          <form method="post" action="/demote/{{ m.id }}"><button class="small" type="submit">Demote</button></form>
          <form method="post" action="/edit/{{ m.id }}"><button class="small" onclick="return promptEdit('{{ m.id }}')">Edit</button></form>
          <form method="post" action="/delete/{{ m.id }}" onsubmit="return confirm('Delete this member?')"><button class="small" style="background:#b91c1c;color:white">Delete</button></form>
        {% else %}
          <div style="color:#9ca3af;font-size:13px">—</div>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="footer">Data file: <code>{{ data_file }}</code></div>
</div>

<script>
function filterItems(){const q=document.getElementById('q').value.toLowerCase();document.querySelectorAll('#grid .card').forEach(card=>{const u=card.getAttribute('data-username')||'',r=card.getAttribute('data-rank')||'',d=card.getAttribute('data-display')||'';card.style.display=(u.includes(q)||r.includes(q)||d.includes(q))?'' : 'none';});}
function exportCSV(){const rows=[['id','rank','display_name','username','avatar_url','created_at']];document.querySelectorAll('#grid .card').forEach(card=>{const id = card.querySelector('form input[name=\"member_id\"]') ? card.querySelector('form input[name=\"member_id\"]').value : '';const rank = card.getAttribute('data-rank')||'';const username = card.getAttribute('data-username')||'';const display = card.getAttribute('data-display')||'';rows.push([id,rank,display,username,'','']);});const csv = rows.map(r=>r.map(c=>`\"${String(c||'').replace(/\"/g,'\"\"')}\"`).join(',')).join('\\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='probisya_roster.csv';a.click();}
function promptEdit(id){const newDisplay=prompt('New display name (leave blank to keep):');if(newDisplay===null) return false;const newUsername=prompt('New Roblox username (leave blank to keep):');if(newUsername===null) return false;const newRank=prompt('New rank (leave blank to keep):');if(newRank===null) return false;const f=document.createElement('form');f.method='POST';f.action='/edit/'+id;const add=(n,v)=>{const i=document.createElement('input');i.type='hidden';i.name=n;i.value=v;f.appendChild(i);};add('display_name', newDisplay);add('username', newUsername);add('rank', newRank);document.body.appendChild(f);f.submit();return false;}
function fetchData(){location.reload()}
</script>
</body></html>"""

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"content="width=device-width,initial-scale=1"><title>Admin Login</title>
<style>body{font-family:Inter,system-ui,Arial;background:#071023;color:#e6eef8;display:flex;align-items:center;justify-content:center;height:100vh}.box{background:#0b1220;padding:22px;border-radius:8px;width:340px}input{width:100%;padding:10px;margin:8px 0;border-radius:6px;border:1px solid rgba(255,255,255,0.05);background:#06121b;color:#e6eef8}button{width:100%;padding:10px;border-radius:6px;border:none;background:#f59e0b;color:#071023;font-weight:700}.hint{color:#9ca3af;font-size:13px;margin-top:10px;text-align:center}</style>
</head><body><div class="box"><h3 style="margin:0 0 8px">Admin login</h3>{% if error %}<div style="color:#fca5a5;margin-bottom:8px">{{ error }}</div>{% endif %}
<form method="post"><input name="username" placeholder="username" required /><input name="password" type="password" placeholder="password" required /><button type="submit">Login</button></form></div></body></html>"""

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    data = load_data()
    data_sorted = sorted(data, key=lambda m: (rank_index(m.get("rank")), (m.get("display_name") or "").lower(), m.get("created_at") or ""))
    return render_template_string(INDEX_HTML, roster=data_sorted, ranks=PNP_RANKS, is_admin=bool(session.get("admin")), data_file=DATA_FILE)

@app.route("/login", methods=["GET","POST"])
def login():
    err=None
    if request.method=="POST":
        u = request.form.get("username","")
        p = request.form.get("password","")
        if u==ADMIN_USER and p==ADMIN_PASS:
            session["admin"]=True
            return redirect(url_for("index"))
        err="Invalid credentials"
    return render_template_string(LOGIN_HTML, error=err)

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))

@app.route("/add", methods=["POST"])
def add_member():
    if not session.get("admin"): return "Admin required", 403
    username = (request.form.get("username") or "").strip()
    display_name = (request.form.get("display_name") or "").strip()
    rank = (request.form.get("rank") or "").strip()
    if not rank: return "Rank required", 400
    avatar_url = fetch_roblox_avatar(username) if username else ""
    member = {"id": str(uuid.uuid4()), "rank": rank, "display_name": display_name, "username": username, "avatar_url": avatar_url, "created_at": datetime.datetime.utcnow().isoformat()}
    data = load_data(); data.append(member); save_data(data)
    return redirect(url_for("index"))

@app.route("/promote/<member_id>", methods=["POST"])
def promote(member_id):
    if not session.get("admin"): return "Admin required", 403
    data=load_data(); m=find_member(data, member_id)
    if m:
        idx=rank_index(m.get("rank"))
        if idx>0: m["rank"]=PNP_RANKS[idx-1]; save_data(data)
    return redirect(url_for("index"))

@app.route("/demote/<member_id>", methods=["POST"])
def demote(member_id):
    if not session.get("admin"): return "Admin required", 403
    data=load_data(); m=find_member(data, member_id)
    if m:
        idx=rank_index(m.get("rank"))
        if idx < len(PNP_RANKS)-1: m["rank"]=PNP_RANKS[idx+1]; save_data(data)
    return redirect(url_for("index"))

@app.route("/edit/<member_id>", methods=["POST"])
def edit_member(member_id):
    if not session.get("admin"): return "Admin required", 403
    data=load_data(); m=find_member(data, member_id)
    if not m: return "Not found", 404
    new_display=request.form.get("display_name"); new_username=request.form.get("username"); new_rank=request.form.get("rank")
    if new_display and new_display.strip(): m["display_name"]=new_display.strip()
    if new_rank and new_rank.strip(): m["rank"]=new_rank.strip()
    if new_username and new_username.strip() and new_username.strip()!=m.get("username"):
        m["username"]=new_username.strip(); m["avatar_url"]=fetch_roblox_avatar(m["username"])
    save_data(data); return redirect(url_for("index"))

@app.route("/delete/<member_id>", methods=["POST"])
def delete_member(member_id):
    if not session.get("admin"): return "Admin required", 403
    data=load_data(); new=[x for x in data if x.get("id")!=member_id]
    if len(new)==len(data): return "Not found",404
    save_data(new); return redirect(url_for("index"))

@app.route("/api/roster", methods=["GET"])
def api_roster():
    return jsonify(load_data())

# ---------- Run ----------
if __name__=="__main__":
    print(f"Starting PPNP roster on port {PORT} (admin user: {ADMIN_USER})")
    app.run(host="0.0.0.0", port=PORT)
