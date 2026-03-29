"""Export shortlist to Google Sheets."""

import json
import os
import gspread
from google.oauth2.service_account import Credentials
from db import get_shortlist
from telegram_notifier import SOURCE_LABELS

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_client() -> gspread.Client | None:
    """Create a gspread client from credentials."""
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
    if not creds_json:
        return None
    creds_data = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
    return gspread.authorize(creds)


def export_shortlist() -> str | None:
    """Sync the shortlist to Google Sheets. Returns the sheet URL or None."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if not sheet_id:
        return None

    client = _get_client()
    if not client:
        return None

    spreadsheet = client.open_by_key(sheet_id)

    # Use first worksheet or create "Shortlist"
    try:
        worksheet = spreadsheet.worksheet("Shortlist")
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet("Shortlist", rows=100, cols=10)

    items = get_shortlist()

    # Build rows: header + data
    header = ["#", "Titolo", "Prezzo", "Locali", "m\u00b2", "Indirizzo", "Fonte", "Link", "Data"]
    rows = [header]
    for i, item in enumerate(items, 1):
        price_str = f"\u20ac {item['price']:,}".replace(",", ".") if item["price"] else ""
        label = SOURCE_LABELS.get(item["source"], item["source"])
        rows.append([
            i,
            item["title"],
            price_str,
            item["rooms"],
            item["sqm"],
            item["address"],
            label,
            item["url"],
            item["added_at"][:10] if item["added_at"] else "",
        ])

    # Clear and write
    worksheet.clear()
    worksheet.update(rows, value_input_option="USER_ENTERED")

    # Format header row bold
    worksheet.format("A1:I1", {"textFormat": {"bold": True}})

    return spreadsheet.url
