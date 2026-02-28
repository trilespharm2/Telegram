import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "/data/bot.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_recordbot_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS recordbot_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            email TEXT,
            username TEXT UNIQUE,
            password_hash TEXT,
            activation_code TEXT,
            stripe_customer_id TEXT,
            credit_seconds REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS recordbot_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_telegram_id INTEGER,
            model_name TEXT,
            added_at TEXT,
            UNIQUE(user_telegram_id, model_name)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS recordbot_recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_telegram_id INTEGER,
            model_name TEXT,
            started_at TEXT,
            ended_at TEXT,
            duration_seconds REAL DEFAULT 0,
            status TEXT DEFAULT 'recording'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS recordbot_activation_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            email TEXT,
            plan_key TEXT,
            credit_hours REAL,
            used INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_rb_user(telegram_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM recordbot_users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


def get_rb_user_by_username(username):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM recordbot_users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row


def get_rb_user_by_code(code):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM recordbot_users WHERE activation_code = ?", (code,)
    ).fetchone()
    conn.close()
    return row


def get_rb_user_by_stripe_customer(stripe_customer_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM recordbot_users WHERE stripe_customer_id = ?",
        (stripe_customer_id,)
    ).fetchone()
    conn.close()
    return row


def create_rb_user(telegram_id, email, activation_code, stripe_customer_id, credit_hours):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    credit_seconds = credit_hours * 3600
    existing = conn.execute(
        "SELECT * FROM recordbot_users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE recordbot_users
            SET email = ?, activation_code = ?, stripe_customer_id = ?,
                credit_seconds = credit_seconds + ?, is_active = 1
            WHERE telegram_id = ?
        """, (email, activation_code, stripe_customer_id, credit_seconds, telegram_id))
    else:
        conn.execute("""
            INSERT INTO recordbot_users
            (telegram_id, email, activation_code, stripe_customer_id,
             credit_seconds, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (telegram_id, email, activation_code, stripe_customer_id,
              credit_seconds, now))

    conn.commit()
    conn.close()


def add_credits(telegram_id, hours):
    conn = get_conn()
    seconds = hours * 3600
    conn.execute(
        "UPDATE recordbot_users SET credit_seconds = credit_seconds + ? WHERE telegram_id = ?",
        (seconds, telegram_id)
    )
    conn.commit()
    conn.close()


def deduct_credits(telegram_id, seconds):
    conn = get_conn()
    conn.execute(
        "UPDATE recordbot_users SET credit_seconds = MAX(0, credit_seconds - ?) WHERE telegram_id = ?",
        (seconds, telegram_id)
    )
    conn.commit()
    conn.close()


def get_remaining_credits(telegram_id):
    user = get_rb_user(telegram_id)
    if not user:
        return 0
    return user["credit_seconds"]


def update_rb_credentials(telegram_id, username, password_hash):
    conn = get_conn()
    conn.execute(
        "UPDATE recordbot_users SET username = ?, password_hash = ? WHERE telegram_id = ?",
        (username, password_hash, telegram_id)
    )
    conn.commit()
    conn.close()


def add_model(telegram_id, model_name):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    try:
        conn.execute(
            "INSERT INTO recordbot_models (user_telegram_id, model_name, added_at) VALUES (?, ?, ?)",
            (telegram_id, model_name.strip().lower(), now)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def remove_model(telegram_id, model_name):
    conn = get_conn()
    conn.execute(
        "DELETE FROM recordbot_models WHERE user_telegram_id = ? AND model_name = ?",
        (telegram_id, model_name.strip().lower())
    )
    conn.commit()
    conn.close()


def get_user_models(telegram_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM recordbot_models WHERE user_telegram_id = ? ORDER BY added_at",
        (telegram_id,)
    ).fetchall()
    conn.close()
    return rows


def get_all_monitored_models():
    conn = get_conn()
    rows = conn.execute("""
        SELECT rm.model_name, rm.user_telegram_id, ru.credit_seconds
        FROM recordbot_models rm
        JOIN recordbot_users ru ON rm.user_telegram_id = ru.telegram_id
        WHERE ru.is_active = 1 AND ru.credit_seconds > 0
    """).fetchall()
    conn.close()
    return rows


def start_recording_entry(telegram_id, model_name):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    c = conn.cursor()
    c.execute("""
        INSERT INTO recordbot_recordings
        (user_telegram_id, model_name, started_at, status)
        VALUES (?, ?, ?, 'recording')
    """, (telegram_id, model_name, now))
    rec_id = c.lastrowid
    conn.commit()
    conn.close()
    return rec_id


def end_recording_entry(rec_id, duration_seconds):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE recordbot_recordings
        SET ended_at = ?, duration_seconds = ?, status = 'completed'
        WHERE id = ?
    """, (now, duration_seconds, rec_id))
    conn.commit()
    conn.close()


def get_active_recordings_for_user(telegram_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM recordbot_recordings WHERE user_telegram_id = ? AND status = 'recording'",
        (telegram_id,)
    ).fetchall()
    conn.close()
    return rows


def get_all_active_recordings():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM recordbot_recordings WHERE status = 'recording'"
    ).fetchall()
    conn.close()
    return rows


def store_rb_activation_code(code, email, plan_key, credit_hours):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO recordbot_activation_codes
        (code, email, plan_key, credit_hours, used, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
    """, (code, email, plan_key, credit_hours, now))
    conn.commit()
    conn.close()


def get_rb_activation_code(code):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM recordbot_activation_codes WHERE code = ?", (code,)
    ).fetchone()
    conn.close()
    return row


def mark_rb_code_used(code, telegram_id):
    conn = get_conn()
    conn.execute(
        "UPDATE recordbot_activation_codes SET used = 1 WHERE code = ?",
        (code,)
    )
    conn.commit()
    conn.close()
