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
    conn = _get_conn()
    new = []
    for listing in listings:
        row = conn.execute(
            "SELECT 1 FROM seen WHERE source = ? AND listing_id = ?",
            (listing.source, listing.listing_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO seen (source, listing_id, first_seen) VALUES (?, ?, ?)",
                (listing.source, listing.listing_id, listing.scraped_at),
            )
            new.append(listing)
    conn.commit()
    conn.close()
    return new
