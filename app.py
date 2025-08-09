from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# Sample PNP Ranks
PNP_RANKS = [
    # PNCOs
    "Patrolman/Patrolwoman",
    "Police Corporal",
    "Police Staff Sergeant",
    "Police Master Sergeant",
    "Police Senior Master Sergeant",
    "Police Chief Master Sergeant",
    "Police Executive Master Sergeant",
    # PCOs
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

# Player database in memory
players = {}  # username -> {rank, avatar_url}

# Admin credentials (simple for demo)
ADMIN_USER = "admin"
ADMIN_PASS = "password123"

# Roblox avatar API
def get_roblox_avatar(username):
    try:
        # Get userId from username
        user_res = requests.get(
            f"https://api.roblox.com/users/get-by-username?username={username}"
        ).json()
        if "Id" not in user_res or user_res["Id"] == -1:
            return None
        user_id = user_res["Id"]

        # Get avatar thumbnail
        avatar_res = requests.get(
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png"
        ).json()
        if avatar_res.get("data") and len(avatar_res["data"]) > 0:
            return avatar_res["data"][0]["imageUrl"]
        return None
    except:
        return None

@app.route("/")
def index():
    return render_template("index.html", players=players, ranks=PNP_RANKS)

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    if data["username"] == ADMIN_USER and data["password"] == ADMIN_PASS:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Invalid credentials"})

@app.route("/add_player", methods=["POST"])
def add_player():
    data = request.json
    username = data["username"]
    rank = data["rank"]
    avatar_url = get_roblox_avatar(username) or "https://via.placeholder.com/150"
    players[username] = {"rank": rank, "avatar_url": avatar_url}
    return jsonify({"success": True, "players": players})

@app.route("/promote", methods=["POST"])
def promote():
    data = request.json
    username = data["username"]
    if username in players:
        current_rank = players[username]["rank"]
        if current_rank in PNP_RANKS:
            idx = PNP_RANKS.index(current_rank)
            if idx < len(PNP_RANKS) - 1:
                players[username]["rank"] = PNP_RANKS[idx + 1]
    return jsonify(players)

@app.route("/demote", methods=["POST"])
def demote():
    data = request.json
    username = data["username"]
    if username in players:
        current_rank = players[username]["rank"]
        if current_rank in PNP_RANKS:
            idx = PNP_RANKS.index(current_rank)
            if idx > 0:
                players[username]["rank"] = PNP_RANKS[idx - 1]
    return jsonify(players)

@app.route("/delete", methods=["POST"])
def delete():
    data = request.json
    username = data["username"]
    if username in players:
        del players[username]
    return jsonify(players)

if __name__ == "__main__":
    app.run(debug=True)
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
