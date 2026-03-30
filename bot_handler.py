"""Handle Telegram bot updates: callback queries (button presses) and commands."""

import csv
import io
import json
import re
import tempfile
import httpx
from db import (
    get_listing_by_message_id, add_to_shortlist, remove_from_shortlist,
    get_shortlist,
)
from telegram_notifier import answer_callback, send_text, SOURCE_LABELS


def _get_updates(bot_token: str, offset: int = 0) -> list[dict]:
    """Fetch pending updates from Telegram."""
    resp = httpx.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params={"offset": offset, "timeout": 5},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json().get("result", [])
    return []



def _handle_callback(bot_token: str, callback: dict) -> None:
    """Handle a callback query (inline button press)."""
    cb_id = callback["id"]
    data_str = callback.get("data", "")

    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        answer_callback(bot_token, cb_id, "Errore: dati non validi")
        return

    action = data.get("a")
    source = data.get("s", "")
    listing_id = data.get("id", "")

    if action == "save":
        # Get listing details from the message text
        msg = callback.get("message", {})
        text = msg.get("text", "")
        chat_id = msg.get("chat", {}).get("id")

        # Extract info from message text
        title = ""
        price = 0
        sqm = ""
        rooms = ""
        address = ""
        url = ""

        for line in text.split("\n"):
            if line.startswith("\U0001f3e0"):
                pass  # header
            elif line.startswith("\U0001f4cd"):
                address = line.replace("\U0001f4cd", "").strip()
            elif line.startswith("\U0001f4b0"):
                price_str = line.replace("\U0001f4b0", "").replace("\u20ac", "").replace(".", "").strip()
                try:
                    price = int(price_str)
                except ValueError:
                    pass
            elif line.startswith("\U0001f4d0"):
                details = line.replace("\U0001f4d0", "").strip()
                if "locali" in details:
                    parts = details.split("\u00b7")
                    for p in parts:
                        p = p.strip()
                        if "locali" in p:
                            rooms = p.replace("locali", "").strip()
                        elif "m\u00b2" in p:
                            sqm = p.replace("m\u00b2", "").strip()
            elif "Vedi annuncio" in line:
                # Extract URL from markdown link
                import re
                m = re.search(r"\((https?://[^)]+)\)", line)
                if m:
                    url = m.group(1)
            elif not title and len(line.strip()) > 3:
                title = line.strip()

        added = add_to_shortlist(source, listing_id, url, title, price, sqm, rooms, address)
        if added:
            answer_callback(bot_token, cb_id, "\u2b50 Salvato nella shortlist!")
        else:
            answer_callback(bot_token, cb_id, "Gi\u00e0 nella shortlist")

    elif action == "remove":
        removed = remove_from_shortlist(source, listing_id)
        if removed:
            answer_callback(bot_token, cb_id, "\u274c Rimosso dalla shortlist")
        else:
            answer_callback(bot_token, cb_id, "Non trovato nella shortlist")


