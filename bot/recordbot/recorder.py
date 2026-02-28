import asyncio
import logging
import os
import signal
import subprocess
import sys
import time

try:
    import requests
except ImportError:
    requests = None

try:
    from curl_cffi import requests as cf_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import InputPeerUser
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

from bot.recordbot.database import (
    get_all_monitored_models, get_remaining_credits,
    deduct_credits, start_recording_entry, end_recording_entry,
    get_all_active_recordings
)

logger = logging.getLogger("RecordBot.Recorder")

TG_API_ID = int(os.environ.get("TG_API_ID", "0"))
TG_API_HASH = os.environ.get("TG_API_HASH", "")
TG_SESSION = os.environ.get("TG_SESSION", "")
_tg_dest_raw = os.environ.get("RECORDBOT_TG_DEST", os.environ.get("TG_DEST", "me"))
try:
    TG_DEST = int(_tg_dest_raw)
except ValueError:
    TG_DEST = _tg_dest_raw

SEGMENT_MAX_BYTES = int(os.environ.get("SEGMENT_MAX_BYTES", str(500 * 1024 * 1024)))
SIZE_CHECK_SECS = 5
VIDEOS_DIR = os.environ.get("VIDEOS_DIR", "/tmp/recordings")
YOUTUBE_DL_CMD = os.environ.get("YOUTUBE_DL_CMD", "yt-dlp")
FFMPEG_CMD = os.environ.get("FFMPEG_CMD", "ffmpeg")
RATE_LIMIT_TIME = 5
POLL_INTERVAL = 60
CREDIT_CHECK_INTERVAL = 30

os.makedirs(VIDEOS_DIR, exist_ok=True)

_IMPERSONATE_TARGETS = ["chrome131", "chrome124", "chrome120", "chrome116", "chrome110"]


class UserRecording:
    def __init__(self, user_telegram_id, model_name, out_dir, ffmpeg_proc, 
