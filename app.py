import asyncio
import logging

from flask import Flask, abort, jsonify, request

import bot


app = Flask(__name__)
logger = logging.getLogger("music-editor.web")


@app.get("/")
@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/telegram-webhook")
def telegram_webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not bot.verify_webhook_secret(secret):
        abort(403)

    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return jsonify({"ok": False, "error": "invalid update"}), 400

    if bot.BOT_LOOP is None:
        logger.error("Webhook received before the Telegram client was ready.")
        return jsonify({"ok": False, "error": "bot is starting"}), 503

    future = asyncio.run_coroutine_threadsafe(bot.process_update(update), bot.BOT_LOOP)

    def log_failure(task):
        try:
            task.result()
        except Exception:
            logger.exception("Unhandled webhook processing error")

    future.add_done_callback(log_failure)
    return jsonify({"ok": True})
