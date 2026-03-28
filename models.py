from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Listing:
    source: str  # "immobiliare", "idealista", "casa"
    listing_id: str
    title: str
    price: int
    city: str
    url: str
    image_url: str = ""
    rooms: str = ""
    sqm: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
