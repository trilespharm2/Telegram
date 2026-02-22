import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler,
                           CommandHandler)
from bot.config import STRIPE_SECRET_KEY
from bot.database import (get_subscriber, get_subscriber_by_code,
                           get_subscriber_by_transaction, deactivate_subscriber,
                           get_code_by_email, save_inquiry)
from bot.utils import revoke_user_from_channel, generate_invite_link
from bot.email_service import send_cancellation_email, send_activation_email
from bot.handlers.start import back_to_menu

stripe.api_key = STRIPE_SECRET_KEY

# States
CANCEL_ENTER_ID, CANCEL_CONFIRM = range(2)
RESEND_ENTER_EMAIL = 2
INQUIRY_ENTER_MESSAGE = 3

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

# ── Help Menu ────────────────────────────────────────────────────────

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("❌ Cancel Membership", callback_data="cancel_membership")],
        [InlineKeyboardButton("📧 Didn't Receive Activation Code", callback_data="resend_code")],
        [InlineKeyboardButton("✏️ Write Inquiry", callback_data="write_inquiry")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    await query.edit_message_text(
        "❓ *Help Center*\n\nHow can we help you?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ── Cancel Membership ────────────────────────────────────────────────

async def cancel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ *Cancel Membership*\n\n"
        "Please enter your *activation code* or *transaction ID* to proceed:",
        parse_mode="Markdown"
    )
    return CANCEL_ENTER_ID

async def cancel_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered = update.message.text.strip().upper()
    telegram_id = update.effective_user.id

    subscriber = (get_subscriber_by_code(entered) or
                  get_subscriber_by_transaction(entered) or
                  get_subscriber(telegram_id))

    if not subscriber:
        await update.message.reply_text(
            "❌ No subscription found with that code/ID. Please try again or contact support."
        )
        return CANCEL_ENTER_ID

    context.user_data["cancel_subscriber"] = dict(subscriber)

    keyboard = [
        [InlineKeyboardButton("✅ Yes, Cancel", callback_data="cancel_confirm_yes")],
        [InlineKeyboardButton("❌ No, Keep Subscription", callback_data="cancel_confirm_no")],
    ]
    await update.message.reply_text(
        "⚠️ *Are you sure you want to cancel your subscription?*\n\n"
        "You will lose access to the private channel.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CANCEL_CONFIRM

async def cancel_confirm_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    subscriber = context.user_data.get("cancel_subscriber")
    if not subscriber:
        await query.edit_message_text("⚠️ Session expired. Please start over with /start.")
        return ConversationHandler.END

    telegram_id = subscriber.get("telegram_id")

    stripe_sub_id = subscriber.get("stripe_subscription_id")
    if stripe_sub_id:
        try:
            stripe.Subscription.cancel(stripe_sub_id)
        except Exception as e:
            print(f"Stripe cancel error: {e}")

    if telegram_id:
        deactivate_subscriber(telegram_id)
        await revoke_user_from_channel(telegram_id)

    email = subscriber.get("email")
    if email:
        send_cancellation_email(email)

    await query.edit_message_text(
        "✅ *Your subscription has been cancelled.*\n\n"
        "You have been removed from the private channel.\n"
        "We hope to see you again. Use /start to resubscribe anytime.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_confirm_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ *No problem!* Your subscription remains active.\n\nUse /start to return to the menu.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ── Resend Activation Code ───────────────────────────────────────────

async def resend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📧 *Resend Activation Code*\n\n"
        "Please enter the email address you used during payment:",
        parse_mode="Markdown"
    )
    return RESEND_ENTER_EMAIL

async def resend_by_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip().lower()
    record = get_code_by_email(email)

    if not record:
        await update.message.reply_text(
            "❌ No record found for that email.\n\n"
            "Please make sure you entered the email used during payment, "
            "or use Write Inquiry to contact support."
        )
        return ConversationHandler.END

    invite_link = await generate_invite_link()

    await update.message.reply_text(
        f"✅ *Here are your access details:*\n\n"
        f"Activation Code: `{record['code']}`\n"
        f"Transaction ID: `{record['transaction_id']}`\n\n"
        f"[Join Private Channel]({invite_link})",
        parse_mode="Markdown"
    )

    send_activation_email(email, record["code"], record["transaction_id"], invite_link)
    return ConversationHandler.END

# ── Write Inquiry ────────────────────────────────────────────────────

async def inquiry_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✏️ *Write Inquiry*\n\n"
        "Type your message below and we'll get back to you as soon as possible:",
        parse_mode="Markdown"
    )
    return INQUIRY_ENTER_MESSAGE

async def inquiry_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from bot.config import ADMIN_ID
    message = update.message.text.strip()
    user = update.effective_user
    telegram_id = user.id
    username = user.username or user.first_name or str(telegram_id)

    save_inquiry(telegram_id, username, message)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 *New Inquiry*\n\n"
                 f"From: @{username} (ID: `{telegram_id}`)\n\n"
                 f"Message:\n{message}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error forwarding inquiry: {e}")

    await update.message.reply_text(
        "✅ *Your message has been sent!*\n\n"
        "We'll get back to you as soon as possible.\n\nUse /start to return to the menu.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ── Conversation Handler ─────────────────────────────────────────────

help_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(help_menu, pattern="^help$")],
    states={
        CANCEL_ENTER_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_verify),
            CallbackQueryHandler(cancel_start, pattern="^cancel_membership$"),
        ],
        CANCEL_CONFIRM: [
            CallbackQueryHandler(cancel_confirm_yes, pattern="^cancel_confirm_yes$"),
            CallbackQueryHandler(cancel_confirm_no, pattern="^cancel_confirm_no$"),
        ],
        RESEND_ENTER_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, resend_by_email),
        ],
        INQUIRY_ENTER_MESSAGE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, inquiry_receive),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CallbackQueryHandler(help_menu, pattern="^help$"),
        CallbackQueryHandler(cancel_start, pattern="^cancel_membership$"),
        CallbackQueryHandler(resend_start, pattern="^resend_code$"),
        CallbackQueryHandler(inquiry_start, pattern="^write_inquiry$"),
        CommandHandler("cancel", cancel),
    ],
    per_message=False
)
