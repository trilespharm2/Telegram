import stripe
import asyncio
from flask import Flask, request, jsonify
from telegram import Bot
from bot.config import (STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
                         BOT_TOKEN, ADMIN_ID)
from bot.database import (store_activation_code, create_subscriber,
                            deactivate_subscriber, get_subscriber_by_transaction)
from bot.utils import generate_activation_code, generate_transaction_id, generate_invite_link
from bot.email_service import send_activation_email

stripe.api_key = STRIPE_SECRET_KEY

app = Flask(__name__)

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        asyncio.run(handle_payment_success(event["data"]["object"]))

    elif event["type"] == "customer.subscription.deleted":
        asyncio.run(handle_subscription_cancelled(event["data"]["object"]))

    elif event["type"] == "invoice.payment_failed":
        asyncio.run(handle_payment_failed(event["data"]["object"]))

    return jsonify({"status": "ok"}), 200

async def handle_payment_success(session):
    """Called when Stripe payment is completed successfully."""
    telegram_id_str = session.get("metadata", {}).get("telegram_id")
    email = session.get("customer_email") or session.get("metadata", {}).get("email")
    stripe_customer_id = session.get("customer")
    stripe_subscription_id = session.get("subscription")

    if not telegram_id_str or not email:
        print("Missing telegram_id or email in session metadata")
        return

    telegram_id = int(telegram_id_str)

    # Generate codes
    activation_code = generate_activation_code()
    transaction_id = session.get("payment_intent") or generate_transaction_id()

    # Generate invite link
    invite_link = await generate_invite_link()

    # Store in DB
    store_activation_code(activation_code, transaction_id, email)
    create_subscriber(
        telegram_id=telegram_id,
        email=email,
        activation_code=activation_code,
        transaction_id=transaction_id,
        stripe_customer_id=stripe_customer_id or "",
        stripe_subscription_id=stripe_subscription_id or ""
    )

    # Send email
    send_activation_email(email, activation_code, transaction_id, invite_link)

    # Send Telegram message
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=f"🎉 *Payment Confirmed! Welcome to Premium Access*\n\n"
                 f"Here are your access details — save these:\n\n"
                 f"🔑 Activation Code: `{activation_code}`\n"
                 f"🧾 Transaction ID: `{transaction_id}`\n\n"
                 f"📺 [Join Private Channel]({invite_link})\n\n"
                 f"_Your activation code and channel link have also been sent to {email}_\n\n"
                 f"Once inside the channel, you may optionally set up login credentials "
                 f"via the bot menu for faster future access.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

async def handle_subscription_cancelled(subscription):
    """Called when a subscription is cancelled or expires."""
    stripe_sub_id = subscription.get("id")
    # Find subscriber by stripe subscription ID
    from bot.database import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscribers WHERE stripe_subscription_id = ?",
        (stripe_sub_id,)
    ).fetchone()
    conn.close()

    if row:
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

async def handle_payment_failed(invoice):
    """Called when a renewal payment fails."""
    stripe_customer_id = invoice.get("customer")
    from bot.database import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscribers WHERE stripe_customer_id = ?",
        (stripe_customer_id,)
    ).fetchone()
    conn.close()

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

@app.route("/success")
def payment_success():
    return "<h2>✅ Payment successful! Check Telegram for your access details.</h2>", 200

@app.route("/cancel")
def payment_cancel():
    return "<h2>❌ Payment cancelled. Return to Telegram and try again.</h2>", 200

@app.route("/health")
def health():
    return jsonify({"status": "running"}), 200
