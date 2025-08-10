import os
import json
import psycopg
from pathlib import Path
from datetime import datetime

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "players.json"

DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a/pnp_website_database"

def ensure_tables():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    rank_index INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id SERIAL PRIMARY KEY,
                    at TIMESTAMP NOT NULL,
                    admin TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT
                );
            """)
            conn.commit()

def load_json():
    if not DATA_FILE.exists():
        print("players.json not found!")
        return None
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_iso8601(dt_str):
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None

def sync_members(members):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            data = []
            for m in members:
                created_at = parse_iso8601(m.get("created_at")) or datetime.utcnow()
                data.append((
                    m.get("id"),
                    m.get("username"),
                    m.get("rank_index", 0),
                    created_at,
                ))

            sql = """
            INSERT INTO members (id, username, rank_index, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                rank_index = EXCLUDED.rank_index,
                created_at = EXCLUDED.created_at;
            """
            cur.executemany(sql, data)
            conn.commit()
    print(f"Synced {len(members)} members.")

def sync_logs(logs):
    if not logs:
        return
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT at, admin, action, details FROM logs;")
            existing = set(cur.fetchall())

            data = []
            for log in logs:
                at = parse_iso8601(log.get("at"))
                admin = log.get("admin", "")
                action = log.get("action", "")
                details = log.get("details", "")
                key = (at, admin, action, details)
                if key not in existing:
                    data.append((at, admin, action, details))
                    existing.add(key)

            if data:
                sql = """
                INSERT INTO logs (at, admin, action, details)
                VALUES (%s, %s, %s, %s)
                """
                cur.executemany(sql, data)
                conn.commit()
                print(f"Synced {len(data)} new logs.")
            else:
                print("No new logs to sync.")
