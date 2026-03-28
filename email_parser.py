import re
from bs4 import BeautifulSoup
from models import Listing


def _parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_immobiliare(html: str, subject: str) -> list[Listing]:
    """Parse Immobiliare.it alert email HTML into Listing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Immobiliare alert emails contain listing cards with links to annunci
    for link in soup.select("a[href*='immobiliare.it/annunci/']"):
        href = link.get("href", "")
        # Extract listing ID from URL
        lid_match = re.search(r"/annunci/(\d+)", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        # Try to get title from link text or nearby elements
        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            parent = link.find_parent(["tr", "div", "td"])
            if parent:
                title = parent.get_text(" ", strip=True)[:120]

        # Look for price near the link
        price = 0
        parent = link.find_parent(["tr", "div", "td", "table"])
        if parent:
            price_match = re.search(
                r"[€]\s*([\d.]+(?:\.\d{3})*)", parent.get_text()
            )
            if price_match:
                price = _parse_price(price_match.group(1))

        # Extract rooms/sqm from surrounding text
        context = parent.get_text(" ", strip=True) if parent else ""
        rooms = ""
        sqm = ""
        rooms_m = re.search(r"(\d+)\s*local", context, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)
        sqm_m = re.search(r"(\d+)\s*m[²2q]", context, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        # Clean URL (remove tracking params)
        clean_url = href.split("?")[0]

        listings.append(Listing(
            source="immobiliare",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="",
            url=clean_url,
            rooms=rooms,
            sqm=sqm,
        ))

    # Deduplicate by listing_id within this email
    seen = set()
    unique = []
    for l in listings:
        if l.listing_id not in seen:
            seen.add(l.listing_id)
            unique.append(l)

    return unique


def parse_idealista(html: str, subject: str) -> list[Listing]:
    """Parse Idealista.it alert email HTML into Listing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    for link in soup.select("a[href*='idealista.it/immobile/']"):
        href = link.get("href", "")
        lid_match = re.search(r"/immobile/(\d+)", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            parent = link.find_parent(["tr", "div", "td"])
            if parent:
                title = parent.get_text(" ", strip=True)[:120]

        price = 0
        parent = link.find_parent(["tr", "div", "td", "table"])
        if parent:
            price_match = re.search(
                r"[€]\s*([\d.]+(?:\.\d{3})*)", parent.get_text()
            )
            if price_match:
                price = _parse_price(price_match.group(1))

        context = parent.get_text(" ", strip=True) if parent else ""
        rooms = ""
        sqm = ""
        rooms_m = re.search(r"(\d+)\s*local", context, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)
        sqm_m = re.search(r"(\d+)\s*m[²2q]", context, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        clean_url = href.split("?")[0]

        listings.append(Listing(
            source="idealista",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="",
            url=clean_url,
            rooms=rooms,
            sqm=sqm,
        ))

    seen = set()
    unique = []
    for l in listings:
        if l.listing_id not in seen:
            seen.add(l.listing_id)
            unique.append(l)

    return unique


def parse_casa(html: str, subject: str) -> list[Listing]:
    """Parse Casa.it alert email HTML into Listing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    for link in soup.select("a[href*='casa.it/']"):
        href = link.get("href", "")
        # Casa.it listing URLs contain numeric IDs
        lid_match = re.search(r"/(\d{6,})", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            parent = link.find_parent(["tr", "div", "td"])
            if parent:
                title = parent.get_text(" ", strip=True)[:120]

        price = 0
        parent = link.find_parent(["tr", "div", "td", "table"])
        if parent:
            price_match = re.search(
                r"[€]\s*([\d.]+(?:\.\d{3})*)", parent.get_text()
            )
            if price_match:
                price = _parse_price(price_match.group(1))

        clean_url = href.split("?")[0]

        listings.append(Listing(
            source="casa",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="",
            url=clean_url,
        ))

    seen = set()
    unique = []
    for l in listings:
        if l.listing_id not in seen:
            seen.add(l.listing_id)
            unique.append(l)

    return unique


PARSERS = {
    "immobiliare": parse_immobiliare,
    "idealista": parse_idealista,
    "casa": parse_casa,
}


def parse_alert(alert: dict) -> list[Listing]:
    """Route an alert email to the correct parser."""
    source = alert["source"]
    parser = PARSERS.get(source)
    if not parser:
        print(f"  No parser for source: {source}")
        return []
    return parser(alert["html"], alert["subject"])
