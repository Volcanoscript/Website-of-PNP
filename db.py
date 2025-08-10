import os
import psycopg
from psycopg.rows import dict_row
from pathlib import Path
from datetime import datetime

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "players.json"

DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/pnp_website_database"

def ensure_tables():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
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

def get_all_members():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM members ORDER BY id;")
            return cur.fetchall()

def add_member(username, rank_index, created_at):
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO members (username, rank_index, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO NOTHING;
            """, (username, rank_index, created_at))

def log_action(at, admin, action, details=""):
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO logs (at, admin, action, details)
                VALUES (%s, %s, %s, %s);
            """, (at, admin, action, details))
