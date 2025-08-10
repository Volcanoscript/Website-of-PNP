import os
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse

DATABASE_URL = os.getenv("postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/pnp_website_databaseL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable is not set")

# Parse DATABASE_URL
result = urlparse(DATABASE_URL)
DB_CONFIG = {
    "dbname": result.path[1:],  # strip leading /
    "user": result.username,
    "password": result.password,
    "host": result.hostname,
    "port": result.port,
}

def get_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

def init_db():
    """Create tables if not exists"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    rank_index INT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id SERIAL PRIMARY KEY,
                    at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    admin TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT
                );
            """)
        conn.commit()

def get_members():
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM members ORDER BY id;")
            return cur.fetchall()

def add_member(username, rank_index):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO members (username, rank_index) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING RETURNING id;",
                (username, rank_index),
            )
            new_id = cur.fetchone()
            conn.commit()
            return new_id[0] if new_id else None

def delete_member(member_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM members WHERE id = %s;", (member_id,))
            conn.commit()

def update_member_rank(member_id, new_rank_index):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE members SET rank_index = %s WHERE id = %s;", (new_rank_index, member_id))
            conn.commit()

def log_action(admin, action, details=""):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO logs (admin, action, details) VALUES (%s, %s, %s);",
                (admin, action, details),
            )
            conn.commit()

def get_logs(limit=500):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM logs ORDER BY at DESC LIMIT %s;", (limit,))
            return cur.fetchall()
