import re
import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler,
                           CommandHandler)
from bot.config import STRIPE_SECRET_KEY
from bot.database import (get_activation_code_record, mark_code_used,
                           create_subscriber, get_subscriber, is_active_subscriber,
                           get_conn, get_subscriber_by_stripe_customer)
from bot.utils import generate_invite_link, generate_and_store_invite_link, unban_user_for_channel
from bot.handlers.start import back_to_menu

stripe.api_key = STRIPE_SECRET_KEY

ENTER_CODE = 1

BACK = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END

def looks_like_invoice_number(text: str) -> bool:
    """Detect Stripe invoice number format e.g. KHDEXB2Z-0001"""
    return bool(re.match(r'^[A-Z0-9]{6,}-\d{4}$', text.upper()))

async def lookup_by_invoice(invoice_number: str):
    """Look up subscriber via Stripe invoice number. Also returns Stripe subscription status."""
    try:
        invoices = stripe.Invoice.list(limit=100)
        for invoice in invoices.auto_paging_iter():
            if invoice.get("number", "").upper() == invoice_number.upper():
                customer_id = invoice.get("customer")
                subscription_id = invoice.get("subscription")
                stripe_active = False

                # Check Stripe subscription status directly
                if subscription_id:
                    try:
                        sub = stripe.Subscription.retrieve(subscription_id)
                        stripe_active = sub.get("status") == "active"
                    except Exception as e:
                        print(f"Error retrieving subscription {subscription_id}: {e}")

                if customer_id:
                    subscriber = get_subscriber_by_stripe_customer(customer_id)
                    if subscriber:
                        return subscriber, invoice, stripe_active
                    # No local record but Stripe confirms active — return invoice details
                    return None, invoice, stripe_active
        return None, None, False
    except Exception as e:
        print(f"Error looking up invoice {invoice_number}: {e}")
        return None, None, False

async def activation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *Enter Access Code*\n\n"
        "Please type your *access code* or *invoice number* below:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(BACK)
    )
    return ENTER_CODE

