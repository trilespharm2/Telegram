from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler,
                           CommandHandler)
from bot.database import (get_subscriber, get_subscriber_by_code,
                           update_subscriber_credentials, is_active_subscriber,
                           get_conn, get_code_by_email)
from bot.utils import generate_invite_link, hash_password, verify_password
from bot.email_service import send_login_credentials_email
from bot.handlers.start import back_to_menu

# ── States ───────────────────────────────────────────────────────────
(LOGIN_MENU,
 CREATE_ENTER_CODE_OR_EMAIL, CREATE_ENTER_USERNAME, CREATE_ENTER_PASSWORD, CREATE_CONFIRM_PASSWORD,
 LOGIN_USERNAME, LOGIN_PASSWORD,
 FORGOT_ENTER_CODE_OR_EMAIL) = range(8)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

# ── Login Menu ───────────────────────────────────────────────────────

async def login_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🆕 Create Login", callback_data="create_login")],
        [InlineKeyboardButton("🔐 Enter Login Credentials", callback_data="enter_login")],
        [InlineKeyboardButton("🔑 Forgot Login / Password", callback_data="forgot_login")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    await query.edit_message_text(
        "🔐 *Login*\n\nPlease select an option:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return LOGIN_MENU

# ── Create Login ─────────────────────────────────────────────────────

async def create_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🆕 *Create Login*\n\n"
        "Please enter your *access code* or *email address* to verify your account:",
        parse_mode="Markdown"
    )
    return CREATE_ENTER_CODE_OR_EMAIL

async def create_verify_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered = update.message.text.strip()
    telegram_id = update.effective_user.id

    # Try access code first
    subscriber = get_subscriber_by_code(entered.upper())

    # Try email
    if not subscriber:
        conn = get_conn()
        subscriber = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?", (entered.lower(),)
        ).fetchone()
        conn.close()

    # Try current telegram_id
    if not subscriber:
        subscriber = get_subscriber(telegram_id)

    if not subscriber:
        await update.message.reply_text(
            "❌ *No active account found.*\n\n"
            "Please check your access code or email and try again.\n"
            "If you haven't subscribed yet, use /start → Subscribe.",
            parse_mode="Markdown"
        )
        return CREATE_ENTER_CODE_OR_EMAIL

    if not subscriber["is_active"]:
        keyboard = [[InlineKeyboardButton("💳 Resubscribe", callback_data="subscribe")]]
        await update.message.reply_text(
            "⚠️ *Your subscription is not active.*\n\n"
            "Please resubscribe to create login credentials.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    # Check if login already exists
    if subscriber["username"]:
        await update.message.reply_text(
            f"⚠️ *Login already exists for this account.*\n\n"
            f"Username: `{subscriber['username']}`\n\n"
            f"If you forgot your password, go back and use *Forgot Login / Password*.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    context.user_data["create_telegram_id"] = subscriber["telegram_id"]
    await update.message.reply_text(
        "✅ *Account verified!*\n\n"
        "Please choose a username (min 3 characters):"
    )
    return CREATE_ENTER_USERNAME

async def create_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if len(username) < 3:
        await update.message.reply_text("⚠️ Username must be at least 3 characters. Try again:")
        return CREATE_ENTER_USERNAME

    # Check username not already taken
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM subscribers WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if existing:
        await update.message.reply_text(
            "⚠️ That username is already taken. Please choose a different one:"
        )
        return CREATE_ENTER_USERNAME

    context.user_data["new_username"] = username
    await update.message.reply_text(
        "Now create a password (min 6 characters):"
    )
    return CREATE_ENTER_PASSWORD

async def create_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text("⚠️ Password must be at least 6 characters. Try again:")
        return CREATE_ENTER_PASSWORD
    context.user_data["new_password"] = password
    await update.message.reply_text("Confirm your password:")
    return CREATE_CONFIRM_PASSWORD

async def create_confirm_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirm = update.message.text.strip()
    if confirm != context.user_data.get("new_password"):
        await update.message.reply_text("⚠️ Passwords don't match. Enter your password again:")
        return CREATE_ENTER_PASSWORD

    telegram_id = context.user_data["create_telegram_id"]
    username = context.user_data["new_username"]
    password_hash = hash_password(context.user_data["new_password"])

    update_subscriber_credentials(telegram_id, username, password_hash)
    context.user_data.clear()

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await update.message.reply_text(
        "✅ *Login credentials created successfully!*\n\n"
        f"Username: `{username}`\n\n"
        "You can now use *Enter Login Credentials* from the Login menu to access your channel anytime.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ── Enter Login Credentials ──────────────────────────────────────────

async def enter_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔐 *Enter Login Credentials*\n\nPlease enter your username:",
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

    conn = get_conn()
    subscriber = conn.execute(
        "SELECT * FROM subscribers WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if not subscriber or not verify_password(password, subscriber["password_hash"] or ""):
        await update.message.reply_text(
            "❌ *Invalid username or password.*\n\n"
            "Please try again or use *Forgot Login / Password* to recover your credentials.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    if not subscriber["is_active"]:
        keyboard = [[InlineKeyboardButton("💳 Resubscribe", callback_data="subscribe")]]
        await update.message.reply_text(
            "⚠️ *Your subscription has expired.*\n\nPlease resubscribe to regain access.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    invite_link = await generate_invite_link()
    keyboard = [
        [InlineKeyboardButton("📺 Join Channel", url=invite_link)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    await update.message.reply_text(
        "✅ *Login successful!*\n\nHere's your channel access link:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ── Forgot Login / Password ──────────────────────────────────────────

async def forgot_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *Forgot Login / Password*\n\n"
        "Please enter your *access code* or *email address*:",
        parse_mode="Markdown"
    )
    return FORGOT_ENTER_CODE_OR_EMAIL

async def forgot_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered = update.message.text.strip()

    # Try access code
    subscriber = get_subscriber_by_code(entered.upper())
    method = "code"

    # Try email
    if not subscriber:
        conn = get_conn()
        subscriber = conn.execute(
            "SELECT * FROM subscribers WHERE email = ?", (entered.lower(),)
        ).fetchone()
        conn.close()
        method = "email"

    if not subscriber:
        await update.message.reply_text(
            "❌ *No account found.*\n\n"
            "Please check your access code or email and try again.",
            parse_mode="Markdown"
        )
        return FORGOT_ENTER_CODE_OR_EMAIL

    if not subscriber["is_active"]:
        keyboard = [[InlineKeyboardButton("💳 Resubscribe", callback_data="subscribe")]]
        await update.message.reply_text(
            "⚠️ *Your subscription is not active.*\n\n"
            "Please resubscribe to recover your login credentials.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    if not subscriber["username"]:
        await update.message.reply_text(
            "⚠️ *No login credentials found for this account.*\n\n"
            "You haven't set up a login yet. Go to Login → Create Login to get started.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    username = subscriber["username"]
    email = subscriber["email"]

    if method == "code":
        # Return credentials directly in Telegram
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await update.message.reply_text(
            f"✅ *Your Login Credentials*\n\n"
            f"Username: `{username}`\n\n"
            f"_Your password cannot be displayed for security reasons._\n"
            f"If you've forgotten your password, please contact support via Help → Write Inquiry.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Send credentials to email
        try:
            send_login_credentials_email(email, username)
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
            await update.message.reply_text(
                f"✅ *Login details sent!*\n\n"
                f"Your username has been sent to `{email}`.\n\n"
                f"_If you've also forgotten your password, please contact support via Help → Write Inquiry._",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"Error sending login credentials email: {e}")
            await update.message.reply_text(
                "⚠️ Failed to send email. Please contact support via Help → Write Inquiry."
            )

    return ConversationHandler.END

# ── Conversation Handlers ────────────────────────────────────────────

setup_credentials_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(create_login_start, pattern="^setup_credentials$")],
    states={
        CREATE_ENTER_CODE_OR_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_verify_account)],
        CREATE_ENTER_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_get_username)],
        CREATE_ENTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_get_password)],
        CREATE_CONFIRM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_confirm_password)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel_cmd),
    ],
    per_message=False
)

login_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(login_menu, pattern="^login$")],
    states={
        LOGIN_MENU: [
            CallbackQueryHandler(create_login_start, pattern="^create_login$"),
            CallbackQueryHandler(enter_login_start, pattern="^enter_login$"),
            CallbackQueryHandler(forgot_login_start, pattern="^forgot_login$"),
            CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        ],
        CREATE_ENTER_CODE_OR_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_verify_account)],
        CREATE_ENTER_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_get_username)],
        CREATE_ENTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_get_password)],
        CREATE_CONFIRM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_confirm_password)],
        LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_get_username)],
        LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_get_password)],
        FORGOT_ENTER_CODE_OR_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, forgot_lookup)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CallbackQueryHandler(login_menu, pattern="^login$"),
        CommandHandler("cancel", cancel_cmd),
    ],
    per_message=False
)
