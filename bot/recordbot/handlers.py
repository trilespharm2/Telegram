import os
import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, MessageHandler,
    filters, CallbackQueryHandler, CommandHandler,
)

from bot.config import STRIPE_SECRET_KEY, WEBHOOK_URL
from bot.utils import generate_activation_code, hash_password, verify_password
from bot.recordbot.config import RECORDBOT_PLANS, RECORDBOT_CHANNEL_ID, get_price_id
from bot.recordbot.database import (
    get_rb_user, get_rb_user_by_username, get_rb_user_by_code,
    create_rb_user, update_rb_credentials, add_model, remove_model,
    get_user_models, get_remaining_credits, get_rb_activation_code,
    mark_rb_code_used, add_credits, get_conn,
)
from bot.recordbot.recorder import (
    get_user_active_recordings, stop_user_recording, recording_key,
    active_recordings,
)

stripe.api_key = STRIPE_SECRET_KEY

(
    RB_MENU,
    RB_ASK_PLAN,
    RB_ASK_EMAIL,
    RB_ENTER_CODE,
    RB_LOGIN_USERNAME,
    RB_LOGIN_PASSWORD,
    RB_CREATE_USERNAME,
    RB_CREATE_PASSWORD,
    RB_CREATE_CONFIRM_PASSWORD,
    RB_HOME,
    RB_ADD_MODEL_NAME,
) = range(11)

BACK_MENU = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
BACK_RB = [[InlineKeyboardButton("🔙 Back", callback_data="rb_home")]]


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled. Use /start to return to the menu.")
    return ConversationHandler.END


