from unittest.mock import patch, MagicMock


def test_is_processed_returns_false_for_new_update():
    mock_store = MagicMock()
    mock_store.get.return_value = None
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import is_processed

        assert is_processed(123) is False
        mock_store.get.assert_called_once_with("update:123")


def test_is_processed_returns_true_for_known_update():
    mock_store = MagicMock()
    mock_store.get.return_value = "1"
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import is_processed

        assert is_processed(123) is True


def test_mark_processed_sets_ttl():
    mock_store = MagicMock()
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import mark_processed, DEDUPE_TTL

        mark_processed(456)
        mock_store.set.assert_called_once()
        args, kwargs = mock_store.set.call_args
        assert args[0] == "update:456"
        assert kwargs["ex"] == DEDUPE_TTL


def test_dedupe_stateless_mode():
    """Without Redis, never claim a duplicate — better a possible double
    reply than a silently dropped legitimate message."""
    with patch("bot.dedupe.store", None):
        from bot.dedupe import is_processed, mark_processed

        assert is_processed(789) is False
        mark_processed(789)  # no-op, must not raise


def test_dedupe_redis_failure_doesnt_block_handling():
    """A Redis hiccup must not break message handling — read returns False
    (process the update) and write swallows the error."""
    mock_store = MagicMock()
    mock_store.get.side_effect = Exception("connection refused")
    mock_store.set.side_effect = Exception("connection refused")
    with patch("bot.dedupe.store", mock_store):
        from bot.dedupe import is_processed, mark_processed

        assert is_processed(999) is False
        mark_processed(999)  # must not raise
