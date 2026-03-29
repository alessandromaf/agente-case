import time
import httpx
from models import Listing

SOURCE_LABELS = {
    "immobiliare": "Immobiliare.it",
    "idealista": "Idealista.it",
    "casa": "Casa.it",
    "tecnocasa": "Tecnocasa Forlì",
    "romagnacase": "Romagnacase",
    "alphacase": "Alphacase",
    "sansoni": "Agenzia Sansoni",
}


def _format_message(listing: Listing) -> str:
    label = SOURCE_LABELS.get(listing.source, listing.source)

    lines = [f"\U0001f3e0 *Nuovo annuncio su {label}*"]

    if listing.title:
        lines.append(f"{listing.title}")

    # Location line: address and/or city
    location_parts = []
    if listing.address:
        location_parts.append(listing.address)
    if listing.city and listing.city not in (listing.address or ""):
        location_parts.append(listing.city)
    if location_parts:
        lines.append(f"\U0001f4cd {', '.join(location_parts)}")

    # Price
    if listing.price > 0:
        price_str = f"\u20ac {listing.price:,}".replace(",", ".")
        lines.append(f"\U0001f4b0 {price_str}")

    # Details: rooms, sqm
    details = []
    if listing.rooms:
        details.append(f"{listing.rooms} locali")
    if listing.sqm:
        details.append(f"{listing.sqm} m\u00b2")
    if details:
        lines.append(f"\U0001f4d0 {' \u00b7 '.join(details)}")

    lines.append(f"\n\U0001f517 [Vedi annuncio]({listing.url})")
    return "\n".join(lines)


def _send_message(bot_token: str, channel_id: str, text: str) -> bool:
    """Send a single message with retry on rate limit (429)."""
    for attempt in range(3):
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": channel_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 30)
            print(f"  Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after + 1)
            continue
        return False
    return False


def send_listings(listings: list[Listing], bot_token: str, channel_id: str) -> int:
    sent = 0
    for listing in listings:
        text = _format_message(listing)
        if _send_message(bot_token, channel_id, text):
            sent += 1
        else:
            print(f"Telegram error for {listing.listing_id}")
        time.sleep(3)  # rate limit courtesy
    return sent
