import os
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://pnp_website_database_user:JgSW6mMvhBVernIALTJpR296LMPIlme9@dpg-d2bu4bp5pdvs73d4lmd0-a/pnp_website_database"

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
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, rank_index, created_at FROM members;")
            rows = cur.fetchall()
    return rows

def add_member(username, rank_index, created_at):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO members (username, rank_index, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    rank_index = EXCLUDED.rank_index,
                    created_at = EXCLUDED.created_at;
            """, (username, rank_index, created_at))
        conn.commit()

def log_action(at, admin, action, details):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO logs (at, admin, action, details)
                VALUES (%s, %s, %s, %s);
            """, (at, admin, action, details))
        conn.commit()
