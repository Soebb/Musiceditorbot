"""Render Web Service entry point."""

import asyncio
import logging
import os
import threading

from waitress import create_server

import bot
from app import app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("music-editor.runner")


async def main():
    bot.BOT_LOOP = asyncio.get_running_loop()

    logger.info("Starting Pyrogram MTProto client...")
    await bot.Bot.start()
    logger.info("Pyrogram client started.")

    port = int(os.environ.get("PORT", "10000"))
    server = create_server(app, host="0.0.0.0", port=port, threads=8)
    server_thread = threading.Thread(target=server.run, name="http-server", daemon=True)
    server_thread.start()
    logger.info("HTTP server listening on port %s.", port)

    try:
        bot.configure_webhook()
        logger.info("Telegram webhook registration completed.")
        await asyncio.Event().wait()
    finally:
        logger.info("Stopping Telegram client...")
        try:
            await bot.Bot.stop()
        except Exception:
            logger.exception("Error while stopping Telegram client.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    except Exception:
        logger.exception("Application startup/runtime failed.")
        raise
