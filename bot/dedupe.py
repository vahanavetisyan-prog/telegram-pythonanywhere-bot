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
# Trade-off vs. the old "mark after success" pattern: a crash mid-flight
# now causes the retry to be dropped (within DEDUPE_TTL) instead of
# producing a duplicate reply. For a teaching bot, message loss on rare
# crashes is the better failure mode — duplicate replies confuse users
# and burn rate limit.

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
