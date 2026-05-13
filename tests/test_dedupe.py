from unittest.mock import MagicMock, patch


def test_try_acquire_succeeds_when_key_absent():
    mock_store = MagicMock()
    mock_store.set_nx.return_value = True
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import try_acquire, DEDUPE_TTL

        assert try_acquire(123) is True
        mock_store.set_nx.assert_called_once()
        args, kwargs = mock_store.set_nx.call_args
        assert args[0] == "update:123"
        assert kwargs["ex"] == DEDUPE_TTL


def test_try_acquire_fails_when_already_claimed():
    mock_store = MagicMock()
    mock_store.set_nx.return_value = False
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import try_acquire

        assert try_acquire(123) is False


def test_try_acquire_stateless_mode_always_true():
    """Without storage, never drop a legitimate update — process every one."""
    with patch("bot.dedupe.store", None):
        from bot.dedupe import try_acquire

        assert try_acquire(789) is True


def test_try_acquire_storage_failure_falls_through_to_process():
    """A storage hiccup must not block message handling — return True so the
    handler still processes the update."""
    mock_store = MagicMock()
    mock_store.set_nx.side_effect = Exception("connection refused")
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import try_acquire

        assert try_acquire(999) is True
