from bot.clients import store

# Telegram retries the same update_id when a webhook call doesn't return
# 200 (e.g. our function timed out or crashed). Without dedupe, a slow
# but successful run plus a retry results in two replies and double
# rate-limit consumption.
#
# `try_acquire` uses an atomic set-if-not-exists (set_nx) so two
# concurrent webhook requests for the same update_id can't both win the
# claim — only the first does, the second sees False and skips. This
# fixes a TOCTOU race that the previous "check then mark" pattern had.
#
# When processing crashes after a successful claim, the webhook calls
# `release` so Telegram's retry isn't silently dropped — a crash means
# the reply almost certainly wasn't sent, so reprocessing beats message
# loss (observed in production: a transient PA proxy 503 made every
# handler 500, and dedupe then ate each retry). Slow-but-successful runs
# raise nothing, so the duplicate-reply protection is unaffected.

DEDUPE_TTL = 600  # seconds


def try_acquire(update_id: int) -> bool:
    """Atomically claim this update_id for processing.

    Returns True if the caller "won" the claim and should process the
    update, False if another delivery (or a previous successful run) is
    already handling it.

    Stateless mode (no store) returns True — better to process every
    request than drop legitimate updates. Storage errors also return
    True for the same reason.
    """
    if store is None:
        return True
    try:
        return store.set_nx(f"update:{update_id}", "1", ex=DEDUPE_TTL)
    except Exception as e:
        print(f"Store error (dedupe acquire): {e}")
        return True


def release(update_id: int) -> None:
    """Release a claim taken by `try_acquire`.

    Called when processing crashed after the claim, so Telegram's retry
    of the same update_id can be processed instead of being dropped.
    Best-effort: a storage error just logs (the claim then expires via
    DEDUPE_TTL).
    """
    if store is None:
        return
    try:
        store.delete(f"update:{update_id}")
    except Exception as e:
        print(f"Store error (dedupe release): {e}")
