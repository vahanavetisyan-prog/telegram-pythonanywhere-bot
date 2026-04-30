from unittest.mock import patch, MagicMock


def test_is_processed_returns_false_for_new_update():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    with patch("bot.dedupe.redis", mock_redis):
        from bot.dedupe import is_processed

        assert is_processed(123) is False
        mock_redis.get.assert_called_once_with("update:123")


def test_is_processed_returns_true_for_known_update():
    mock_redis = MagicMock()
    mock_redis.get.return_value = "1"
    with patch("bot.dedupe.redis", mock_redis):
        from bot.dedupe import is_processed

        assert is_processed(123) is True


def test_mark_processed_sets_ttl():
    mock_redis = MagicMock()
    with patch("bot.dedupe.redis", mock_redis):
        from bot.dedupe import mark_processed, DEDUPE_TTL

        mark_processed(456)
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert args[0] == "update:456"
        assert kwargs["ex"] == DEDUPE_TTL


def test_dedupe_stateless_mode():
    """Without Redis, never claim a duplicate — better a possible double
    reply than a silently dropped legitimate message."""
    with patch("bot.dedupe.redis", None):
        from bot.dedupe import is_processed, mark_processed

        assert is_processed(789) is False
        mark_processed(789)  # no-op, must not raise


def test_dedupe_redis_failure_doesnt_block_handling():
    """A Redis hiccup must not break message handling — read returns False
    (process the update) and write swallows the error."""
    mock_redis = MagicMock()
    mock_redis.get.side_effect = Exception("connection refused")
    mock_redis.set.side_effect = Exception("connection refused")
    with patch("bot.dedupe.redis", mock_redis):
        from bot.dedupe import is_processed, mark_processed

        assert is_processed(999) is False
        mark_processed(999)  # must not raise
