import re
import time

import requests

from bot.clients import ai
from bot.config import (
    AI_REQUEST_TIMEOUT,
    AI_RETRIES,
    HF_REQUEST_TIMEOUT,
    HF_SPACE_ID,
    HF_TOKEN,
    IMAGE_API_BASE,
    IMAGE_MODEL,
    IMAGE_REQUEST_TIMEOUT,
    MODEL,
)
from bot.preferences import get_provider

# HF Gradio knobs — hardcoded defaults for ArmGPT
# 80 tokens at ~5 tok/s ≈ 16s. Must finish well inside Telegram's webhook
# timeout (~60s) accounting for HF cold-start jitter and network round-trips.
HF_LENGTH = 100
HF_TEMPERATURE = 0.6
HF_TOP_K = 30


def _call_main(messages: list, retries: int = AI_RETRIES):
    """Call the OpenAI-compatible API with bounded retries.

    Each attempt is capped by AI_REQUEST_TIMEOUT and the per-attempt timeout
    is dynamically reduced if the wall-clock budget is shrinking, so total
    elapsed time stays under Telegram's ~60s webhook window even on the worst path.
    """
    deadline = time.monotonic() + AI_REQUEST_TIMEOUT * retries + retries
    for attempt in range(retries):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("AI provider deadline exceeded")
        timeout = min(AI_REQUEST_TIMEOUT, remaining)
        try:
            response = ai.chat.completions.create(
                model=MODEL,
                messages=messages,
                timeout=timeout,
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = min(2**attempt, max(0, deadline - time.monotonic()))
            print(
                f"AI call failed (attempt {attempt + 1}/{retries}): {e} — retrying in {wait}s"
            )
            time.sleep(wait)


def _last_user_message(messages: list) -> str:
    """Return only the most recent user message.

    ArmGPT is a base completion model trained on raw Armenian text — it has
    no concept of chat turns. Feeding it a "User: ...\\nAssistant:" transcript
    just confuses it. Pass the bare user prompt and let the model continue.
    """
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def _strip_html(text: str) -> str:
    """Remove HTML tags from Gradio output."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _call_hf(messages: list) -> str:
    """Call the Hugging Face Gradio space. No retry — HF is slow."""
    from gradio_client import Client

    prompt = _last_user_message(messages)
    # httpx_kwargs caps every underlying HTTP call (config fetch + predict)
    # so a hung Space can't wedge the PA worker past Telegram's webhook
    # timeout — without it, dedupe pre-claim would silently swallow retries.
    client = Client(
        HF_SPACE_ID,
        hf_token=HF_TOKEN or None,
        httpx_kwargs={"timeout": HF_REQUEST_TIMEOUT},
    )
    result = client.predict(
        prompt,
        HF_LENGTH,
        HF_TEMPERATURE,
        HF_TOP_K,
        api_name="/generate",
    )
    # Gradio predict returns the final yielded value. For this space it's a
    # tuple (html_output, status_text). We only want the text.
    if isinstance(result, (tuple, list)) and len(result) >= 1:
        text = result[0]
    else:
        text = result
    text = _strip_html(str(text))
    # Remove the echoed prompt if the model includes it
    if text.startswith(prompt):
        text = text[len(prompt) :].strip()
    return text or "(empty response from ArmGPT)"


def generate(user_id: int, messages: list) -> str:
    """Dispatch to the user's chosen AI provider and return a reply string."""
    provider = get_provider(user_id)
    if provider == "hf":
        return _call_hf(messages)
    return _call_main(messages)


# Byte-returning fallback models on the hf-inference provider. All stream
# raw image bytes back through router.huggingface.co (the only image host on
# PA's free-tier outbound whitelist — URL-returning providers like fal-ai
# would hand back a fal.media link the PA worker can't fetch). Tried in order
# after the configured IMAGE_MODEL, so a model that's momentarily unavailable
# (404 / not-supported) doesn't sink the whole command.
_IMAGE_FALLBACK_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
]


