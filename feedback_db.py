import sqlite3
import os
import datetime
import json

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "politiscan.db")

_initialized = False


def init_db():
    global _initialized
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_email TEXT NOT NULL,
            article_url TEXT NOT NULL,
            article_headline TEXT,
            primary_tag TEXT,
            original_score REAL,
            source_name TEXT,
            affects_region INTEGER DEFAULT 0,
            action TEXT NOT NULL,
            promoted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS client_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_email TEXT NOT NULL UNIQUE,
            profile_json TEXT,
            generated_at TIMESTAMP,
            total_promotions_at_generation INTEGER,
            next_refresh_at TIMESTAMP
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_email ON feedback(client_email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_email_time ON feedback(client_email, promoted_at)")

    conn.commit()
    conn.close()

    if not _initialized:
        print(f"Database initialised at {DATABASE_PATH}")
        _initialized = True


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


init_db()


if __name__ == "__main__":
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("Tables in database:")
    for table in tables:
        print(f"  - {table['name']}")
    conn.close()
