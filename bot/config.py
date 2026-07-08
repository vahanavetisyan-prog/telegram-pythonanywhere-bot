import os
import secrets as _secrets_mod
import subprocess as _subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEBHOOK_SECRET_FILE = _PROJECT_ROOT / ".webhook_secret"


def _get_commit_sha() -> str:
    """Return the short SHA of the deployed commit, or an empty string.

    Computed once at module import — so the value reflects the worker's
    actual code, not whatever `git pull` did since boot. The auto-deploy
    flow touches the WSGI file on pull, which spawns a fresh worker on
    the next request with the new SHA. This makes /about a reliable
    "what version is live right now" probe.
    """
    try:
        result = _subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (_subprocess.SubprocessError, OSError):
        pass
    return ""


COMMIT_SHA = _get_commit_sha()


def _bootstrap_webhook_secret(file_path: Path = _WEBHOOK_SECRET_FILE) -> str:
    """Return WEBHOOK_SECRET from env if set; otherwise read/generate a
    persistent random secret in `file_path`.

    This makes the webhook signed-by-default: a fresh PA deploy with no
    manual `openssl rand` step still rejects forged updates because the
    bot auto-generates and persists a 64-hex-char secret on first run,
    then registers it with Telegram via the boot-time `register_webhook()`.

    Precedence: env var > on-disk file > newly generated. Filesystem
    errors fall back to the empty string so a read-only mount can't
    crash worker boot — the webhook just stays unsigned in that case.
    """
    env_value = os.environ.get("WEBHOOK_SECRET", "").strip()
    if env_value:
        return env_value
    try:
        if file_path.exists():
            existing = file_path.read_text().strip()
            # Empty or whitespace-only file: treat as missing and regenerate,
            # otherwise we'd silently disable webhook auth.
            if existing:
                return existing
        new_secret = _secrets_mod.token_hex(32)
        file_path.write_text(new_secret)
        try:
            os.chmod(file_path, 0o600)
        except OSError:
            pass  # best-effort tightening; Windows / odd mounts can skip
        print(f"Generated webhook secret at {file_path} (auto-bootstrap)")
        return new_secret
    except OSError as e:
        print(f"Could not persist webhook secret ({e}); webhook will be unsigned")
        return ""


# Telegram
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
WEBHOOK_SECRET = _bootstrap_webhook_secret()

# When set, the bot auto-registers this URL as the Telegram webhook on
# worker boot and after every /api/deploy. Leave unset for local
# polling (run_local.py). Example value on PA:
#   WEBHOOK_URL=https://<your-pa-username>.pythonanywhere.com/api/webhook
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()

# AI provider
AI_API_KEY = os.environ["AI_API_KEY"].strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.cerebras.ai/v1").strip()
MODEL = os.environ.get("AI_MODEL", "gpt-oss-120b").strip()

# Hugging Face provider (optional) — when set, users can switch via /model
HF_SPACE_ID = os.environ.get("HF_SPACE_ID", "").strip()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()  # optional, for private spaces
DEFAULT_PROVIDER = "main"

# Image generation (optional) — powers the /createimage command. Uses the
# Hugging Face Inference API (the huggingface.co family is on PA's free-tier
# outbound whitelist). Requires HF_TOKEN — HF's hosted inference rejects
# anonymous calls. IMAGE_MODEL can be any HF text-to-image model id.
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell").strip()
# Router root. Image calls hit the OpenAI-compatible endpoint
# {IMAGE_API_BASE}/{provider}/v1/images/generations, which returns the image as
# base64 inside a JSON body. That body comes back over router.huggingface.co
# (on PA's free-tier whitelist), unlike providers that reply with an image URL
# on a CDN PA can't reach. The old /hf-inference/models raw-bytes endpoint was
# dropped: hf-inference is deprecating text-to-image models and returning 500s.
IMAGE_API_BASE = os.environ.get("IMAGE_API_BASE", "https://router.huggingface.co").strip()
# Ordered HF Inference Providers to try for IMAGE_MODEL; first success wins.
# nscale/together serve FLUX.1-schnell and return base64 JSON. Comma-separated.
IMAGE_PROVIDERS = [
    p.strip()
    for p in os.environ.get("IMAGE_PROVIDERS", "nscale,together").split(",")
    if p.strip()
]
# Wall-clock cap on the image call. Text-to-image is slow (cold starts +
# diffusion steps); keep it under Telegram's ~60s webhook window.
IMAGE_REQUEST_TIMEOUT = int(os.environ.get("IMAGE_REQUEST_TIMEOUT", "55"))

