"""Tests for the WEBHOOK_SECRET auto-bootstrap in bot/config.py.

The function generates and persists a random secret on first run if the
env var is unset — making the bot secure-by-default with zero manual
`openssl rand` setup.
"""

import os
import re
from unittest.mock import patch

from bot.config import _bootstrap_webhook_secret


def test_bootstrap_uses_env_var_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "from-env")
    result = _bootstrap_webhook_secret(file_path=tmp_path / ".webhook_secret")
    assert result == "from-env"
    # Must not have written a file when env wins.
    assert not (tmp_path / ".webhook_secret").exists()


def test_bootstrap_reads_existing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    path = tmp_path / ".webhook_secret"
    path.write_text("pre-existing-secret")
    result = _bootstrap_webhook_secret(file_path=path)
    assert result == "pre-existing-secret"


def test_bootstrap_generates_new_secret_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    path = tmp_path / ".webhook_secret"
    assert not path.exists()
    result = _bootstrap_webhook_secret(file_path=path)
    # 64 hex chars = 32 bytes of entropy.
    assert re.fullmatch(r"[0-9a-f]{64}", result), f"unexpected secret: {result!r}"
    # File persisted with the secret.
    assert path.exists()
    assert path.read_text() == result


def test_bootstrap_persisted_secret_survives_second_call(tmp_path, monkeypatch):
    """Two calls return the same secret — important so the value the bot
    registers with Telegram matches the one it uses to verify subsequent
    webhook requests."""
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    path = tmp_path / ".webhook_secret"
    first = _bootstrap_webhook_secret(file_path=path)
    second = _bootstrap_webhook_secret(file_path=path)
    assert first == second


def test_bootstrap_sets_restrictive_file_mode(tmp_path, monkeypatch):
    """The generated file should be 0600 — readable only by the worker
    user. Skip on platforms where chmod is a no-op (Windows)."""
    if os.name != "posix":
        return
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    path = tmp_path / ".webhook_secret"
    _bootstrap_webhook_secret(file_path=path)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_bootstrap_falls_back_to_empty_on_filesystem_error(monkeypatch):
    """A read-only mount or missing parent dir must not crash worker boot.
    The bot tolerates an unsigned webhook (already a documented mode) over
    a startup crash."""
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    with patch("bot.config.Path.write_text", side_effect=PermissionError("read-only")):
        # Non-existent dir, no env var → bootstrap tries to write, fails.
        result = _bootstrap_webhook_secret(
            file_path=__import__("pathlib").Path("/nonexistent/dir/.webhook_secret")
        )
        assert result == ""
