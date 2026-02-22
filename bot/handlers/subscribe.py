import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler)
from bot.config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, WEBHOOK_URL
from bot.handlers.start import back_to_menu

stripe.api_key = STRIPE_SECRET_KEY
ASK_EMAIL = 1

async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💳 *Subscribe to Premium Access*\n\n"
        "Please enter your email address:",
        parse_mode="Markdown"
    )
    return ASK_EMAIL

async def subscribe_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("⚠️ Invalid email. Please try again:")
        return ASK_EMAIL

    telegram_id = update.effective_user.id
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            customer_email=email,
            metadata={"telegram_id": str(telegram_id), "email": email},
            success_url=f"{WEBHOOK_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{WEBHOOK_URL}/cancel",
        )
        keyboard = [[InlineKeyboardButton("💳 Pay Now", url=session.url)],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await update.message.reply_text(
            f"✅ *Almost there!*\n\nClick below to complete payment.\n\n"
            f"Your activation code and channel link will be sent to `{email}` after payment.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        print(f"Stripe error: {e}")
        await update.message.reply_text("⚠️ Error creating payment link. Please try again later.")
    return ConversationHandler.END

subscribe_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(subscribe_start, pattern="^subscribe$")],
    states={
        ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_get_email)],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel),
        CommandHandler("start", start),
    ],
    per_message=False
)