def _extract_error_detail(resp) -> str:
    """Pull a human-readable reason out of a non-image HF response.

    HF's ``error`` field is usually a string but can be a list/dict, so coerce
    to ``str`` — ``"loading" in detail.lower()`` must never raise.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        detail = body.get("error") or body.get("message") or ""
    else:
        detail = body
    return str(detail)[:200]


def _request_image(model: str, prompt: str, deadline: float) -> bytes:
    """POST one model to the hf-inference endpoint, retrying only cold starts.

    Returns image bytes on success. Raises ``RuntimeError`` on failure; the
    message is prefixed with a category (``auth:`` / ``billing:`` / ``model:``
    / ``timeout:``) so the caller can decide whether trying another model helps.
    """
    url = f"{IMAGE_API_BASE.rstrip('/')}/{model}"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        # Ask HF to hold the request until the model is warm instead of
        # returning an immediate 503 on a cold start. Honored by the
        # Inference API; harmless where it isn't (we also retry 503 below).
        "x-wait-for-model": "true",
    }
    last_detail = ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise RuntimeError(f"timeout: {last_detail or 'image generation timed out'}")
        try:
            resp = requests.post(
                url,
                headers=headers,
                json={"inputs": prompt},
                timeout=min(IMAGE_REQUEST_TIMEOUT, remaining),
            )
        except requests.RequestException as e:
            raise RuntimeError(f"network: image request failed: {e}") from e

        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and content_type.startswith("image/"):
            return resp.content

        last_detail = _extract_error_detail(resp)
        code = resp.status_code

        # A cold model (503 / "loading") is transient — wait and retry while
        # the time budget allows.
        if (code == 503 or "loading" in last_detail.lower()) and (
            deadline - time.monotonic()
        ) > 4:
            time.sleep(3)
            continue

        # Classify the fatal errors. auth/billing are token-config problems
        # that no other model will fix; model errors are worth a fallback.
        if code in (401, 403):
            raise RuntimeError(
                f"auth: HF token rejected (HTTP {code}) — check HF_TOKEN has "
                f"'Make calls to Inference Providers' permission. {last_detail}"
            )
        if code == 402:
            raise RuntimeError(
                f"billing: HF inference credits exhausted (HTTP 402) — the free "
                f"monthly quota is used up or billing isn't enabled. {last_detail}"
            )
        if code in (404, 400) or "not supported" in last_detail.lower():
            raise RuntimeError(f"model: '{model}' unavailable (HTTP {code}). {last_detail}")
        raise RuntimeError(f"provider: HTTP {code}. {last_detail}")


def generate_image(prompt: str) -> bytes:
    """Generate an image from a text prompt via the Hugging Face Inference API.

    Tries the configured ``IMAGE_MODEL`` first, then a small list of
    byte-returning fallback models on the same whitelisted hf-inference
    endpoint. A ``model:`` failure (unavailable / not-supported) rolls on to
    the next candidate; ``auth:`` and ``billing:`` failures abort immediately
    (no other model will fix a bad token or empty credit balance).

    Raises ``RuntimeError`` with a short, categorized message on any failure so
    the handler can log the real reason and surface a clean apology.
    """
    if not HF_TOKEN:
        raise RuntimeError("image generation is not configured (HF_TOKEN is unset)")

    # Configured model first, then fallbacks, de-duplicated, order preserved.
    candidates = [IMAGE_MODEL] + [m for m in _IMAGE_FALLBACK_MODELS if m != IMAGE_MODEL]

    deadline = time.monotonic() + IMAGE_REQUEST_TIMEOUT
    last_error = None
    for model in candidates:
        if deadline - time.monotonic() <= 1:
            break
        try:
            return _request_image(model, prompt, deadline)
        except RuntimeError as e:
            last_error = e
            # Only a per-model problem is worth another attempt; a token or
            # billing problem is global, so stop and report it.
            if not str(e).startswith("model:"):
                raise
            print(f"Image model fallback: {e}")
    raise last_error or RuntimeError("image generation failed")
