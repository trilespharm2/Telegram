from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler)
from bot.database import (get_activation_code_record, mark_code_used,
                           create_subscriber, get_subscriber, is_active_subscriber)
from bot.utils import generate_invite_link
from bot.handlers.start import back_to_menu

ENTER_CODE = 1

async def activation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicked Enter Activation Code."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *Enter Activation Code*\n\n"
        "Please type your activation code below:",
        parse_mode="Markdown"
    )
    return ENTER_CODE

async def activation_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate activation code and send channel invite link."""
    code = update.message.text.strip().upper()
    telegram_id = update.effective_user.id

    # Check if user already has active subscription
    if is_active_subscriber(telegram_id):
        invite_link = await generate_invite_link()
        keyboard = [[InlineKeyboardButton("📺 Join Channel", url=invite_link)],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "✅ *You already have an active subscription!*\n\n"
            "Here's your fresh channel access link:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    record = get_activation_code_record(code)

    if not record:
        await update.message.reply_text(
            "❌ *Invalid activation code.*\n\n"
            "Please double-check and try again, or use /start to return to the menu.",
            parse_mode="Markdown"
        )
        return ENTER_CODE

    if record["used"]:
        await update.message.reply_text(
            "⚠️ *This activation code has already been used.*\n\n"
            "If you believe this is an error, go to Help → Didn't receive activation code.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Valid unused code — grant access
    invite_link = await generate_invite_link()

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
    fallbacks=[CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$")],
    per_message=False
)
