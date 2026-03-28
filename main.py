import os
import re
import yaml
from scrapers import ALL_SCRAPERS
from db import filter_new
from telegram_notifier import send_listings


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        raw = f.read()
    # Substitute ${ENV_VAR} with environment variable values
    def _replace(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))
    resolved = re.sub(r"\$\{(\w+)\}", _replace, raw)
    return yaml.safe_load(resolved)


def main() -> None:
    config = load_config()

    # Scrape all sources
    all_listings = []
    for name, scrape_fn in ALL_SCRAPERS:
        try:
            results = scrape_fn(config)
            all_listings.extend(results)
        except Exception as e:
            print(f"[{name}] Scraper failed: {e}")

    print(f"\nTotal listings found: {len(all_listings)}")

    # Filter to new-only
    new_listings = filter_new(all_listings)
    print(f"New listings: {len(new_listings)}")

    if not new_listings:
        print("No new listings to send.")
        return

    # Send to Telegram
    bot_token = config["telegram"]["bot_token"]
    channel_id = config["telegram"]["channel_id"]

    if not bot_token or bot_token.startswith("$"):
        print("WARNING: TELEGRAM_BOT_TOKEN not set, skipping Telegram send.")
        for l in new_listings:
            print(f"  - [{l.source}] {l.title} | {l.price} | {l.url}")
        return

    sent = send_listings(new_listings, bot_token, channel_id)
    print(f"Sent {sent}/{len(new_listings)} messages to Telegram.")


if __name__ == "__main__":
    main()
