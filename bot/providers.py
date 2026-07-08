import base64
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
    IMAGE_PROVIDERS,
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


def _extract_error_detail(resp) -> str:
    """Pull a human-readable reason out of an error response.

    The ``error`` field may be a string or an OpenAI-style nested object, so
    coerce to ``str`` — ``"loading" in detail.lower()`` must never raise.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            err = err.get("message") or err.get("type")
        detail = err or body.get("message") or ""
    else:
        detail = body
    return str(detail)[:200]


def _request_image(provider: str, prompt: str, deadline: float) -> bytes:
    """Ask one HF Inference Provider to generate an image; return raw bytes.

    Uses the OpenAI-compatible endpoint
    ``{IMAGE_API_BASE}/{provider}/v1/images/generations`` with
    ``response_format=b64_json`` so the image comes back as base64 inside the
    JSON body (fetchable on PA's whitelist — no CDN download needed).

    Raises ``RuntimeError`` on failure; the message is prefixed with a category
    (``auth:`` / ``billing:`` / ``model:`` / ``timeout:`` / ``provider:``) so
    the caller knows whether trying the next provider would help.
    """
    url = f"{IMAGE_API_BASE.rstrip('/')}/{provider}/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"model": IMAGE_MODEL, "prompt": prompt, "response_format": "b64_json"}
    last_detail = ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise RuntimeError(f"timeout: {last_detail or 'image generation timed out'}")
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=min(IMAGE_REQUEST_TIMEOUT, remaining),
            )
        except requests.RequestException as e:
            raise RuntimeError(f"network: image request failed: {e}") from e

        code = resp.status_code
        if code == 200:
            try:
                item = resp.json()["data"][0]
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise RuntimeError(
                    f"provider: unexpected response from {provider}: {e}"
                ) from e
            b64 = item.get("b64_json")
            if b64:
                try:
                    return base64.b64decode(b64)
                except (ValueError, TypeError) as e:
                    raise RuntimeError(f"provider: bad base64 from {provider}: {e}") from e
            # A URL-only reply points at a CDN PA can't reach — treat as a
            # per-provider problem so the next provider is tried.
            if item.get("url"):
                raise RuntimeError(f"model: {provider} returned a URL, not image bytes")
            raise RuntimeError(f"provider: no image in {provider} response")

        last_detail = _extract_error_detail(resp)

        # A cold model (503 / "loading") is transient — wait and retry while
        # the time budget allows.
        if (code == 503 or "loading" in last_detail.lower()) and (
            deadline - time.monotonic()
        ) > 4:
            time.sleep(3)
            continue

        # auth/billing are token-config problems no other provider will fix.
        if code in (401, 403):
            raise RuntimeError(
                f"auth: HF token rejected (HTTP {code}) — check HF_TOKEN has the "
                f"'Make calls to Inference Providers' permission. {last_detail}"
            )
        if code == 402:
            raise RuntimeError(
                f"billing: HF inference credits exhausted (HTTP 402) — the free "
                f"monthly quota is used up or billing isn't enabled. {last_detail}"
            )
        # 4xx model issues and 5xx provider outages are both worth trying the
        # next provider (a provider-side 500 often clears by switching).
        if code in (400, 404) or code >= 500 or "not supported" in last_detail.lower():
            raise RuntimeError(f"model: {provider} unavailable (HTTP {code}). {last_detail}")
        raise RuntimeError(f"provider: HTTP {code}. {last_detail}")


def generate_image(prompt: str) -> bytes:
    """Generate an image from a text prompt via HF Inference Providers.

    Tries each provider in ``IMAGE_PROVIDERS`` in order, sharing one wall-clock
    budget. A ``model:`` / ``provider:`` failure (model unavailable, outage,
    URL-only reply) rolls on to the next provider; ``auth:`` and ``billing:``
    failures abort immediately (no other provider will fix a bad token or an
    empty credit balance).

    Raises ``RuntimeError`` with a short, categorized message on any failure so
    the handler can log the real reason and surface a clean apology.
    """
    if not HF_TOKEN:
        raise RuntimeError("image generation is not configured (HF_TOKEN is unset)")
    if not IMAGE_PROVIDERS:
        raise RuntimeError("image generation is not configured (no IMAGE_PROVIDERS set)")

    deadline = time.monotonic() + IMAGE_REQUEST_TIMEOUT
    last_error = None
    for provider in IMAGE_PROVIDERS:
        if deadline - time.monotonic() <= 1:
            break
        try:
            return _request_image(provider, prompt, deadline)
        except RuntimeError as e:
            last_error = e
            # Only a per-provider problem is worth another attempt; a token or
            # billing problem is global, so stop and report it.
            if not str(e).startswith(("model:", "provider:", "network:")):
                raise
            print(f"Image provider fallback: {e}")
    raise last_error or RuntimeError("image generation failed")
