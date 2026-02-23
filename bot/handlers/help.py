import stripe
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler,
                           CommandHandler)
from bot.config import STRIPE_SECRET_KEY, ADMIN_ID
from bot.database import (get_subscriber, get_subscriber_by_code,
                           get_subscriber_by_transaction, deactivate_subscriber,
                           get_code_by_email, save_inquiry, get_conn)
from bot.utils import revoke_user_from_channel, generate_invite_link
from bot.email_service import send_cancellation_email, send_activation_email
from bot.handlers.start import back_to_menu

stripe.api_key = STRIPE_SECRET_KEY

# ── States ───────────────────────────────────────────────────────────
(HELP_MENU,
 CANCEL_ENTER_ID, CANCEL_CONFIRM,
 RESEND_ENTER_EMAIL,
 INQUIRY_ENTER_EMAIL, INQUIRY_ENTER_MESSAGE) = range(6)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    return HELP_MENU

# ── Cancel Membership ────────────────────────────────────────────────

async def cancel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ *Cancel Membership*\n\n"
        "Please enter your *activation code*, *transaction ID*, or *login username* to proceed:",
        parse_mode="Markdown"
    )
    return CANCEL_ENTER_ID

async def cancel_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered = update.message.text.strip()
    telegram_id = update.effective_user.id

    entered_upper = entered.upper()
    subscriber = (
        get_subscriber_by_code(entered_upper) or
        get_subscriber_by_transaction(entered_upper) or
        get_subscriber(telegram_id)
    )

    if not subscriber:
        conn = get_conn()
        subscriber = conn.execute(
            "SELECT * FROM subscribers WHERE username = ?", (entered,)
        ).fetchone()
        conn.close()

    if not subscriber:
        await update.message.reply_text(
            "❌ No subscription found with that code, ID, or username.\n\n"
            "Please try again or use *Write Inquiry* to contact support.",
            parse_mode="Markdown"
        )
        return CANCEL_ENTER_ID

    context.user_data["cancel_subscriber"] = dict(subscriber)

    keyboard = [
        [InlineKeyboardButton("✅ Yes, Cancel My Subscription", callback_data="cancel_confirm_yes")],
        [InlineKeyboardButton("❌ No, Keep My Subscription", callback_data="cancel_confirm_no")],
    ]
    await update.message.reply_text(
        "⚠️ *Are you sure you want to cancel your subscription?*\n\n"
        "🚫 *Your access will be immediately revoked* and you will be removed from the private channel.\n\n"
        "_You would need to resubscribe to regain access._",
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
    cancellation_ref = None

    if stripe_sub_id:
        try:
            result = stripe.Subscription.cancel(stripe_sub_id)
            cancellation_ref = result.get("id", stripe_sub_id)
        except Exception as e:
            print(f"Stripe cancel error: {e}")
            cancellation_ref = stripe_sub_id

    if telegram_id:
        deactivate_subscriber(telegram_id)
        await revoke_user_from_channel(telegram_id)

    email = subscriber.get("email")
    if email:
        send_cancellation_email(email)

    cancelled_at = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")
    confirmation_text = (
        "✅ *Your subscription has been cancelled.*\n\n"
        f"📅 Cancellation Date: {cancelled_at}\n"
    )
    if cancellation_ref:
        confirmation_text += f"🧾 Cancellation Ref: `{cancellation_ref}`\n"
    confirmation_text += (
        "\nYou have been removed from the private channel.\n"
        "We hope to see you again! Use /start to resubscribe anytime."
    )

    await query.edit_message_text(confirmation_text, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_confirm_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        "✅ *No problem!* Your subscription remains active.\n\n"
        "You still have full access to the private channel.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ── Didn't Receive Activation Code ──────────────────────────────────

async def resend_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📧 *Didn't Receive Activation Code?*\n\n"
        "Please enter the email address you used during payment:",
        parse_mode="Markdown"
    )
    return RESEND_ENTER_EMAIL

async def resend_by_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip().lower()
    record = get_code_by_email(email)

    if not record:
        keyboard = [
            [InlineKeyboardButton("✏️ Write Inquiry", callback_data="write_inquiry")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        await update.message.reply_text(
            "❌ *No record found for that email.*\n\n"
            "Please make sure you entered the exact email used during payment.\n\n"
            "If you need further help, use Write Inquiry to contact support.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    conn = get_conn()
    subscriber = conn.execute(
        "SELECT * FROM subscribers WHERE activation_code = ? OR transaction_id = ?",
        (record["code"], record["transaction_id"])
    ).fetchone()
    conn.close()

    if subscriber and subscriber["is_active"] == 0:
        cancelled_at = subscriber.get("expires_at", "Unknown")
        try:
            cancelled_date = datetime.fromisoformat(cancelled_at).strftime("%B %d, %Y")
        except Exception:
            cancelled_date = cancelled_at

        keyboard = [
            [InlineKeyboardButton("💳 Resubscribe", callback_data="subscribe")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        await update.message.reply_text(
            f"⚠️ *Subscription Found — Cancelled*\n\n"
            f"🔑 Activation Code: `{record['code']}`\n"
            f"🧾 Transaction ID: `{record['transaction_id']}`\n"
            f"📅 Cancellation Date: {cancelled_date}\n\n"
            f"Your subscription has been cancelled. Use the button below to resubscribe.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    invite_link = await generate_invite_link()
    send_activation_email(email, record["code"], record["transaction_id"], invite_link)

    keyboard = [
        [InlineKeyboardButton("📺 Join Private Channel", url=invite_link)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    await update.message.reply_text(
        f"✅ *Here are your access details:*\n\n"
        f"🔑 Activation Code: `{record['code']}`\n"
        f"🧾 Transaction ID: `{record['transaction_id']}`\n\n"
        f"_These details have also been resent to {email}_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ── Write Inquiry ────────────────────────────────────────────────────

async def inquiry_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✏️ *Write Inquiry*\n\n"
        "Please enter your *email address* so we can follow up with you:",
        parse_mode="Markdown"
    )
    return INQUIRY_ENTER_EMAIL

async def inquiry_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid email. Please try again:"
        )
        return INQUIRY_ENTER_EMAIL

    context.user_data["inquiry_email"] = email
    await update.message.reply_text(
        "📝 *Got it!*\n\nNow please type your message below:",
        parse_mode="Markdown"
    )
    return INQUIRY_ENTER_MESSAGE

async def inquiry_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    user = update.effective_user
    telegram_id = user.id
    username = user.username or user.first_name or str(telegram_id)
    inquiry_email = context.user_data.get("inquiry_email", "Not provided")

    save_inquiry(telegram_id, username, message)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 *New Inquiry*\n\n"
                 f"From: @{username} (ID: `{telegram_id}`)\n"
                 f"Email: {inquiry_email}\n\n"
                 f"Message:\n{message}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error forwarding inquiry to admin: {e}")

    try:
        from bot.email_service import send_inquiry_email
        send_inquiry_email(inquiry_email, username, telegram_id, message)
    except Exception as e:
        print(f"Error sending inquiry email: {e}")

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await update.message.reply_text(
        "✅ *Thank you for reaching out!*\n\n"
        "Someone will review your message and get back to you within 24 hours.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ── Conversation Handler ─────────────────────────────────────────────

help_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(help_menu, pattern="^help$")],
    states={
        HELP_MENU: [
            CallbackQueryHandler(cancel_start, pattern="^cancel_membership$"),
            CallbackQueryHandler(resend_start, pattern="^resend_code$"),
            CallbackQueryHandler(inquiry_start, pattern="^write_inquiry$"),
            CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        ],
        CANCEL_ENTER_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_verify),
        ],
        CANCEL_CONFIRM: [
            CallbackQueryHandler(cancel_confirm_yes, pattern="^cancel_confirm_yes$"),
            CallbackQueryHandler(cancel_confirm_no, pattern="^cancel_confirm_no$"),
        ],
        RESEND_ENTER_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, resend_by_email),
        ],
        INQUIRY_ENTER_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, inquiry_get_email),
        ],
        INQUIRY_ENTER_MESSAGE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, inquiry_receive),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
        CallbackQueryHandler(help_menu, pattern="^help$"),
        CommandHandler("cancel", cancel_cmd),
    ],
    per_message=False
)
