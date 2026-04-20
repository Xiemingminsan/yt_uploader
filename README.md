# YouTube Auto-Uploader (Telegram bot trigger)

Editors send a Telegram message to a bot, the bot uploads the MP4 to YouTube
as Private, generates AI metadata from a transcript (or a short topic hint,
or skips AI entirely), logs to Google Sheets, and notifies the admin. Editors
never see channel identities, YouTube URLs, or analytics — they only see a
project codename.

---

## Editor flow

```
editor: /start
bot:    Hi <name>. Which project?
        [Falcon]  [Meridian]                 ← only projects they're authorized for

editor: (taps Falcon)
bot:    Falcon. Do you have a transcript?
        [With script]  [Without script]

editor: (taps With script)
bot:    OK. Paste the Drive link to the MP4.

editor: https://drive.google.com/file/d/.../view
bot:    Got it. Now paste the Drive link to the .txt transcript.

editor: https://drive.google.com/file/d/.../view
bot:    Processing... I'll ping you when it's done.

        ✅ Falcon video delivered.
```

Without-script branch: after the MP4 link, the bot asks for a short topic/notes
text (or `skip` to upload with no AI metadata at all).

`/cancel` aborts at any step. Conversations time out after 10 min.

---

## Architecture

```
┌─ Submissions Google account (neutral, 200GB paid) ──┐
│  Drive: submissions/<codename>/  shared per-editor  │
│  Sheets: upload log                                 │
│  Tokens: token_drive.json, token_sheets.json        │
└─────────────────────────────────────────────────────┘
                  │  (bot reads via token_drive.json)
                  ▼
┌─ Bot (on droplet) ──────────────────────────────────┐
│  python-telegram-bot v21 (async)                    │
│  ConversationHandler: /start → project → mode →     │
│    MP4 link → (TXT link | hint | skip) → pipeline   │
└─────────────────────────────────────────────────────┘
                  │
                  ▼  (per-channel YouTube tokens)
┌─ N YouTube channels ────────────────────────────────┐
│  Each channel has its own Google account +          │
│  token_<internal_name>.json. Channels are fully     │
│  isolated — no master account, no shared identity.  │
└─────────────────────────────────────────────────────┘
```

Three token categories in `tokens/`:

| Token                          | Scope                    | OAuth'd as                     |
| ------------------------------ | ------------------------ | ------------------------------ |
| `token_drive.json`             | Drive reads              | neutral submissions account    |
| `token_sheets.json`            | Sheets writes            | neutral submissions (or admin) |
| `token_<internal_name>.json`   | YouTube upload + update  | each channel's own account     |

---

## Codename naming rule

Editor-facing `display_codename` values **must not leak sequence or count**. Do
not use `Project A / B / C`. Pick unrelated, content-neutral words (birds,
stars, cities) and avoid anything that hints at topic or brand.

Good: `Falcon`, `Meridian`, `Atlas`
Bad:  `Project A`, `Channel 1`, `Gaming Ch`

---

## Setup

### 1. Clone + install

