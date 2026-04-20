"""
Telegram bot — editor-facing. Uses python-telegram-bot v21+ (async).

Flow:
    /start
      -> inline buttons: one per project (codename) the editor is authorized for
      -> on pick: "With script" | "Without script" buttons
        -> With script:    ask MP4 Drive link, then ask TXT Drive link
        -> Without script: ask MP4 Drive link, then ask hint text (or "skip")
      -> kicks off pipeline.run_pipeline() as a background task
      -> editor gets "Processing..." and eventually "Done" or "Failed"

Editor never sees channel internal names, YouTube URLs, or analytics. All
codename-keyed. Admin (TELEGRAM_ADMIN_CHAT_ID) gets the YouTube URL + full
diagnostics via notify_admin() from notify.py.
"""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot_helpers import (
    authorized_projects_for as _authorized_projects_for,
    channel_by_codename as _channel_by_codename,
    editor_for as _editor_for,
    is_authorized,
    parse_drive_link,
)
from pipeline import run_pipeline, PipelineError
from notify import notify_admin

log = logging.getLogger(__name__)

CHOOSING_PROJECT, CHOOSING_MODE, AWAITING_MP4_LINK, AWAITING_TXT_LINK, AWAITING_HINT = range(5)

CONVERSATION_TIMEOUT_SEC = 600  # 10 min


def _projects_keyboard(codenames):
    """Two columns of codename buttons."""
    rows, row = [], []
    for i, name in enumerate(codenames):
        row.append(InlineKeyboardButton(name, callback_data=f"proj:{name}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _mode_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("With script", callback_data="mode:with_script"),
            InlineKeyboardButton("Without script", callback_data="mode:without_script"),
        ]
    ])


# -------- Handlers --------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    config = context.bot_data["config"]
    ed = _editor_for(user.id, config)
    if not ed:
        await update.message.reply_text(
            "Not authorized. Contact the admin if you think this is a mistake."
        )
        return ConversationHandler.END

    codenames = _authorized_projects_for(user.id, config)
    if not codenames:
        await update.message.reply_text("No projects assigned. Contact the admin.")
        return ConversationHandler.END

    name = ed.get("display_name", user.first_name or "there")
    await update.message.reply_text(
        f"Hi {name}. Which project?",
        reply_markup=_projects_keyboard(codenames),
    )
    return CHOOSING_PROJECT


async def cb_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("proj:"):
        return CHOOSING_PROJECT
    codename = data[len("proj:"):]

    config = context.bot_data["config"]
    user_id = update.effective_user.id
    if not is_authorized(user_id, codename, config):
        await query.edit_message_text("Not authorized for that project.")
        return ConversationHandler.END

    ch = _channel_by_codename(codename, config)
    if not ch:
        await query.edit_message_text("Project not found. Contact the admin.")
        return ConversationHandler.END

    context.user_data["project_codename"] = codename
    await query.edit_message_text(
        f"{codename}. Do you have a transcript?",
        reply_markup=_mode_keyboard(),
    )
    return CHOOSING_MODE


async def cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("mode:"):
        return CHOOSING_MODE
    choice = data[len("mode:"):]
    if choice not in ("with_script", "without_script"):
        return CHOOSING_MODE

    context.user_data["mode_choice"] = choice  # temp; finalized after hint step
    await query.edit_message_text("OK. Paste the Drive link to the MP4.")
    return AWAITING_MP4_LINK


async def msg_mp4_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    file_id = parse_drive_link(text)
    if not file_id:
        await update.message.reply_text(
            "That doesn't look like a Drive link. Paste the MP4 link again, or /cancel."
        )
        return AWAITING_MP4_LINK

    context.user_data["mp4_file_id"] = file_id
    choice = context.user_data.get("mode_choice")
    if choice == "with_script":
        await update.message.reply_text("Got it. Now paste the Drive link to the .txt transcript.")
        return AWAITING_TXT_LINK
    else:
        await update.message.reply_text(
            "Got it. Send a short topic/notes message so AI has context, "
            "or send `skip` to upload without AI metadata.",
            parse_mode="Markdown",
        )
        return AWAITING_HINT


async def msg_txt_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    file_id = parse_drive_link(text)
    if not file_id:
        await update.message.reply_text(
            "That doesn't look like a Drive link. Paste the TXT link again, or /cancel."
        )
        return AWAITING_TXT_LINK

    context.user_data["txt_file_id"] = file_id
    context.user_data["mode"] = "with_script"
    await _kick_pipeline(update, context)
    return ConversationHandler.END


