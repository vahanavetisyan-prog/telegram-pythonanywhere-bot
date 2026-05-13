import telebot
from openai import OpenAI
from bot.config import (
    TELEGRAM_TOKEN,
    AI_API_KEY,
    AI_BASE_URL,
    UPSTASH_URL,
    UPSTASH_TOKEN,
    SQLITE_PATH,
)
from bot.store import RedisStore, SqliteStore

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
ai = OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)

# Persistent storage is optional. Pick the first configured backend:
#   1. Upstash Redis  — UPSTASH_REDIS_REST_URL + _TOKEN set
#   2. Local SQLite   — SQLITE_PATH set
#   3. Stateless mode — nothing set; history / rate limit / preferences /
#                       search cache / dedupe all no-op
#
# Each consumer in bot/ checks `store is None` for stateless and wraps
# every call in try/except so a misbehaving backend never takes the bot
# down — replies just lose memory until the backend recovers.
if UPSTASH_URL and UPSTASH_TOKEN:
    from upstash_redis import Redis

    store = RedisStore(Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN))
elif SQLITE_PATH:
    store = SqliteStore(SQLITE_PATH)
    print(f"Using SQLite store at {SQLITE_PATH}.")
else:
    store = None
    print(
        "Storage not configured — running in stateless mode (no memory, no rate limit)."
    )

BOT_INFO = bot.get_me()  # cached at startup for group mention detection