# Storage — optional. When SQLITE_PATH is unset the bot runs in
# stateless mode: history / rate limiting / preferences / dedupe all
# degrade gracefully (the consumer modules in bot/ check `store is
# None` at the top of every function and return safe defaults).
SQLITE_PATH = os.environ.get("SQLITE_PATH", "").strip()

# Label shown by the /about command. Defaults to "PythonAnywhere" since
# that is the documented deployment target. Override to suit your host.
HOSTING_LABEL = os.environ.get("HOSTING_LABEL", "PythonAnywhere").strip()

# Auto-deploy webhook secret. When set, /api/deploy accepts requests
# that present this value in the X-Deploy-Secret header and runs
# `git pull` + WSGI reload. When unset, /api/deploy returns 403 — the
# endpoint is fail-closed.
DEPLOY_SECRET = os.environ.get("DEPLOY_SECRET", "").strip()

# App
#
# This prompt gates FREE-FORM chat only (the `handle_message` -> `ask_ai` path).
# Slash commands never reach the model as "/command" text — Telegram routes
# them to their dedicated handler in bot/handlers.py first, which sends the
# model an expanded prompt (e.g. /roast -> "Write a roast of Bob"). So trying
# to whitelist "/help, /roast, ..." here would never match anything. Commands
# that should bypass this programming-only filter call ask_ai(..., system_prompt=None)
# or generate() directly instead.
#
# NOTE on formatting: these are adjacent string literals Python concatenates at
# parse time. Each fragment MUST end with a trailing space, or sentences run
# together ("coding.You must ...").
SYSTEM_PROMPT = (
    "You are a helpful and concise AI assistant. "
    "Your only role is to answer questions about programming, software "
    "development, and coding logic. "
    "If a user asks about anything that is NOT related to programming or coding, "
    "do not answer it. Instead reply with exactly this sentence and nothing else: "
    '"I don\'t answer questions about that. I answer questions about programming and coding." '
    "When a question IS about programming, answer step-by-step, ask clarifying "
    "questions when needed, and stay respectful, clear, and brief. "
    'If you do not know an answer, say "I don\'t know." '
    "Always reply in the same language the user used."
)
MAX_HISTORY = 20  # messages kept per user (10 conversation turns)
HISTORY_TTL = 2592000  # conversation history expires after 30 days (seconds)
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "250"))  # max messages per user per day

# Comma-separated whitelist of Telegram users. Each entry is either a
# username (with or without leading @) or a numeric user_id. Empty
# (default) means everyone can talk to the bot. When non-empty, the
# bot stays silent for anyone not in the list — silence instead of a
# rejection message so scanners don't get confirmation the bot exists.
#
# Example: ALLOWED_USERS=@alice,bob,123456789
ALLOWED_USERS = [
    u.strip().lstrip("@")
    for u in os.environ.get("ALLOWED_USERS", "").split(",")
    if u.strip()
]
MAX_MSG_LEN = 4096  # Telegram's character limit per message
# Provider call budget. Total worst case =
# AI_RETRIES * AI_REQUEST_TIMEOUT + sum of backoff sleeps. With
# retries=2 and timeout=25s plus 1s backoff: 25 + 1 + 25 = 51s.
AI_REQUEST_TIMEOUT = 25  # seconds, applied per-attempt to OpenAI-compatible calls
AI_RETRIES = 2  # total attempts (not extra retries) — 2 means one retry on failure
# HF Gradio request timeout. Without this a hung `predict()` would occupy the
# PA worker indefinitely; combined with the dedupe pre-claim, Telegram's
# retries get silently dropped for ~10 min. Tuned to give ArmGPT enough
# headroom for cold-start jitter while still freeing the worker before
# Telegram's webhook timeout (~60s).
HF_REQUEST_TIMEOUT = 50
