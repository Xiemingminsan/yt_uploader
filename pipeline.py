"""
Upload pipeline. Called by bot.py once the editor has submitted a Drive link
and (optionally) a transcript link or topic hint.

Steps:
  1. Dedupe check (state.db)
  2. Validate MP4 link (drive.get_file_metadata)
  3. Get transcript (from Drive TXT link / editor hint / empty)
  4. Download MP4 to /tmp
  5. Upload to YouTube as Private (placeholder title)
  6. Log to Sheets (safety net)
  7. Generate AI metadata (skipped in "skip" mode)
  8. Patch YouTube metadata (skipped in "skip" mode)
  9. Update Sheets row
 10. Mark done in state.db
 11. Cleanup /tmp

All Google/YouTube/AI SDKs are sync; wrapped in asyncio.to_thread to keep the
bot's event loop unblocked.
"""
import asyncio
import os

from drive import DriveClient
from youtube import YouTubeClient
from ai import generate_metadata
from sheets import SheetsLogger
from state import State
from notify import notify_admin


class PipelineError(Exception):
    """Step-labeled error so the bot reply can say where it failed."""
    def __init__(self, step, message):
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message


def _dry_run():
    return os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")


async def run_pipeline(
    *,
    channel_cfg,
    editor_cfg,
    mode,
    mp4_file_id,
    txt_file_id=None,
    video_hint="",
    state,
    sheets,
    drive_token_file,
    notify_cb,
):
    """
    Run the upload pipeline end-to-end.

    Args:
        channel_cfg: dict with internal_name, display_codename, yt_token_file,
                     category_id, ai_hint.
        editor_cfg:  dict with telegram_user_id, display_name (for logs).
        mode:        "with_script" | "with_hint" | "skip".
        mp4_file_id: Drive file ID of the MP4.
        txt_file_id: Drive file ID of the transcript (only for with_script).
        video_hint:  one-off per-video hint text (only for with_hint).
        state:       State (SQLite dedup).
        sheets:      SheetsLogger.
        drive_token_file: path to the submissions-account Drive OAuth token.
        notify_cb:   async callable(str) -> None. Used for editor-facing updates.
                     Admin alerts are sent separately via notify_admin.

    Raises PipelineError on failure. Caller is expected to catch and surface
    the error to the editor + admin.
    """
    internal = channel_cfg["internal_name"]
    codename = channel_cfg["display_codename"]
    yt_token = channel_cfg["yt_token_file"]
    category_id = str(channel_cfg.get("category_id", "22"))
    channel_hint = channel_cfg.get("ai_hint", "")

    editor_name = editor_cfg.get("display_name", "editor")
    editor_tg_id = editor_cfg["telegram_user_id"]

    # 1. Dedupe
    if state.is_done(mp4_file_id):
        raise PipelineError("dedupe", "this file has already been uploaded")

    if _dry_run():
        await notify_cb(f"[DRY_RUN] would process mp4={mp4_file_id} mode={mode}")
        fake_video_id = f"dryrun_{mp4_file_id[:10]}"
        state.mark_done(mp4_file_id)
        await notify_cb(f"✅ {codename} delivered. (dry run, no YouTube upload)")
        return fake_video_id

    drive = await asyncio.to_thread(DriveClient, drive_token_file)
    yt = await asyncio.to_thread(YouTubeClient, yt_token)

    # 2. Validate MP4 link
    try:
        meta = await asyncio.to_thread(drive.get_file_metadata, mp4_file_id)
    except Exception as e:
        raise PipelineError("validate", f"can't access that Drive file ({e})")

    mime = meta.get("mimeType", "")
    if not (mime.startswith("video/") or mime == "application/octet-stream"):
        raise PipelineError("validate", f"not a video file (mimeType={mime})")

    mp4_name = meta.get("name", f"{mp4_file_id}.mp4")
    size = int(meta.get("size", 0))
    if size > 5 * 1024 * 1024 * 1024:
        raise PipelineError("validate", f"file too large ({size // 1024 // 1024}MB > 5GB)")

    # 3. Get transcript
    transcript = ""
    if mode == "with_script":
        if not txt_file_id:
            raise PipelineError("transcript", "with_script mode requires a .txt Drive link")
        try:
            transcript = await asyncio.to_thread(drive.read_text, txt_file_id)
        except Exception as e:
            raise PipelineError("transcript", f"can't read TXT from Drive ({e})")
    elif mode == "with_hint":
        if not video_hint.strip():
            raise PipelineError("transcript", "with_hint mode requires hint text")

    # 4. Download MP4
    os.makedirs("/tmp", exist_ok=True)
    local_mp4 = f"/tmp/{mp4_file_id}.mp4"
    try:
        await notify_cb(f"Downloading ({size // 1024 // 1024}MB)...")
        try:
            await asyncio.to_thread(drive.download, mp4_file_id, local_mp4)
        except Exception as e:
            raise PipelineError("download", str(e))

        # 5. Upload to YouTube as Private with placeholder title
        base_name = os.path.splitext(mp4_name)[0]
        placeholder_title = f"[Processing] {base_name}"[:95]
        try:
            video_id = await asyncio.to_thread(
                yt.upload, local_mp4, placeholder_title, "private", category_id
            )
        except Exception as e:
            raise PipelineError("youtube_upload", str(e))

        # 6. Log to Sheets (safety net: video_id written before AI runs)
        try:
            await asyncio.to_thread(
                sheets.append_initial,
                internal,
                codename,
                editor_name,
                editor_tg_id,
                mp4_file_id,
                mp4_name,
                mode,
                video_id,
            )
        except Exception as e:
            # Sheets failure is non-fatal — the video is up. Alert admin only.
            notify_admin(f"⚠️ Sheets append failed for {internal} video {video_id}: {e}")

        # 7 + 8. AI metadata + patch (skipped in "skip" mode)
        if mode != "skip":
            try:
                meta_out = await asyncio.to_thread(
                    generate_metadata,
                    transcript=transcript,
                    channel_hint=channel_hint,
                    video_hint=video_hint,
                )
            except Exception as e:
                # AI failed: leave placeholder title, mark sheet failed, notify admin
                try:
                    await asyncio.to_thread(sheets.mark_failed, video_id, f"ai: {e}")
                except Exception:
                    pass
                notify_admin(
                    f"⚠️ *{internal}* AI metadata failed (video uploaded)\n"
                    f"video_id: `{video_id}`\n"
                    f"error: `{str(e)[:300]}`"
                )
                raise PipelineError("ai", str(e))

            try:
                await asyncio.to_thread(
                    yt.update_metadata,
                    video_id,
                    meta_out["title"],
                    meta_out["description"],
                    meta_out["tags"],
                    category_id,
                )
            except Exception as e:
                try:
                    await asyncio.to_thread(sheets.mark_failed, video_id, f"patch: {e}")
                except Exception:
                    pass
                notify_admin(
                    f"⚠️ *{internal}* metadata patch failed (video uploaded)\n"
                    f"video_id: `{video_id}`\n"
                    f"error: `{str(e)[:300]}`"
                )
                raise PipelineError("youtube_patch", str(e))

            final_title = meta_out["title"]
        else:
            final_title = placeholder_title

        # 9. Update Sheets row with final metadata
        url = f"https://youtube.com/watch?v={video_id}"
        try:
            await asyncio.to_thread(
                sheets.update_final, video_id, final_title, url, "success"
            )
        except Exception as e:
            notify_admin(f"⚠️ Sheets update_final failed for {video_id}: {e}")

        # 10. Mark done
        state.mark_done(mp4_file_id)

        # Admin gets the YouTube URL; editor does not (anonymity).
        notify_admin(
            f"✅ *{internal}* ({codename}) uploaded\n"
            f"Editor: {editor_name}\n"
            f"Title: {final_title}\n"
            f"{url}"
        )
        return video_id

    finally:
        # 11. Cleanup always
        if os.path.exists(local_mp4):
            try:
                os.remove(local_mp4)
            except Exception:
                pass


def make_clients(cfg, drive_token_file, sheets_token_file, sheets_id):
    """Factory used by main.py bootstrap. Returns (state, sheets, drive_token_file)."""
    os.makedirs("tokens", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    state = State("data/state.db")
    sheets = SheetsLogger(sheets_token_file, sheets_id) if not _dry_run() else _DrySheets()
    return state, sheets


class _DrySheets:
    """No-op sheets logger for DRY_RUN mode."""
    def append_initial(self, *a, **k):
        print(f"[DRY_RUN sheets.append_initial] {a}")
    def update_final(self, *a, **k):
        print(f"[DRY_RUN sheets.update_final] {a}")
    def mark_failed(self, *a, **k):
        print(f"[DRY_RUN sheets.mark_failed] {a}")
