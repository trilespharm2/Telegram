import random
import string
import hashlib
import asyncio
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
        member_limit=1,   # Single use — cannot be shared or reused
        expire_date=None
    )
    return link.invite_link

async def revoke_user_from_channel(telegram_id: int):
    """
    Ban user from channel. Does NOT unban — user stays blocked
    until they resubscribe and activate a new access code.
    """
    bot = Bot(token=BOT_TOKEN)
    try:
        logger.info(f"Revoking user {telegram_id} from channel {CHANNEL_ID}")
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id)
        logger.info(f"Successfully banned user {telegram_id} — they cannot rejoin until resubscribed")
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
        await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id,
                                    only_if_banned=True)
        logger.info(f"Successfully unbanned user {telegram_id} — can now rejoin with new invite link")
    except TelegramError as e:
        logger.error(f"Failed to unban user {telegram_id}: {e}")
