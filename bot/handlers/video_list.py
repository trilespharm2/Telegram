from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# ── HOW TO GET YOUR FILE_ID ──────────────────────────────────────────
# 1. Send your video to the bot directly (as a private message to Premium_3)
# 2. The bot will print the file_id to Railway logs
# 3. Copy the file_id and paste it below as VIDEO_FILE_ID
# ────────────────────────────────────────────────────────────────────

VIDEO_FILE_ID = ""   # Paste your file_id here after following steps above
VIDEO_CAPTION = (
    "🎬 *Premium Video*\n\n"
    "📲 _New videos are uploaded regularly — check back often!_"
)

async def video_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the premium video directly in bot chat."""
    query = update.callback_query
    await query.answer()

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]

    if not VIDEO_FILE_ID:
        await query.edit_message_text(
            "🎬 *Premium Video*\n\n"
            "Video coming soon! Check back shortly.\n\n"
            "📲 _New videos are uploaded regularly._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Edit the menu message first, then send video below it
    await query.edit_message_text(
        "🎬 *Premium Video*\n\n"
        "📲 _New videos are uploaded regularly — check back often!_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # Send video directly in bot chat
    await context.bot.send_video(
        chat_id=query.message.chat_id,
        video=VIDEO_FILE_ID,
        caption=VIDEO_CAPTION,
        parse_mode="Markdown",
        supports_streaming=True
    )


async def capture_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper: when admin sends a video to the bot, log its file_id."""
    from bot.config import ADMIN_ID
    if update.effective_user.id != ADMIN_ID:
        return
    if update.message.video:
        file_id = update.message.video.file_id
        print(f"VIDEO FILE_ID: {file_id}")
        await update.message.reply_text(
            f"✅ *Video file_id captured:*\n\n`{file_id}`\n\n"
            "Copy this and paste it as `VIDEO_FILE_ID` in `video_list.py`",
            parse_mode="Markdown"
        )