def rb_home_keyboard():
    buttons = [
        [InlineKeyboardButton("➕ Add Model", callback_data="rb_add_model")],
        [InlineKeyboardButton("📋 Model List", callback_data="rb_model_list")],
        [InlineKeyboardButton("🔴 Currently Recording", callback_data="rb_recording")],
    ]
    if RECORDBOT_CHANNEL_ID:
        try:
            channel_id = int(RECORDBOT_CHANNEL_ID)
            buttons.append([InlineKeyboardButton(
                "🎬 View Recordings",
                url=f"tg://user?id={channel_id}",
            )])
        except ValueError:
            buttons.append([InlineKeyboardButton(
                "🎬 View Recordings",
                url=f"https://t.me/{RECORDBOT_CHANNEL_ID}",
            )])
    buttons.append([InlineKeyboardButton("💰 Total Credits", callback_data="rb_credits")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)


async def recordbot_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💳 Subscribe to RecordBot", callback_data="rb_subscribe")],
        [InlineKeyboardButton("🔑 Enter Activation Code", callback_data="rb_activation")],
        [InlineKeyboardButton("🔐 Login", callback_data="rb_login")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    await query.edit_message_text(
        "📹 *RecordBot*\n\n"
        "Record your favorite models automatically.\n"
        "Select an option below:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return RB_MENU


async def rb_subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("⏱ 2 Hours — $5", callback_data="rb_plan_2h")],
        [InlineKeyboardButton("⏱ 5 Hours — $10", callback_data="rb_plan_5h")],
        [InlineKeyboardButton("⏱ 20 Hours — $20", callback_data="rb_plan_20h")],
        [InlineKeyboardButton("🔙 Back", callback_data="rb_back_menu")],
    ]
    await query.edit_message_text(
        "💳 *RecordBot — Choose a Plan*\n\n"
        "Select your recording credit package:\n\n"
        "⏱ *2 Hours — $5*\n"
        "⏱ *5 Hours — $10*\n"
        "⏱ *20 Hours — $20*\n\n"
        "_Credits are used while models are being recorded._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return RB_ASK_PLAN


async def rb_plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plan_key = query.data
    plan = RECORDBOT_PLANS.get(plan_key)
    if not plan:
        await query.edit_message_text("⚠️ Invalid plan.", reply_markup=InlineKeyboardMarkup(BACK_MENU))
        return ConversationHandler.END

    context.user_data["rb_plan"] = plan_key
    context.user_data["rb_plan_label"] = plan["label"]

    await query.edit_message_text(
        f"✅ *Plan selected:* {plan['label']}\n\n"
        "Please enter your email address:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_ASK_EMAIL


async def rb_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()

    if "@" not in email or "." not in email:
        await update.message.reply_text(
            "⚠️ Please enter a valid email address:",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return RB_ASK_EMAIL

    plan_key = context.user_data.get("rb_plan")
    if not plan_key:
        await update.message.reply_text(
            "⚠️ No plan selected. Please start over.",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return ConversationHandler.END

    plan = RECORDBOT_PLANS.get(plan_key)
    if not plan:
        await update.message.reply_text(
            "⚠️ Invalid plan. Please start over.",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return ConversationHandler.END

    plan_label = context.user_data.get("rb_plan_label", plan["label"])
    telegram_id = update.effective_user.id

    price_id = get_price_id(plan_key)
    if not price_id:
        await update.message.reply_text(
            "⚠️ This plan is not yet configured. Please contact support.",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return ConversationHandler.END

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=email,
            metadata={
                "telegram_id": str(telegram_id),
                "email": email,
                "plan": plan_key,
                "service": "recordbot",
                "credit_hours": str(plan["hours"]),
            },
            success_url=f"{WEBHOOK_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{WEBHOOK_URL}/cancel",
        )

        keyboard = [
            [InlineKeyboardButton("💳 Pay Now", url=session.url)],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
        ]
        await update.message.reply_text(
            f"✅ *Almost there!*\n\n"
            f"Plan: *{plan_label}*\n\n"
            f"Click below to complete your payment.\n\n"
            f"After payment, your *activation code* will be sent to:\n"
            f"`{email}` and here in Telegram.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        print(f"Stripe error (RecordBot): {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong. Please try again later.",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )

    return ConversationHandler.END


async def rb_activation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *RecordBot — Enter Activation Code*\n\n"
        "Please type your activation code below:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_ENTER_CODE


async def rb_activation_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    telegram_id = update.effective_user.id

    record = get_rb_activation_code(code)
    if not record:
        await update.message.reply_text(
            "❌ *Invalid activation code.*\n\n"
            "Please check and try again.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return RB_ENTER_CODE

    if record["used"]:
        existing = get_rb_user_by_code(code)
        if existing and existing["telegram_id"] == telegram_id:
            context.user_data["rb_telegram_id"] = telegram_id
            await update.message.reply_text(
                "✅ *Welcome back!*\n\nYou already have an account.",
                parse_mode="Markdown",
                reply_markup=rb_home_keyboard(),
            )
            return RB_HOME

        await update.message.reply_text(
            "⚠️ *This code has already been used.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return ConversationHandler.END

    credit_hours = record["credit_hours"]
    email = record["email"]

    create_rb_user(telegram_id, email, code, "", credit_hours)
    mark_rb_code_used(code, telegram_id)

    user = get_rb_user(telegram_id)
    if user and user["username"]:
        context.user_data["rb_telegram_id"] = telegram_id
        await update.message.reply_text(
            f"✅ *Credits added!*\n\n"
            f"Added *{credit_hours} hours* to your account.\n\n"
            f"Welcome back to RecordBot!",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
        return RB_HOME

    context.user_data["rb_telegram_id"] = telegram_id
    await update.message.reply_text(
        f"✅ *Activation successful!*\n\n"
        f"You have *{credit_hours} hours* of recording credit.\n\n"
        "Please create a username (min 3 characters):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_CREATE_USERNAME


async def rb_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔐 *RecordBot — Login*\n\nPlease enter your username:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_LOGIN_USERNAME


async def rb_login_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rb_login_username"] = update.message.text.strip()
    await update.message.reply_text(
        "Now enter your password:",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_LOGIN_PASSWORD


async def rb_login_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    username = context.user_data.get("rb_login_username")

    user = get_rb_user_by_username(username)

    if not user or not verify_password(password, user["password_hash"] or ""):
        await update.message.reply_text(
            "❌ *Invalid username or password.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return ConversationHandler.END

    if not user["is_active"]:
        keyboard = [
            [InlineKeyboardButton("💳 Subscribe", callback_data="recordbot")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
        ]
        await update.message.reply_text(
            "⚠️ *Your account is not active.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    context.user_data["rb_telegram_id"] = user["telegram_id"]
    await update.message.reply_text(
        "✅ *Login successful!*\n\nWelcome to RecordBot.",
        parse_mode="Markdown",
        reply_markup=rb_home_keyboard(),
    )
    return RB_HOME


async def rb_create_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if len(username) < 3:
        await update.message.reply_text(
            "⚠️ Username must be at least 3 characters. Try again:",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return RB_CREATE_USERNAME

    existing = get_rb_user_by_username(username)
    if existing:
        await update.message.reply_text(
            "⚠️ That username is taken. Please choose a different one:",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return RB_CREATE_USERNAME

    context.user_data["rb_new_username"] = username
    await update.message.reply_text(
        "Now create a password (min 6 characters):",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_CREATE_PASSWORD


async def rb_create_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text(
            "⚠️ Password must be at least 6 characters. Try again:",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return RB_CREATE_PASSWORD

    context.user_data["rb_new_password"] = password
    await update.message.reply_text(
        "Confirm your password:",
        reply_markup=InlineKeyboardMarkup(BACK_MENU),
    )
    return RB_CREATE_CONFIRM_PASSWORD


async def rb_confirm_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirm = update.message.text.strip()
    if confirm != context.user_data.get("rb_new_password"):
        await update.message.reply_text(
            "⚠️ Passwords don't match. Please enter your password again:",
            reply_markup=InlineKeyboardMarkup(BACK_MENU),
        )
        return RB_CREATE_PASSWORD

    telegram_id = context.user_data["rb_telegram_id"]
    username = context.user_data["rb_new_username"]
    password_hash = hash_password(context.user_data["rb_new_password"])

    update_rb_credentials(telegram_id, username, password_hash)

    await update.message.reply_text(
        f"✅ *Account created!*\n\n"
        f"Username: `{username}`\n\n"
        f"Welcome to RecordBot!",
        parse_mode="Markdown",
        reply_markup=rb_home_keyboard(),
    )
    return RB_HOME


async def rb_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = context.user_data.get("rb_telegram_id")
    if not telegram_id:
        user = get_rb_user(update.effective_user.id)
        if user:
            telegram_id = user["telegram_id"]
            context.user_data["rb_telegram_id"] = telegram_id
        else:
            await query.edit_message_text(
                "⚠️ Please login or activate first.",
                reply_markup=InlineKeyboardMarkup(BACK_MENU),
            )
            return ConversationHandler.END

    await query.edit_message_text(
        "📹 *RecordBot Home*\n\nSelect an option:",
        parse_mode="Markdown",
        reply_markup=rb_home_keyboard(),
    )
    return RB_HOME


async def rb_add_model_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "➕ *Add Model*\n\n"
        "Enter the Chaturbate username of the model to record:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(BACK_RB),
    )
    return RB_ADD_MODEL_NAME


async def rb_add_model_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = context.user_data.get("rb_telegram_id", update.effective_user.id)
    model_name = update.message.text.strip().lower()

    if not model_name:
        await update.message.reply_text(
            "⚠️ Please enter a valid username.",
            reply_markup=InlineKeyboardMarkup(BACK_RB),
        )
        return RB_ADD_MODEL_NAME

    added = add_model(telegram_id, model_name)
    if added:
        await update.message.reply_text(
            f"✅ `{model_name}` added to your model list.\n\n"
            f"Recording will start automatically when they go live.",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
    else:
        await update.message.reply_text(
            f"`{model_name}` is already in your list.",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
    return RB_HOME


async def rb_model_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = context.user_data.get("rb_telegram_id", update.effective_user.id)
    models = get_user_models(telegram_id)

    if not models:
        await query.edit_message_text(
            "📋 *Model List*\n\nNo models added yet.\n\n"
            "Use *Add Model* to start monitoring.",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
        return RB_HOME

    lines = ["📋 *Model List*\n"]
    buttons = []
    for m in models:
        name = m["model_name"]
        key = recording_key(telegram_id, name)
        status = "🔴 recording" if key in active_recordings else "⚫ idle"
        lines.append(f"• `{name}` — {status}")
        buttons.append([InlineKeyboardButton(f"❌ Remove {name}", callback_data=f"rb_remove:{name}")])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="rb_home")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return RB_HOME


async def rb_remove_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = context.user_data.get("rb_telegram_id", update.effective_user.id)
    model_name = query.data.replace("rb_remove:", "")

    key = recording_key(telegram_id, model_name)
    if key in active_recordings:
        stop_user_recording(active_recordings[key], reason="model removed")

    remove_model(telegram_id, model_name)

    await query.edit_message_text(
        f"✅ `{model_name}` removed from your list.",
        parse_mode="Markdown",
        reply_markup=rb_home_keyboard(),
    )
    return RB_HOME


async def rb_currently_recording(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = context.user_data.get("rb_telegram_id", update.effective_user.id)
    recs = get_user_active_recordings(telegram_id)

    if not recs:
        await query.edit_message_text(
            "🔴 *Currently Recording*\n\nNothing recording right now.",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
        return RB_HOME

    buttons = []
    for rec in recs:
        buttons.append([InlineKeyboardButton(
            f"🔴 {rec.model_name} · {rec.duration_str()}",
            callback_data=f"rb_stop:{rec.model_name}",
        )])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="rb_home")])

    await query.edit_message_text(
        "🔴 *Currently Recording*\n\nTap to stop a recording:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return RB_HOME


async def rb_stop_recording(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = context.user_data.get("rb_telegram_id", update.effective_user.id)
    model_name = query.data.replace("rb_stop:", "")

    key = recording_key(telegram_id, model_name)
    if key in active_recordings:
        stop_user_recording(active_recordings[key], reason="user request")
        await query.edit_message_text(
            f"⏹ *{model_name}* — stop signal sent.\n\n"
            f"Recording will finalize and upload automatically.",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
    else:
        await query.edit_message_text(
            f"`{model_name}` is not currently recording.",
            parse_mode="Markdown",
            reply_markup=rb_home_keyboard(),
        )
    return RB_HOME


async def rb_total_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = context.user_data.get("rb_telegram_id", update.effective_user.id)
    credits_seconds = get_remaining_credits(telegram_id)

    hours = int(credits_seconds // 3600)
    minutes = int((credits_seconds % 3600) // 60)

    await query.edit_message_text(
        f"💰 *Total Credits*\n\n"
        f"Remaining: *{hours}h {minutes}m*\n\n"
        f"_Credits are consumed while models are being recorded._",
        parse_mode="Markdown",
        reply_markup=rb_home_keyboard(),
    )
    return RB_HOME


async def rb_back_to_menu_from_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from bot.handlers.start import back_to_menu
    await back_to_menu(update, context)
    return ConversationHandler.END


async def rb_back_to_rb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💳 Subscribe to RecordBot", callback_data="rb_subscribe")],
        [InlineKeyboardButton("🔑 Enter Activation Code", callback_data="rb_activation")],
        [InlineKeyboardButton("🔐 Login", callback_data="rb_login")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    await query.edit_message_text(
        "📹 *RecordBot*\n\nSelect an option:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return RB_MENU


recordbot_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(recordbot_menu, pattern="^recordbot$")],
    states={
        RB_MENU: [
            CallbackQueryHandler(rb_subscribe_start, pattern="^rb_subscribe$"),
            CallbackQueryHandler(rb_activation_start, pattern="^rb_activation$"),
            CallbackQueryHandler(rb_login_start, pattern="^rb_login$"),
            CallbackQueryHandler(rb_back_to_menu_from_conv, pattern="^back_to_menu$"),
        ],
        RB_ASK_PLAN: [
            CallbackQueryHandler(rb_plan_selected, pattern="^rb_plan_"),
            CallbackQueryHandler(rb_back_to_rb_menu, pattern="^rb_back_menu$"),
        ],
        RB_ASK_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_get_email),
        ],
        RB_ENTER_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_activation_check),
        ],
        RB_LOGIN_USERNAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_login_get_username),
        ],
        RB_LOGIN_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_login_get_password),
        ],
        RB_CREATE_USERNAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_create_username),
        ],
        RB_CREATE_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_create_password),
        ],
        RB_CREATE_CONFIRM_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_confirm_password),
        ],
        RB_HOME: [
            CallbackQueryHandler(rb_add_model_start, pattern="^rb_add_model$"),
            CallbackQueryHandler(rb_model_list, pattern="^rb_model_list$"),
            CallbackQueryHandler(rb_currently_recording, pattern="^rb_recording$"),
            CallbackQueryHandler(rb_total_credits, pattern="^rb_credits$"),
            CallbackQueryHandler(rb_home, pattern="^rb_home$"),
            CallbackQueryHandler(rb_remove_model, pattern="^rb_remove:"),
            CallbackQueryHandler(rb_stop_recording, pattern="^rb_stop:"),
            CallbackQueryHandler(rb_back_to_menu_from_conv, pattern="^back_to_menu$"),
        ],
        RB_ADD_MODEL_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rb_add_model_name),
            CallbackQueryHandler(rb_home, pattern="^rb_home$"),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(rb_back_to_menu_from_conv, pattern="^back_to_menu$"),
        CommandHandler("cancel", cancel_cmd),
        CommandHandler("start", cancel_cmd),
    ],
    per_message=False,
)
