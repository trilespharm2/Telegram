from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# ── Edit this list to add your videos ───────────────────────────────
# Each video needs a title, description, and url (direct link to video file or post)
VIDEO_LIST = [
    {
        "title": "Video 1 — Introduction",
        "description": "Getting started guide",
        "url": "https://t.me/your_channel/1"   # Replace with actual post link
    },
    {
        "title": "Video 2 — Advanced Techniques",
        "description": "Deep dive tutorial",
        "url": "https://t.me/your_channel/2"   # Replace with actual post link
    },
    {
        "title": "Video 3 — Pro Strategies",
        "description": "Expert level content",
        "url": "https://t.me/your_channel/3"   # Replace with actual post link
    },
    # Add more videos here as you upload them:
    # {
    #     "title": "Video 4 — Title Here",
    #     "description": "Short description",
    #     "url": "https://t.me/your_channel/4"
    # },
]

async def video_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the list of available videos with clickable links."""
    query = update.callback_query
    await query.answer()

    keyboard = []

    if not VIDEO_LIST:
        text = (
            "🎬 *Premium Video Library*\n\n"
            "No videos posted yet — check back soon!\n\n"
            "📲 _New videos are uploaded regularly. Subscribe to get instant access._"
        )
    else:
        text = (
            "🎬 *Premium Video Library*\n\n"
            "Click any video below to open and watch:\n\n"
            "📲 _New videos are uploaded regularly — check back often!_"
        )
        # Add a button for each video
        for i, video in enumerate(VIDEO_LIST, 1):
            keyboard.append([
                InlineKeyboardButton(
                    f"▶️ {i}. {video['title']}",
                    url=video["url"]
                )
            ])

    keyboard.append([InlineKeyboardButton("💳 Subscribe Now", callback_data="subscribe")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
