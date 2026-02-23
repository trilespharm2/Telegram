from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler,
                           CommandHandler)
from bot.database import (get_activation_code_record, mark_code_used,
                           create_subscriber, get_subscriber, is_active_subscriber,
                           get_conn, update_subscriber_stripe_ids)
from bot.utils import generate_invite_link
from bot.handlers.start import back_to_menu

ENTER_CODE = 1

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

async def activation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *Enter Access Code*\n\nPlease type your access code below:",
        parse_mode="Markdown"
    )
    return ENTER_CODE

async def activation_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    telegram_id = update.effective_user.id

    # Check if user already has active subscription
    if is_active_subscriber(telegram_id):
        invite_link = await generate_invite_link()
        keyboard = [[InlineKeyboardButton("📺 Join Channel", url=invite_link)],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "✅ *Active subscription found!*\n\nHere's your channel link:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    # Check if this telegram_id has a cancelled subscription
    conn = get_conn()
    cancelled = conn.execute(
        "SELECT * FROM subscribers WHERE telegram_id = ? AND is_active = 0",
        (telegram_id,)
    ).fetchone()
    conn.close()

    if cancelled:
        keyboard = [[InlineKeyboardButton("💳 Subscribe Now", callback_data="subscribe")],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "⚠️ *Your subscription has been cancelled.*\n\n"
            "You no longer have access to the premium channel.\n"
            "Please resubscribe to regain access.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    record = get_activation_code_record(code)

    if not record:
        await update.message.reply_text(
            "❌ *Invalid access code.*\n\n"
            "Please double-check and try again, or use /start to return to the menu.",
            parse_mode="Markdown"
        )
        return ENTER_CODE

    if record["used"]:
        conn = get_conn()
        sub = conn.execute(
            "SELECT * FROM subscribers WHERE activation_code = ?", (code,)
        ).fetchone()
        conn.close()

        if sub and sub["is_active"] == 0:
            keyboard = [[InlineKeyboardButton("💳 Subscribe Now", callback_data="subscribe")],
                        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
            await update.message.reply_text(
                "⚠️ *Your subscription has been cancelled.*\n\n"
                "Please resubscribe to regain access.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

        if sub and sub["is_active"] == 1:
            invite_link = await generate_invite_link()
            keyboard = [[InlineKeyboardButton("📺 Join Channel", url=invite_link)],
                        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
            await update.message.reply_text(
                "✅ *Active subscription found!*\n\nHere's your fresh channel link:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

        await update.message.reply_text(
            "⚠️ *This access code has already been used.*\n\n"
            "If you believe this is an error, go to Help → Didn't receive access code.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Valid unused code — grant access
    invite_link = await generate_invite_link()

    # Check if webhook already created a subscriber record with Stripe IDs
    # If so, UPDATE telegram_id only — preserves stripe_customer_id and stripe_subscription_id
    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM subscribers WHERE activation_code = ?", (code,)
    ).fetchone()

    if existing:
        print(f"Activation: found existing record, updating telegram_id to {telegram_id}, preserving Stripe IDs: customer={existing['stripe_customer_id']} sub={existing['stripe_subscription_id']}")
        conn.execute(
            "UPDATE subscribers SET telegram_id = ?, is_active = 1 WHERE activation_code = ?",
            (telegram_id, code)
        )
        conn.commit()
        conn.close()
    else:
        conn.close()
        print(f"Activation: no existing record found for code {code}, creating new subscriber")
        create_subscriber(
            telegram_id=telegram_id,
            email=record["email"],
            activation_code=code,
            transaction_id=record["transaction_id"],
            stripe_customer_id="",
            stripe_subscription_id=""
        )

    mark_code_used(code, telegram_id)

    keyboard = [
        [InlineKeyboardButton("📺 Join Private Channel", url=invite_link)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    await update.message.reply_text(
        "🎉 *Access Granted!*\n\n"
        "Welcome to the premium channel! Click below to join.\n\n"
        "_Once inside, you may optionally set up login credentials "
        "via the bot menu for easier future access._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

activation_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(activation_start, pattern="^activation_code$")],
    states={
        ENTER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activation_check)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel),
    ],
    per_message=False
)
