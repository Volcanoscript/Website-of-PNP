# avatar_live.py
import requests

def get_avatar_url(username):
    try:
        # Get userId from username
        user_id_resp = requests.get(f"https://api.roblox.com/users/get-by-username?username={username}")
        if user_id_resp.status_code != 200:
            return None
        user_id = user_id_resp.json().get("Id")
        if not user_id:
            return None
        
        # Get avatar thumbnail
        avatar_resp = requests.get(
            f"https://thumbnails.roblox.com/v1/users/avatar?userIds={user_id}&size=420x420&format=Png&isCircular=false"
        )
        if avatar_resp.status_code != 200:
            return None
        data = avatar_resp.json()
        if data.get("data") and len(data["data"]) > 0:
            return data["data"][0]["imageUrl"]
        return None
    except Exception as e:
        return None
