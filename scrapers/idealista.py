import json
import re
from bs4 import BeautifulSoup
from models import Listing
from scrapers.base import fetch_page


def _build_url(config: dict) -> str:
    f = config["filters"]
    city = f["city"].lower()
    parts = []
    if f.get("price_min"):
        parts.append(f"prezzo-min_{f['price_min']}")
    if f.get("price_max"):
        parts.append(f"prezzo-max_{f['price_max']}")
    filter_path = ",".join(parts)
    if filter_path:
        return f"https://www.idealista.it/vendita-case/{city}/con-{filter_path}/"
    return f"https://www.idealista.it/vendita-case/{city}/"


def _parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def scrape(config: dict) -> list[Listing]:
    url = _build_url(config)
    print(f"[idealista] Fetching {url}")
    try:
        html = fetch_page(url)
    except Exception as e:
        print(f"[idealista] Failed to fetch: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    listings: list[Listing] = []

    # Strategy 1: JSON-LD (usually only has URLs, not full data)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = []
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            items = data.get("itemListElement", [])
        for item in items:
            obj = item.get("item", item) if isinstance(item, dict) else item
            if not isinstance(obj, dict):
                continue
            listing_url = obj.get("url", "")
            lid = re.search(r"/(\d+)", listing_url)
            if not lid:
                continue
            price_val = 0
            offers = obj.get("offers", {})
            if isinstance(offers, dict):
                price_val = int(offers.get("price", 0))
            if listing_url and not listing_url.startswith("http"):
                listing_url = f"https://www.idealista.it{listing_url}"
            listings.append(Listing(
                source="idealista",
                listing_id=lid.group(1),
                title=obj.get("name", ""),
                price=price_val,
                city=config["filters"]["city"],
                url=listing_url,
                image_url=obj.get("image", ""),
            ))

    # JSON-LD on idealista typically lacks full data, so always try HTML too
    # Strategy 2: HTML parsing with known selectors
    seen_ids = {l.listing_id for l in listings}
    articles = soup.select("article.item, article.item-multimedia-container")

    for article in articles:
        lid = article.get("data-adid", "")
        if not lid:
            lid_el = article.get("data-element-id", "")
            if lid_el:
                lid = lid_el

        link = article.select_one("a.item-link")
        if not link:
            continue

        href = link.get("href", "")
        if not href.startswith("http"):
            href = "https://www.idealista.it" + href

        if not lid:
            lid_match = re.search(r"/(\d+)", href)
            lid = lid_match.group(1) if lid_match else ""
        if not lid or lid in seen_ids:
            continue

        title = link.get_text(strip=True)

        price_el = article.select_one(".item-price")
        price = _parse_price(price_el.get_text()) if price_el else 0

        img = article.select_one("img")
        img_url = ""
        if img:
            img_url = img.get("src", "") or img.get("data-src", "")

        # Parse detail spans for rooms and sqm
        detail_spans = [s.get_text(strip=True) for s in article.select(".item-detail span")]
        rooms = ""
        sqm = ""
        for d in detail_spans:
            if "local" in d.lower() and not rooms:
                m = re.search(r"(\d+)", d)
                if m:
                    rooms = m.group(1)
            if "m\u00b2" in d and not sqm:
                m = re.search(r"(\d+)", d)
                if m:
                    sqm = m.group(1)

        listings.append(Listing(
            source="idealista",
            listing_id=lid,
            title=title,
            price=price,
            city=config["filters"]["city"],
            url=href,
            image_url=img_url,
            rooms=rooms,
            sqm=sqm,
        ))

    print(f"[idealista] Found {len(listings)} listings")
    return listings
