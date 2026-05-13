import threading
import time
from urllib.parse import urlparse

import telebot
from openai import OpenAI

from bot.config import AI_API_KEY, AI_BASE_URL, SQLITE_PATH, TELEGRAM_TOKEN
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


class _LazyBotInfo:
    """Defers `bot.get_me()` until first attribute access; caches the
    result; retries transient failures.

    Why this exists: PA's outbound HTTPS proxy occasionally returns 503
    for a few seconds. If `get_me()` ran at module load, a single
    proxy blip would prevent the WSGI worker from booting at all. With
    lazy access, the worker comes up regardless and individual requests
    that need the bot's username retry up to 3 times with backoff.

    Thread safety: `_load()` is guarded by a class-level lock with a
    double-check so concurrent first-accesses don't both call get_me().
    """

    _info = None
    _lock = threading.Lock()

    def _load(self) -> None:
        if self._info is not None:
            return
        with self.__class__._lock:
            if self.__class__._info is not None:
                return
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    self.__class__._info = bot.get_me()
                    return
                except Exception as e:
                    last_exc = e
                    print(f"bot.get_me() attempt {attempt + 1}/3 failed: {e}")
                    if attempt < 2:
                        time.sleep(1)
            raise RuntimeError(
                f"Could not fetch bot info from Telegram after 3 attempts: {last_exc}"
            )

    def __getattr__(self, name):
        self._load()
        return getattr(self.__class__._info, name)


BOT_INFO = _LazyBotInfo()


def register_webhook() -> str:
    """Register the Telegram webhook against WEBHOOK_URL.

    Idempotent — Telegram treats repeated setWebhook calls with the
    same URL as no-ops. Returns a status string for logging. Never
    raises: failures are caught so a bad token or network blip doesn't
    crash worker boot.

    Validates WEBHOOK_URL before calling Telegram so a typo (missing
    scheme, http instead of https, missing path) fails fast with a
    clear message instead of a confusing Telegram error.
    """
    from bot.config import WEBHOOK_SECRET, WEBHOOK_URL

    if not WEBHOOK_URL:
        return "WEBHOOK_URL unset — auto-registration skipped"

    parsed = urlparse(WEBHOOK_URL)
    if parsed.scheme != "https":
        return f"WEBHOOK_URL must use https:// (got {parsed.scheme or '<no scheme>'}://) — skipping"
    if not parsed.netloc:
        return f"WEBHOOK_URL has no host — skipping ({WEBHOOK_URL!r})"
    if not parsed.path:
        return f"WEBHOOK_URL has no path; Telegram needs a real endpoint — skipping ({WEBHOOK_URL!r})"

    try:
        kwargs = {"url": WEBHOOK_URL}
        if WEBHOOK_SECRET:
            kwargs["secret_token"] = WEBHOOK_SECRET
        result = bot.set_webhook(**kwargs)
    except Exception as e:
        return f"Webhook registration failed: {e}"

    # pyTelegramBotAPI returns True on success, False otherwise. Surface
    # the difference so caller logs are honest.
    if result is False:
        return f"Webhook registration: Telegram returned False for {WEBHOOK_URL}"
    return f"Webhook registered: {WEBHOOK_URL}"
