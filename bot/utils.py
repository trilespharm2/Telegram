import random
import string
import hashlib
import logging
from telegram import Bot
from telegram.error import TelegramError
from bot.config import BOT_TOKEN, CHANNEL_ID

logger = logging.getLogger(__name__)

def generate_activation_code(length=12):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

def generate_transaction_id():
    chars = string.ascii_uppercase + string.digits
    return 'TXN-' + ''.join(random.choices(chars, k=16))

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

async def generate_invite_link() -> str:
    """Generate a single-use invite link to the private channel."""
    bot = Bot(token=BOT_TOKEN)
    link = await bot.create_chat_invite_link(
        chat_id=CHANNEL_ID,
        member_limit=1,   # Single use only
        expire_date=None
    )
    return link.invite_link

async def generate_and_store_invite_link(telegram_id: int) -> str:
    """
    Generate a single-use invite link AND store it in DB linked to telegram_id.
    This allows us to revoke it later if user cancels before clicking.
    """
    from bot.database import get_conn
    bot = Bot(token=BOT_TOKEN)
    link_obj = await bot.create_chat_invite_link(
        chat_id=CHANNEL_ID,
        member_limit=1,
        expire_date=None
    )
    invite_link = link_obj.invite_link

    # Store the invite link against this telegram_id
    conn = get_conn()
    conn.execute(
        "UPDATE subscribers SET invite_link = ? WHERE telegram_id = ?",
        (invite_link, telegram_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"Generated and stored invite link for telegram_id={telegram_id}")
    return invite_link

async def revoke_user_from_channel(telegram_id: int):
    """
    Ban user from channel AND revoke their stored invite link.
    User stays banned until they resubscribe and activate a new code.
    """
    from bot.database import get_conn
    bot = Bot(token=BOT_TOKEN)

    # Revoke stored invite link so it cannot be forwarded to others
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT invite_link FROM subscribers WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        conn.close()

        if row and row["invite_link"]:
            await bot.revoke_chat_invite_link(
                chat_id=CHANNEL_ID,
                invite_link=row["invite_link"]
            )
            logger.info(f"Revoked invite link for telegram_id={telegram_id}")
    except TelegramError as e:
        logger.warning(f"Could not revoke invite link for {telegram_id}: {e}")

    # Ban the user from the channel
    try:
        logger.info(f"Banning user {telegram_id} from channel {CHANNEL_ID}")
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id)
        logger.info(f"Banned user {telegram_id} — cannot rejoin until resubscribed")
    except TelegramError as e:
        logger.error(f"Failed to ban user {telegram_id}: {e}")

async def unban_user_for_channel(telegram_id: int):
    """
    Unban user so they can rejoin the channel.
    Called only when a user successfully activates a new subscription.
    """
    bot = Bot(token=BOT_TOKEN)
    try:
        logger.info(f"Unbanning user {telegram_id} for channel {CHANNEL_ID}")
        await bot.unban_chat_member(
            chat_id=CHANNEL_ID,
            user_id=telegram_id,
            only_if_banned=True
        )
        logger.info(f"Unbanned user {telegram_id} — can now rejoin with new invite link")
    except TelegramError as e:
        logger.error(f"Failed to unban user {telegram_id}: {e}")
