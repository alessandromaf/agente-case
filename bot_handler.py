"""Handle Telegram bot updates: callback queries (button presses) and commands."""

import json
import httpx
from db import (
    get_listing_by_message_id, add_to_shortlist, remove_from_shortlist,
    get_shortlist, _get_conn,
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


def _get_listing_info(source: str, listing_id: str) -> dict | None:
    """Get full listing info from the seen table."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT source, listing_id, telegram_message_id FROM seen WHERE source = ? AND listing_id = ?",
        (source, listing_id),
    ).fetchone()
    conn.close()
    if row:
        return {"source": row[0], "listing_id": row[1]}
    return None


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

    elif text.startswith("/export"):
        from sheets_export import export_shortlist
        items = get_shortlist()
        if not items:
            send_text(bot_token, str(chat_id), "La shortlist \u00e8 vuota, niente da esportare.")
            return
        send_text(bot_token, str(chat_id), "\u23f3 Esportazione in corso...")
        try:
            url = export_shortlist()
            if url:
                send_text(bot_token, str(chat_id),
                          f"\u2705 Shortlist esportata su Google Sheets!\n\n"
                          f"\U0001f517 [Apri spreadsheet]({url})")
            else:
                send_text(bot_token, str(chat_id),
                          "Google Sheets non configurato. Serve impostare "
                          "GOOGLE\\_SHEETS\\_CREDENTIALS e GOOGLE\\_SHEET\\_ID.")
        except Exception as e:
            send_text(bot_token, str(chat_id), f"Errore nell'esportazione: {e}")

    elif text.startswith("/start") or text.startswith("/help"):
        send_text(bot_token, str(chat_id),
                  "\U0001f3e0 *Bot Agente Case*\n\n"
                  "Premi \u2b50 *Salva* sotto un annuncio per aggiungerlo alla shortlist.\n\n"
                  "Comandi:\n"
                  "/shortlist \u2014 Vedi la tua shortlist\n"
                  "/remove\\_N \u2014 Rimuovi elemento N dalla shortlist\n"
                  "/export \u2014 Esporta shortlist su Google Sheets")


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
