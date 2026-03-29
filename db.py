import sqlite3
from pathlib import Path
from models import Listing

DB_PATH = Path(__file__).parent / "seen_listings.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        "  source TEXT, listing_id TEXT, first_seen TEXT,"
        "  telegram_message_id INTEGER,"
        "  PRIMARY KEY (source, listing_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shortlist ("
        "  source TEXT, listing_id TEXT, url TEXT, title TEXT,"
        "  price INTEGER, sqm TEXT, rooms TEXT, address TEXT,"
        "  added_at TEXT,"
        "  PRIMARY KEY (source, listing_id)"
        ")"
    )
    # Migrate: add column if missing (existing DBs)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(seen)").fetchall()]
    if "telegram_message_id" not in cols:
        conn.execute("ALTER TABLE seen ADD COLUMN telegram_message_id INTEGER")
    return conn


def filter_new(listings: list[Listing]) -> list[Listing]:
    """Return only listings not previously seen. Does NOT mark them as seen."""
    conn = _get_conn()
    new = []
    for listing in listings:
        row = conn.execute(
            "SELECT 1 FROM seen WHERE source = ? AND listing_id = ?",
            (listing.source, listing.listing_id),
        ).fetchone()
        if row is None:
            new.append(listing)
    conn.close()
    return new


def get_listing_by_message_id(message_id: int) -> dict | None:
    """Look up a listing by its Telegram message ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT source, listing_id, telegram_message_id FROM seen WHERE telegram_message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    if row:
        return {"source": row[0], "listing_id": row[1], "telegram_message_id": row[2]}
    return None


def add_to_shortlist(source: str, listing_id: str, url: str, title: str,
                     price: int, sqm: str, rooms: str, address: str) -> bool:
    """Add a listing to the shortlist. Returns True if newly added."""
    from datetime import datetime
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO shortlist (source, listing_id, url, title, price, sqm, rooms, address, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, listing_id, url, title, price, sqm, rooms, address, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def remove_from_shortlist(source: str, listing_id: str) -> bool:
    """Remove a listing from the shortlist."""
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM shortlist WHERE source = ? AND listing_id = ?",
        (source, listing_id),
    )
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


def get_shortlist() -> list[dict]:
    """Get all shortlisted listings."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT source, listing_id, url, title, price, sqm, rooms, address, added_at "
        "FROM shortlist ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [
        {"source": r[0], "listing_id": r[1], "url": r[2], "title": r[3],
         "price": r[4], "sqm": r[5], "rooms": r[6], "address": r[7], "added_at": r[8]}
        for r in rows
    ]


def mark_seen(listings: list[Listing], message_ids: dict[str, int] | None = None) -> None:
    """Mark listings as seen in the database, optionally storing Telegram message IDs."""
    conn = _get_conn()
    for listing in listings:
        key = f"{listing.source}:{listing.listing_id}"
        msg_id = (message_ids or {}).get(key)
        conn.execute(
            "INSERT OR IGNORE INTO seen (source, listing_id, first_seen, telegram_message_id) VALUES (?, ?, ?, ?)",
            (listing.source, listing.listing_id, listing.scraped_at, msg_id),
        )
    conn.commit()
    conn.close()
