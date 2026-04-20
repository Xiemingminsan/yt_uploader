"""
YouTube Auto-Uploader
Polls Drive folders, uploads matched MP4+TXT pairs to YouTube,
generates AI metadata, logs to Sheets, pings Telegram.

Run: python main.py
"""
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from drive import DriveClient
from youtube import YouTubeClient
from ai import generate_metadata
from sheets import SheetsLogger
from telegram import notify
from state import State

load_dotenv()

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "120"))  # 2 min default
TXT_GRACE_SEC = int(os.getenv("TXT_GRACE_SEC", "180"))          # 3 min wait for TXT


def log(msg, channel=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}]" + (f"[{channel}]" if channel else "")
    print(f"{prefix} {msg}", flush=True)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def process_channel(ch, state, sheets):
    name = ch["name"]
    token_file = f"tokens/token_{name}.json"

    if not os.path.exists(token_file):
        log(f"NO TOKEN. Run: python auth.py {name}", channel=name)
        return

    drive = DriveClient(token_file)
    yt = YouTubeClient(token_file)

    # Find new MP4s
    mp4s = drive.list_mp4s(ch["drive_folder_id"])
    for mp4 in mp4s:
        mp4_id = mp4["id"]
        mp4_name = mp4["name"]
        base = os.path.splitext(mp4_name)[0]

        if state.is_done(mp4_id):
            continue

        # State tracking: when did we first see this MP4?
        first_seen = state.first_seen(mp4_id)

        # Check for matching TXT
        txt = drive.find_txt(ch["drive_folder_id"], base)

        if not txt:
            age = time.time() - first_seen
            if age < TXT_GRACE_SEC:
                log(f"{mp4_name}: waiting for TXT ({int(age)}s/{TXT_GRACE_SEC}s)", channel=name)
                continue
            # Grace period expired, alert once
            if not state.alert_sent(mp4_id):
                notify(
                    f"⚠️ *{name}*\n"
                    f"File: `{mp4_name}` uploaded\n"
                    f"No matching `{base}.txt` found after {TXT_GRACE_SEC}s.\n"
                    f"Upload the transcript to proceed."
                )
                state.mark_alert_sent(mp4_id)
                log(f"{mp4_name}: ALERT sent, no TXT", channel=name)
            continue

        # Both files present -> process
        log(f"Processing {mp4_name}", channel=name)
        try:
            process_video(ch, drive, yt, sheets, mp4, txt, name)
            state.mark_done(mp4_id)
        except Exception as e:
            log(f"FAIL {mp4_name}: {e}", channel=name)
            traceback.print_exc()
            notify(
                f"❌ *{name}* workflow failed\n"
                f"File: `{mp4_name}`\n"
                f"Error: `{str(e)[:300]}`"
            )


def process_video(ch, drive, yt, sheets, mp4, txt, channel_name):
    mp4_name = mp4["name"]
    base = os.path.splitext(mp4_name)[0]

    # 1. Download MP4 + TXT
    local_mp4 = f"/tmp/{mp4['id']}.mp4"
    drive.download(mp4["id"], local_mp4)
    transcript = drive.read_text(txt["id"])
    log(f"Downloaded {mp4_name} ({os.path.getsize(local_mp4)//1024//1024}MB)", channel=channel_name)

    try:
        # 2. Upload to YouTube as Private with placeholder title
        video_id = yt.upload(local_mp4, title=f"[Processing] {base}", privacy="private")
        log(f"Uploaded to YouTube: {video_id}", channel=channel_name)

        # 3. SAFETY NET: log video_id immediately (orphan recovery)
        sheets.append_initial(channel_name, mp4_name, video_id)

        # 4. Generate AI metadata
        meta = generate_metadata(transcript, channel_hint=ch.get("ai_hint", ""))
        log(f"AI generated: {meta['title'][:60]}", channel=channel_name)

        # 5. Update YouTube with real metadata
        yt.update_metadata(
            video_id,
            title=meta["title"],
            description=meta["description"],
            tags=meta["tags"],
            category_id=ch.get("category_id", "22"),
        )

        # 6. Final log update
        url = f"https://youtube.com/watch?v={video_id}"
        sheets.update_final(video_id, meta["title"], url, "success")

        # 7. Telegram success
        notify(
            f"✅ *{channel_name}*\n"
            f"Title: {meta['title']}\n"
            f"Uploaded: Private (ready to review)\n"
            f"{url}"
        )

    finally:
        # 8. Always cleanup local file
        if os.path.exists(local_mp4):
            os.remove(local_mp4)


def main():
    os.makedirs("tokens", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    cfg = load_config()
    state = State("data/state.db")
    sheets = SheetsLogger(
        os.getenv("SHEETS_TOKEN_FILE", "tokens/token_sheets.json"),
        os.getenv("SHEETS_SPREADSHEET_ID"),
    )

    log(f"Started. Polling {len(cfg['channels'])} channel(s) every {POLL_INTERVAL_SEC}s")
    notify(f"🟢 YT Uploader started\nChannels: {', '.join(c['name'] for c in cfg['channels'])}")

    while True:
        for ch in cfg["channels"]:
            try:
                process_channel(ch, state, sheets)
            except Exception as e:
                log(f"Channel loop error: {e}", channel=ch["name"])
                traceback.print_exc()
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Shutting down")
        sys.exit(0)
