"""Music Editor Telegram bot with webhook delivery for Render Web Services.

Pyrogram is used for MTProto media downloads/uploads. Telegram Bot API webhooks
deliver updates so the service can receive inbound HTTP traffic on Render.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

import requests
from pyrogram import Client
from PIL import Image
from music_tag import load_file


logger = logging.getLogger("music-editor")

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET") or None

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

Bot = Client(
    "MusicEditorBot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH,
    no_updates=True,
)

BOT_LOOP = None
SESSIONS = {}
CHAT_LOCKS = {}


def configure_webhook():
    if not APP_URL:
        raise RuntimeError("RENDER_EXTERNAL_URL is not set; cannot configure Telegram webhook.")

    payload = {
        "url": f"{APP_URL}/telegram-webhook",
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    }
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram setWebhook failed: {result}")
    logger.info("Telegram webhook configured: %s", payload["url"])


def verify_webhook_secret(value):
    if not WEBHOOK_SECRET:
        return True
    import hmac
    return bool(value) and hmac.compare_digest(WEBHOOK_SECRET, value)


async def _send(chat_id, text, **kwargs):
    await Bot.send_message(chat_id, text, **kwargs)


async def _finish_edit(chat_id, session, artwork_from_user=False):
    music = session["music"]
    music.remove_tag("artist")
    music.remove_tag("title")
    music["artist"] = session["artist"]
    music["title"] = session["title"]

    artwork_path = session.get("artwork_path")
    if artwork_from_user and artwork_path:
        music.remove_tag("artwork")
        with open(artwork_path, "rb") as image_file:
            music["artwork"] = image_file.read()

    music.save()

    await Bot.send_audio(
        chat_id=chat_id,
        audio=session["audio_path"],
        file_name=session["filename"],
        performer=session["artist"],
        title=session["title"],
        duration=session["duration"],
        thumb=artwork_path if artwork_path and os.path.exists(artwork_path) else None,
    )
    shutil.rmtree(session["workdir"], ignore_errors=True)
    SESSIONS.pop(chat_id, None)


async def _process_message(update):
    message_data = update.get("message") or {}
    chat = message_data.get("chat") or {}
    if chat.get("type") != "private":
        return

    chat_id = chat.get("id")
    message_id = message_data.get("message_id")
    if not chat_id or not message_id:
        return

    lock = CHAT_LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:
        message = await Bot.get_messages(chat_id, message_id)
        if not message:
            return

        text = (message_data.get("text") or message_data.get("caption") or "").strip()

        if text.split(maxsplit=1)[0].split("@")[0] == "/start" if text else False:
            await _send(
                chat_id,
                f"Hi {message.from_user.mention if message.from_user else 'there'}, "
                "I am Music Editor Bot.\nI can change the music tags and artwork.\n\n"
                "Send a music file to get started.",
                disable_web_page_preview=True,
            )
            return

        if text == "/cancel":
            old = SESSIONS.pop(chat_id, None)
            if old:
                shutil.rmtree(old["workdir"], ignore_errors=True)
            await _send(chat_id, "Editing cancelled.")
            return

        session = SESSIONS.get(chat_id)
        if session:
            state = session["state"]
            if state == "filename":
                session["filename"] = text
                session["state"] = "title"
                await _send(chat_id, "Send the Title name")
                return
            if state == "title":
                session["title"] = text
                session["state"] = "artist"
                await _send(chat_id, "Send the Artist(s) name")
                return
            if state == "artist":
                session["artist"] = text
                session["state"] = "artwork"
                await _send(chat_id, "Send the Artwork or /skip")
                return
            if state == "artwork":
                if message.photo:
                    photo_path = await Bot.download_media(
                        message,
                        file_name=os.path.join(session["workdir"], "artwork.jpg"),
                    )
                    session["artwork_path"] = photo_path
                    await _finish_edit(chat_id, session, artwork_from_user=True)
                elif text.lower() == "/skip":
                    await _finish_edit(chat_id, session, artwork_from_user=False)
                else:
                    await _send(chat_id, "Please send an image or /skip")
                return

        if message.audio:
            workdir = TEMP_DIR / f"{chat_id}_{message_id}"
            workdir.mkdir(parents=True, exist_ok=True)
            try:
                progress = await _send(chat_id, "Downloading...")
                audio_path = await Bot.download_media(
                    message,
                    file_name=str(workdir) + os.sep,
                )
                if not audio_path:
                    raise RuntimeError("Telegram media download returned no file path.")

                music = load_file(audio_path)
                artwork_path = None
                try:
                    artwork_data = music["artwork"].value.data
                    if artwork_data:
                        artwork_path = str(workdir / "artwork.jpg")
                        Image.open(__import__("io").BytesIO(artwork_data)).convert("RGB").save(artwork_path, "JPEG")
                except (ValueError, KeyError, AttributeError):
                    artwork_path = None

                try:
                    await progress.delete()
                except Exception:
                    pass

                SESSIONS[chat_id] = {
                    "state": "filename",
                    "workdir": str(workdir),
                    "audio_path": audio_path,
                    "music": music,
                    "artwork_path": artwork_path,
                    "duration": message.audio.duration,
                }
                await _send(chat_id, "Send the Filename\n\nSend /cancel to cancel.")
            except Exception:
                logger.exception("Could not prepare incoming audio for chat %s", chat_id)
                shutil.rmtree(workdir, ignore_errors=True)
                await _send(chat_id, "Sorry, I couldn't process this audio file.")
            return

        if not session:
            await _send(chat_id, "Send an audio file to get started.")


async def process_update(update):
    try:
        await _process_message(update)
    except Exception:
        logger.exception("Failed to process Telegram update")
