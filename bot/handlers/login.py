from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler,
                           CommandHandler)
from bot.database import (get_subscriber, update_subscriber_credentials,
                           is_active_subscriber)
from bot.utils import generate_invite_link, hash_password, verify_password
from bot.handlers.start import back_to_menu, start

# States for setup flow
SETUP_USERNAME, SETUP_PASSWORD, SETUP_CONFIRM = range(3)
# States for login flow
LOGIN_USERNAME, LOGIN_PASSWORD = range(3, 5)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

# ── Setup Login Credentials ──────────────────────────────────────────

async def setup_credentials_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔐 *Set Up Login Credentials* _(Optional)_\n\n"
        "Create a username for easy future access.\n\n"
        "Please enter a username:",
        parse_mode="Markdown"
    )
    return SETUP_USERNAME

async def setup_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if len(username) < 3:
        await update.message.reply_text("⚠️ Username must be at least 3 characters. Try again:")
        return SETUP_USERNAME
    context.user_data["new_username"] = username
    await update.message.reply_text("Now enter a password (min 6 characters):")
    return SETUP_PASSWORD

async def setup_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text("⚠️ Password must be at least 6 characters. Try again:")
        return SETUP_PASSWORD
    context.user_data["new_password"] = password
    await update.message.reply_text("Confirm your password:")
    return SETUP_CONFIRM

async def setup_confirm_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirm = update.message.text.strip()
    if confirm != context.user_data.get("new_password"):
        await update.message.reply_text("⚠️ Passwords don't match. Enter password again:")
        return SETUP_PASSWORD

    telegram_id = update.effective_user.id
    username = context.user_data["new_username"]
    password_hash = hash_password(context.user_data["new_password"])

    update_subscriber_credentials(telegram_id, username, password_hash)

    await update.message.reply_text(
        "✅ *Login credentials saved!*\n\n"
        f"Username: `{username}`\n\n"
        "You can now use Login from the main menu to access your channel link anytime.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ── Login Flow ───────────────────────────────────────────────────────

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔐 *Login*\n\nPlease enter your username:",
        parse_mode="Markdown"
    )
    return LOGIN_USERNAME

async def login_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login_username"] = update.message.text.strip()
    await update.message.reply_text("Now enter your password:")
    return LOGIN_PASSWORD

async def login_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    username = context.user_data.get("login_username")
    telegram_id = update.effective_user.id

    subscriber = get_subscriber(telegram_id)

    if (not subscriber or
            subscriber["username"] != username or
            not verify_password(password, subscriber["password_hash"] or "")):
        await update.message.reply_text(
            "❌ *Invalid username or password.*\n\nPlease try again with /start.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    if not is_active_subscriber(telegram_id):
        keyboard = [[InlineKeyboardButton("💳 Subscribe", callback_data="subscribe")]]
        await update.message.reply_text(
            "⚠️ *Your subscription has expired.*\n\nPlease subscribe to regain access.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    invite_link = await generate_invite_link()
    keyboard = [[InlineKeyboardButton("📺 Join Channel", url=invite_link)],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]

    await update.message.reply_text(
        "✅ *Login successful!*\n\nHere's your channel access link:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ── Conversation Handlers ────────────────────────────────────────────

setup_credentials_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(setup_credentials_start, pattern="^setup_credentials$")],
    states={
        SETUP_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_get_username)],
        SETUP_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_get_password)],
        SETUP_CONFIRM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_confirm_password)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel),
        CommandHandler("start", start),
    ],
    per_message=False
    allow_reentry=True
)

login_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(login_start, pattern="^login$")],
    states={
        LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_get_username)],
        LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_get_password)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel),
        CommandHandler("start", start),
    ],
    per_message=False
    allow_reentry=True
)
