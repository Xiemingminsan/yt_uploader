# YouTube Auto-Uploader

Polls Google Drive folders. When an MP4 + matching TXT transcript land in
a watched folder, downloads both, uploads the MP4 to YouTube as Private,
generates title/description/tags from the transcript via AI, patches the
video, logs to Google Sheets, and pings Telegram.

Built because n8n felt like clicking through walls.

---

## What you need before starting

- A server (your DigitalOcean droplet is fine)
- Python 3.10+ on the server
- One Google Cloud project
- One Telegram bot
- One Google Sheet
- An Anthropic or OpenAI API key

---

## Setup

### 1. Clone + install

```bash
cd /opt
git clone <your-repo> yt_uploader   # or scp the folder up
cd yt_uploader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Google Cloud — one project, enable the APIs

Console: https://console.cloud.google.com

1. Create a project (name it anything, e.g. `yt-uploader`)
2. APIs & Services → Library — enable **all three**:
   - Google Drive API
   - YouTube Data API v3
   - Google Sheets API
3. APIs & Services → OAuth consent screen:
   - User type: **External**
   - App name: anything
   - Test users: **add every Google account** you will authorize (yours + the account that owns each channel)
4. APIs & Services → Credentials → Create Credentials → **OAuth client ID**:
   - Application type: **Desktop app**
   - Download the JSON → save as `client_secret.json` in the project root

> **Desktop app** is the easiest flow. It opens a browser and handles the callback on a local port automatically. No domain / HTTPS / redirect URL headaches.

### 3. Run OAuth once per Google account

On a machine with a browser (your laptop, not the server, easier):

```bash
python auth.py sheets          # the account that owns the logging spreadsheet
python auth.py wiserice        # the account that owns channel #1
python auth.py other_channel   # etc
```

Each run opens a browser, you sign in, click through consent (warning that the app is "unverified" is expected — click "Advanced" → "Go to app"). Token is saved to `tokens/token_<name>.json`.

Copy the `tokens/` folder up to the server once done:
```bash
scp -r tokens/ root@YOUR_SERVER_IP:/opt/yt_uploader/
scp client_secret.json root@YOUR_SERVER_IP:/opt/yt_uploader/
```

### 4. Telegram bot

1. Message @BotFather → `/newbot` → get token
2. Message your new bot once (anything)
3. Message @userinfobot → it replies with your chat_id
4. Both go in `.env`

### 5. Google Sheet

Create a sheet. Rename the first tab to `Log`. Put these headers in row 1:

| timestamp_utc | channel | filename | youtube_id | title | url | status |

Copy the spreadsheet ID from its URL into `.env`.

### 6. Config files

```bash
cp .env.example .env
# fill in .env

nano config.yaml
# add your channels, paste Drive folder IDs
```

### 7. Test run (foreground)

```bash
source venv/bin/activate
python main.py
```

Drop an MP4 + matching TXT into a watched Drive folder. Within 2 minutes:
- log line shows `Processing filename.mp4`
- YouTube gets a Private upload
- Sheet row appears
- Telegram pings

### 8. Run as a service

```bash
sudo cp yt_uploader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yt_uploader
sudo journalctl -u yt_uploader -f    # tail logs
```

---

## How it handles the tricky stuff

| Problem | Solution |
|---|---|
| MP4 uploaded, TXT not yet | `TXT_GRACE_SEC` wait before alerting. Alert sent once. |
| Drive trigger fires on half-uploaded file | Polling interval is slow (2min default); finished file by then |
| Duplicate processing across restarts | SQLite state in `data/state.db` |
| Upload succeeds, AI fails | `video_id` written to Sheets **immediately** — orphan recoverable |
| Large file | Resumable upload in 50MB chunks, exponential backoff on 5xx |
| Network flake mid-upload | Up to 8 retries with backoff |
| OOM on droplet | MP4 streams to `/tmp`, not RAM; deleted after upload |
| Token expires | Auto-refresh on each run, token file rewritten |
| YouTube quota hit | Error bubbles up → Telegram alert → you see it |

---

## Adding a new channel later

1. `python auth.py <new_channel_name>` (on laptop, browser)
2. Copy new `tokens/token_<name>.json` to server
3. Add entry to `config.yaml`
4. `sudo systemctl restart yt_uploader`

---

## Cost

- Droplet: ~$6–12/mo (1–2GB)
- Drive, YouTube, Sheets, Telegram: free at this volume
- AI: Claude Haiku ≈ $0.001 per video; GPT-4o-mini ≈ $0.0005 per video. Negligible.

---

## Files

```
main.py               orchestration loop
auth.py               one-time OAuth per channel
drive.py              Drive list / download / text read
youtube.py            resumable upload + metadata update
ai.py                 Claude / OpenAI call for title+desc+tags
sheets.py             two-phase logger
telegram.py           notifications
state.py              SQLite dedup
config.yaml           channels list
.env                  secrets + tuning
requirements.txt      deps
yt_uploader.service   systemd unit
```

Total: ~500 lines. Read it end-to-end in 15 minutes.