def _handle_command(bot_token: str, message: dict) -> None:
    """Handle bot commands like /shortlist and /remove."""
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text.startswith("/shortlist"):
        items = get_shortlist()
        if not items:
            send_text(bot_token, str(chat_id), "La shortlist \u00e8 vuota.")
            return

        lines = ["\u2b50 *La tua shortlist:*\n"]
        for i, item in enumerate(items, 1):
            label = SOURCE_LABELS.get(item["source"], item["source"])
            price_str = f"\u20ac {item['price']:,}".replace(",", ".") if item["price"] else "N/D"
            details = []
            if item["rooms"]:
                details.append(f"{item['rooms']} locali")
            if item["sqm"]:
                details.append(f"{item['sqm']} m\u00b2")
            detail_str = f" \u00b7 {' \u00b7 '.join(details)}" if details else ""

            lines.append(f"{i}. *{item['title'][:60]}*")
            lines.append(f"   {price_str}{detail_str}")
            if item["address"]:
                lines.append(f"   \U0001f4cd {item['address']}")
            lines.append(f"   \U0001f517 [Vedi]({item['url']}) \u2014 _{label}_")
            lines.append("")

        lines.append("Per rimuovere: /remove\\_N (es. /remove\\_1)")
        send_text(bot_token, str(chat_id), "\n".join(lines))

    elif text.startswith("/remove"):
        # /remove_N or /remove N
        parts = text.replace("_", " ").split()
        if len(parts) < 2:
            send_text(bot_token, str(chat_id), "Uso: /remove\\_N (es. /remove\\_1)")
            return
        try:
            idx = int(parts[1]) - 1
        except ValueError:
            send_text(bot_token, str(chat_id), "Uso: /remove\\_N (es. /remove\\_1)")
            return

        items = get_shortlist()
        if idx < 0 or idx >= len(items):
            send_text(bot_token, str(chat_id), f"Numero non valido. Hai {len(items)} elementi.")
            return

        item = items[idx]
        removed = remove_from_shortlist(item["source"], item["listing_id"])
        if removed:
            send_text(bot_token, str(chat_id), f"\u274c Rimosso: {item['title'][:60]}")
        else:
            send_text(bot_token, str(chat_id), "Errore nella rimozione.")

    elif text.startswith("/save"):
        # /save <url> — save a listing by URL
        parts = text.split(None, 1)
        if len(parts) < 2:
            send_text(bot_token, str(chat_id),
                      "Uso: /save URL\nEs: /save https://romagnacase.it/acquista-case-o-appartamenti/...")
            return

        url = parts[1].strip()

        # Detect source from URL
        source = "unknown"
        listing_id = url
        if "tecnocasa.it" in url:
            source = "tecnocasa"
            m = re.search(r"-(\d{6,})", url)
            if m:
                listing_id = m.group(1)
        elif "romagnacase.it" in url:
            source = "romagnacase"
            m = re.search(r"(IM-\d+)", url)
            if m:
                listing_id = m.group(1)
        elif "alphacase.it" in url:
            source = "alphacase"
            m = re.search(r"-(\d{6,})", url)
            if m:
                listing_id = m.group(1)
        elif "sansoni.it" in url:
            source = "sansoni"
            listing_id = url.rstrip("/").split("/")[-1]
        elif "immobiliare.it" in url:
            source = "immobiliare"
            m = re.search(r"/annunci/(\d+)", url)
            if m:
                listing_id = m.group(1)
        elif "idealista.it" in url:
            source = "idealista"
            m = re.search(r"/immobile/(\d+)", url)
            if m:
                listing_id = m.group(1)
        elif "casa.it" in url:
            source = "casa"
            m = re.search(r"/immobili/(\d+)", url)
            if m:
                listing_id = m.group(1)

        title = url.rstrip("/").split("/")[-1].replace("-", " ").title()[:100]
        added = add_to_shortlist(source, listing_id, url, title, 0, "", "", "")
        if added:
            send_text(bot_token, str(chat_id), f"\u2b50 Salvato: {title}")
        else:
            send_text(bot_token, str(chat_id), "Gi\u00e0 nella shortlist")

    elif text.startswith("/export"):
        items = get_shortlist()
        if not items:
            send_text(bot_token, str(chat_id), "La shortlist \u00e8 vuota, niente da esportare.")
            return

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["#", "Titolo", "Prezzo", "Locali", "m\u00b2", "Indirizzo", "Fonte", "Link", "Data"])
        for i, item in enumerate(items, 1):
            label = SOURCE_LABELS.get(item["source"], item["source"])
            price_str = f"\u20ac {item['price']:,}".replace(",", ".") if item["price"] else ""
            writer.writerow([
                i, item["title"], price_str, item["rooms"], item["sqm"],
                item["address"], label, item["url"],
                item["added_at"][:10] if item["added_at"] else "",
            ])

        # Send CSV file via Telegram
        csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendDocument",
            data={"chat_id": str(chat_id), "caption": f"\u2b50 Shortlist ({len(items)} annunci)"},
            files={"document": ("shortlist.csv", csv_bytes, "text/csv")},
            timeout=15,
        )
        if resp.status_code != 200:
            send_text(bot_token, str(chat_id), "Errore nell'invio del file.")

    elif text.startswith("/start") or text.startswith("/help"):
        send_text(bot_token, str(chat_id),
                  "\U0001f3e0 *Bot Agente Case*\n\n"
                  "Premi \u2b50 *Salva* sotto un annuncio per aggiungerlo alla shortlist.\n\n"
                  "Comandi:\n"
                  "/save URL \u2014 Salva un annuncio tramite link\n"
                  "/shortlist \u2014 Vedi la tua shortlist\n"
                  "/remove\\_N \u2014 Rimuovi elemento N dalla shortlist\n"
                  "/export \u2014 Esporta shortlist come CSV")


def register_commands(bot_token: str) -> None:
    """Register bot commands with Telegram (shows in the / menu)."""
    # Clear first to remove any stale manually-set commands
    httpx.post(
        f"https://api.telegram.org/bot{bot_token}/deleteMyCommands",
        json={},
        timeout=10,
    )
    commands = [
        {"command": "shortlist", "description": "Vedi la tua shortlist"},
        {"command": "remove_1", "description": "Rimuovi elemento N dalla shortlist (es. /remove_2)"},
        {"command": "save",     "description": "Salva un annuncio tramite URL"},
        {"command": "export",   "description": "Esporta shortlist come CSV"},
        {"command": "help",     "description": "Mostra i comandi disponibili"},
    ]
    httpx.post(
        f"https://api.telegram.org/bot{bot_token}/setMyCommands",
        json={"commands": commands},
        timeout=10,
    )


def process_updates(bot_token: str) -> int:
    """Process all pending Telegram updates. Returns number processed."""
    updates = _get_updates(bot_token)
    if not updates:
        return 0

    processed = 0
    max_update_id = 0

    for update in updates:
        update_id = update["update_id"]
        max_update_id = max(max_update_id, update_id)

        if "callback_query" in update:
            _handle_callback(bot_token, update["callback_query"])
            processed += 1
        elif "message" in update:
            msg = update["message"]
            if msg.get("text", "").startswith("/"):
                _handle_command(bot_token, msg)
                processed += 1

    # Acknowledge processed updates
    if max_update_id > 0:
        _get_updates(bot_token, offset=max_update_id + 1)

    return processed
