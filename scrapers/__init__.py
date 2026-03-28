from scrapers.immobiliare import scrape as scrape_immobiliare
from scrapers.idealista import scrape as scrape_idealista
from scrapers.casa import scrape as scrape_casa

ALL_SCRAPERS = [
    ("immobiliare", scrape_immobiliare),
    ("idealista", scrape_idealista),
    ("casa", scrape_casa),
]
