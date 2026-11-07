import os
import io
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen
from PIL import Image
from music_tag import load_file


BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")

# Hostless keeps the application image read-only. Store Pyrofork's SQLite
# session and temporary media in the writable /tmp directory instead.
RUNTIME_DIR = Path("/tmp/music-editor-bot")
SESSION_DIR = RUNTIME_DIR / "sessions"
TEMP_DIR = RUNTIME_DIR / "temp"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

Bot = Client(
    "MusicEditorBot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH,
    workdir=str(SESSION_DIR),
)

START_TXT = """
Hi {}, I am Music Editor Bot.
I can change the music tags and artwork.

Send a music to get started.
"""

START_BTN = InlineKeyboardMarkup(
        [[
        InlineKeyboardButton('Source Code', url='https://github.com/samadii/MusicEditorBot'),
        ]]
    )


@Bot.on_message(filters.command(["start"]))
async def start(bot, update):
    text = START_TXT.format(update.from_user.mention)
    reply_markup = START_BTN
    await update.reply_text(
        text=text,
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )


@Bot.on_message(filters.private & filters.audio)
async def tag(bot, m):
    audio_path = TEMP_DIR / f"{m.audio.file_name}.mp3"
    artwork_path = TEMP_DIR / "artwork.jpg"

    mes = await m.reply("`Downloading...`")
    await m.download(str(audio_path))
    music = load_file(str(audio_path))

    try:
        artwork = music['artwork']
        image_data = artwork.value.data
        img = Image.open(io.BytesIO(image_data))
        img.save(str(artwork_path))
    except ValueError:
        image_data = None

    await mes.delete()
    fname = await bot.ask(m.chat.id, '`Send the Filename`', filters=filters.text)
    title = await bot.ask(m.chat.id, '`Send the Title name`', filters=filters.text)
    artist = await bot.ask(m.chat.id, '`Send the Artist(s) name`', filters=filters.text)
    answer = await bot.ask(m.chat.id, '`Send the Artwork or` /skip', filters=filters.photo | filters.text)
    music.remove_tag('artist')
    music.remove_tag('title')
    music['artist'] = artist.text
    music['title'] = title.text

    if answer.photo:
        await bot.download_media(message=answer.photo, file_name=str(artwork_path))
        music.remove_tag('artwork')
        with open(artwork_path, 'rb') as img_in:
            music['artwork'] = img_in.read()
    music.save()

    try:
        await bot.send_audio(
            chat_id=m.chat.id,
            file_name=fname.text,
            performer=artist.text,
            title=title.text,
            duration=m.audio.duration,
            audio=str(audio_path),
            thumb=str(artwork_path) if answer.photo or image_data else None
        )
    except Exception as e:
        print(e)
        return
    os.remove(audio_path)
