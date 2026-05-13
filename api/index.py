import hmac
import os
import subprocess
from flask import Flask, request

app = Flask(__name__)


@app.route("/api/health")
@app.route("/api/index")
def health():
    # Keep this endpoint dependency-free so uptime pings don't trigger
    # Telegram/store/AI client init.
    return "OK", 200


@app.route("/api/webhook", methods=["POST"])
def webhook():
    # Verify the secret BEFORE any heavy imports. bot.config only reads
    # env vars, no network. bot.clients/handlers/telebot would otherwise
    # trigger bot.get_me() on every cold start — including for forged or
    # mis-secreted POSTs.
    from bot.config import WEBHOOK_SECRET

    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            return "Forbidden", 403

    # Authenticated — now pull the heavyweight modules.
    import telebot
    import bot.handlers  # noqa: F401 — registers @bot.message_handler decorators
    from bot.clients import bot

    raw = request.get_data(as_text=True)
    try:
        update = telebot.types.Update.de_json(raw)
    except Exception as e:
        print(f"Malformed update: {e}")
        return "Bad Request", 400
    if update is None:
        return "Bad Request", 400

    # Dedupe Telegram retries: when our function times out or crashes,
    # Telegram resends the same update_id. We mark "done" only AFTER
    # process_new_updates returns successfully, so a real failure still
    # lets the retry reach the handler.
    update_id = getattr(update, "update_id", None)
    if update_id is not None:
        from bot.dedupe import is_processed, mark_processed

        if is_processed(update_id):
            return "OK", 200
        bot.process_new_updates([update])
        mark_processed(update_id)
    else:
        bot.process_new_updates([update])
    return "OK", 200


# Project root — used by /api/deploy to scope `git pull` correctly.
# api/index.py is at <repo>/api/index.py, so two dirname() calls give us the repo root.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pa_wsgi_path() -> str:
    """Return the PythonAnywhere WSGI file path for the current user, or
    empty string if not running on PA. Touching this file triggers a
    graceful worker reload on the next request."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if not user:
        return ""
    candidate = f"/var/www/{user}_pythonanywhere_com_wsgi.py"
    return candidate if os.path.exists(candidate) else ""


@app.route("/api/deploy", methods=["POST"])
def deploy():
    """Auto-deploy webhook. Pulls the latest commit and reloads the PA worker.

    Verifies an X-Deploy-Secret header against DEPLOY_SECRET. Fail-closed:
    returns 403 if the env var is unset, so a misconfigured deploy can't
    accidentally allow arbitrary callers to trigger code execution.
    """
    from bot.config import DEPLOY_SECRET

    if not DEPLOY_SECRET:
        return "Deploy endpoint disabled (DEPLOY_SECRET unset)", 403

    provided = request.headers.get("X-Deploy-Secret", "")
    if not hmac.compare_digest(provided, DEPLOY_SECRET):
        return "Forbidden", 403

    try:
        result = subprocess.run(
            ["git", "-C", _PROJECT_ROOT, "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "git pull timed out", 504

    if result.returncode != 0:
        return f"git pull failed:\n{result.stderr}", 500

    # Re-register the webhook in case WEBHOOK_URL changed, the secret
    # rotated, or the previous registration was cleared (e.g. by a local
    # polling session). Idempotent and best-effort.
    webhook_status = ""
    try:
        from bot.clients import register_webhook

        webhook_status = "\n" + register_webhook()
    except Exception as e:
        webhook_status = f"\nWebhook registration failed: {e}"

    # Touch the PA WSGI file so the next request boots a fresh worker
    # with the new code. No-op when not running on PA.
    wsgi_path = _pa_wsgi_path()
    if wsgi_path:
        os.utime(wsgi_path, None)

    return f"OK\n{result.stdout}{webhook_status}", 200
