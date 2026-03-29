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

PRICE_MIN = 60000
PRICE_MAX = 140000
MAX_PAGES = 10  # safety limit


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


def _price_ok(price: int) -> bool:
    """Check if price is in range (or unknown)."""
    return price == 0 or (PRICE_MIN <= price <= PRICE_MAX)


# ---------------------------------------------------------------------------
# Tecnocasa: forli1.tecnocasa.it
# Pagination: /pag-2, /pag-3, etc.
# ---------------------------------------------------------------------------
def _parse_tecnocasa_page(soup: BeautifulSoup) -> list[Listing]:
    listings = []
    for card in soup.select("a[href*='/appartamenti-in-vendita-']"):
        href = card.get("href", "")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://forli1.tecnocasa.it" + href

        lid_match = re.search(r"-(\d{6,})", href)
        if not lid_match:
            continue
        lid = lid_match.group(1)

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        h3 = card.select_one("h3")
        title = h3.get_text(strip=True) if h3 else ""
        if not title and price == 0:
            continue

        h4 = card.select_one("h4")
        address = h4.get_text(strip=True) if h4 else ""

        rooms = ""
        rooms_m = re.search(r"(\d+)\s*local", text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)

        sqm = ""
        sqm_m = re.search(r"(\d+)\s*[Mm][qQ²2]", text)
        if sqm_m:
            sqm = sqm_m.group(1)

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
    return listings


def scrape_tecnocasa(base_url: str) -> list[Listing]:
    all_listings = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}/pag-{page}"
        soup = _fetch_page(url)
        if not soup:
            break
        page_listings = _parse_tecnocasa_page(soup)
        if not page_listings:
            break
        for l in page_listings:
            if l.listing_id not in seen:
                seen.add(l.listing_id)
                all_listings.append(l)
        # Check if there's a next page link
        if not soup.select(f"a[href*='pag-{page + 1}']"):
            break
        time.sleep(1)

    print(f"  [site_scraper] tecnocasa: {len(all_listings)} listings ({page} pages)")
    return all_listings


# ---------------------------------------------------------------------------
# Romagnacase: romagnacase.it
# Pagination: &page=2, &page=3, etc.
# ---------------------------------------------------------------------------
def _parse_romagnacase_page(soup: BeautifulSoup) -> list[Listing]:
    listings = []
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

        card = link
        for ancestor in link.parents:
            if ancestor.name == "div" and ancestor != soup:
                classes = ancestor.get("class", [])
                if "@container" in classes:
                    card = ancestor
                    break

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        title = ""
        title_m = re.search(r"€\s*(?:[\d.,]+\s*)?(?:Offerta speciale\s*)?(.+?)(?:\s*Forl[ìi]|\s*IM-)", text, re.IGNORECASE)
        if title_m:
            title = title_m.group(1).strip()

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
    return listings


def scrape_romagnacase(base_url: str) -> list[Listing]:
    all_listings = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}&page={page}"
        soup = _fetch_page(url)
        if not soup:
            break
        page_listings = _parse_romagnacase_page(soup)
        if not page_listings:
            break
        for l in page_listings:
            if l.listing_id not in seen:
                seen.add(l.listing_id)
                all_listings.append(l)
        # Check for next page link
        if not soup.select(f"a[href*='page={page + 1}']"):
            break
        time.sleep(1)

    print(f"  [site_scraper] romagnacase: {len(all_listings)} listings ({page} pages)")
    return all_listings


# ---------------------------------------------------------------------------
# Alphacase: alphacase.it
# Likely single page, but check for pagination
# ---------------------------------------------------------------------------
def _parse_alphacase_page(soup: BeautifulSoup) -> list[Listing]:
    listings = []
    for link in soup.select("a[href*='/annuncio/']"):
        href = link.get("href", "")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.alphacase.it" + href

        lid_match = re.search(r"-(\d{6,})", href)
        if lid_match:
            lid = lid_match.group(1)
        else:
            lid = href.rstrip("/").split("/")[-1]

        card = link
        for ancestor in link.parents:
            if ancestor.name in ("div", "article", "section", "li") and ancestor != soup:
                card_text = ancestor.get_text(" ", strip=True)
                if "€" in card_text and len(card_text) > 30:
                    card = ancestor
                    break

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)

        h3 = card.select_one("h3")
        title = h3.get_text(strip=True) if h3 else link.get_text(strip=True)

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
    return listings


def scrape_alphacase(base_url: str) -> list[Listing]:
    all_listings = []
    seen = set()
    # Alphacase uses WordPress — try /page/2, /page/3 pattern
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}&pag={page}"
        soup = _fetch_page(url)
        if not soup:
            break
        page_listings = _parse_alphacase_page(soup)
        if not page_listings:
            break
        new_on_page = 0
        for l in page_listings:
            if l.listing_id not in seen:
                seen.add(l.listing_id)
                all_listings.append(l)
                new_on_page += 1
        # If all listings on this page were already seen, we've looped
        if new_on_page == 0:
            break
        time.sleep(1)

    print(f"  [site_scraper] alphacase: {len(all_listings)} listings ({page} pages)")
    return all_listings


