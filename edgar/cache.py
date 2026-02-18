"""
SQLite Cache Layer
Caches EDGAR API responses locally so we don't re-download on every call.
Financial data doesn't change often, so caching aggressively is fine.
"""

import sqlite3
import json
import time
import os
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "cache.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create cache tables if they don't exist."""
    with _get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS company_search (
                query TEXT PRIMARY KEY,
                result JSON NOT NULL,
                cached_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS company_submissions (
                cik_padded TEXT PRIMARY KEY,
                result JSON NOT NULL,
                cached_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS company_facts (
                cik_padded TEXT PRIMARY KEY,
                result JSON NOT NULL,
                cached_at INTEGER NOT NULL
            );
        """)


def get_cached(table: str, key_col: str, key_val: str, max_age_hours: int = 24) -> Optional[dict]:
    """
    Retrieve a cached value if it exists and isn't stale.
    Returns None if not cached or expired.
    """
    with _get_connection() as conn:
        row = conn.execute(
            f"SELECT result, cached_at FROM {table} WHERE {key_col} = ?",
            (key_val,)
        ).fetchone()

        if not row:
            return None

        age_hours = (time.time() - row["cached_at"]) / 3600
        if age_hours > max_age_hours:
            return None  # Cache expired

        return json.loads(row["result"])


def set_cached(table: str, key_col: str, key_val: str, data: dict):
    """Store a value in the cache."""
    with _get_connection() as conn:
        conn.execute(
            f"""INSERT OR REPLACE INTO {table} ({key_col}, result, cached_at)
                VALUES (?, ?, ?)""",
            (key_val, json.dumps(data), int(time.time()))
        )


# Initialize DB on import
init_db()