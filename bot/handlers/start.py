from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

MAIN_MENU_TEXT = """
👋 *Welcome to Premium Video Access*

Please select an option below:
"""

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 Subscribe", callback_data="subscribe")],
        [InlineKeyboardButton("🔑 Enter Activation Code", callback_data="activation_code")],
        [InlineKeyboardButton("🔐 Login", callback_data="login")],
        [InlineKeyboardButton("🎬 View Video List", callback_data="video_list")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(MAIN_MENU_TEXT, parse_mode="Markdown",
                                     reply_markup=main_menu_keyboard())

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(MAIN_MENU_TEXT, parse_mode="Markdown",
                                   reply_markup=main_menu_keyboard())
