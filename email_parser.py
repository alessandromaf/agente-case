import re
import httpx
from bs4 import BeautifulSoup
from models import Listing

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _resolve_redirect(url: str) -> str:
    """Follow tracking redirects to get the actual listing URL."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=10) as client:
            resp = client.head(url)
            return str(resp.url)
    except Exception:
        return url


def _parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _extract_price(text: str) -> int:
    """Extract price from text like '€ 95.000', '95000 €', '€95,000', etc."""
    # Try various price patterns
    patterns = [
        r"€\s*([\d.,]+)",           # € 95.000 or €95,000
        r"([\d.,]+)\s*€",           # 95.000 € or 95,000€
        r"EUR\s*([\d.,]+)",         # EUR 95.000
        r"([\d.,]+)\s*EUR",         # 95.000 EUR
        r"prezzo[:\s]*([\d.,]+)",   # prezzo: 95.000
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return _parse_price(m.group(1))
    return 0


def parse_immobiliare(html: str, subject: str) -> list[Listing]:
    """Parse Immobiliare.it alert email HTML into Listing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Debug: print all links to help diagnose
    all_links = soup.select("a[href]")
    immob_links = [a for a in all_links if "immobiliare.it" in a.get("href", "")]
    print(f"    [debug] Total links: {len(all_links)}, immobiliare links: {len(immob_links)}")
    for a in immob_links[:5]:
        href = a.get("href", "")
        text = a.get_text(strip=True)[:60]
        print(f"    [debug] link: {text} -> {href[:80]}")

    # Immobiliare emails use tracking redirects (clicks.immobiliare.it).
    # The listing card is a table with image on left and data on right.
    # Strategy: find title links (have a title attribute with listing info),
    # then walk up to the card container to get price/sqm/rooms.

    # Collect unique listing links by href (skip image-only and button dupes)
    seen_hrefs = {}
    for link in soup.select("a[href*='clicks.immobiliare.it']"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        title_attr = link.get("title", "")
        # Skip generic links
        if text.lower() in ("", "avvia ricerca"):
            continue
        # Prefer the title link (has actual listing name), not image or button
        if href not in seen_hrefs or (title_attr and len(text) > 5):
            seen_hrefs[href] = link

    # Also handle direct links (non-redirect)
    for link in soup.select("a[href*='immobiliare.it/annunci/']"):
        href = link.get("href", "")
        if href not in seen_hrefs:
            seen_hrefs[href] = link

    for href, link in seen_hrefs.items():
        # Walk up to the outermost card container to get all text
        # The card is typically a <td> containing both image and data tables
        card = link
        for ancestor in link.parents:
            if ancestor.name == "td" and ancestor != soup:
                card_text = ancestor.get_text(" ", strip=True)
                # The card container has price + sqm + title — typically 50-500 chars
                if len(card_text) > 50 and ("€" in card_text or "m²" in card_text or "locali" in card_text.lower()):
                    card = ancestor
                    break

        context = card.get_text(" ", strip=True) if card else ""
        print(f"    [debug] immobiliare card context: {context[:200]}")

        # Title from link text or title attribute
        title = link.get_text(strip=True).replace("\ufeff", "")
        if not title or len(title) < 5:
            title = link.get("title", "")

        # Resolve redirect to get actual listing URL and ID
        actual_url = href
        if "clicks.immobiliare.it" in href:
            actual_url = _resolve_redirect(href)
            print(f"    [debug] resolved -> {actual_url[:100]}")

        lid_match = re.search(r"/annunci/(\d+)", actual_url)
        if not lid_match:
            lid_match = re.search(r"/(\d{5,})", actual_url)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        price = _extract_price(context)

        rooms = ""
        sqm = ""
        rooms_m = re.search(r"(\d+)\+?\s*local", context, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)
        sqm_m = re.search(r"(\d+)\s*m[²2q\u00b2]", context, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        # Extract address from title
        address = ""
        addr_m = re.search(r"(?:in vendita (?:in |a )|all'asta\s+(?:via |in |a ))(.+?)(?:,\s*\w+)?$", title, re.IGNORECASE)
        if addr_m:
            address = addr_m.group(1).strip()

        clean_url = actual_url.split("?")[0]

        listings.append(Listing(
            source="immobiliare",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="",
            address=address,
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

    # Debug
    all_links = [a for a in soup.select("a[href]") if "idealista" in a.get("href", "")]
    print(f"    [debug] idealista links: {len(all_links)}")
    for a in all_links[:5]:
        print(f"    [debug] link: {a.get_text(strip=True)[:40]} -> {a.get('href','')[:80]}")

    for link in soup.select("a[href*='idealista.it/immobile/']"):
        href = link.get("href", "")
        lid_match = re.search(r"/immobile/(\d+)", href)
        if not lid_match:
            lid_match = re.search(r"/(\d{5,})", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        parent = link.find_parent(["tr", "div", "td", "table"])

        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            if parent:
                title = parent.get_text(" ", strip=True)[:120]

        context = parent.get_text(" ", strip=True) if parent else ""
        print(f"    [debug] idealista listing {lid}: context={context[:100]}")
        price = _extract_price(context)

        if price == 0 and parent:
            grandparent = parent.find_parent(["tr", "div", "td", "table"])
            if grandparent:
                price = _extract_price(grandparent.get_text(" ", strip=True))

        rooms = ""
        sqm = ""
        rooms_m = re.search(r"(\d+)\s*local", context, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)
        sqm_m = re.search(r"(\d+)\s*m[²2q]", context, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        address = ""
        addr_m = re.search(r"in vendita (?:in |a )(.+)", title, re.IGNORECASE)
        if addr_m:
            address = addr_m.group(1).strip()

        clean_url = href.split("?")[0]

        listings.append(Listing(
            source="idealista",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="",
            address=address,
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

    # Casa.it emails use table layouts — find listing URLs and group by ID
    seen_ids = set()
    listing_links = {}
    for link in soup.select("a[href*='casa.it/immobili/']"):
        href = link.get("href", "")
        lid_match = re.search(r"/immobili/(\d+)", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)
        if lid not in listing_links:
            listing_links[lid] = {"href": href, "elements": []}
        listing_links[lid]["elements"].append(link)

    print(f"    [debug] casa unique listing IDs: {len(listing_links)}")

    # Debug: dump raw HTML around first listing to understand structure
    first_dump = True
    for lid, data in listing_links.items():
        href = data["href"]

        # Walk up from ALL links with this ID to find the largest containing block
        all_text = ""
        title = ""
        card_html = ""
        for el in data["elements"]:
            text = el.get_text(strip=True)
            if len(text) > len(title) and "foto" not in text.lower() and "vedi" not in text.lower():
                title = text

            # Walk up multiple levels to find the card container
            for ancestor in el.parents:
                if ancestor.name in ["table", "div", "tr", "td"] and ancestor != soup:
                    ancestor_text = ancestor.get_text(" ", strip=True)
                    if len(ancestor_text) > len(all_text) and len(ancestor_text) < 3000:
                        all_text = ancestor_text
                        card_html = str(ancestor)
                    if _extract_price(ancestor_text) > 0:
                        break

        # Debug: dump first card raw HTML
        if first_dump:
            print(f"    [debug] FIRST CARD full text ({len(all_text)} chars):")
            print(f"    [debug] {all_text[:500]}")
            first_dump = False

        price = _extract_price(all_text)

        # Extract address from title (e.g. "Appartamento in vendita in Via Fossato Vecchio")
        address = ""
        addr_m = re.search(r"in vendita (?:in |a )(.+)", title, re.IGNORECASE)
        if addr_m:
            address = addr_m.group(1).strip()

        # Extract rooms/sqm from full card text
        rooms = ""
        sqm = ""
        rooms_m = re.search(r"(\d+)\s*local", all_text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)
        sqm_m = re.search(r"(\d+)\s*m[²2q\u00b2]", all_text, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        print(f"    [debug] casa {lid}: price={price} sqm={sqm} rooms={rooms} addr={address[:40]}")

        clean_url = href.split("?")[0]

        listings.append(Listing(
            source="casa",
            listing_id=lid,
            title=title[:150] if title else f"Annuncio {lid}",
            price=price,
            city="",
            address=address,
            url=clean_url,
            rooms=rooms,
            sqm=sqm,
        ))

    return listings


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
