from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# ── Update this with your actual video post link ─────────────────────
VIDEO = {
    "title": "Premium Video",
    "description": "Exclusive premium content",
    "url": "https://t.me/c/3814300159/6"   # Replace with actual Telegram post link
}

async def video_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the premium video with a clickable link."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton(f"▶️ Watch: {VIDEO['title']}", url=VIDEO["url"])],
        [InlineKeyboardButton("💳 Subscribe for Access", callback_data="subscribe")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]

    await query.edit_message_text(
        "🎬 *Premium Video*\n\n"
        f"*{VIDEO['title']}*\n"
        f"_{VIDEO['description']}_\n\n"
        "📲 *New videos are uploaded regularly — check back often!*\n\n"
        "_Active subscribers can click below to watch._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
