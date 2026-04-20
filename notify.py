"""Admin alerts via Telegram HTTP API. Fire-and-forget; never crashes the caller.

Separate from the bot's per-editor replies (which go through python-telegram-bot).
This is only for crash alerts and success confirmations sent to the admin chat.
"""
import os
import requests


def notify_admin(text):
    """Send text to TELEGRAM_ADMIN_CHAT_ID. Silent on config absence."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"[admin notify skipped] {text}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[admin notify error] {e}: {text}")
