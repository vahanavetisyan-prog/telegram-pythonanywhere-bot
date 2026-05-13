"""Tests for the /api/deploy auto-deploy webhook.

Covers the security-critical path (secret verification, fail-closed)
and the happy path with subprocess.run mocked so we don't actually
exec git locally.
"""

from unittest.mock import MagicMock, patch


def test_deploy_fails_closed_when_secret_unset():
    """If DEPLOY_SECRET is empty, /api/deploy MUST refuse all requests.
    This is the safety property — a misconfigured deploy can't accidentally
    expose code execution to anonymous callers."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "anything"
    with (
        patch("bot.config.DEPLOY_SECRET", ""),
        patch("api.index.request", mock_request),
    ):
        from api.index import deploy

        body, status = deploy()
        assert status == 403


def test_deploy_rejects_bad_secret():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "wrong"
    with (
        patch("bot.config.DEPLOY_SECRET", "correct"),
        patch("api.index.request", mock_request),
    ):
        from api.index import deploy

        body, status = deploy()
        assert status == 403


def test_deploy_runs_git_pull_on_correct_secret():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "correct"
    fake_result = MagicMock(returncode=0, stdout="Already up to date.\n", stderr="")
    with (
        patch("bot.config.DEPLOY_SECRET", "correct"),
        patch("api.index.request", mock_request),
        patch("api.index.subprocess.run", return_value=fake_result) as mock_run,
        patch("api.index._pa_wsgi_path", return_value=""),
    ):
        from api.index import deploy

        body, status = deploy()
        assert status == 200
        # Verify we actually invoked git pull (not arbitrary commands).
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "git"
        assert "pull" in cmd
        assert "--ff-only" in cmd


def test_deploy_returns_500_on_git_failure():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "correct"
    fake_result = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: not a git repository\n",
    )
    with (
        patch("bot.config.DEPLOY_SECRET", "correct"),
        patch("api.index.request", mock_request),
        patch("api.index.subprocess.run", return_value=fake_result),
        patch("api.index._pa_wsgi_path", return_value=""),
    ):
        from api.index import deploy

        body, status = deploy()
        assert status == 500
        assert "not a git repository" in body


def test_deploy_touches_wsgi_file_when_on_pa():
    mock_request = MagicMock()
    mock_request.headers.get.return_value = "correct"
    fake_result = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("bot.config.DEPLOY_SECRET", "correct"),
        patch("api.index.request", mock_request),
        patch("api.index.subprocess.run", return_value=fake_result),
        patch(
            "api.index._pa_wsgi_path",
            return_value="/var/www/edisimon_pythonanywhere_com_wsgi.py",
        ),
        patch("api.index.os.utime") as mock_utime,
    ):
        from api.index import deploy

        body, status = deploy()
        assert status == 200
        mock_utime.assert_called_once_with(
            "/var/www/edisimon_pythonanywhere_com_wsgi.py", None
        )


def test_deploy_uses_compare_digest():
    """Constant-time comparison guards against timing-attack secret recovery."""
    import inspect
    from api import index

    src = inspect.getsource(index.deploy)
    assert "hmac.compare_digest" in src