```bash
cd /opt
git clone <your-repo> yt_uploader
cd yt_uploader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Google Cloud — one project, enable APIs

Console: https://console.cloud.google.com

1. Create a project (e.g. `yt-uploader`).
2. APIs & Services → Library → enable **all three**:
   - Google Drive API
   - YouTube Data API v3
   - Google Sheets API
3. APIs & Services → OAuth consent screen:
   - User type: **External**
   - Test users: add every Google account you'll OAuth (submissions + one per channel)
4. APIs & Services → Credentials → Create → **OAuth client ID** → **Desktop app**.
   Download the JSON → save as `client_secret.json` in the project root.

### 3. OAuth once per account (on a machine with a browser)

```bash
python auth.py drive             # sign in as the neutral submissions account
python auth.py sheets            # same or separate account that owns the log sheet
python auth.py wiserice          # sign in as the Google account that owns channel 1
python auth.py <other_channel>   # ... repeat per channel
```

Each call opens a browser, you sign in, click through consent, token lands in
`tokens/token_<name>.json`.

Copy `tokens/` + `client_secret.json` to the server.

### 4. Telegram bot

1. Message `@BotFather` → `/newbot` → get token.
2. Message your bot once so it can reach you.
3. Message `@userinfobot` → it replies with your numeric chat ID.
4. Put token + chat ID in `.env`.

### 5. Google Sheet

Create a sheet. Rename the first tab to `Log`. Put headers in row 1:

| timestamp_utc | internal_channel | display_codename | editor_name | editor_tg_id | source_mp4_id | source_mp4_name | mode | youtube_id | youtube_url | ai_title | status | error |

Copy the spreadsheet ID from its URL into `.env` as `SHEETS_SPREADSHEET_ID`.

### 6. Config

```bash
cp .env.example .env
nano .env                 # fill in tokens, API keys, sheet ID
nano config.yaml          # channels (internal + codename) and editors
```

See `config.yaml` comments for the full schema.

### 7. Test run (foreground)

```bash
source venv/bin/activate
python main.py
```

Message the bot from an authorized Telegram account, walk through the flow,
verify the upload lands on YouTube as Private and the Sheets row appears.

Dry-run mode (no Google/YouTube/AI calls):

```bash
DRY_RUN=1 python main.py
```

### 8. Run as a service

```bash
sudo cp yt_uploader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yt_uploader
sudo journalctl -u yt_uploader -f
```

---

## Adding a new channel

1. `python auth.py <internal_name>` on a laptop (sign in as that channel's Google account).
2. Copy `tokens/token_<internal_name>.json` to the server.
3. Add a `channels:` entry in `config.yaml` (pick a new random `display_codename`).
4. `sudo systemctl restart yt_uploader`.

## Adding a new editor

1. Get their numeric Telegram user ID (`@userinfobot`).
2. Add an entry under `editors:` in `config.yaml` with the `projects:` they're
   authorized for (list of `display_codename`s, or `["*"]` for admin).
3. Share their assigned Drive subfolder with their personal Gmail (Editor access).
4. `sudo systemctl restart yt_uploader`.

---

## Files

```
main.py               bootstrap: loads config, builds app, starts bot
bot.py                Telegram bot (ConversationHandler, states, callbacks)
bot_helpers.py        pure helpers (parse_drive_link, is_authorized); unit-tested
pipeline.py           async upload pipeline (Drive → YouTube → AI → Sheets)
auth.py               one-time OAuth per account
drive.py              Drive: get_file_metadata, download, read_text
youtube.py            resumable upload + metadata update (unchanged)
ai.py                 Claude / OpenAI metadata generation (transcript or hint)
sheets.py             two-phase logger, 13-column schema
state.py              SQLite dedup (by Drive file_id)
notify.py             admin-only Telegram alerts
config.yaml           channels + editors
.env                  secrets + tuning
requirements.txt
yt_uploader.service   systemd unit
tests/                pytest — parser + authorization
docs/archive/         old n8n workflow v1 + the notes that got us here
```

---

## Edge cases

| Scenario | Handling |
| --- | --- |
| Editor pastes a non-Drive link | Parser returns None, bot asks again |
| Editor pastes a link the bot can't access | Drive `get_file_metadata` fails → "can't access" reply |
| File isn't an MP4 | MIME check rejects before download |
| Same link submitted twice | `state.py` dedup: rejects with "already uploaded" |
| Upload succeeds, AI fails | Sheets row has `video_id` + `status=failed` → recoverable |
| Pipeline crash | Editor gets generic "❌ failed" reply; admin gets full traceback |
| Editor ghosts mid-conversation | 10-min timeout clears state |
| Bot restarts mid-upload | In-flight task dies; editor retries by re-sending link |

---

## Cost

- Droplet: ~$6–12/mo
- Google One (submissions account, 200 GB): ~$3/mo
- AI: Claude Haiku ≈ $0.001 per video; GPT-4o-mini ≈ $0.0005 per video
- Drive / YouTube / Sheets / Telegram: free at this volume
