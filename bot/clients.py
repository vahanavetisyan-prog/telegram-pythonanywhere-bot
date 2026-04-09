import telebot
from openai import OpenAI
from bot.config import TELEGRAM_TOKEN, AI_API_KEY, AI_BASE_URL, UPSTASH_URL, UPSTASH_TOKEN

bot      = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
ai       = OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)

# Redis is optional — when unset, the bot runs in stateless mode:
# no conversation memory, no rate limiting, no provider preferences,
# no search cache. Every consumer of `redis` must handle `None`.
if UPSTASH_URL and UPSTASH_TOKEN:
    from upstash_redis import Redis
    redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
else:
    redis = None
    print("Redis not configured — running in stateless mode (no memory, no rate limit).")

BOT_INFO = bot.get_me()  # cached at startup for group mention detection
