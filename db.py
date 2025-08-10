
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/pnp_website_database"

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def ensure_tables():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    rank_index INTEGER NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id SERIAL PRIMARY KEY,
                    at TIMESTAMP WITH TIME ZONE NOT NULL,
                    admin TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT
                );
            """)
            conn.commit()

def read_data():
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, username, rank_index, created_at FROM members ORDER BY id;")
            members = [
                {
                    "id": row["id"],
                    "username": row["username"],
                    "rank_index": row["rank_index"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in cur.fetchall()
            ]

            cur.execute("SELECT at, admin, action, details FROM logs ORDER BY at DESC LIMIT 500;")
            logs = [
                {
                    "at": row["at"].isoformat(),
                    "admin": row["admin"],
                    "action": row["action"],
                    "details": row["details"],
                }
                for row in cur.fetchall()
            ]

    return {"members": members, "logs": logs}

def write_data(data):
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Upsert members
            cur.execute("DELETE FROM members;")
            for m in data.get("members", []):
                created_at = m.get("created_at")
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                cur.execute(
                    "INSERT INTO members (id, username, rank_index, created_at) VALUES (%s, %s, %s, %s);",
                    (m["id"], m["username"], m["rank_index"], created_at),
                )
            # Insert logs - you can either replace or append
            # For simplicity, replace logs
            cur.execute("DELETE FROM logs;")
            for log in data.get("logs", [])[:500]:
                at = datetime.fromisoformat(log["at"])
                cur.execute(
                    "INSERT INTO logs (at, admin, action, details) VALUES (%s, %s, %s, %s);",
                    (at, log["admin"], log["action"], log.get("details")),
                )
            conn.commit()
