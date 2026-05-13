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
