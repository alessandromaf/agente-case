import json
import re
from bs4 import BeautifulSoup
from models import Listing
from scrapers.base import fetch_page


def _build_url(config: dict) -> str:
    f = config["filters"]
    city = f["city"].lower()
    params = []
    if f.get("price_min"):
        params.append(f"prezzoMinimo={f['price_min']}")
    if f.get("price_max"):
        params.append(f"prezzoMassimo={f['price_max']}")
    qs = "&".join(params)
    return f"https://www.immobiliare.it/vendita-case/{city}/?{qs}"


def _parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _parse_next_data(soup: BeautifulSoup, config: dict) -> list[Listing]:
    """Parse __NEXT_DATA__ JSON embedded by Next.js — most reliable source."""
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        nd = json.loads(script.string)
    except (json.JSONDecodeError, TypeError):
        return []

    listings: list[Listing] = []
    queries = (
        nd.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )
    for query in queries:
        results = query.get("state", {}).get("data", {}).get("results", [])
        if not isinstance(results, list):
            continue
        for entry in results:
            re_data = entry.get("realEstate", entry)
            if not isinstance(re_data, dict):
                continue
            lid = str(re_data.get("id", ""))
            if not lid:
                continue

            price_obj = re_data.get("price", {})
            price_val = int(price_obj.get("value", 0)) if isinstance(price_obj, dict) else int(price_obj or 0)

            location = re_data.get("location", {})
            address = location.get("address", "") if isinstance(location, dict) else ""

            props = re_data.get("properties", [])
            rooms = ""
            sqm = ""
            if isinstance(props, list) and props:
                p = props[0]
                rooms = str(p.get("rooms", ""))
                sqm = str(p.get("surface", ""))

            photos = re_data.get("multimedia", {}).get("photos", [])
            img_url = photos[0].get("url", "") if photos else ""

            detail_url = f"https://www.immobiliare.it/annunci/{lid}/"

            listings.append(Listing(
                source="immobiliare",
                listing_id=lid,
                title=re_data.get("title", address),
                price=price_val,
                city=config["filters"]["city"],
                url=detail_url,
                image_url=img_url,
                rooms=rooms,
                sqm=sqm,
            ))
    return listings


def scrape(config: dict) -> list[Listing]:
    url = _build_url(config)
    print(f"[immobiliare] Fetching {url}")
    html = fetch_page(url)
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: __NEXT_DATA__ JSON (best)
    listings = _parse_next_data(soup, config)
    if listings:
        print(f"[immobiliare] Found {len(listings)} listings via __NEXT_DATA__")
        return listings

    # Strategy 2: JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = []
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            items = data.get("itemListElement", [])
        elif isinstance(data, list):
            items = data

        for item in items:
            obj = item.get("item", item) if isinstance(item, dict) else item
            if not isinstance(obj, dict):
                continue
            listing_url = obj.get("url", "")
            listing_id = re.search(r"/(\d+)/", listing_url)
            if not listing_id:
                continue
            price_val = 0
            offers = obj.get("offers", {})
            if isinstance(offers, dict):
                price_val = int(offers.get("price", 0))
            elif isinstance(offers, list) and offers:
                price_val = int(offers[0].get("price", 0))
            listings.append(Listing(
                source="immobiliare",
                listing_id=listing_id.group(1),
                title=obj.get("name", ""),
                price=price_val,
                city=config["filters"]["city"],
                url=listing_url,
                image_url=obj.get("image", ""),
            ))

    if listings:
        print(f"[immobiliare] Found {len(listings)} listings via JSON-LD")
        return listings

    # Strategy 3: HTML card parsing (fallback)
    cards = soup.select("li.nd-list__item.in-realEstateResults__item")
    if not cards:
        cards = soup.select("div.in-realEstateResult")

    for card in cards:
        data_id = card.get("data-id", "")
        link = card.select_one("a.in-card__title") or card.select_one("a[href*='/annunci/']")
        if not link:
            continue
        href = link.get("href", "")
        if not href.startswith("http"):
            href = "https://www.immobiliare.it" + href

        lid = data_id or ""
        if not lid:
            lid_match = re.search(r"/(\d+)/", href)
            lid = lid_match.group(1) if lid_match else ""
        if not lid:
            continue

        title = link.get_text(strip=True)

        price_el = card.select_one("li.in-realEstateResult__price, div.in-realEstateResult__price, [class*=price]")
        price = _parse_price(price_el.get_text()) if price_el else 0

        img = card.select_one("img")
        img_url = (img.get("src", "") or img.get("data-src", "")) if img else ""

        features_text = ""
        for feat in card.select("[class*=feature], [class*=feat]"):
            features_text += " " + feat.get_text(" ", strip=True)

        rooms = ""
        sqm = ""
        rooms_match = re.search(r"(\d+)\s*local", features_text, re.IGNORECASE)
        if rooms_match:
            rooms = rooms_match.group(1)
        sqm_match = re.search(r"(\d+)\s*m", features_text, re.IGNORECASE)
        if sqm_match:
            sqm = sqm_match.group(1)

        listings.append(Listing(
            source="immobiliare",
            listing_id=lid,
            title=title,
            price=price,
            city=config["filters"]["city"],
            url=href,
            image_url=img_url,
            rooms=rooms,
            sqm=sqm,
        ))

    print(f"[immobiliare] Found {len(listings)} listings via HTML")
    return listings
