from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                           MessageHandler, filters, CallbackQueryHandler)
from bot.database import (get_activation_code_record, mark_code_used,
                           create_subscriber, is_active_subscriber)
from bot.utils import generate_invite_link
from bot.handlers.start import back_to_menu

ENTER_CODE = 1

async def activation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔑 *Enter Activation Code*\n\nPlease type your activation code:",
                                   parse_mode="Markdown")
    return ENTER_CODE

async def activation_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    telegram_id = update.effective_user.id

    if is_active_subscriber(telegram_id):
        invite_link = await generate_invite_link()
        keyboard = [[InlineKeyboardButton("📺 Join Channel", url=invite_link)],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await update.message.reply_text("✅ *Active subscription found!*\n\nHere's your channel link:",
                                         parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    record = get_activation_code_record(code)
    if not record:
        await update.message.reply_text("❌ *Invalid activation code.* Please try again:",
                                         parse_mode="Markdown")
        return ENTER_CODE

    if record["used"]:
        await update.message.reply_text(
            "⚠️ *This code has already been used.*\n\nGo to Help → Didn't receive activation code.",
            parse_mode="Markdown")
        return ConversationHandler.END

    invite_link = await generate_invite_link()
    create_subscriber(telegram_id=telegram_id, email=record["email"], activation_code=code,
                       transaction_id=record["transaction_id"], stripe_customer_id="",
                       stripe_subscription_id="")
    mark_code_used(code, telegram_id)

    keyboard = [[InlineKeyboardButton("📺 Join Private Channel", url=invite_link)],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    await update.message.reply_text(
        "🎉 *Access Granted!*\n\nWelcome! Click below to join the channel.\n\n"
        "_You may optionally set up login credentials from the menu for faster future access._",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

activation_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(activation_start, pattern="^activation_code$")],
    states={ENTER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activation_check)]},
    fallbacks=[CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$")],
    per_message=False
)
