"""Tests for the auto webhook registration helper (bot.clients.register_webhook).

These cover both the happy-path success message and the no-op + error
branches, since this runs at every PA worker boot and after every
/api/deploy — failures must never bubble up and crash the worker.
"""

from unittest.mock import patch


def test_register_webhook_skips_when_url_unset():
    with (
        patch("bot.config.WEBHOOK_URL", ""),
        patch("bot.config.WEBHOOK_SECRET", ""),
    ):
        from bot.clients import register_webhook

        msg = register_webhook()
        assert "skipped" in msg.lower() or "unset" in msg.lower()


def test_register_webhook_calls_set_webhook_with_url():
    with (
        patch("bot.config.WEBHOOK_URL", "https://example.com/api/webhook"),
        patch("bot.config.WEBHOOK_SECRET", ""),
        patch("bot.clients.bot") as mock_bot,
    ):
        from bot.clients import register_webhook

        msg = register_webhook()
        mock_bot.set_webhook.assert_called_once_with(
            url="https://example.com/api/webhook"
        )
        assert "https://example.com/api/webhook" in msg


def test_register_webhook_includes_secret_when_set():
    with (
        patch("bot.config.WEBHOOK_URL", "https://example.com/api/webhook"),
        patch("bot.config.WEBHOOK_SECRET", "topsecret"),
        patch("bot.clients.bot") as mock_bot,
    ):
        from bot.clients import register_webhook

        register_webhook()
        kwargs = mock_bot.set_webhook.call_args.kwargs
        assert kwargs["secret_token"] == "topsecret"


def test_register_webhook_does_not_raise_on_failure():
    """Failures must never crash the worker — they're logged and swallowed."""
    with (
        patch("bot.config.WEBHOOK_URL", "https://example.com/api/webhook"),
        patch("bot.config.WEBHOOK_SECRET", ""),
        patch("bot.clients.bot") as mock_bot,
    ):
        mock_bot.set_webhook.side_effect = RuntimeError("Telegram down")
        from bot.clients import register_webhook

        msg = register_webhook()
        assert "fail" in msg.lower()
