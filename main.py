import logging
from telegram import Update
from telegram.ext import (Application, CommandHandler, ChatMemberHandler, CallbackQueryHandler,
                           MessageHandler, ChatMemberHandler, filters,
                           ContextTypes, ConversationHandler)

from bot.config import BOT_TOKEN, ADMIN_ID
from bot.database import init_db
from bot.handlers.start import start, back_to_menu, main_menu_keyboard
from bot.handlers.subscribe import subscribe_conv
from bot.handlers.activation import activation_conv
from bot.handlers.login import login_conv, setup_credentials_conv
from bot.handlers.video_list import video_list_handler
from bot.handlers.admin import (subscribers_cmd, stats_cmd, members_cmd,
                                    kick_cmd, audit_cmd, track_channel_member)
from bot.handlers.help import help_conv
from bot.handlers.channel_guard import guard_channel_join

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "✅ Action cancelled.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

async def capture_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: send a video to the bot to get its file_id."""
    if update.effective_user.id != ADMIN_ID:
        return
    if update.message.video:
        file_id = update.message.video.file_id
        print(f"VIDEO FILE_ID: {file_id}")
        await update.message.reply_text(
            f"✅ *Video file_id captured:*\n\n`{file_id}`\n\n"
            "Copy this and paste it as `VIDEO_FILE_ID` in `video_list.py`",
            parse_mode="Markdown"
        )

def main():
    init_db()
    logger.info("Database initialized")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(10)
        .get_updates_write_timeout(10)
        .build()
    )

    # ── Conversation handlers ────────────────────────────────────────
    app.add_handler(subscribe_conv)
    app.add_handler(activation_conv)
    app.add_handler(login_conv)
    app.add_handler(setup_credentials_conv)
    app.add_handler(help_conv)

    # ── Command handlers ─────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))

    # ── Callback handlers ────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(video_list_handler, pattern="^video_list$"))

    # ── Channel guard — ban non-subscribers who join via forwarded links
    app.add_handler(ChatMemberHandler(guard_channel_join, ChatMemberHandler.CHAT_MEMBER))

    # ── Admin: capture video file_id ─────────────────────────────────
    app.add_handler(MessageHandler(filters.VIDEO & filters.User(ADMIN_ID), capture_file_id))

    logger.info("Bot started — polling...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,  # Required to receive chat_member updates
        drop_pending_updates=True,
        poll_interval=0.5
    )

if __name__ == "__main__":
    main()
