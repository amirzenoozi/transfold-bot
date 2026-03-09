import sqlite3
import os
from datetime import datetime

# Path relative to the project root
DB_PATH = os.path.join("database", "bot.db")

def init_db():
    # Ensure database directory exists
    os.makedirs("database", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Create table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            is_subscribed BOOLEAN DEFAULT 0,
            expiry_date DATETIME,
            join_date DATETIME,
            language TEXT DEFAULT 'en'
        )
    ''')
    conn.commit()
    conn.close()


def add_user(user_id):
    # Register a new user or ignore if already exists
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)', (user_id, now))
    conn.commit()
    conn.close()


def get_all_users(exclude_id=None):
    """Fetches all user IDs from the database for broadcasting."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if exclude_id:
        cursor.execute('SELECT user_id FROM users WHERE user_id != ?', (exclude_id,))
    else:
        cursor.execute('SELECT user_id FROM users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def get_freemium_users():
    """Fetches user IDs who do NOT have an active subscription."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Users where is_subscribed is 0 OR the expiry date has passed
    cursor.execute('SELECT user_id FROM users WHERE is_subscribed = 0 OR expiry_date <= ?', (now,))
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def get_active_subscribers():
    # Fetch all users with a valid subscription
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('SELECT user_id FROM users WHERE is_subscribed = 1 AND expiry_date > ?', (now,))
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def update_subscription(user_id, days=30):
    # Logic to extend or activate subscription
    from datetime import timedelta
    new_expiry = datetime.now() + timedelta(days=days)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_subscribed = 1, expiry_date = ? WHERE user_id = ?', (new_expiry.strftime('%Y-%m-%d %H:%M:%S'), user_id))
    conn.commit()
    conn.close()
    return new_expiry


def deactivate_subscription(user_id):
    """ Sets is_subscribed to 0 and clears the expiry date for a user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_subscribed = 0, expiry_date = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def get_user_info(user_id):
    """Fetches all settings for a specific user."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def set_user_language(user_id, lang_code):
    """Updates the preferred language for a specific user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (lang_code, user_id))
    conn.commit()
    conn.close()


def get_user_language(user_id):
    """Returns the user's language, defaults to 'en'."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT language FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else 'en'


def is_user_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Check for an active subscription/stars record
    cursor.execute('SELECT is_subscribed FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row[0]) if row else False

