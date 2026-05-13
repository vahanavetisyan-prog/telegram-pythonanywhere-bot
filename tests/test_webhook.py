from unittest.mock import MagicMock, patch


def test_webhook_rejects_bad_secret():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "wrong_secret"
    mock_request.get_data.return_value = "{}"
    with (
        patch("bot.config.WEBHOOK_SECRET", "correct_secret"),
        patch("api.index.request", mock_request),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("Forbidden", 403)


def test_webhook_accepts_correct_secret():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "correct_secret"
    mock_request.get_data.return_value = "{}"
    fake_update = MagicMock(update_id=1001)
    with (
        patch("bot.config.WEBHOOK_SECRET", "correct_secret"),
        patch("api.index.request", mock_request),
        patch("bot.clients.bot"),
        patch("bot.dedupe.try_acquire", return_value=True),
        patch("telebot.types.Update.de_json", return_value=fake_update),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("OK", 200)


def test_webhook_skips_validation_when_no_secret():
    mock_request = MagicMock()
    mock_request.get_data.return_value = "{}"
    fake_update = MagicMock(update_id=1002)
    with (
        patch("bot.config.WEBHOOK_SECRET", ""),
        patch("api.index.request", mock_request),
        patch("bot.clients.bot"),
        patch("bot.dedupe.try_acquire", return_value=True),
        patch("telebot.types.Update.de_json", return_value=fake_update),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("OK", 200)


def test_webhook_dedupes_concurrently_claimed_update():
    """If another delivery already claimed this update_id (atomic set_nx),
    the webhook must not double-process. Codex review caught the TOCTOU
    race in the previous check-then-mark pattern."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = ""
    mock_request.get_data.return_value = "{}"
    fake_update = MagicMock(update_id=42)
    mock_bot = MagicMock()
    with (
        patch("bot.config.WEBHOOK_SECRET", ""),
        patch("api.index.request", mock_request),
        patch("bot.clients.bot", mock_bot),
        patch("bot.dedupe.try_acquire", return_value=False),
        patch("telebot.types.Update.de_json", return_value=fake_update),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("OK", 200)
        mock_bot.process_new_updates.assert_not_called()


def test_webhook_handles_malformed_json():
    import sys

    mock_request = MagicMock()
    mock_request.headers.get.return_value = ""
    mock_request.get_data.return_value = "not json"
    with (
        patch.object(
            sys.modules["telebot"].types.Update,
            "de_json",
            side_effect=ValueError("bad"),
        ),
        patch("bot.config.WEBHOOK_SECRET", ""),
        patch("api.index.request", mock_request),
        patch("bot.clients.bot"),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("Bad Request", 400)


def test_webhook_uses_compare_digest():
    """Wrong secret of identical length must still be rejected."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "x" * 16
    mock_request.get_data.return_value = "{}"
    with (
        patch("bot.config.WEBHOOK_SECRET", "y" * 16),
        patch("api.index.request", mock_request),
    ):
        from api.index import webhook

        result = webhook()
        assert result == ("Forbidden", 403)


def test_webhook_rejects_secret_before_loading_handlers():
    """A bad-secret POST must NOT trigger bot.handlers / bot.clients import
    (which would call bot.get_me() on cold start). Regression guard for the
    lazy-import ordering: secret check first, heavy imports after."""
    import sys

    sys.modules.pop("bot.handlers", None)
    sys.modules.pop("bot.clients", None)

    mock_request = MagicMock()
    mock_request.headers.get.return_value = "wrong"
    mock_request.get_data.return_value = "{}"
    with (
        patch("bot.config.WEBHOOK_SECRET", "right"),
        patch("api.index.request", mock_request),
    ):
        from api.index import webhook

        result = webhook()
    assert result == ("Forbidden", 403)
    assert "bot.handlers" not in sys.modules
    assert "bot.clients" not in sys.modules
