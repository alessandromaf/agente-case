import time
import httpx
from models import Listing

SOURCE_LABELS = {
    "immobiliare": "Immobiliare.it",
    "idealista": "Idealista.it",
    "casa": "Casa.it",
}


def _format_message(listing: Listing) -> str:
    label = SOURCE_LABELS.get(listing.source, listing.source)
    price_str = f"\u20ac{listing.price:,}".replace(",", ".")

    lines = [
        f"\U0001f3e0 *Nuovo annuncio su {label}*",
        f"{listing.title}",
        f"\U0001f4cd {listing.city} \u2014 {price_str}",
    ]

    details = []
    if listing.rooms:
        details.append(f"{listing.rooms} locali")
    if listing.sqm:
        details.append(f"{listing.sqm} m\u00b2")
    if details:
        lines.append(" \u00b7 ".join(details))

    lines.append(f"\U0001f517 [Vedi annuncio]({listing.url})")
    return "\n".join(lines)


def send_listings(listings: list[Listing], bot_token: str, channel_id: str) -> int:
    sent = 0
    for listing in listings:
        text = _format_message(listing)
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
            sent += 1
        else:
            print(f"Telegram error for {listing.listing_id}: {resp.text}")
        time.sleep(1)  # rate limit courtesy
    return sent
