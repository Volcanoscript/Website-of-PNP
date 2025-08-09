from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

players = {}  # Example structure: {"john": {"score": 10}}

@app.route("/add_player", methods=["POST"])
def add_player():
    data = request.json
    username = data.get("username")
    if username in players:
        return jsonify({"error": "Player already exists"}), 400
    players[username] = {"score": 0}
    return jsonify({"message": f"Player {username} added"}), 201

@app.route("/remove_player", methods=["POST"])
def remove_player():
    data = request.json
    username = data.get("username")
    if username not in players:
        return jsonify({"error": "Player not found"}), 404
    del players[username]
    return jsonify({"message": f"Player {username} removed"}), 200

@app.route("/players", methods=["GET"])
def list_players():
    return jsonify(players)

if __name__ == "__main__":
    # Always the last line
    app.run(host="0.0.0.0", port=5000, debug=True)    data["logs"].insert(0, {
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
