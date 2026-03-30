"""Telegram webhook server — handles bot updates in real-time via FastAPI."""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from bot_handler import _handle_callback, _handle_command, register_commands
from db import init_db

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # e.g. https://myapp.up.railway.app


def _set_webhook() -> None:
    if not BOT_TOKEN or not WEBHOOK_URL:
        print("WEBHOOK_URL not set — skipping webhook registration")
        return
    url = f"{WEBHOOK_URL.rstrip('/')}/webhook/{BOT_TOKEN}"
    resp = httpx.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json={"url": url, "allowed_updates": ["message", "callback_query"]},
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        print(f"Webhook registered: {url}")
    else:
        print(f"Webhook registration failed: {data}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if BOT_TOKEN:
        register_commands(BOT_TOKEN)
        _set_webhook()
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403)
    update = await request.json()
    if "callback_query" in update:
        _handle_callback(BOT_TOKEN, update["callback_query"])
    elif "message" in update:
        msg = update["message"]
        if msg.get("text", "").startswith("/"):
            _handle_command(BOT_TOKEN, msg)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
