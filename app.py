import os
import requests
from flask import Flask, request, redirect, session, jsonify, render_template_string

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "replace_this_secret")

# ===== CONFIG =====
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "PNP2025")

# ===== Roblox Avatar Fetch Functions =====
def get_roblox_userid(username: str):
    url = "https://users.roblox.com/v1/usernames/users"
    resp = requests.post(url, json={"usernames": [username], "excludeBannedUsers": False}, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if data.get("data"):
        return data["data"][0].get("id")
    return None

def roblox_avatar_url_for_userid(userid: int, size=100, circular=True):
    is_circ = "true" if circular else "false"
    return (
        f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
        f"?userIds={userid}&size={size}x{size}&format=Png&isCircular={is_circ}"
    )

# ===== HTML TEMPLATE =====
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Admin Login</title>
  <style>
    body { background: #111; color: white; font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; }
    .login-box { background: #1e1e1e; padding: 20px; border-radius: 8px; width: 300px; text-align: center; }
    input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 5px; border: none; }
    button { background: #f6b10a; color: black; padding: 10px; border: none; border-radius: 5px; cursor: pointer; width: 100%; font-weight: bold; }
    img { border-radius: 50%; margin-bottom: 10px; }
  </style>
</head>
<body>
  <div class="login-box">
    <h2>Admin login</h2>
    {% if roblox_avatar_url %}
      <img src="{{ roblox_avatar_url }}" width="80" height="80">
    {% else %}
      <img id="roblox-preview-img" src="" width="80" height="80" style="display:none;">
    {% endif %}
    {% if error %}
      <p style="color:red;">{{ error }}</p>
    {% endif %}
    <form method="POST">
      <input type="text" name="username" id="roblox-name-input" placeholder="Username" required>
      <input type="password" name="password" placeholder="Password" required>
      <button type="submit">Login</button>
    </form>
  </div>

  <script>
  const nameInput = document.getElementById('roblox-name-input');
  const previewImg = document.getElementById('roblox-preview-img');

  nameInput.addEventListener('input', async () => {
    const name = nameInput.value.trim();
    if (!name) { previewImg.style.display = 'none'; return; }
    const res = await fetch(`/roblox_avatar_preview?username=${encodeURIComponent(name)}`);
    const data = await res.json();
    if (data.url) {
      previewImg.src = data.url;
      previewImg.style.display = 'block';
    } else {
      previewImg.style.display = 'none';
    }
  });
  </script>
</body>
</html>
"""

# ===== ROUTES =====
@app.route("/", methods=["GET"])
def index():
    if "logged_in" in session:
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    roblox_avatar_url = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        try:
            uid = get_roblox_userid(username)
            if uid:
                roblox_avatar_url = roblox_avatar_url_for_userid(uid, size=128)
        except Exception:
            roblox_avatar_url = None

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect("/dashboard")
        else:
            return render_template_string(LOGIN_HTML, error="Invalid credentials", roblox_avatar_url=roblox_avatar_url)

    return render_template_string(LOGIN_HTML, roblox_avatar_url=roblox_avatar_url)

@app.route("/roblox_avatar_preview")
def roblox_preview():
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"url": None})
    try:
        uid = get_roblox_userid(username)
        if uid:
            return jsonify({"url": roblox_avatar_url_for_userid(uid, size=128)})
    except Exception:
        pass
    return jsonify({"url": None})

@app.route("/dashboard")
def dashboard():
    if "logged_in" not in session:
        return redirect("/login")
    return "<h1>Welcome to the Admin Dashboard</h1><p><a href='/logout'>Logout</a></p>"

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")

if __name__ == "__main__":
    app.run(debug=True)
