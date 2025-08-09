import os
import requests
from flask import Flask, request, redirect, session, jsonify, render_template

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

# Admin credentials (set in Render Environment Variables for security)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "PNP2025")

# If you want a fixed Roblox ID to always show this avatar
# Example: ROBLOX_FIXED_ID = 1 will show "Roblox" default account
ROBLOX_FIXED_ID = os.getenv("ROBLOX_FIXED_ID")  # Set this in Render if needed

# ----------------------------------------------------------------------------
# ROBLOX API FUNCTIONS
# ----------------------------------------------------------------------------
def get_roblox_userid(username: str):
    """
    Given a Roblox username, fetch the user ID from Roblox's API.
    Returns None if not found or on error.
    """
    try:
        url = "https://users.roblox.com/v1/usernames/users"
        payload = {"usernames": [username]}
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("data") and len(data["data"]) > 0:
            return data["data"][0].get("id")
    except Exception:
        return None

def roblox_avatar_url(userid: int):
    """
    Given a Roblox user ID, return the avatar image URL.
    """
    if not userid:
        return None
    return (
        f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
        f"?userIds={userid}&size=150x150&format=Png&isCircular=true"
    )

# ----------------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    roblox_avatar = None
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # Decide which Roblox avatar to use
        if ROBLOX_FIXED_ID:  # Always use fixed ID
            roblox_avatar = roblox_avatar_url(ROBLOX_FIXED_ID)
        else:  # Lookup from typed username
            uid = get_roblox_userid(username)
            if uid:
                roblox_avatar = roblox_avatar_url(uid)

        # Check credentials
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect("/dashboard")
        else:
            error = "Invalid credentials"

    return render_template("login.html", roblox_avatar_url=roblox_avatar, error=error)

@app.route("/roblox_avatar_preview")
def roblox_avatar_preview():
    """
    API endpoint — given ?username=xxx returns Roblox avatar URL in JSON.
    """
    if ROBLOX_FIXED_ID:
        return jsonify({"url": roblox_avatar_url(ROBLOX_FIXED_ID)})
    username = request.args.get("username", "").strip()
    uid = get_roblox_userid(username)
    if uid:
        return jsonify({"url": roblox_avatar_url(uid)})
    return jsonify({"url": None})

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect("/login")
    return """
    <h1>Dashboard</h1>
    <p>Welcome, admin!</p>
    <p><a href='/logout'>Logout</a></p>
    """

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")

# ----------------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
