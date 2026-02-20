import random
import string
import hashlib
from telegram import Bot
from bot.config import BOT_TOKEN, CHANNEL_ID

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
    bot = Bot(token=BOT_TOKEN)
    link = await bot.create_chat_invite_link(chat_id=CHANNEL_ID, member_limit=1)
    return link.invite_link

async def revoke_user_from_channel(telegram_id: int):
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id)
        await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id)
    except Exception as e:
        print(f"Error revoking user {telegram_id}: {e}")
