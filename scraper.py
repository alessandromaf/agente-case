"""Scrape listing details (price, sqm, rooms, address) from property pages."""

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


def _scrape_immobiliare(url: str, soup: BeautifulSoup) -> dict:
    """Extract details from an Immobiliare.it listing page."""
    info = {}
    text = soup.get_text(" ", strip=True)

    # Price
    price_el = soup.select_one("[class*='price']") or soup.select_one("[class*='Price']")
    price_text = price_el.get_text(strip=True) if price_el else text
    m = re.search(r"€\s*([\d.]+)", price_text)
    if m:
        info["price"] = int(re.sub(r"\D", "", m.group(1)))

    # Features (sqm, rooms) from the feature list
    for el in soup.select("[class*='feature'], [class*='Feature'], dt, dd, li"):
        t = el.get_text(strip=True).lower()
        if "superficie" in t or "m²" in t or "m2" in t:
            m = re.search(r"(\d+)\s*m", t)
            if m:
                info["sqm"] = m.group(1)
        if "local" in t:
            m = re.search(r"(\d+)", t)
            if m:
                info["rooms"] = m.group(1)

    # Fallback: regex on full text
    if "sqm" not in info:
        m = re.search(r"(\d+)\s*m[²2]", text)
        if m:
            info["sqm"] = m.group(1)
    if "rooms" not in info:
        m = re.search(r"(\d+)\s*local", text, re.IGNORECASE)
        if m:
            info["rooms"] = m.group(1)

    # Title / address from <h1> or og:title
    og_title = soup.select_one("meta[property='og:title']")
    if og_title:
        info["title"] = og_title.get("content", "")
    elif soup.h1:
        info["title"] = soup.h1.get_text(strip=True)

    # Address from title
    title = info.get("title", "")
    addr_m = re.search(r"(?:in vendita\s+(?:in |a ))(.+?)(?:\s*[-,]\s*\d|\s*$)", title, re.IGNORECASE)
    if addr_m:
        info["address"] = addr_m.group(1).strip()

    return info


def _scrape_idealista(url: str, soup: BeautifulSoup) -> dict:
    """Extract details from an Idealista.it listing page."""
    info = {}
    text = soup.get_text(" ", strip=True)

    # Price
    price_el = soup.select_one("[class*='price']") or soup.select_one("[class*='Price']")
    price_text = price_el.get_text(strip=True) if price_el else ""
    m = re.search(r"([\d.]+)\s*€", price_text) or re.search(r"€\s*([\d.]+)", price_text)
    if m:
        info["price"] = int(re.sub(r"\D", "", m.group(1)))
    else:
        m = re.search(r"([\d.]+)\s*€", text) or re.search(r"€\s*([\d.]+)", text)
        if m:
            info["price"] = int(re.sub(r"\D", "", m.group(1)))

    # Info features
    for el in soup.select("[class*='info-feature'], [class*='detail'], span, li"):
        t = el.get_text(strip=True).lower()
        if "m²" in t or "m2" in t:
            m = re.search(r"(\d+)", t)
            if m and "sqm" not in info:
                info["sqm"] = m.group(1)
        if "hab" in t or "local" in t or "stanz" in t:
            m = re.search(r"(\d+)", t)
            if m and "rooms" not in info:
                info["rooms"] = m.group(1)

    # Fallback
    if "sqm" not in info:
        m = re.search(r"(\d+)\s*m[²2]", text)
        if m:
            info["sqm"] = m.group(1)
    if "rooms" not in info:
        m = re.search(r"(\d+)\s*local", text, re.IGNORECASE)
        if m:
            info["rooms"] = m.group(1)

    # Title
    og_title = soup.select_one("meta[property='og:title']")
    if og_title:
        info["title"] = og_title.get("content", "")
    elif soup.h1:
        info["title"] = soup.h1.get_text(strip=True)

    # Address
    title = info.get("title", "")
    addr_m = re.search(r"(?:in |a )([^,]+(?:,\s*[^,]+)?)", title, re.IGNORECASE)
    if addr_m:
        info["address"] = addr_m.group(1).strip()

    return info


def _scrape_casa(url: str, soup: BeautifulSoup) -> dict:
    """Extract details from a Casa.it listing page."""
    info = {}
    text = soup.get_text(" ", strip=True)

    # Price
    m = re.search(r"€\s*([\d.]+)", text) or re.search(r"([\d.]+)\s*€", text)
    if m:
        info["price"] = int(re.sub(r"\D", "", m.group(1)))

    # Sqm/rooms
    m = re.search(r"(\d+)\s*m[²2]", text)
    if m:
        info["sqm"] = m.group(1)
    m = re.search(r"(\d+)\s*local", text, re.IGNORECASE)
    if m:
        info["rooms"] = m.group(1)

    # Title
    og_title = soup.select_one("meta[property='og:title']")
    if og_title:
        info["title"] = og_title.get("content", "")
    elif soup.h1:
        info["title"] = soup.h1.get_text(strip=True)

    # Address
    title = info.get("title", "")
    addr_m = re.search(r"(?:in vendita\s+(?:in |a ))(.+?)(?:\s*[-,]\s*\d|\s*$)", title, re.IGNORECASE)
    if addr_m:
        info["address"] = addr_m.group(1).strip()

    return info


SCRAPERS = {
    "immobiliare": _scrape_immobiliare,
    "idealista": _scrape_idealista,
    "casa": _scrape_casa,
}


def enrich_listing(listing: Listing) -> Listing:
    """Fetch the listing page and fill in missing details."""
    if not listing.url:
        return listing

    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = client.get(listing.url)
        if resp.status_code != 200:
            print(f"  [scraper] HTTP {resp.status_code} for {listing.url}")
            return listing

        soup = BeautifulSoup(resp.text, "lxml")
        scraper = SCRAPERS.get(listing.source)
        if not scraper:
            return listing

        info = scraper(listing.url, soup)
        print(f"  [scraper] {listing.source} {listing.listing_id}: scraped price={info.get('price')} sqm={info.get('sqm')} rooms={info.get('rooms')}")

        # Only fill in missing fields — don't overwrite existing good data
        if info.get("price") and listing.price == 0:
            listing.price = info["price"]
        if info.get("sqm") and not listing.sqm:
            listing.sqm = info["sqm"]
        if info.get("rooms") and not listing.rooms:
            listing.rooms = info["rooms"]
        if info.get("address") and not listing.address:
            listing.address = info["address"]
        if info.get("title") and (not listing.title or len(listing.title) < 10):
            listing.title = info["title"][:150]

    except Exception as e:
        print(f"  [scraper] Error scraping {listing.url}: {e}")

    return listing


def enrich_listings(listings: list[Listing]) -> list[Listing]:
    """Enrich all listings with scraped data. Adds a delay between requests."""
    for i, listing in enumerate(listings):
        enrich_listing(listing)
        if i < len(listings) - 1:
            time.sleep(1)
    return listings
