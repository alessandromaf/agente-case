import os
import re
import yaml
from email_reader import fetch_new_alerts
from email_parser import parse_alert
from db import filter_new, mark_seen
from telegram_notifier import send_listings
from scraper import enrich_listings
from site_scraper import scrape_all_sites


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

    gmail_email = config["gmail"]["email"]
    app_password = config["gmail"]["app_password"]

    if not gmail_email or gmail_email.startswith("$"):
        print("ERROR: GMAIL_EMAIL not set")
        return
    if not app_password or app_password.startswith("$"):
        print("ERROR: GMAIL_APP_PASSWORD not set")
        return

    # Fetch new alert emails
    all_listings = []
    alerts = fetch_new_alerts(gmail_email, app_password)
    if not alerts:
        print("No new alert emails.")
    else:
        # Parse listings from each email
        for alert in alerts:
            print(f"Parsing {alert['source']} email: {alert['subject'][:60]}")
            listings = parse_alert(alert)
            print(f"  Found {len(listings)} listings")
            all_listings.extend(listings)

    # Also scrape agency websites directly
    print("\nScraping agency websites...")
    site_listings = scrape_all_sites()
    all_listings.extend(site_listings)

    print(f"\nTotal listings parsed: {len(all_listings)}")

    # Filter to new-only and mark as seen immediately to prevent duplicates
    new_listings = filter_new(all_listings)
    print(f"New listings: {len(new_listings)}")

    if not new_listings:
        print("No new listings to send.")
        return

    # Mark as seen right away (before sending) to prevent duplicate sends
    # from concurrent or overlapping runs
    mark_seen(new_listings)

    # Enrich listings with scraped details (price, sqm, rooms, address)
    print("Enriching listings with scraped details...")
    enrich_listings(new_listings)

    # Send to Telegram
    bot_token = config["telegram"]["bot_token"]
    channel_id = config["telegram"]["channel_id"]

    if not bot_token or bot_token.startswith("$"):
        print("WARNING: TELEGRAM_BOT_TOKEN not set, printing listings instead:")
        for l in new_listings:
            print(f"  [{l.source}] {l.title} | {l.price} | {l.url}")
        return

    sent, message_ids = send_listings(new_listings, bot_token, channel_id)
    print(f"Sent {sent}/{len(new_listings)} messages to Telegram.")

    # Update DB with telegram message IDs
    if message_ids:
        mark_seen(new_listings, message_ids)


if __name__ == "__main__":
    main()
