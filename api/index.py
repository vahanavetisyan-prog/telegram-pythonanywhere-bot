import hmac
from flask import Flask, request

app = Flask(__name__)


@app.route("/api/health")
@app.route("/api/index")
def health():
    # Keep this endpoint dependency-free so cold-start uptime pings don't
    # trigger Telegram/Redis/AI client init.
    return "OK", 200


@app.route("/api/webhook", methods=["POST"])
def webhook():
    # Verify the secret BEFORE any heavy imports. bot.config only reads
    # env vars, no network. bot.clients/handlers/telebot would otherwise
    # trigger bot.get_me() on every cold start — including for forged or
    # mis-secreted POSTs.
    from bot.config import WEBHOOK_SECRET

    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            return "Forbidden", 403

    # Authenticated — now pull the heavyweight modules.
    import telebot
    import bot.handlers  # noqa: F401 — registers @bot.message_handler decorators
    from bot.clients import bot

    raw = request.get_data(as_text=True)
    try:
        update = telebot.types.Update.de_json(raw)
    except Exception as e:
        print(f"Malformed update: {e}")
        return "Bad Request", 400
    if update is None:
        return "Bad Request", 400

    # Dedupe Telegram retries: when our function times out (Vercel cap or
    # crash), Telegram resends the same update_id. We mark "done" only
    # AFTER process_new_updates returns successfully, so a real failure
    # still lets the retry reach the handler.
    update_id = getattr(update, "update_id", None)
    if update_id is not None:
        from bot.dedupe import is_processed, mark_processed

        if is_processed(update_id):
            return "OK", 200
        bot.process_new_updates([update])
        mark_processed(update_id)
    else:
        bot.process_new_updates([update])
    return "OK", 200
