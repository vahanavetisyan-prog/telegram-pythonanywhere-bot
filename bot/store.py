"""KV store backed by SQLite, with lazy TTL expiry.

Every storage call in the bot reduces to five operations against a
keyed value: get / set / delete / incr / expire — all TTL-aware.
SqliteStore implements them against a local SQLite file, which is
the right fit for hosts with persistent disk (PythonAnywhere).

Lazy expiry: expired rows are filtered on read and overwritten on
write. There is no background sweeper — stale rows accumulate slowly
but never affect correctness. PA free disk is 512MB; the bot's
entire state stays well under 10MB even with hundreds of users.

WAL mode is enabled so the (currently unused) future case of
multiple workers won't have readers blocking writers.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Optional


class SqliteStore:
    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expires_at INTEGER
        )
    """

    def __init__(self, path: str) -> None:
        # check_same_thread=False lets keep_typing()'s daemon thread
        # share the connection if it ever needs to. isolation_level=None
        # enables autocommit so simple ops don't need explicit BEGIN/COMMIT.
        self._conn = sqlite3.connect(
            path, check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(self._SCHEMA)

    @staticmethod
    def _now() -> int:
        return int(time.time())

    def get(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value, expires_at FROM kv WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at is not None and expires_at <= self._now():
            return None
        return value

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        expires_at = self._now() + ex if ex else None
        self._conn.execute(
            "INSERT OR REPLACE INTO kv (key, value, expires_at) VALUES (?, ?, ?)",
            (key, value, expires_at),
        )

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))

    def incr(self, key: str) -> int:
        # Missing or expired keys are (re)created at 1 with no TTL.
        # Existing keys keep their TTL untouched. Callers that need a
        # TTL on the first increment must call expire() separately
        # when the returned value is 1 (see bot/rate_limit.py).
        row = self._conn.execute(
            "SELECT value, expires_at FROM kv WHERE key = ?", (key,)
        ).fetchone()
        now = self._now()
        if row is None or (row[1] is not None and row[1] <= now):
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, expires_at) "
                "VALUES (?, '1', NULL)",
                (key,),
            )
            return 1
        new_value = int(row[0]) + 1
        self._conn.execute(
            "UPDATE kv SET value = ? WHERE key = ?", (str(new_value), key)
        )
        return new_value

    def expire(self, key: str, ex: int) -> None:
        self._conn.execute(
            "UPDATE kv SET expires_at = ? WHERE key = ?",
            (self._now() + ex, key),
        )
