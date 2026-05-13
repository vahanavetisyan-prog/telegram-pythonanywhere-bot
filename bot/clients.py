import telebot
from openai import OpenAI
from bot.config import TELEGRAM_TOKEN, AI_API_KEY, AI_BASE_URL, SQLITE_PATH
from bot.store import SqliteStore

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
ai = OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)

# Persistent storage is optional. Set SQLITE_PATH to the absolute path
# of a SQLite file to enable history / rate limiting / preferences /
# dedupe. Without it the bot runs in stateless mode — every consumer
# in bot/ checks `store is None` and falls back to safe defaults.
if SQLITE_PATH:
    store = SqliteStore(SQLITE_PATH)
    print(f"Using SQLite store at {SQLITE_PATH}.")
else:
    store = None
    print(
        "Storage not configured — running in stateless mode (no memory, no rate limit)."
    )

BOT_INFO = bot.get_me()  # cached at startup for group mention detection


def register_webhook() -> str:
    """Register the Telegram webhook against WEBHOOK_URL.

    Idempotent — Telegram treats repeated setWebhook calls with the same
    URL as no-ops. Returns a status string for logging. Never raises:
    failures are caught so a bad token or network blip doesn't crash
    worker boot.
    """
    from bot.config import WEBHOOK_URL, WEBHOOK_SECRET

    if not WEBHOOK_URL:
        return "WEBHOOK_URL unset — auto-registration skipped"
    try:
        kwargs = {"url": WEBHOOK_URL}
        if WEBHOOK_SECRET:
            kwargs["secret_token"] = WEBHOOK_SECRET
        bot.set_webhook(**kwargs)
        return f"Webhook registered: {WEBHOOK_URL}"
    except Exception as e:
        return f"Webhook registration failed: {e}"
