from bot.clients import store

# Telegram retries the same update_id when a webhook call doesn't return
# 200 (e.g. our function timed out or Vercel killed it). Without dedupe,
# a successful-but-slow run plus a retry results in two replies and double
# rate-limit consumption. We mark an update as done ONLY after successful
# processing so a crash mid-flight still allows Telegram to retry.
DEDUPE_TTL = 600  # seconds


def is_processed(update_id: int) -> bool:
    """Has this update_id already been handled successfully?

    Stateless mode (no store) and storage errors return False — better
    to risk a double reply than to silently drop a real message.
    """
    if store is None:
        return False
    try:
        return store.get(f"update:{update_id}") is not None
    except Exception as e:
        print(f"Store error (dedupe read): {e}")
        return False


def mark_processed(update_id: int) -> None:
    """Mark the update as successfully handled. Retries within
    DEDUPE_TTL seconds will be dropped.
    """
    if store is None:
        return
    try:
        store.set(f"update:{update_id}", "1", ex=DEDUPE_TTL)
    except Exception as e:
        print(f"Store error (dedupe write): {e}")
