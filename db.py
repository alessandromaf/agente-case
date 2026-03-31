import os
import sys
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from models import Listing

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = Path(__file__).parent / "seen_listings.db"

# SQL placeholder style differs between drivers
_PH = "%s" if DATABASE_URL else "?"

# Fail fast if running on CI without a persistent database
if os.environ.get("GITHUB_ACTIONS") and not DATABASE_URL:
    print("FATAL: DATABASE_URL not set — SQLite is ephemeral on CI, listings will be re-sent every run.")
    sys.exit(1)


@contextmanager
def _connect():
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _ph(n: int) -> str:
    """Return n comma-separated placeholders."""
    return ", ".join([_PH] * n)


def init_db() -> None:
    backend = "PostgreSQL" if DATABASE_URL else f"SQLite ({DB_PATH})"
    print(f"[db] Using {backend}")
    with _connect() as conn:
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seen (
                    source TEXT NOT NULL,
                    listing_id TEXT NOT NULL,
                    first_seen TEXT,
                    telegram_message_id BIGINT,
                    PRIMARY KEY (source, listing_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shortlist (
                    source TEXT NOT NULL,
                    listing_id TEXT NOT NULL,
                    url TEXT,
                    title TEXT,
                    price INTEGER,
                    sqm TEXT,
                    rooms TEXT,
                    address TEXT,
                    added_at TEXT,
                    PRIMARY KEY (source, listing_id)
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seen (
                    source TEXT, listing_id TEXT, first_seen TEXT,
                    telegram_message_id INTEGER,
                    PRIMARY KEY (source, listing_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shortlist (
                    source TEXT, listing_id TEXT, url TEXT, title TEXT,
                    price INTEGER, sqm TEXT, rooms TEXT, address TEXT,
                    added_at TEXT,
                    PRIMARY KEY (source, listing_id)
                )
            """)
            cols = [r[1] for r in cur.execute("PRAGMA table_info(seen)").fetchall()]
            if "telegram_message_id" not in cols:
                cur.execute("ALTER TABLE seen ADD COLUMN telegram_message_id INTEGER")
        cur.execute("SELECT COUNT(*) FROM seen")
        count = cur.fetchone()[0]
        print(f"[db] {count} listings already marked as seen")


def filter_new(listings: list[Listing]) -> list[Listing]:
    """Return only listings not previously seen."""
    with _connect() as conn:
        cur = conn.cursor()
        new = []
        for listing in listings:
            cur.execute(
                f"SELECT 1 FROM seen WHERE source = {_PH} AND listing_id = {_PH}",
                (listing.source, listing.listing_id),
            )
            if cur.fetchone() is None:
                new.append(listing)
    return new


def get_listing_by_message_id(message_id: int) -> dict | None:
    """Look up a listing by its Telegram message ID."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT source, listing_id, telegram_message_id FROM seen WHERE telegram_message_id = {_PH}",
            (message_id,),
        )
        row = cur.fetchone()
    if row:
        return {"source": row[0], "listing_id": row[1], "telegram_message_id": row[2]}
    return None


def add_to_shortlist(source: str, listing_id: str, url: str, title: str,
                     price: int, sqm: str, rooms: str, address: str) -> bool:
    """Add a listing to the shortlist. Returns True if newly added."""
    ph = _ph(9)
    values = (source, listing_id, url, title, price, sqm, rooms, address, datetime.utcnow().isoformat())
    with _connect() as conn:
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute(
                f"INSERT INTO shortlist (source, listing_id, url, title, price, sqm, rooms, address, added_at) "
                f"VALUES ({ph}) ON CONFLICT DO NOTHING",
                values,
            )
        else:
            cur.execute(
                f"INSERT OR IGNORE INTO shortlist (source, listing_id, url, title, price, sqm, rooms, address, added_at) "
                f"VALUES ({ph})",
                values,
            )
        return cur.rowcount > 0


def remove_from_shortlist(source: str, listing_id: str) -> bool:
    """Remove a listing from the shortlist."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM shortlist WHERE source = {_PH} AND listing_id = {_PH}",
            (source, listing_id),
        )
        return cur.rowcount > 0


def get_shortlist() -> list[dict]:
    """Get all shortlisted listings."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT source, listing_id, url, title, price, sqm, rooms, address, added_at "
            "FROM shortlist ORDER BY added_at DESC"
        )
        rows = cur.fetchall()
    return [
        {"source": r[0], "listing_id": r[1], "url": r[2], "title": r[3],
         "price": r[4], "sqm": r[5], "rooms": r[6], "address": r[7], "added_at": r[8]}
        for r in rows
    ]


def mark_seen(listings: list[Listing], message_ids: dict[str, int] | None = None) -> None:
    """Mark listings as seen, storing Telegram message IDs if provided."""
    ph = _ph(4)
    with _connect() as conn:
        cur = conn.cursor()
        for listing in listings:
            key = f"{listing.source}:{listing.listing_id}"
            msg_id = (message_ids or {}).get(key)
            if DATABASE_URL:
                cur.execute(
                    f"INSERT INTO seen (source, listing_id, first_seen, telegram_message_id) "
                    f"VALUES ({ph}) ON CONFLICT (source, listing_id) "
                    f"DO UPDATE SET telegram_message_id = EXCLUDED.telegram_message_id",
                    (listing.source, listing.listing_id, listing.scraped_at, msg_id),
                )
            else:
                cur.execute(
                    f"INSERT OR REPLACE INTO seen (source, listing_id, first_seen, telegram_message_id) "
                    f"VALUES ({ph})",
                    (listing.source, listing.listing_id, listing.scraped_at, msg_id),
                )