async def activation_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered = update.message.text.strip()
    code = entered.upper()
    telegram_id = update.effective_user.id

    # Check if user already has active subscription
    if is_active_subscriber(telegram_id):
        invite_link = await generate_invite_link()
        keyboard = [
            [InlineKeyboardButton("📺 Join Channel", url=invite_link)],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        await update.message.reply_text(
            "✅ *Active subscription found!*\n\nHere's your channel link:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    # ── Invoice number check — Stripe is authoritative, skip local DB ─
    if looks_like_invoice_number(code):
        await update.message.reply_text(
            "🔍 Looking up your invoice, please wait...",
        )
        subscriber, invoice, stripe_active = await lookup_by_invoice(code)

        if not invoice:
            await update.message.reply_text(
                "❌ *Invoice not found.*\n\n"
                "Please check the invoice number and try again, or enter your "
                "12-character access code sent via Telegram and email after payment.\n\n"
                "_Example access code: `ABC123DEF456`_",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(BACK)
            )
            return ENTER_CODE

        # Trust Stripe status over local database
        if not stripe_active:
            keyboard = [
                [InlineKeyboardButton("💳 Resubscribe", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            await update.message.reply_text(
                "⚠️ *Subscription found but not active.*\n\n"
                f"Invoice: `{code}`\n\n"
                "Please resubscribe to regain access.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

        # Active subscription confirmed by Stripe — unban and give access
        await unban_user_for_channel(telegram_id)
        invite_link = await generate_and_store_invite_link(telegram_id)

        # Update or create subscriber record with correct telegram_id
        customer_id = invoice.get("customer", "")
        subscription_id = invoice.get("subscription", "")
        email = invoice.get("customer_email", "")

        if subscriber:
            # Update telegram_id on existing record and reactivate
            conn = get_conn()
            conn.execute(
                "UPDATE subscribers SET telegram_id = ?, is_active = 1 WHERE stripe_customer_id = ?",
                (telegram_id, customer_id)
            )
            conn.commit()
            conn.close()
        else:
            # No local record — create one now
            from bot.utils import generate_activation_code, generate_transaction_id
            from bot.database import store_activation_code
            new_code = generate_activation_code()
            new_txn = generate_transaction_id()
            store_activation_code(new_code, new_txn, email)
            create_subscriber(
                telegram_id=telegram_id,
                email=email,
                activation_code=new_code,
                transaction_id=new_txn,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id
            )

        keyboard = [
            [InlineKeyboardButton("📺 Join Private Channel", url=invite_link)],
            [InlineKeyboardButton("🔐 Set Up Login Credentials", callback_data="setup_credentials")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        await update.message.reply_text(
            f"✅ *Access Granted via Invoice!*\n\n"
            f"Invoice: `{code}`\n\n"
            f"Welcome to the premium channel! Click below to join.\n\n"
            f"💡 _Set up login credentials for quick future access._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    # ── Try as access code ───────────────────────────────────────────
    record = get_activation_code_record(code)

    if not record:
        await update.message.reply_text(
            "❌ *Invalid access code or invoice number.*\n\n"
            "Please check and try again.\n\n"
            "• *Access code:* 12-character code like `ABC123DEF456`\n"
            "• *Invoice number:* format like `KHDEXB2Z-0001`\n\n"
            "_Both were sent to you via Telegram and email after payment._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(BACK)
        )
        return ENTER_CODE

    if record["used"]:
        conn = get_conn()
        sub = conn.execute(
            "SELECT * FROM subscribers WHERE activation_code = ?", (code,)
        ).fetchone()
        conn.close()

        if sub and sub["is_active"] == 0:
            keyboard = [
                [InlineKeyboardButton("💳 Subscribe Now", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            await update.message.reply_text(
                "⚠️ *Your subscription has been cancelled.*\n\n"
                "Please resubscribe to regain access.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

        if sub and sub["is_active"] == 1:
            invite_link = await generate_invite_link()
            keyboard = [
                [InlineKeyboardButton("📺 Join Channel", url=invite_link)],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            await update.message.reply_text(
                "✅ *Active subscription found!*\n\nHere's your fresh channel link:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END

        await update.message.reply_text(
            "⚠️ *This access code has already been used.*\n\n"
            "If you believe this is an error, go to Help → Didn't Receive Access Code.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(BACK)
        )
        return ConversationHandler.END

    # Valid unused access code — grant access
    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM subscribers WHERE activation_code = ?", (code,)
    ).fetchone()

    if existing:
        print(f"Activation: updating telegram_id to {telegram_id}, preserving Stripe IDs: customer={existing['stripe_customer_id']} sub={existing['stripe_subscription_id']}")
        conn.execute(
            "UPDATE subscribers SET telegram_id = ?, is_active = 1 WHERE activation_code = ?",
            (telegram_id, code)
        )
        conn.commit()
        conn.close()
    else:
        conn.close()
        print(f"Activation: no existing record for code {code}, creating new subscriber")
        create_subscriber(
            telegram_id=telegram_id,
            email=record["email"],
            activation_code=code,
            transaction_id=record["transaction_id"],
            stripe_customer_id="",
            stripe_subscription_id=""
        )

    mark_code_used(code, telegram_id)
    await unban_user_for_channel(telegram_id)
    invite_link = await generate_and_store_invite_link(telegram_id)

    keyboard = [
        [InlineKeyboardButton("📺 Join Private Channel", url=invite_link)],
        [InlineKeyboardButton("🔐 Set Up Login Credentials", callback_data="setup_credentials")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    await update.message.reply_text(
        "🎉 *Access Granted!*\n\n"
        "Welcome to the premium channel! Click below to join.\n\n"
        "💡 _Set up login credentials for quick future access — "
        "no need to find your access code next time._",
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
        CommandHandler("cancel", cancel_cmd),
        CommandHandler("start", cancel_cmd),
    ],
    per_message=False
)
