import logging
from telegram import Update
from telegram.ext import (Application, CommandHandler,
                           CallbackQueryHandler, MessageHandler, filters,
                           ContextTypes, ConversationHandler)

from bot.config import BOT_TOKEN
from bot.database import init_db
from bot.handlers.start import start, back_to_menu, main_menu_keyboard
from bot.handlers.subscribe import subscribe_conv
from bot.handlers.activation import activation_conv
from bot.handlers.login import login_conv, setup_credentials_conv
from bot.handlers.video_list import video_list_handler
from bot.handlers.help import help_conv

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any active conversation and return to main menu."""
    context.user_data.clear()
    await update.message.reply_text(
        "✅ Action cancelled. Use /start to return to the main menu.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

def main():
    init_db()
    logger.info("Database initialized")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(subscribe_conv)
    app.add_handler(activation_conv)
    app.add_handler(login_conv)
    app.add_handler(setup_credentials_conv)
    app.add_handler(help_conv)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(video_list_handler, pattern="^video_list$"))

    logger.info("Bot started — polling...")
    app.run_polling(
        drop_pending_updates=True,
        poll_interval=0.5,
        timeout=10,
        connect_timeout=10,
        read_timeout=10,
        write_timeout=10
    )

if __name__ == "__main__":
    main()
