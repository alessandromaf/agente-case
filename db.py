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
