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
        params.append(f"prezzo_min={f['price_min']}")
    if f.get("price_max"):
        params.append(f"prezzo_max={f['price_max']}")
    qs = "&".join(params)
    base = f"https://www.casa.it/vendita/residenziale/{city}/"
    return f"{base}?{qs}" if qs else base


def _parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def scrape(config: dict) -> list[Listing]:
    url = _build_url(config)
    print(f"[casa] Fetching {url}")
    try:
        html = fetch_page(url)
    except Exception as e:
        print(f"[casa] Failed to fetch: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    listings: list[Listing] = []

    # Try JSON-LD structured data
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
            lid = re.search(r"/(\d+)", listing_url)
            if not lid:
                continue
            price_val = 0
            offers = obj.get("offers", {})
            if isinstance(offers, dict):
                price_val = int(offers.get("price", 0))
            listings.append(Listing(
                source="casa",
                listing_id=lid.group(1),
                title=obj.get("name", ""),
                price=price_val,
                city=config["filters"]["city"],
                url=listing_url if listing_url.startswith("http") else f"https://www.casa.it{listing_url}",
                image_url=obj.get("image", ""),
            ))

    # Fallback: HTML parsing
    if not listings:
        # Casa.it uses React/Next.js — look for __NEXT_DATA__ JSON
        next_data = soup.select_one("script#__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                nd = json.loads(next_data.string)
                results = (
                    nd.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                    .get("queries", [])
                )
                for query in results:
                    state = query.get("state", {}).get("data", {})
                    items = state.get("results", state.get("items", []))
                    if isinstance(items, dict):
                        items = items.get("results", items.get("items", []))
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        lid = str(item.get("id", ""))
                        if not lid:
                            continue
                        price = item.get("price", {})
                        price_val = int(price.get("value", 0)) if isinstance(price, dict) else int(price or 0)
                        item_url = item.get("url", item.get("seoUrl", ""))
                        if item_url and not item_url.startswith("http"):
                            item_url = f"https://www.casa.it{item_url}"
                        imgs = item.get("images", item.get("photos", []))
                        img_url = imgs[0].get("url", "") if imgs else ""
                        features = item.get("features", {})
                        listings.append(Listing(
                            source="casa",
                            listing_id=lid,
                            title=item.get("title", ""),
                            price=price_val,
                            city=config["filters"]["city"],
                            url=item_url,
                            image_url=img_url,
                            rooms=str(features.get("rooms", "")),
                            sqm=str(features.get("surface", "")),
                        ))
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

    # Final fallback: generic card parsing
    if not listings:
        cards = soup.select("[class*=listing], [class*=Listing], [class*=property], [class*=Property]")
        for card in cards:
            link = card.select_one("a[href*='/vendita/'], a[href*='/dettaglio/']")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = "https://www.casa.it" + href
            lid = re.search(r"/(\d+)", href)
            if not lid:
                continue

            title = link.get_text(strip=True)
            price_el = card.select_one("[class*=price], [class*=Price]")
            price = _parse_price(price_el.get_text()) if price_el else 0

            img = card.select_one("img")
            img_url = img.get("src", "") if img else ""

            listings.append(Listing(
                source="casa",
                listing_id=lid.group(1),
                title=title,
                price=price,
                city=config["filters"]["city"],
                url=href,
                image_url=img_url,
            ))

    print(f"[casa] Found {len(listings)} listings")
    return listings
