import random
import string
import hashlib
import logging
from telegram import Bot
from telegram.error import TelegramError
from bot.config import BOT_TOKEN, CHANNEL_ID

logger = logging.getLogger(__name__)

def generate_activation_code(length=12):
    """Generate a random alphanumeric activation code."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

def generate_transaction_id():
    """Generate a unique transaction ID."""
    chars = string.ascii_uppercase + string.digits
    return 'TXN-' + ''.join(random.choices(chars, k=16))

def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == hashed

async def generate_invite_link() -> str:
    """Generate a single-use invite link to the private channel."""
    bot = Bot(token=BOT_TOKEN)
    link = await bot.create_chat_invite_link(
        chat_id=CHANNEL_ID,
        member_limit=1,
        expire_date=None
    )
    return link.invite_link

async def revoke_user_from_channel(telegram_id: int):
    """Remove a user from the private channel and allow future rejoin."""
    bot = Bot(token=BOT_TOKEN)

    logger.info(f"Attempting to revoke user {telegram_id} from channel {CHANNEL_ID}")

    # Step 1 — Ban the user (kicks them from channel)
    try:
        await bot.ban_chat_member(
            chat_id=CHANNEL_ID,
            user_id=telegram_id,
            revoke_messages=False  # Keep their messages, just remove access
        )
        logger.info(f"Successfully banned user {telegram_id} from channel")
    except TelegramError as e:
        logger.error(f"Failed to ban user {telegram_id}: {e}")
        return

    # Step 2 — Unban so they can rejoin if they resubscribe
    try:
        await bot.unban_chat_member(
            chat_id=CHANNEL_ID,
            user_id=telegram_id,
            only_if_banned=True
        )
        logger.info(f"Successfully unbanned user {telegram_id} — they can rejoin if they resubscribe")
    except TelegramError as e:
        logger.error(f"Failed to unban user {telegram_id}: {e}")
