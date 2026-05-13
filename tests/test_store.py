"""Direct tests for SqliteStore against real SQLite (file-backed via
the :memory: special path). Each test gets a fresh in-memory store so
state doesn't leak between cases.
"""

import time
from bot.store import SqliteStore


def make_store():
    return SqliteStore(":memory:")


def test_get_missing_returns_none():
    s = make_store()
    assert s.get("nope") is None


def test_set_then_get_roundtrips():
    s = make_store()
    s.set("k", "v")
    assert s.get("k") == "v"


def test_set_overwrites_existing_value():
    s = make_store()
    s.set("k", "first")
    s.set("k", "second")
    assert s.get("k") == "second"


def test_delete_removes_key():
    s = make_store()
    s.set("k", "v")
    s.delete("k")
    assert s.get("k") is None


def test_set_with_ttl_returns_value_before_expiry():
    s = make_store()
    s.set("k", "v", ex=60)
    assert s.get("k") == "v"


def test_set_with_zero_ttl_treated_as_no_expiry():
    # ex=0 (falsy) means no TTL — matches the bot's existing call sites
    # which never pass 0 but defensively check truthiness.
    s = make_store()
    s.set("k", "v", ex=0)
    assert s.get("k") == "v"


def test_expired_key_returns_none(monkeypatch):
    s = make_store()
    s.set("k", "v", ex=10)
    # Advance the store's clock past the expiry.
    monkeypatch.setattr(
        SqliteStore, "_now", staticmethod(lambda: int(time.time()) + 100)
    )
    assert s.get("k") is None


def test_incr_creates_missing_key_at_one():
    s = make_store()
    assert s.incr("counter") == 1
    assert s.get("counter") == "1"


def test_incr_increments_existing_key():
    s = make_store()
    s.incr("counter")
    s.incr("counter")
    assert s.incr("counter") == 3


def test_incr_preserves_existing_ttl(monkeypatch):
    """Redis INCR does not touch an existing key's TTL. The SQLite impl
    must match — otherwise rate-limit windows would shift each request."""
    s = make_store()
    s.set("counter", "1", ex=86400)
    # First incr at t=0 — TTL was set at construction
    s.incr("counter")
    # After the increment, the row should still expire at the original time.
    row = s._conn.execute(
        "SELECT value, expires_at FROM kv WHERE key = ?", ("counter",)
    ).fetchone()
    assert row[0] == "2"
    # expires_at must still be ~24h in the future (not None, not refreshed
    # to "now"). Allow some slop for test runtime.
    assert row[1] is not None
    assert row[1] >= int(time.time()) + 86000


def test_incr_recreates_expired_key_at_one(monkeypatch):
    s = make_store()
    s.set("counter", "5", ex=10)
    monkeypatch.setattr(
        SqliteStore, "_now", staticmethod(lambda: int(time.time()) + 100)
    )
    # The old key has expired; incr should treat it as missing.
    assert s.incr("counter") == 1


def test_expire_sets_ttl_on_existing_key(monkeypatch):
    s = make_store()
    s.set("k", "v")
    s.expire("k", 10)
    # Before expiry the value is still readable.
    assert s.get("k") == "v"
    # After expiry it's gone.
    monkeypatch.setattr(
        SqliteStore, "_now", staticmethod(lambda: int(time.time()) + 100)
    )
    assert s.get("k") is None


def test_incr_is_atomic_under_concurrent_calls(tmp_path):
    """Codex review found that the pre-fix incr() was a non-atomic
    read-modify-write that lost ~50% of increments under contention
    (expected 200, got 93 with 20 errors). This test reproduces that
    workload and asserts the post-fix SqliteStore.incr() returns the
    exact expected count."""
    import threading

    db_path = tmp_path / "concurrent.db"
    s = SqliteStore(str(db_path))
    THREADS = 10
    PER_THREAD = 50
    EXPECTED = THREADS * PER_THREAD
    errors = []

    def worker():
        for _ in range(PER_THREAD):
            try:
                s.incr("counter")
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"unexpected errors: {errors[:5]}"
    assert s.get("counter") == str(EXPECTED), (
        f"expected {EXPECTED}, got {s.get('counter')} — lost increments"
    )


def test_set_nx_returns_true_when_absent(tmp_path):
    s = SqliteStore(str(tmp_path / "nx.db"))
    assert s.set_nx("k", "v") is True
    assert s.get("k") == "v"


def test_set_nx_returns_false_when_present(tmp_path):
    s = SqliteStore(str(tmp_path / "nx.db"))
    s.set("k", "first")
    assert s.set_nx("k", "second") is False
    assert s.get("k") == "first"  # not overwritten


def test_set_nx_overwrites_expired_entry(tmp_path, monkeypatch):
    s = SqliteStore(str(tmp_path / "nx.db"))
    s.set("k", "stale", ex=10)
    monkeypatch.setattr(
        SqliteStore, "_now", staticmethod(lambda: int(time.time()) + 100)
    )
    assert s.set_nx("k", "fresh") is True
    assert s.get("k") == "fresh"


def test_set_nx_is_atomic_under_contention(tmp_path):
    """Only one of N concurrent set_nx callers should win — the rest
    must see False. Mirrors the dedupe.try_acquire workload."""
    import threading

    s = SqliteStore(str(tmp_path / "race.db"))
    THREADS = 32
    won = []

    def worker():
        if s.set_nx("update:42", "1", ex=600):
            won.append(1)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(won) == 1, f"expected exactly one winner, got {sum(won)}"


def test_rate_limit_pattern_end_to_end(monkeypatch):
    """Mirror the exact incr+expire+gt-check pattern used in bot/rate_limit.py
    to catch regressions across the abstraction boundary."""
    s = make_store()
    user_key = "rate:42:2026-05-13"
    # Burst of 5 messages — first sets TTL, none should be rate-limited
    # below the threshold of 10.
    for i in range(5):
        count = s.incr(user_key)
        if count == 1:
            s.expire(user_key, 86400)
        assert count <= 10
    # Force expiry — the next message should reset the counter.
    monkeypatch.setattr(
        SqliteStore, "_now", staticmethod(lambda: int(time.time()) + 86500)
    )
    assert s.incr(user_key) == 1
