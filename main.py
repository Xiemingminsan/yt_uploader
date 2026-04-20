"""
YouTube Auto-Uploader — bot entry point.

Loads .env + config.yaml, wires the SQLite state + Sheets logger, starts
the Telegram bot. Run as: python main.py
"""
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

from bot import build_application
from pipeline import make_clients
from notify import notify_admin

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("yt_uploader")


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN missing in .env")
        sys.exit(1)

    cfg = load_config()
    drive_token_file = os.getenv("DRIVE_TOKEN_FILE", "tokens/token_drive.json")
    sheets_token_file = os.getenv("SHEETS_TOKEN_FILE", "tokens/token_sheets.json")
    sheets_id = os.getenv("SHEETS_SPREADSHEET_ID")

    state, sheets = make_clients(cfg, drive_token_file, sheets_token_file, sheets_id)
    app = build_application(token, cfg, state, sheets, drive_token_file)

    channel_list = ", ".join(c.get("display_codename", c["internal_name"]) for c in cfg.get("channels", []))
    log.info("Bot starting. Projects: %s", channel_list or "(none)")
    notify_admin(f"🟢 YT Uploader bot started\nProjects: {channel_list or '(none)'}")

    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
