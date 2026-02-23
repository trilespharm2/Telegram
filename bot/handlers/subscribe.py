import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler,
                           filters, CallbackQueryHandler, CommandHandler)
from bot.config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, WEBHOOK_URL
from bot.handlers.start import back_to_menu

stripe.api_key = STRIPE_SECRET_KEY

ASK_EMAIL = 1

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        "💳 *Subscribe to Premium Access*\n\n"
        "Please enter your email address so we can send your access code after payment:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_EMAIL

async def subscribe_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    back_keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]

    if "@" not in email or "." not in email:
        await update.message.reply_text(
            "⚠️ *That doesn't look like a valid email address.*\n\n"
            "Please enter a valid email (e.g. name@example.com):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back_keyboard)
        )
        return ASK_EMAIL

    context.user_data["email"] = email
    telegram_id = update.effective_user.id

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            customer_email=email,
            metadata={
                "telegram_id": str(telegram_id),
                "email": email
            },
            success_url=f"{WEBHOOK_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{WEBHOOK_URL}/cancel",
        )

        keyboard = [
            [InlineKeyboardButton("💳 Pay Now", url=session.url)],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]

        await update.message.reply_text(
            f"✅ *Almost there!*\n\n"
            f"Click the button below to complete your payment.\n\n"
            f"After payment, your *access code*, *transaction ID*, and "
            f"*private channel link* will be sent to:\n`{email}`\n\n"
            f"_You'll also receive them here in Telegram._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        print(f"Stripe error: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong creating your payment link. Please try again later.",
            reply_markup=InlineKeyboardMarkup(back_keyboard)
        )

    return ConversationHandler.END

subscribe_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(subscribe_start, pattern="^subscribe$")],
    states={
        ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_get_email)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel_cmd),
        CommandHandler("start", cancel_cmd),
    ],
    per_message=False
)
