import sqlite3

DB_NAME = "wallets.db"

def init_db():
    """Initializes the database and creates the table if it doesn't exist."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitored_wallets (
                address TEXT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

def add_wallets_db(addresses: list) -> int:
    """Inserts a list of unique addresses. Returns the number of newly added rows."""
    added_count = 0
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        for addr in addresses:
            try:
                cursor.execute("INSERT INTO monitored_wallets (address) VALUES (?)", (addr,))
                added_count += 1
            except sqlite3.IntegrityError:
                # Address already exists
                continue
        conn.commit()
    return added_count

def remove_wallets_db(addresses: list) -> int:
    """Removes a list of addresses. Returns the number of deleted rows."""
    removed_count = 0
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        for addr in addresses:
            cursor.execute("DELETE FROM monitored_wallets WHERE address = ?", (addr,))
            if cursor.rowcount > 0:
                removed_count += 1
        conn.commit()
    return removed_count

def get_all_wallets() -> set:
    """Retrieves all tracked wallets as a set for quick memory lookups."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT address FROM monitored_wallets")
        rows = cursor.fetchall()
        return {row[0] for row in rows}
