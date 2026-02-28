import asyncio
import logging
import os
import signal
import subprocess
import sys
import time

import requests
try:
    from curl_cffi import requests as cf_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerUser

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
    def __init__(self, user_telegram_id, model_name, out_dir, ffmpeg_proc, current_file, db_rec_id):
        self.user_telegram_id = user_telegram_id
        self.model_name = model_name
        self.out_dir = out_dir
        self.ffmpeg_proc = ffmpeg_proc
        self.current_file = current_file
        self.db_rec_id = db_rec_id
        self.start_time = time.time()
        self.stopping = False
        self.segment_count = 0
        self.upload_tasks = []
        self.watcher_task = None
        self.last_credit_deduct = time.time()

    def duration_str(self):
        elapsed = int(time.time() - self.start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    def elapsed_seconds(self):
        return time.time() - self.start_time


active_recordings = {}
_ptb_bot = None
_upload_client = None
_upload_client_lock = asyncio.Lock()


def _telethon_client():
    return TelegramClient(StringSession(TG_SESSION), TG_API_ID, TG_API_HASH)


async def _get_upload_client():
    global _upload_client
    async with _upload_client_lock:
        if _upload_client is None or not _upload_client.is_connected():
            _upload_client = _telethon_client()
            await _upload_client.connect()
        return _upload_client


async def _resolve_dest(client):
    try:
        return await client.get_input_entity(TG_DEST)
    except ValueError:
        pass
    try:
        await client.get_dialogs()
        return await client.get_input_entity(TG_DEST)
    except ValueError:
        pass
    if isinstance(TG_DEST, int):
        return InputPeerUser(TG_DEST, 0)
    raise ValueError(f"Cannot resolve TG_DEST: {TG_DEST}")


async def tg_notify(text, chat_id=None):
    if _ptb_bot:
        try:
            target = chat_id or TG_DEST
            await _ptb_bot.send_message(
                chat_id=target,
                text=text,
                parse_mode="Markdown",
            )
            return
        except Exception as e:
            logger.warning(f"PTB notify failed: {e}")


async def tg_upload(filepath, caption, dest_chat_id=None):
    size_mb = os.path.getsize(filepath) / 1024 ** 2
    logger.info(f"Uploading: {os.path.basename(filepath)} ({size_mb:.0f} MB)")

    if dest_chat_id and _ptb_bot:
        try:
            with open(filepath, "rb") as f:
                await _ptb_bot.send_video(
                    chat_id=dest_chat_id,
                    video=f,
                    caption=caption,
                    parse_mode="Markdown",
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=60,
                )
            logger.info(f"Upload complete via PTB to {dest_chat_id}: {os.path.basename(filepath)}")
            return True
        except Exception as e:
            logger.warning(f"PTB upload failed, trying Telethon: {e}")

    last_logged = [0]

    def progress(sent, total):
        pct = sent / total * 100
        if pct - last_logged[0] >= 10 or pct >= 100:
            last_logged[0] = pct
            logger.info(f"  ↑ {os.path.basename(filepath)}: {pct:.0f}%")

    try:
        client = await _get_upload_client()
        if dest_chat_id:
            dest = await client.get_input_entity(dest_chat_id)
        else:
            dest = await _resolve_dest(client)
        await client.send_file(
            dest, filepath, caption=caption,
            supports_streaming=True, progress_callback=progress,
        )
        logger.info(f"Upload complete: {os.path.basename(filepath)}")
        return True
    except Exception as e:
        logger.exception(f"Upload failed for {filepath}: {e}")
        global _upload_client
        _upload_client = None
        return False


def _is_online(username):
    if not CURL_CFFI_AVAILABLE:
        logger.error("curl_cffi not available")
        return None

    common_headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }

    for target in _IMPERSONATE_TARGETS:
        try:
            time.sleep(3)
            session = cf_requests.Session(impersonate=target)
            page_resp = session.get(
                f"https://chaturbate.com/{username}/",
                headers=common_headers, timeout=25,
            )
            if page_resp.status_code == 403:
                continue

            csrf_token = session.cookies.get("csrftoken", "")
            r = session.post(
                "https://chaturbate.com/get_edge_hls_url_ajax/",
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": csrf_token,
                    "Referer": f"https://chaturbate.com/{username}/",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Origin": "https://chaturbate.com",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                data={"room_slug": username, "bandwidth": "high"},
                timeout=25,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("room_status", "") == "public"
        except Exception:
            continue

    for target in _IMPERSONATE_TARGETS:
        try:
            time.sleep(3)
            session = cf_requests.Session(impersonate=target)
            r = session.get(
                f"https://chaturbate.com/api/chatvideocontext/{username}/",
                headers=common_headers, timeout=25,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("room_status", "") == "public"
        except Exception:
            continue

    return None


def _get_hls_url(username):
    try:
        result = subprocess.run(
            [YOUTUBE_DL_CMD, "--get-url", f"https://chaturbate.com/{username}/"],
            capture_output=True, text=True, timeout=45,
        )
        url = result.stdout.strip().split("\n")[0]
        if url.startswith("http"):
            return url
        return None
    except Exception as e:
        logger.exception(f"[{username}] yt-dlp error: {e}")
        return None


def recording_key(user_tid, model):
    return f"{user_tid}:{model}"


async def start_user_recording(user_telegram_id, model_name):
    loop = asyncio.get_event_loop()
    hls_url = await loop.run_in_executor(None, _get_hls_url, model_name)
    if not hls_url:
        return None

    out_dir = os.path.join(VIDEOS_DIR, str(user_telegram_id), model_name)
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "part_000.mp4")

    ffmpeg_cmd = [
        FFMPEG_CMD, "-hide_banner", "-loglevel", "error",
        "-i", hls_url, "-c", "copy", "-map", "0", out_file,
    ]

    try:
        proc = subprocess.Popen(ffmpeg_cmd, env=os.environ.copy())
    except Exception as e:
        logger.error(f"[{model_name}] Failed to start ffmpeg: {e}")
        return None

    db_rec_id = start_recording_entry(user_telegram_id, model_name)
    rec = UserRecording(user_telegram_id, model_name, out_dir, proc, out_file, db_rec_id)
    task = asyncio.create_task(user_size_watcher(rec))
    rec.watcher_task = task

    key = recording_key(user_telegram_id, model_name)
    active_recordings[key] = rec
    logger.info(f"[{model_name}] Recording started for user {user_telegram_id}")
    return rec


def stop_user_recording(rec, reason="stop"):
    rec.stopping = True
    if rec.ffmpeg_proc.poll() is None:
        logger.info(f"[{rec.model_name}] Sending SIGINT ({reason})")
        rec.ffmpeg_proc.send_signal(signal.SIGINT)


async def user_size_watcher(rec):
    logger.info(f"[{rec.model_name}] Size watcher started for user {rec.user_telegram_id}")

    while True:
        await asyncio.sleep(SIZE_CHECK_SECS)
        if rec.stopping:
            break

        remaining = get_remaining_credits(rec.user_telegram_id)
        if remaining <= 0:
            logger.info(f"[{rec.model_name}] User {rec.user_telegram_id} out of credits — stopping")
            await tg_notify(
                f"⚠️ *Recording stopped* for `{rec.model_name}` — you have no remaining credits.\n\n"
                f"Purchase more credits to continue recording.",
                chat_id=rec.user_telegram_id
            )
            rec.stopping = True
            break

        now = time.time()
        elapsed_since_deduct = now - rec.last_credit_deduct
        if elapsed_since_deduct >= CREDIT_CHECK_INTERVAL:
            deduct_credits(rec.user_telegram_id, elapsed_since_deduct)
            rec.last_credit_deduct = now

        filepath = rec.current_file
        if not filepath or not os.path.exists(filepath):
            if rec.ffmpeg_proc.poll() is not None:
                break
            continue

        try:
            size = os.path.getsize(filepath)
        except OSError:
            continue

        if size >= SEGMENT_MAX_BYTES and rec.ffmpeg_proc.poll() is None:
            logger.info(f"[{rec.model_name}] File reached {size // 1024 // 1024} MB — rotating")

            loop = asyncio.get_event_loop()
            hls_url = await loop.run_in_executor(None, _get_hls_url, rec.model_name)
            if not hls_url:
                break

            rec.segment_count += 1
            new_file = os.path.join(rec.out_dir, f"part_{rec.segment_count:03d}.mp4")

            ffmpeg_cmd = [
                FFMPEG_CMD, "-hide_banner", "-loglevel", "error",
                "-i", hls_url, "-c", "copy", "-map", "0", new_file,
            ]
            try:
                new_proc = subprocess.Popen(ffmpeg_cmd, env=os.environ.copy())
            except Exception:
                break

            old_proc = rec.ffmpeg_proc
            old_file = filepath
            rec.ffmpeg_proc = new_proc
            rec.current_file = new_file

            old_proc.send_signal(signal.SIGINT)
            part_num = rec.segment_count
            task = asyncio.create_task(_finalize_and_upload(rec, old_proc, old_file, part_num))
            rec.upload_tasks.append(task)

            if rec.stopping:
                break

        if rec.ffmpeg_proc.poll() is not None:
            break

    elapsed = time.time() - rec.last_credit_deduct
    if elapsed > 0:
        deduct_credits(rec.user_telegram_id, elapsed)

    if rec.ffmpeg_proc.poll() is None:
        rec.ffmpeg_proc.send_signal(signal.SIGINT)
        for _ in range(15):
            if rec.ffmpeg_proc.poll() is not None:
                break
            await asyncio.sleep(1)

    if rec.current_file and os.path.exists(rec.current_file):
        size = os.path.getsize(rec.current_file)
        if size > 0:
            await _upload_and_delete(rec, rec.current_file, rec.segment_count + 1)

    if rec.upload_tasks:
        await asyncio.gather(*rec.upload_tasks, return_exceptions=True)

    total_duration = time.time() - rec.start_time
    end_recording_entry(rec.db_rec_id, total_duration)

    key = recording_key(rec.user_telegram_id, rec.model_name)
    active_recordings.pop(key, None)

    logger.info(f"[{rec.model_name}] Recording complete for user {rec.user_telegram_id}")
    await tg_notify(
        f"✅ *{rec.model_name}* — recording complete.",
        chat_id=rec.user_telegram_id
    )


async def _finalize_and_upload(rec, proc, filepath, part_num):
    for _ in range(30):
        if proc.poll() is not None:
            break
        await asyncio.sleep(1)
    else:
        proc.kill()

    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        await _upload_and_delete(rec, filepath, part_num)


async def _upload_and_delete(rec, filepath, part_num):
    size_mb = os.path.getsize(filepath) / 1024 ** 2
    caption = (
        f"🎬 *{rec.model_name}* — Part {part_num}\n"
        f"({size_mb:.0f} MB)"
    )
    ok = await tg_upload(filepath, caption, dest_chat_id=rec.user_telegram_id)
    if ok:
        try:
            os.remove(filepath)
        except Exception:
            pass
    else:
        await tg_notify(
            f"⚠️ Upload failed for *{rec.model_name}*: `{os.path.basename(filepath)}`",
            chat_id=rec.user_telegram_id
        )


def get_user_active_recordings(user_telegram_id):
    results = []
    for key, rec in active_recordings.items():
        if rec.user_telegram_id == user_telegram_id:
            results.append(rec)
    return results


async def recorder_loop():
    logger.info("RecordBot recorder loop started.")
    while True:
        try:
            done_keys = [
                key for key, rec in active_recordings.items()
                if rec.ffmpeg_proc.poll() is not None
                and rec.watcher_task is not None
                and rec.watcher_task.done()
            ]
            for key in done_keys:
                del active_recordings[key]

            monitored = get_all_monitored_models()

            models_by_user = {}
            for row in monitored:
                uid = row["user_telegram_id"]
                if uid not in models_by_user:
                    models_by_user[uid] = []
                models_by_user[uid].append(row["model_name"])

            for uid, models in models_by_user.items():
                credits = get_remaining_credits(uid)
                if credits <= 0:
                    continue

                for model in models:
                    key = recording_key(uid, model)
                    if key in active_recordings:
                        continue

                    logger.info(f"Checking {model} for user {uid}...")
                    loop = asyncio.get_event_loop()
                    online = await loop.run_in_executor(None, _is_online, model)

                    if online:
                        rec = await start_user_recording(uid, model)
                        if rec:
                            await tg_notify(
                                f"🔴 *{model}* is live — recording started.\n"
                                f"Files will be uploaded automatically.",
                                chat_id=uid
                            )

                    await asyncio.sleep(RATE_LIMIT_TIME)

            await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.exception(f"Recorder loop error: {e}")
            await asyncio.sleep(10)
