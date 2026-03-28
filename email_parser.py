import re
from bs4 import BeautifulSoup
from models import Listing


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

    # Immobiliare alert emails contain listing cards with links to annunci
    for link in soup.select("a[href*='immobiliare.it/annunci/']"):
        href = link.get("href", "")
        # Extract listing ID from URL
        lid_match = re.search(r"/annunci/(\d+)", href)
        if not lid_match:
            # Also try /vendita-case/.../ID/ pattern
            lid_match = re.search(r"/(\d{5,})", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        # Walk up to find the containing card/block
        parent = link.find_parent(["tr", "div", "td", "table"])

        # Try to get title from link text or nearby elements
        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            if parent:
                title = parent.get_text(" ", strip=True)[:120]

        # Look for price - search in parent and siblings
        context = parent.get_text(" ", strip=True) if parent else ""
        print(f"    [debug] listing {lid}: context={context[:100]}")
        price = _extract_price(context)

        # If no price in parent, try grandparent
        if price == 0 and parent:
            grandparent = parent.find_parent(["tr", "div", "td", "table"])
            if grandparent:
                gp_text = grandparent.get_text(" ", strip=True)
                price = _extract_price(gp_text)

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

    for lid, data in listing_links.items():
        href = data["href"]

        # Walk up from ALL links with this ID to find the largest containing block
        all_text = ""
        title = ""
        for el in data["elements"]:
            text = el.get_text(strip=True)
            if len(text) > len(title) and "foto" not in text.lower() and "vedi" not in text.lower():
                title = text

            # Walk up multiple levels to find the card container
            for ancestor in el.parents:
                if ancestor.name in ["table", "div"] and ancestor != soup:
                    ancestor_text = ancestor.get_text(" ", strip=True)
                    if len(ancestor_text) > len(all_text) and len(ancestor_text) < 2000:
                        all_text = ancestor_text
                    if _extract_price(ancestor_text) > 0:
                        break

        price = _extract_price(all_text)
        print(f"    [debug] casa {lid}: price={price} title={title[:50]}")

        # Extract rooms/sqm
        rooms = ""
        sqm = ""
        rooms_m = re.search(r"(\d+)\s*local", all_text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)
        sqm_m = re.search(r"(\d+)\s*m[²2q]", all_text, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        clean_url = href.split("?")[0]

        listings.append(Listing(
            source="casa",
            listing_id=lid,
            title=title[:150] if title else f"Annuncio {lid}",
            price=price,
            city="",
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
