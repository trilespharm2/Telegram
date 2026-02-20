import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "data/bot.db")

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Subscribers table
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            email TEXT,
            username TEXT,
            password_hash TEXT,
            activation_code TEXT,
            transaction_id TEXT,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            subscribed_at TEXT,
            expires_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    # Activation codes table
    c.execute("""
        CREATE TABLE IF NOT EXISTS activation_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            telegram_id INTEGER,
            transaction_id TEXT,
            email TEXT,
            used INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    # Inquiries table
    c.execute("""
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            username TEXT,
            message TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

# ---------- Subscriber Operations ----------

def get_subscriber(telegram_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row

def get_subscriber_by_code(code):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscribers WHERE activation_code = ?", (code,)
    ).fetchone()
    conn.close()
    return row

def get_subscriber_by_transaction(transaction_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscribers WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()
    conn.close()
    return row

def create_subscriber(telegram_id, email, activation_code, transaction_id,
                       stripe_customer_id, stripe_subscription_id):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO subscribers
        (telegram_id, email, activation_code, transaction_id,
         stripe_customer_id, stripe_subscription_id,
         subscribed_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (telegram_id, email, activation_code, transaction_id,
          stripe_customer_id, stripe_subscription_id, now, expires))
    conn.commit()
    conn.close()

def update_subscriber_credentials(telegram_id, username, password_hash):
    conn = get_conn()
    conn.execute(
        "UPDATE subscribers SET username = ?, password_hash = ? WHERE telegram_id = ?",
        (username, password_hash, telegram_id)
    )
    conn.commit()
    conn.close()

def deactivate_subscriber(telegram_id):
    conn = get_conn()
    conn.execute(
        "UPDATE subscribers SET is_active = 0 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

def is_active_subscriber(telegram_id):
    row = get_subscriber(telegram_id)
    if not row:
        return False
    if not row["is_active"]:
        return False
    expires = datetime.fromisoformat(row["expires_at"])
    return datetime.utcnow() < expires

# ---------- Activation Code Operations ----------

def store_activation_code(code, transaction_id, email):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO activation_codes
        (code, transaction_id, email, used, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (code, transaction_id, email, now))
    conn.commit()
    conn.close()

def get_activation_code_record(code):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM activation_codes WHERE code = ?", (code,)
    ).fetchone()
    conn.close()
    return row

def mark_code_used(code, telegram_id):
    conn = get_conn()
    conn.execute(
        "UPDATE activation_codes SET used = 1, telegram_id = ? WHERE code = ?",
        (telegram_id, code)
    )
    conn.commit()
    conn.close()

def get_code_by_email(email):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM activation_codes WHERE email = ? ORDER BY created_at DESC LIMIT 1",
        (email,)
    ).fetchone()
    conn.close()
    return row

# ---------- Inquiry Operations ----------

def save_inquiry(telegram_id, username, message):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO inquiries (telegram_id, username, message, created_at)
        VALUES (?, ?, ?, ?)
    """, (telegram_id, username, message, now))
    conn.commit()
    conn.close()
