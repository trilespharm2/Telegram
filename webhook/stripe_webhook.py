import stripe
import asyncio
from flask import Flask, request, jsonify
from telegram import Bot
from bot.config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, BOT_TOKEN, ADMIN_ID
from bot.database import store_activation_code, create_subscriber, deactivate_subscriber
from bot.utils import generate_activation_code, generate_transaction_id, generate_invite_link
from bot.email_service import send_activation_email

stripe.api_key = STRIPE_SECRET_KEY
app = Flask(__name__)

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
    elif event["type"] == "customer.subscription.deleted":
        asyncio.run(handle_subscription_cancelled(event["data"]["object"]))
    elif event["type"] == "invoice.payment_failed":
        asyncio.run(handle_payment_failed(event["data"]["object"]))
    return jsonify({"status": "ok"}), 200

async def handle_payment_success(session):
    telegram_id_str = session.get("metadata", {}).get("telegram_id")
    email = session.get("customer_email") or session.get("metadata", {}).get("email")
    if not telegram_id_str or not email:
        return
    telegram_id = int(telegram_id_str)
    activation_code = generate_activation_code()
    transaction_id = session.get("payment_intent") or generate_transaction_id()
    invite_link = await generate_invite_link()
    store_activation_code(activation_code, transaction_id, email)
    create_subscriber(telegram_id=telegram_id, email=email, activation_code=activation_code,
                       transaction_id=transaction_id,
                       stripe_customer_id=session.get("customer") or "",
                       stripe_subscription_id=session.get("subscription") or "")
    send_activation_email(email, activation_code, transaction_id, invite_link)
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=f"🎉 *Payment Confirmed!*\n\n"
                 f"🔑 Activation Code: `{activation_code}`\n"
                 f"🧾 Transaction ID: `{transaction_id}`\n\n"
                 f"📺 [Join Private Channel]({invite_link})\n\n"
                 f"_Details also sent to {email}_",
            parse_mode="Markdown")
    except Exception as e:
        print(f"Telegram message error: {e}")

async def handle_subscription_cancelled(subscription):
    from bot.database import get_conn
    conn = get_conn()
    row = conn.execute("SELECT * FROM subscribers WHERE stripe_subscription_id = ?",
                        (subscription.get("id"),)).fetchone()
    conn.close()
    if row:
        from bot.utils import revoke_user_from_channel
        deactivate_subscriber(row["telegram_id"])
        await revoke_user_from_channel(row["telegram_id"])
        bot = Bot(token=BOT_TOKEN)
        try:
            await bot.send_message(chat_id=row["telegram_id"],
                                    text="⚠️ *Subscription ended.* Use /start to resubscribe.",
                                    parse_mode="Markdown")
        except Exception as e:
            print(f"Error: {e}")

async def handle_payment_failed(invoice):
    from bot.database import get_conn
    conn = get_conn()
    row = conn.execute("SELECT * FROM subscribers WHERE stripe_customer_id = ?",
                        (invoice.get("customer"),)).fetchone()
    conn.close()
    if row:
        bot = Bot(token=BOT_TOKEN)
        try:
            await bot.send_message(chat_id=row["telegram_id"],
                                    text="⚠️ *Payment failed.* Please update your payment method.\nUse /start → Subscribe.",
                                    parse_mode="Markdown")
        except Exception as e:
            print(f"Error: {e}")

@app.route("/success")
def payment_success():
    return "<h2>✅ Payment successful! Check Telegram for your access details.</h2>", 200

@app.route("/cancel")
def payment_cancel():
    return "<h2>❌ Payment cancelled. Return to Telegram and try again.</h2>", 200

@app.route("/health")
def health():
    return jsonify({"status": "running"}), 200
