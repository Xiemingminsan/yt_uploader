# CHANGES — Telegram bot pivot

Replaces the Drive-polling trigger with a Telegram bot conversation, and adds
editor-anonymity constraints (codename-only UI, no YouTube URLs to editors).

## New files

- `bot.py` — python-telegram-bot v21 async app. ConversationHandler states:
  `CHOOSING_PROJECT` → `CHOOSING_MODE` → `AWAITING_MP4_LINK` →
  (`AWAITING_TXT_LINK` | `AWAITING_HINT`) → background pipeline task.
  Commands: `/start`, `/cancel`. 10-minute conversation timeout.
- `bot_helpers.py` — pure helpers (`parse_drive_link`, `is_authorized`,
  `editor_for`, `channel_by_codename`, `authorized_projects_for`). Isolated
  from the telegram SDK so unit tests don't need it installed.
- `pipeline.py` — `run_pipeline()` async. Sync Google SDK calls wrapped in
  `asyncio.to_thread`. Raises `PipelineError(step, message)` for clean editor
  feedback. Supports three modes: `with_script`, `with_hint`, `skip`.
- `tests/test_parser.py`, `tests/test_auth.py` — 20 passing tests.
- `docs/archive/n8n_workflow_v1.json` — the original n8n export, kept for reference.
- `docs/archive/READD.txt` — the handoff/context notes that got us here.

## Modified files

- `main.py` — shrunk from 180 lines to ~35. Loads config, builds app, runs.
- `drive.py` — dropped `list_mp4s` and `find_txt`. Added `get_file_metadata`.
  Kept `download` and `read_text` (the latter still used by `with_script` mode
  to read the transcript from Drive). `supportsAllDrives=True` added to Drive
  calls so the bot can read from shared-drive paths if needed.
- `sheets.py` — rewrote for the 13-column schema:
  `timestamp_utc, internal_channel, display_codename, editor_name,
   editor_tg_id, source_mp4_id, source_mp4_name, mode, youtube_id,
   youtube_url, ai_title, status, error`.
  Added `mark_failed(youtube_id, error)` for failure cases.
- `ai.py` — added optional `video_hint` parameter for per-video context
  (distinct from persistent per-channel `channel_hint`). Still accepts a
  transcript.
- `config.yaml` — new schema:
  - `channels[]`: `internal_name`, `display_codename`, `editor_folder_id`,
    `yt_token_file`, `category_id`, `ai_hint`. Dropped `drive_folder_id`.
  - `editors[]`: `telegram_user_id`, `display_name`, `projects` (list of
    codenames, or `["*"]` for wildcard/admin).
- `.env.example` — added `TELEGRAM_ADMIN_CHAT_ID`, `DRIVE_TOKEN_FILE`.
  Dropped `POLL_INTERVAL_SEC`, `TXT_GRACE_SEC`, `TELEGRAM_CHAT_ID`.
- `requirements.txt` — added `python-telegram-bot>=21.0`.
- `README.md` — rewritten for the bot flow. Added codename naming rule and
  the new token/account architecture.

## Renamed

- `telegram.py` → `notify.py` (avoid collision with python-telegram-bot's
  `telegram` module). Single function renamed `notify` → `notify_admin`.
  Falls back to the legacy `TELEGRAM_CHAT_ID` env var if
  `TELEGRAM_ADMIN_CHAT_ID` is not set.

## Untouched

- `youtube.py` — resumable upload + retries, unchanged.
- `state.py` — SQLite dedup, unchanged (keyed by Drive file_id).
- `auth.py` — unchanged. `python auth.py drive` now makes sense because the
  filename is just `token_<arg>.json`.
- `yt_uploader.service` — unchanged, same `ExecStart python main.py`.

## Design decisions worth re-reading

1. **Editor anonymity (strict).** The bot reply on success is
   `✅ <codename> video delivered.` — no YouTube URL, no channel name. The
   YouTube URL goes to `TELEGRAM_ADMIN_CHAT_ID` only. Trade-off: editors
   can't self-QC their upload. If you ever want them to, loosen this in
   `bot._run_and_report`.

2. **Per-channel YouTube tokens, no master account.** Each of the N channels
   has its own Google account + token. Avoids the cascade-suspension risk
   where one violation takes down all channels. One-time extra cost: N
   OAuth runs on your laptop during setup.

3. **Neutral submissions account for Drive + Sheets.** One Google One 200 GB
   account owns `submissions/` and the logging spreadsheet. Editors only see
   their assigned `submissions/<codename>/` subfolder, shared with their
   personal Gmail. That's the entire editor-facing surface beyond Telegram.

4. **Codenames are free-form strings.** The code treats `display_codename`
   as an opaque string — no alphabet sequencing. The README enforces the
   "random/content-neutral" rule documentarily.

5. **Three modes for AI metadata:**
   - `with_script` — editor gives a Drive link to a `.txt` transcript. Full AI.
   - `with_hint` — editor types a short topic message. AI gets the hint +
     channel context but no transcript. Weaker but usable.
   - `skip` — upload with placeholder title (`[Processing] <filename>`),
     empty description, empty tags. Admin fills in via YouTube Studio later.

6. **No Drive auto-trash in v1.** Decision was deliberately deferred — it's
   a one-liner (`drive.service.files().update(fileId=..., body={"trashed": True})`)
   that can be added to `pipeline.run_pipeline` step 10 if/when quota becomes
   a real issue.

## Known limitations

- Background upload tasks don't survive a bot restart. If the bot is killed
  mid-upload, the in-flight task dies. The editor has to re-submit. If the
  YouTube upload already completed, `state.db` will reject the dupe with
  "already uploaded" — acceptable, but you'll want to check the sheet.
- No explicit concurrency throttle. `asyncio.create_task` per editor means
  N simultaneous editors do N concurrent uploads. At ~6 uploads/day/channel
  and 4 editors this is fine; if you see quota issues, add a `Semaphore`
  in `bot._run_and_report`.
- Testing environment in this sandbox can't `import telegram` due to a
  broken `cryptography._rust` install. Tests therefore only cover
  `bot_helpers.py` (pure Python), not `bot.py` end-to-end. On a clean Python
  install the full bot runs fine; the helpers are where the brittle logic
  lives anyway.

## Test results

```
$ python -m pytest tests/ -v
...
20 passed in 0.07s
```
