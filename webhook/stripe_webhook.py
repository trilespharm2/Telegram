import stripe
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from bot.config import (STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, BOT_TOKEN, ADMIN_ID)
from bot.database import (store_activation_code, create_subscriber,
                            deactivate_subscriber, init_db, get_conn,
                            get_subscriber_by_stripe_customer,
                            get_subscriber_by_stripe_subscription,
                            get_subscriber_by_email)
from bot.utils import generate_activation_code, generate_transaction_id, generate_invite_link, generate_and_store_invite_link
from bot.email_service import send_activation_email

stripe.api_key = STRIPE_SECRET_KEY
app = Flask(__name__)
init_db()

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        asyncio.run(handle_payment_success(event["data"]["object"]))
    elif event["type"] == "invoice.paid":
        asyncio.run(handle_renewal_success(event["data"]["object"]))
    elif event["type"] == "invoice.payment_failed":
        asyncio.run(handle_payment_failed(event["data"]["object"]))
    elif event["type"] == "customer.subscription.deleted":
        asyncio.run(handle_subscription_cancelled(event["data"]["object"]))

    return jsonify({"status": "ok"}), 200


async def handle_payment_success(session):
    """Handles both one-time and subscription checkout completions."""
    telegram_id_str = session.get("metadata", {}).get("telegram_id")
    email = session.get("customer_email") or session.get("metadata", {}).get("email")
    stripe_customer_id = session.get("customer")
    stripe_subscription_id = session.get("subscription") or ""
    plan = session.get("metadata", {}).get("plan", "plan_monthly")
    mode = session.get("mode", "subscription")

    if not telegram_id_str or not email:
        print("Missing telegram_id or email in session metadata")
        return

    telegram_id = int(telegram_id_str)

    # For one-time payment, expires in 30 days and no subscription ID
    if mode == "payment":
        plan_label = "One Month Access"
        expires_days = 30
        stripe_subscription_id = ""
    else:
        plan_label = "Monthly Subscription"
        expires_days = 30

    activation_code = generate_activation_code()
    transaction_id = session.get("payment_intent") or generate_transaction_id()
    store_activation_code(activation_code, transaction_id, email)
    create_subscriber(
        telegram_id=telegram_id,
        email=email,
        activation_code=activation_code,
        transaction_id=transaction_id,
        stripe_customer_id=stripe_customer_id or "",
        stripe_subscription_id=stripe_subscription_id,
        expires_days=expires_days
    )

    print(f"Subscriber created: telegram_id={telegram_id}, plan={plan_label}, customer={stripe_customer_id}")

    # Generate and store invite link so it can be revoked on cancellation
    invite_link = await generate_and_store_invite_link(telegram_id)
    send_activation_email(email, activation_code, transaction_id, invite_link)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Join Private Channel", url=invite_link)],
        [InlineKeyboardButton("🔐 Set Up Login Credentials", callback_data="setup_credentials")],
    ])

    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=f"🎉 *Payment Confirmed! Welcome to Premium Access*\n\n"
                 f"Plan: *{plan_label}*\n\n"
                 f"Here are your access details — save these:\n\n"
                 f"🔑 Access Code: `{activation_code}`\n"
                 f"🧾 Transaction ID: `{transaction_id}`\n\n"
                 f"📺 [Join Private Channel]({invite_link})\n\n"
                 f"_Your access code and channel link have also been sent to {email}_\n\n"
                 f"⚠️ *Important:* Your channel invite link is personal — do not forward it to others. Forwarded links will be automatically invalidated if your subscription ends.

"                 f"⬇️ *Recommended:* Set up login credentials below for quick future access.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"Error sending Telegram message: {e}")


async def handle_renewal_success(invoice):
    """Called when a monthly subscription renews."""
    stripe_customer_id = invoice.get("customer")
    billing_reason = invoice.get("billing_reason")

    # Skip first payment — handled by checkout.session.completed
    if billing_reason == "subscription_create":
        return

    row = get_subscriber_by_stripe_customer(stripe_customer_id)
    if not row:
        print(f"Renewal: No subscriber found for customer {stripe_customer_id}")
        return

    conn = get_conn()
    new_expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    conn.execute(
        "UPDATE subscribers SET expires_at = ?, is_active = 1 WHERE stripe_customer_id = ?",
        (new_expires, stripe_customer_id)
    )
    conn.commit()
    conn.close()

    print(f"Renewed subscription for customer {stripe_customer_id} until {new_expires}")

    bot = Bot(token=BOT_TOKEN)
    try:
        invite_link = await generate_invite_link()
        await bot.send_message(
            chat_id=row["telegram_id"],
            text=f"✅ *Subscription Renewed!*\n\n"
                 f"Your premium access has been extended for another 30 days.\n\n"
                 f"📺 [Rejoin Channel if needed]({invite_link})",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error sending renewal message: {e}")


async def handle_payment_failed(invoice):
    """Called when a renewal payment fails."""
    stripe_customer_id = invoice.get("customer")
    row = get_subscriber_by_stripe_customer(stripe_customer_id)

    if row:
        bot = Bot(token=BOT_TOKEN)
        try:
            await bot.send_message(
                chat_id=row["telegram_id"],
                text="⚠️ *Payment Failed*\n\n"
                     "We couldn't process your subscription renewal.\n"
                     "Please update your payment method to maintain access.\n\n"
                     "Use /start → Subscribe to resubscribe.",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error notifying failed payment: {e}")


async def handle_subscription_cancelled(subscription):
    """Called when a monthly subscription is cancelled."""
    stripe_sub_id = subscription.get("id")
    stripe_customer_id = subscription.get("customer")

    print(f"Cancellation received — sub_id={stripe_sub_id}, customer={stripe_customer_id}")

    row = get_subscriber_by_stripe_subscription(stripe_sub_id)
    if not row:
        row = get_subscriber_by_stripe_customer(stripe_customer_id)
    if not row:
        try:
            customer = stripe.Customer.retrieve(stripe_customer_id)
            email = customer.get("email")
            if email:
                print(f"Falling back to email lookup: {email}")
                row = get_subscriber_by_email(email)
        except Exception as e:
            print(f"Error fetching Stripe customer: {e}")

    if not row:
        print(f"FATAL: No subscriber found for sub={stripe_sub_id}, customer={stripe_customer_id}")
        return

    print(f"Found subscriber telegram_id={row['telegram_id']} — revoking access")

    from bot.utils import revoke_user_from_channel
    deactivate_subscriber(row["telegram_id"])
    await revoke_user_from_channel(row["telegram_id"])

    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=row["telegram_id"],
            text="⚠️ *Your subscription has ended.*\n\n"
                 "You have been removed from the private channel.\n"
                 "Use /start to resubscribe anytime.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error notifying cancelled user: {e}")


@app.route("/success")
def payment_success():
    return "<h2>✅ Payment successful! Check Telegram for your access details.</h2>", 200

@app.route("/cancel")
def payment_cancel():
    return "<h2>❌ Payment cancelled. Return to Telegram and try again.</h2>", 200

@app.route("/health")
def health():
    return jsonify({"status": "running"}), 200
