from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

VIDEO_LIST = [
    {"title": "🎬 Video 1 — Introduction", "description": "Getting started guide"},
    {"title": "🎬 Video 2 — Advanced Techniques", "description": "Deep dive tutorial"},
    {"title": "🎬 Video 3 — Pro Strategies", "description": "Expert level content"},
]

async def video_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lines = ["🎬 *Premium Video Library*\n"]
    for i, video in enumerate(VIDEO_LIST, 1):
        lines.append(f"{i}. *{video['title']}*")
        lines.append(f"   _{video['description']}_\n")
    lines.append("\n_Subscribe to get full access._")
    keyboard = [[InlineKeyboardButton("💳 Subscribe Now", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
