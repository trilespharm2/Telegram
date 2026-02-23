import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, MessageHandler,
                           filters, CallbackQueryHandler, CommandHandler)
from bot.config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, WEBHOOK_URL
import os

stripe.api_key = STRIPE_SECRET_KEY

# ── Stripe Price IDs ─────────────────────────────────────────────────
# Create both prices in Stripe dashboard and paste IDs here
PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "price_1T2i76AEty6YzLTj0GTpEvZT")  # $9.99/month recurring
PRICE_ONE_MONTH = os.getenv("STRIPE_PRICE_ONE_MONTH", "")  # $15.99 one-time month

ASK_PLAN = 1
ASK_EMAIL = 2

from bot.handlers.start import back_to_menu

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📅 One Month Access — $15.99", callback_data="plan_one_month")],
        [InlineKeyboardButton("🔄 Monthly Subscription — $9.99/mo", callback_data="plan_monthly")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    await query.edit_message_text(
        "💳 *Subscribe to Premium Access*\n\n"
        "Please select a plan:\n\n"
        "📅 *One Month Access — $15.99*\n"
        "_Single payment. Access for 30 days, then automatically ends._\n\n"
        "🔄 *Monthly Subscription — $9.99/mo*\n"
        "_Billed monthly. Cancel anytime._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_PLAN

async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plan = query.data  # "plan_one_month" or "plan_monthly"
    context.user_data["plan"] = plan

    if plan == "plan_one_month":
        plan_label = "One Month Access — $15.99"
    else:
        plan_label = "Monthly Subscription — $9.99/mo"

    context.user_data["plan_label"] = plan_label

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        f"✅ *Plan selected:* {plan_label}\n\n"
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

    plan = context.user_data.get("plan", "plan_monthly")
    plan_label = context.user_data.get("plan_label", "Monthly Subscription")
    telegram_id = update.effective_user.id

    # Select correct price and mode
    if plan == "plan_one_month":
        price_id = PRICE_ONE_MONTH
        mode = "payment"  # One-time payment
    else:
        price_id = PRICE_MONTHLY
        mode = "subscription"  # Recurring

    if not price_id:
        await update.message.reply_text(
            "⚠️ This plan is not yet configured. Please contact support.",
            reply_markup=InlineKeyboardMarkup(back_keyboard)
        )
        return ConversationHandler.END

    try:
        session_params = {
            "payment_method_types": ["card"],
            "mode": mode,
            "line_items": [{"price": price_id, "quantity": 1}],
            "customer_email": email,
            "metadata": {
                "telegram_id": str(telegram_id),
                "email": email,
                "plan": plan
            },
            "success_url": f"{WEBHOOK_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{WEBHOOK_URL}/cancel",
        }

        session = stripe.checkout.Session.create(**session_params)

        keyboard = [
            [InlineKeyboardButton("💳 Pay Now", url=session.url)],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]

        await update.message.reply_text(
            f"✅ *Almost there!*\n\n"
            f"Plan: *{plan_label}*\n\n"
            f"Click below to complete your payment.\n\n"
            f"After payment, your *access code* and *private channel link* "
            f"will be sent to:\n`{email}`\n\n"
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
        ASK_PLAN: [
            CallbackQueryHandler(plan_selected, pattern="^plan_one_month$"),
            CallbackQueryHandler(plan_selected, pattern="^plan_monthly$"),
        ],
        ASK_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_get_email)
        ],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel_cmd),
        CommandHandler("start", cancel_cmd),
    ],
    per_message=False
)
