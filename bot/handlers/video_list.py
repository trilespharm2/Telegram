from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# ── HOW TO GET YOUR FILE_ID ──────────────────────────────────────────
# 1. Send your video directly to Premium_3 bot as a message
# 2. Bot will reply with the file_id
# 3. Copy the file_id and paste it below
# ────────────────────────────────────────────────────────────────────

VIDEO_FILE_ID = "BAACAgEAAyEFAATjWZn_AAMGaZvWBGX5sET7j6NZBfboNayfznYAAh0GAALwN9lErsU3Id1qQSg6BA"   # Paste your file_id here
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

    await query.edit_message_text(
        "🎬 *Premium Video*\n\n"
        "📲 _New videos are uploaded regularly — check back often!_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await context.bot.send_video(
        chat_id=query.message.chat_id,
        video=VIDEO_FILE_ID,
        caption=VIDEO_CAPTION,
        parse_mode="Markdown",
        supports_streaming=True
    )