# ---------------------------------------------------------------------------
# Agenzia Sansoni: agenziasansoni.it
# Uses ASP.NET PostBack for pagination — need to POST with __VIEWSTATE
# ---------------------------------------------------------------------------
def _parse_sansoni_page(soup: BeautifulSoup) -> list[Listing]:
    listings = []
    for card in soup.select("a[href*='/immobili/vendita/']"):
        href = card.get("href", "")
        if href.rstrip("/").endswith("/vendita"):
            continue
        if not href:
            continue
        if href.startswith("/"):
            href = "https://agenziasansoni.it" + href

        slug = href.rstrip("/").split("/")[-1]
        ref_match = re.search(r"-(\d{3,})$", slug)
        lid = ref_match.group(1) if ref_match else slug

        text = card.get_text(" ", strip=True)
        price = _parse_price(text)
        if price == 0:
            continue

        title = ""
        for el in card.select("h2, h3, h4, strong"):
            t = el.get_text(strip=True)
            if len(t) > 5 and "€" not in t:
                title = t
                break
        if not title:
            title = slug.replace("-", " ").title()

        rooms = ""
        rooms_m = re.search(r"(\d+)\s*(?:Lett[oi]|local|stanz|camer)", text, re.IGNORECASE)
        if rooms_m:
            rooms = rooms_m.group(1)

        sqm = ""
        sqm_m = re.search(r"(\d+)\s*m[²2q]", text, re.IGNORECASE)
        if sqm_m:
            sqm = sqm_m.group(1)

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
    return listings


def scrape_sansoni(base_url: str) -> list[Listing]:
    """Scrape Sansoni with ASP.NET PostBack pagination."""
    all_listings = []
    seen = set()

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        # First page — normal GET
        resp = client.get(base_url)
        if resp.status_code != 200:
            print(f"  [site_scraper] HTTP {resp.status_code} for {base_url}")
            return []

        for page in range(1, MAX_PAGES + 1):
            soup = BeautifulSoup(resp.text, "lxml")
            page_listings = _parse_sansoni_page(soup)
            if not page_listings:
                break
            for l in page_listings:
                if l.listing_id not in seen:
                    seen.add(l.listing_id)
                    all_listings.append(l)

            # Check for next page PostBack link
            next_link = None
            for a in soup.select("a[href*='__doPostBack']"):
                text = a.get_text(strip=True)
                if text == str(page + 1):
                    next_link = a
                    break
            if not next_link:
                break

            # Extract PostBack parameters
            onclick = next_link.get("href", "")
            pb_match = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", onclick)
            if not pb_match:
                break

            # Get form state
            viewstate = soup.select_one("input[name='__VIEWSTATE']")
            viewstate_gen = soup.select_one("input[name='__VIEWSTATEGENERATOR']")
            event_val = soup.select_one("input[name='__EVENTVALIDATION']")

            form_data = {
                "__EVENTTARGET": pb_match.group(1),
                "__EVENTARGUMENT": pb_match.group(2),
                "__VIEWSTATE": viewstate.get("value", "") if viewstate else "",
                "__VIEWSTATEGENERATOR": viewstate_gen.get("value", "") if viewstate_gen else "",
                "__EVENTVALIDATION": event_val.get("value", "") if event_val else "",
            }

            time.sleep(1)
            resp = client.post(base_url, data=form_data)
            if resp.status_code != 200:
                break

    print(f"  [site_scraper] sansoni: {len(all_listings)} listings ({page} pages)")
    return all_listings


# ---------------------------------------------------------------------------
# Registry of all site scrapers with their URLs
# All searches: Forlì, price range 60k-140k
# ---------------------------------------------------------------------------
SITE_SCRAPERS = [
    ("tecnocasa", "https://forli1.tecnocasa.it/appartamenti-in-vendita", scrape_tecnocasa),
    ("romagnacase", "https://romagnacase.it/acquista-case-o-appartamenti?filter%5Bcontract_type%5D=vendita&filter%5Bprovince%5D=Forl%C3%AC-Cesena&filter%5Bcity%5D%5B%5D=Forl%C3%AC&filter%5Bsurface%5D=&filter%5Broom_count%5D=&filter%5Bprice%5D=60000%2C140000", scrape_romagnacase),
    ("alphacase", "https://www.alphacase.it/risultati/?tipoContratto=V&tipologiaImmobile=Appartamento&fascePrezzo=60000+-+140000&comune=40012&ordinamento=Prezzo&ordinamento2=ASC", scrape_alphacase),
    ("sansoni", "https://agenziasansoni.it/immobili/vendita?tp=&zn=63,129,72,75,80,93,95&l1=0&l2=0&p1=60000&p2=140000&cd=&cr=", scrape_sansoni),
]


def scrape_all_sites() -> list[Listing]:
    """Scrape all configured real estate agency websites."""
    all_listings = []
    for name, url, scraper_fn in SITE_SCRAPERS:
        print(f"Scraping {name}...")
        try:
            listings = scraper_fn(url)
            # Apply price filter (some sites don't filter server-side)
            filtered = [l for l in listings if _price_ok(l.price)]
            print(f"  After price filter ({PRICE_MIN}-{PRICE_MAX}): {len(filtered)}/{len(listings)}")
            all_listings.extend(filtered)
        except Exception as e:
            print(f"  [site_scraper] Error scraping {name}: {e}")
        time.sleep(2)  # Be polite between sites
    return all_listings
