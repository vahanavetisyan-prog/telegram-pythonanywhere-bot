"""Tests for the ALLOWED_USERS whitelist (bot.helpers.is_allowed).

The function is wired into every message_handler's func= filter, so
telebot silently drops non-whitelisted updates. These tests verify the
matcher itself against representative message shapes.
"""

from unittest.mock import MagicMock, patch


def _msg(user_id=123, username=""):
    m = MagicMock()
    m.from_user = MagicMock(id=user_id, username=username)
    return m


def test_is_allowed_open_when_list_empty():
    """Default config (no whitelist) means everyone is allowed."""
    with patch("bot.helpers.ALLOWED_USERS", []):
        from bot.helpers import is_allowed

        assert is_allowed(_msg(username="anyone")) is True
        assert is_allowed(_msg(user_id=42, username="")) is True


def test_is_allowed_matches_username_case_insensitive():
    with (
        patch("bot.helpers.ALLOWED_USERS", ["Alice", "bob"]),
        patch("bot.helpers._ALLOWED_USERNAMES", {"alice", "bob"}),
        patch("bot.helpers._ALLOWED_USER_IDS", set()),
    ):
        from bot.helpers import is_allowed

        assert is_allowed(_msg(username="alice")) is True
        assert is_allowed(_msg(username="ALICE")) is True
        assert is_allowed(_msg(username="bOb")) is True
        assert is_allowed(_msg(username="carol")) is False


def test_is_allowed_rejects_username_not_in_list():
    with (
        patch("bot.helpers.ALLOWED_USERS", ["alice"]),
        patch("bot.helpers._ALLOWED_USERNAMES", {"alice"}),
        patch("bot.helpers._ALLOWED_USER_IDS", set()),
    ):
        from bot.helpers import is_allowed

        assert is_allowed(_msg(username="mallory")) is False


def test_is_allowed_matches_numeric_user_id():
    with (
        patch("bot.helpers.ALLOWED_USERS", ["123456"]),
        patch("bot.helpers._ALLOWED_USERNAMES", set()),
        patch("bot.helpers._ALLOWED_USER_IDS", {"123456"}),
    ):
        from bot.helpers import is_allowed

        # Username unset but ID matches — still allowed.
        assert is_allowed(_msg(user_id=123456, username="")) is True
        assert is_allowed(_msg(user_id=999, username="")) is False


def test_is_allowed_mixed_username_and_id_list():
    with (
        patch("bot.helpers.ALLOWED_USERS", ["alice", "123456"]),
        patch("bot.helpers._ALLOWED_USERNAMES", {"alice"}),
        patch("bot.helpers._ALLOWED_USER_IDS", {"123456"}),
    ):
        from bot.helpers import is_allowed

        assert is_allowed(_msg(user_id=999, username="alice")) is True  # username hit
        assert is_allowed(_msg(user_id=123456, username="bob")) is True  # ID hit
        assert is_allowed(_msg(user_id=999, username="bob")) is False  # neither


def test_is_allowed_rejects_message_with_no_from_user():
    """Channel posts and anonymous group admins arrive without from_user.
    Don't allow them when a whitelist is configured."""
    with (
        patch("bot.helpers.ALLOWED_USERS", ["alice"]),
        patch("bot.helpers._ALLOWED_USERNAMES", {"alice"}),
        patch("bot.helpers._ALLOWED_USER_IDS", set()),
    ):
        from bot.helpers import is_allowed

        m = MagicMock()
        m.from_user = None
        assert is_allowed(m) is False


def test_is_allowed_treats_none_username_safely():
    """user.username can legitimately be None for users without a public handle."""
    with (
        patch("bot.helpers.ALLOWED_USERS", ["alice"]),
        patch("bot.helpers._ALLOWED_USERNAMES", {"alice"}),
        patch("bot.helpers._ALLOWED_USER_IDS", set()),
    ):
        from bot.helpers import is_allowed

        m = MagicMock()
        m.from_user = MagicMock(id=42, username=None)
        assert is_allowed(m) is False