async def msg_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lower() == "skip":
        context.user_data["mode"] = "skip"
        context.user_data["video_hint"] = ""
    else:
        context.user_data["mode"] = "with_hint"
        context.user_data["video_hint"] = text
    await _kick_pipeline(update, context)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("Cancelled.")
    elif update.callback_query:
        await update.callback_query.answer("Cancelled.")
    return ConversationHandler.END


async def on_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        if chat:
            await context.bot.send_message(chat.id, "Session timed out. Send /start to try again.")
    except Exception:
        pass
    context.user_data.clear()
    return ConversationHandler.END


async def fallback_unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any non-conversation message from a non-whitelisted user."""
    config = context.bot_data["config"]
    if _editor_for(update.effective_user.id, config):
        await update.message.reply_text("Send /start to begin.")
    else:
        await update.message.reply_text("Not authorized.")


# -------- Pipeline launcher --------

async def _kick_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = context.bot_data["config"]
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    codename = context.user_data.get("project_codename")
    mode = context.user_data.get("mode")
    mp4_file_id = context.user_data.get("mp4_file_id")
    txt_file_id = context.user_data.get("txt_file_id")
    video_hint = context.user_data.get("video_hint", "")

    ch = _channel_by_codename(codename, config)
    ed = _editor_for(user_id, config)

    if not (ch and ed and mp4_file_id and mode):
        await context.bot.send_message(chat_id, "Something went wrong. Send /start to try again.")
        return

    await context.bot.send_message(chat_id, "Processing... I'll ping you when it's done.")

    bot = context.bot

    async def notify_cb(msg):
        try:
            await bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            log.warning("notify_cb failed: %s", e)

    # Fire and forget
    asyncio.create_task(_run_and_report(
        bot=bot,
        chat_id=chat_id,
        codename=codename,
        channel_cfg=ch,
        editor_cfg=ed,
        mode=mode,
        mp4_file_id=mp4_file_id,
        txt_file_id=txt_file_id,
        video_hint=video_hint,
        notify_cb=notify_cb,
        state=context.bot_data["state"],
        sheets=context.bot_data["sheets"],
        drive_token_file=context.bot_data["drive_token_file"],
    ))

    # Clear conversation state
    context.user_data.clear()


async def _run_and_report(
    *, bot, chat_id, codename, channel_cfg, editor_cfg, mode,
    mp4_file_id, txt_file_id, video_hint, notify_cb,
    state, sheets, drive_token_file,
):
    """Wrap run_pipeline + surface success/failure to editor (blind) and admin."""
    try:
        await run_pipeline(
            channel_cfg=channel_cfg,
            editor_cfg=editor_cfg,
            mode=mode,
            mp4_file_id=mp4_file_id,
            txt_file_id=txt_file_id,
            video_hint=video_hint,
            state=state,
            sheets=sheets,
            drive_token_file=drive_token_file,
            notify_cb=notify_cb,
        )
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ {codename} video delivered.",
        )
    except PipelineError as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Failed at {e.step}: {e.message}",
        )
        notify_admin(
            f"❌ *{channel_cfg['internal_name']}* ({codename}) pipeline failed\n"
            f"Editor: {editor_cfg.get('display_name', 'editor')}\n"
            f"Step: {e.step}\n"
            f"Error: `{e.message[:300]}`"
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Something went wrong. Admin has been notified.",
        )
        notify_admin(
            f"❌ *{channel_cfg['internal_name']}* ({codename}) crash\n"
            f"Editor: {editor_cfg.get('display_name', 'editor')}\n"
            f"```\n{tb[-1500:]}\n```"
        )


# -------- Application factory --------

def build_application(token, config, state, sheets, drive_token_file):
    app = Application.builder().token(token).build()
    app.bot_data["config"] = config
    app.bot_data["state"] = state
    app.bot_data["sheets"] = sheets
    app.bot_data["drive_token_file"] = drive_token_file

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            CHOOSING_PROJECT: [CallbackQueryHandler(cb_project, pattern=r"^proj:")],
            CHOOSING_MODE: [CallbackQueryHandler(cb_mode, pattern=r"^mode:")],
            AWAITING_MP4_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_mp4_link)],
            AWAITING_TXT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_txt_link)],
            AWAITING_HINT: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_hint)],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, on_timeout)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        conversation_timeout=CONVERSATION_TIMEOUT_SEC,
        per_user=True,
        per_chat=True,
    )
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_unauth))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    return app
