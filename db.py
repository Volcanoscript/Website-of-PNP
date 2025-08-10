import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

DATABASE_URL = os.getenv("postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a.oregon-postgres.render.com/pnp_website_database")

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def ensure_tables():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id SERIAL PRIMARY KEY,
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

def get_all_members():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM members ORDER BY id ASC;")
            return cur.fetchall()

def add_member(username, rank_index, created_at):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO members (username, rank_index, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO NOTHING;
            """, (username, rank_index, created_at))
            conn.commit()

def update_member_rank(member_id, new_rank_index):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE members SET rank_index = %s WHERE id = %s;", (new_rank_index, member_id))
            conn.commit()

def delete_member(member_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM members WHERE id = %s;", (member_id,))
            conn.commit()

def log_action(at, admin, action, details=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO logs (at, admin, action, details)
                VALUES (%s, %s, %s, %s);
            """, (at, admin, action, details))
            conn.commit()

def get_logs(limit=500):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM logs ORDER BY at DESC LIMIT %s;", (limit,))
            return cur.fetchall()
