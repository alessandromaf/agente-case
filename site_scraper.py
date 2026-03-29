"""Scrape listings directly from real estate agency websites."""

import re
import time
import httpx
from bs4 import BeautifulSoup
from models import Listing

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


def _parse_price(text: str) -> int:
    """Extract price integer from text like '€ 93.000' or '120.000,00 €'."""
    m = re.search(r"€\s*([\d.,]+)", text) or re.search(r"([\d.,]+)\s*€", text)
    if m:
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            return int(float(raw))
        except ValueError:
            return 0
    return 0


def _fetch_page(url: str) -> BeautifulSoup | None:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            print(f"  [site_scraper] HTTP {resp.status_code} for {url}")
            return None
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [site_scraper] Error fetching {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Tecnocasa: forli1.tecnocasa.it
# Cards are <a href="/forli/appartamenti-in-vendita-XXXXX"> containing
# price, h3 (type), h4 (address), and text with locali/Mq
# ---------------------------------------------------------------------------
def scrape_tecnocasa(url: str) -> list[Listing]:
    soup = _fetch_page(url)
    if not soup:
        return []

    listings = []
    for card in soup.select("a[href*='/appartamenti-in-vendita-']"):
        href = card.get("href", "")
        if not href:
            continue

        # Build full URL
        if href.startswith("/"):
            href = "https://forli1.tecnocasa.it" + href

        # Listing ID from URL
        lid_match = re.search(r"-(\d{6,})", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        # Title from h3
        h3 = card.select_one("h3")
        title = h3.get_text(strip=True) if h3 else ""

        # Address from h4
        h4 = card.select_one("h4")
        address = h4.get_text(strip=True) if h4 else ""

        # Rooms
        rooms = ""
        rooms_m = re.search(r"(\d+)\s*local", text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)

        # Sqm
        sqm = ""
        sqm_m = re.search(r"(\d+)\s*[Mm][qQ²2]", text)
        if sqm_m:
            sqm = sqm_m.group(1)

        # Skip empty cards (image-only links with no data)
        if not title and price == 0:
            continue

        listings.append(Listing(
            source="tecnocasa",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="Forlì",
            address=address,
            url=href.split("?")[0],
            rooms=rooms,
            sqm=sqm,
        ))

    # Deduplicate by listing_id
    seen = set()
    unique = []
    for l in listings:
        if l.listing_id not in seen:
            seen.add(l.listing_id)
            unique.append(l)

    print(f"  [site_scraper] tecnocasa: {len(unique)} listings")
    return unique


# ---------------------------------------------------------------------------
# Romagnacase: romagnacase.it
# Cards are <a href="/acquista-case-o-appartamenti/..."> with price, title,
# location, rooms, sqm
# ---------------------------------------------------------------------------
def scrape_romagnacase(url: str) -> list[Listing]:
    soup = _fetch_page(url)
    if not soup:
        return []

    listings = []
    # Each listing card is in a div with @container class, containing IM-XXXXX links
    # Find all links with IM- in the href, then walk up to the card container
    seen_ids = set()
    for link in soup.select("a[href*='/IM-']"):
        href = link.get("href", "")
        lid_match = re.search(r"(IM-\d+)", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)
        if lid in seen_ids:
            continue
        seen_ids.add(lid)

        if href.startswith("/"):
            href = "https://romagnacase.it" + href

        # Walk up to the card container (div.@container or similar)
        card = link
        for ancestor in link.parents:
            if ancestor.name == "div" and ancestor != soup:
                classes = ancestor.get("class", [])
                if "@container" in classes:
                    card = ancestor
                    break

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        # Title — text between price and address, usually uppercase
        title = ""
        # Look for the main title (uppercase text after €)
        title_m = re.search(r"€\s*(?:[\d.,]+\s*)?(?:Offerta speciale\s*)?(.+?)(?:\s*Forl[ìi]|\s*IM-)", text, re.IGNORECASE)
        if title_m:
            title = title_m.group(1).strip()

        # Address
        address = ""
        addr_m = re.search(r"Forl[ìi]\s*[-–]\s*(.+?)(?:\s*IM-|\s*\d+\s*local|\s*ca\.)", text)
        if addr_m:
            address = addr_m.group(1).strip()

        rooms = ""
        rooms_m = re.search(r"(\d+)\s*local", text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)

        sqm = ""
        sqm_m = re.search(r"ca\.?\s*(\d+)\s*m[²2\u00b2]|(\d+)\s*m[²2\u00b2]", text, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1) or sqm_m.group(2)

        listings.append(Listing(
            source="romagnacase",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="Forlì",
            address=address,
            url=href.split("?")[0],
            rooms=rooms,
            sqm=sqm,
        ))

    print(f"  [site_scraper] romagnacase: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Alphacase: alphacase.it
# Cards have <h3><a href="...">Title</a></h3>, price in <p> with €,
# details like "locali 3 | superficie 95m2 | 1 bagno"
# ---------------------------------------------------------------------------
def scrape_alphacase(url: str) -> list[Listing]:
    soup = _fetch_page(url)
    if not soup:
        return []

    listings = []
    for link in soup.select("a[href*='/annuncio/']"):
        href = link.get("href", "")
        if not href:
            continue

        if href.startswith("/"):
            href = "https://www.alphacase.it" + href

        # Listing ID from URL slug or Getrix ID
        lid_match = re.search(r"-(\d{6,})", href)
        if lid_match:
            lid = lid_match.group(1)
        else:
            lid = href.rstrip("/").split("/")[-1]

        # Find the card container — walk up to find a block with price+details
        card = link
        for ancestor in link.parents:
            if ancestor.name in ("div", "article", "section", "li") and ancestor != soup:
                card_text = ancestor.get_text(" ", strip=True)
                if "€" in card_text and len(card_text) > 30:
                    card = ancestor
                    break

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        # Title from h3 or link text
        h3 = card.select_one("h3")
        title = h3.get_text(strip=True) if h3 else link.get_text(strip=True)

        # Address from title (e.g., "Forlì - Trilocale in ...")
        address = ""
        addr_m = re.search(r"Forlì\s*[-–]\s*(.+)", title)
        if addr_m:
            address = addr_m.group(1).strip()

        rooms = ""
        rooms_m = re.search(r"locali\s*\*?\*?(\d+)|(\d+)\s*local", text, re.IGNORECASE)
        if rooms_m:
            val = rooms_m.group(1) or rooms_m.group(2)
            if val and int(val) > 0:
                rooms = val

        sqm = ""
        sqm_m = re.search(r"superficie\s*\*?\*?(\d+)\s*m|(\d+)\s*m[²2q]", text, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1) or sqm_m.group(2)

        listings.append(Listing(
            source="alphacase",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="Forlì",
            address=address,
            url=href.split("?")[0],
            rooms=rooms,
            sqm=sqm,
        ))

    # Deduplicate by listing_id (multiple links per listing)
    seen = set()
    unique = []
    for l in listings:
        if l.listing_id not in seen:
            seen.add(l.listing_id)
            unique.append(l)

    print(f"  [site_scraper] alphacase: {len(unique)} listings")
    return unique


# ---------------------------------------------------------------------------
# Agenzia Sansoni: agenziasansoni.it
# Cards are <a href="/immobili/vendita/..."> with price (€ XX.XXX,00),
# title, beds/baths via icons
# ---------------------------------------------------------------------------
def scrape_sansoni(url: str) -> list[Listing]:
    soup = _fetch_page(url)
    if not soup:
        return []

    listings = []
    for card in soup.select("a[href*='/immobili/vendita/']"):
        href = card.get("href", "")
        # Skip nav/filter links
        if href.rstrip("/").endswith("/vendita"):
            continue
        if not href:
            continue

        if href.startswith("/"):
            href = "https://agenziasansoni.it" + href

        # Listing ID from URL slug — extract ref number if present
        slug = href.rstrip("/").split("/")[-1]
        ref_match = re.search(r"-(\d{3,})$", slug)
        lid = ref_match.group(1) if ref_match else slug

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        # Skip cards with no price (probably nav links)
        if price == 0:
            continue

        # Title — make it readable from slug if no heading found
        title = ""
        for el in card.select("h2, h3, h4, strong"):
            t = el.get_text(strip=True)
            if len(t) > 5 and "€" not in t:
                title = t
                break
        if not title:
            # Convert slug to readable title
            title = slug.replace("-", " ").title()

        # Rooms — look for bed count (Sansoni uses "Letto" icons)
        rooms = ""
        rooms_m = re.search(r"(\d+)\s*(?:Lett[oi]|local|stanz|camer)", text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)

        sqm = ""
        sqm_m = re.search(r"(\d+)\s*m[²2q]", text, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

        # Address — look for "rif XXXX" preceded by location
        address = ""
        addr_m = re.search(r"(?:Via|Viale|Corso|Piazza|P\.le|Centro)[^€\d]*?(?=\s*(?:rif|€|\d+\s*Lett))", text, re.IGNORECASE)
        if addr_m:
            address = addr_m.group(0).strip()

        listings.append(Listing(
            source="sansoni",
            listing_id=lid,
            title=title[:150],
            price=price,
            city="Forlì",
            address=address,
            url=href.split("?")[0],
            rooms=rooms,
            sqm=sqm,
        ))

    print(f"  [site_scraper] sansoni: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Registry of all site scrapers with their URLs
# ---------------------------------------------------------------------------
SITE_SCRAPERS = [
    ("tecnocasa", "https://forli1.tecnocasa.it/appartamenti-in-vendita", scrape_tecnocasa),
    ("romagnacase", "https://romagnacase.it/acquista-case-o-appartamenti?filter%5Bcontract_type%5D=vendita&filter%5Bprovince%5D=Forl%C3%AC-Cesena&filter%5Bcity%5D%5B%5D=Forl%C3%AC&filter%5Bsurface%5D=&filter%5Broom_count%5D=&filter%5Bprice%5D=", scrape_romagnacase),
    ("alphacase", "https://www.alphacase.it/risultati/?tipoContratto=V&tipologiaImmobile=Appartamento&fascePrezzo=70000+-+150000&comune=40012&ordinamento=Prezzo&ordinamento2=ASC", scrape_alphacase),
    ("sansoni", "https://agenziasansoni.it/immobili/vendita?tp=&zn=63,129,72,75,80,93,95&l1=0&l2=0&p1=70000&p2=140000&cd=&cr=", scrape_sansoni),
]


def scrape_all_sites() -> list[Listing]:
    """Scrape all configured real estate agency websites."""
    all_listings = []
    for name, url, scraper_fn in SITE_SCRAPERS:
        print(f"Scraping {name}...")
        try:
            listings = scraper_fn(url)
            all_listings.extend(listings)
        except Exception as e:
            print(f"  [site_scraper] Error scraping {name}: {e}")
        time.sleep(2)  # Be polite between sites
    return all_listings
