import sqlite3
from pathlib import Path
from models import Listing

DB_PATH = Path(__file__).parent / "seen_listings.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        "  source TEXT, listing_id TEXT, first_seen TEXT,"
        "  PRIMARY KEY (source, listing_id)"
        ")"
    )
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


def mark_seen(listings: list[Listing]) -> None:
    """Mark listings as seen in the database."""
    conn = _get_conn()
    for listing in listings:
        conn.execute(
            "INSERT OR IGNORE INTO seen (source, listing_id, first_seen) VALUES (?, ?, ?)",
            (listing.source, listing.listing_id, listing.scraped_at),
        )
    conn.commit()
    conn.close()
