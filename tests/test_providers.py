import base64
from unittest.mock import patch, MagicMock


# ── _call_main retry logic ──────────────────────────────────────────────────


def test_call_main_retries_on_failure():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    with (
        patch("bot.providers.ai") as mock_ai,
        patch("bot.providers.time.sleep") as mock_sleep,
    ):
        mock_ai.chat.completions.create.side_effect = [
            Exception("network error"),
            mock_response,
        ]
        from bot.providers import _call_main

        result = _call_main([{"role": "user", "content": "hi"}])
        assert result == "hello"
        assert mock_ai.chat.completions.create.call_count == 2
        mock_sleep.assert_called_once_with(1)


def test_call_main_raises_after_max_retries():
    with patch("bot.providers.ai") as mock_ai, patch("bot.providers.time.sleep"):
        mock_ai.chat.completions.create.side_effect = Exception("persistent")
        from bot.providers import _call_main

        try:
            _call_main([{"role": "user", "content": "hi"}], retries=3)
            assert False, "Should have raised"
        except Exception as e:
            assert str(e) == "persistent"
        assert mock_ai.chat.completions.create.call_count == 3


def test_call_main_succeeds_first_try():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"
    with (
        patch("bot.providers.ai") as mock_ai,
        patch("bot.providers.time.sleep") as mock_sleep,
    ):
        mock_ai.chat.completions.create.return_value = mock_response
        from bot.providers import _call_main

        assert _call_main([{"role": "user", "content": "hi"}]) == "ok"
        mock_sleep.assert_not_called()


# ── _last_user_message ────────────────────────────────────────────────────────


def test_last_user_message_skips_system():
    from bot.providers import _last_user_message

    result = _last_user_message(
        [
            {"role": "system", "content": "you are a bot"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert result == "hi"


def test_last_user_message_returns_most_recent():
    from bot.providers import _last_user_message

    messages = []
    for i in range(5):
        messages.append({"role": "user", "content": f"u{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})
    # No trailing user message — most recent user is u4
    assert _last_user_message(messages) == "u4"


def test_last_user_message_empty_when_no_user_turn():
    from bot.providers import _last_user_message

    assert _last_user_message([{"role": "system", "content": "x"}]) == ""


# ── _strip_html ───────────────────────────────────────────────────────────────


def test_strip_html_removes_tags():
    from bot.providers import _strip_html

    assert _strip_html("<div>hello <b>world</b></div>") == "hello world"


def test_strip_html_preserves_text_without_tags():
    from bot.providers import _strip_html

    assert _strip_html("plain text") == "plain text"


# ── _call_hf ──────────────────────────────────────────────────────────────────


def test_call_hf_calls_gradio_client():
    mock_client = MagicMock()
    mock_client.predict.return_value = ("<p>Armenian response</p>", "done")
    with patch("bot.providers.HF_SPACE_ID", "edisimon/armgpt-demo"):
        import gradio_client

        with patch.object(
            gradio_client, "Client", return_value=mock_client
        ) as mock_cls:
            from bot.providers import _call_hf, HF_REQUEST_TIMEOUT

            result = _call_hf([{"role": "user", "content": "Բարև"}])
            mock_cls.assert_called_once_with(
                "edisimon/armgpt-demo",
                hf_token=None,
                httpx_kwargs={"timeout": HF_REQUEST_TIMEOUT},
            )
            mock_client.predict.assert_called_once()
            assert "Armenian response" in result


def test_call_hf_handles_plain_string_result():
    mock_client = MagicMock()
    mock_client.predict.return_value = "just text"
    with patch("bot.providers.HF_SPACE_ID", "fake/space"):
        import gradio_client

        with patch.object(gradio_client, "Client", return_value=mock_client):
            from bot.providers import _call_hf

            assert _call_hf([{"role": "user", "content": "hi"}]) == "just text"


def test_call_hf_no_retry_on_failure():
    mock_client = MagicMock()
    mock_client.predict.side_effect = Exception("HF down")
    with patch("bot.providers.HF_SPACE_ID", "fake/space"):
        import gradio_client

        with patch.object(gradio_client, "Client", return_value=mock_client):
            from bot.providers import _call_hf

            try:
                _call_hf([{"role": "user", "content": "hi"}])
                assert False, "Should have raised"
            except Exception as e:
                assert "HF down" in str(e)
            # Only one call — no retry
            assert mock_client.predict.call_count == 1


# ── generate dispatch ─────────────────────────────────────────────────────────


def test_generate_dispatches_to_main():
    with (
        patch("bot.providers.get_provider", return_value="main"),
        patch("bot.providers._call_main", return_value="main reply") as mock_main,
        patch("bot.providers._call_hf") as mock_hf,
    ):
        from bot.providers import generate

        assert generate(123, [{"role": "user", "content": "hi"}]) == "main reply"
        mock_main.assert_called_once()
        mock_hf.assert_not_called()


def test_generate_dispatches_to_hf():
    with (
        patch("bot.providers.get_provider", return_value="hf"),
        patch("bot.providers._call_main") as mock_main,
        patch("bot.providers._call_hf", return_value="hf reply") as mock_hf,
    ):
        from bot.providers import generate

        assert generate(123, [{"role": "user", "content": "hi"}]) == "hf reply"
        mock_hf.assert_called_once()
        mock_main.assert_not_called()


# ── generate_image ──────────────────────────────────────────────────────────


def _img_ok(raw: bytes):
    """A 200 image response carrying base64-encoded bytes in OpenAI shape."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"b64_json": base64.b64encode(raw).decode()}]}
    return resp


def _img_err(status: int, message: str):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"error": message}
    return resp


def test_generate_image_returns_bytes_on_success():
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_API_BASE", "https://router.example"),
        patch("bot.providers.IMAGE_MODEL", "some/model"),
        patch("bot.providers.IMAGE_PROVIDERS", ["nscale"]),
        patch("bot.providers.requests.post", return_value=_img_ok(b"\x89PNG-bytes")) as mock_post,
    ):
        from bot.providers import generate_image

        assert generate_image("a red apple") == b"\x89PNG-bytes"
        # Hits the provider's OpenAI-compatible image endpoint with model+prompt
        args, kwargs = mock_post.call_args
        assert args[0] == "https://router.example/nscale/v1/images/generations"
        assert kwargs["json"]["model"] == "some/model"
        assert kwargs["json"]["prompt"] == "a red apple"
        assert kwargs["json"]["response_format"] == "b64_json"
        assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_generate_image_raises_without_token():
    with patch("bot.providers.HF_TOKEN", ""):
        from bot.providers import generate_image

        try:
            generate_image("anything")
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "not configured" in str(e)


def test_generate_image_retries_on_cold_model_then_succeeds():
    """A 503 'model loading' is transient: wait and retry within the budget,
    then return the image once the model is warm."""
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_PROVIDERS", ["nscale"]),
        patch("bot.providers.time.sleep") as mock_sleep,
        patch(
            "bot.providers.requests.post",
            side_effect=[_img_err(503, "Model is currently loading"), _img_ok(b"warm-image")],
        ) as mock_post,
    ):
        from bot.providers import generate_image

        assert generate_image("a cat") == b"warm-image"
        assert mock_post.call_count == 2
        mock_sleep.assert_called()  # waited between the cold 503 and the retry


def test_generate_image_raises_immediately_on_auth_error():
    """A 401 (bad token / missing permission) fails fast and does NOT try the
    next provider — no other provider would accept the same bad token."""
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_PROVIDERS", ["nscale", "together"]),
        patch("bot.providers.time.sleep") as mock_sleep,
        patch(
            "bot.providers.requests.post", return_value=_img_err(401, "Invalid credentials")
        ) as mock_post,
    ):
        from bot.providers import generate_image

        try:
            generate_image("a cat")
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "auth" in str(e)
            assert "Invalid credentials" in str(e)
        assert mock_post.call_count == 1  # did not try the second provider
        mock_sleep.assert_not_called()


def test_generate_image_falls_back_to_next_provider_on_5xx():
    """A provider outage (500) rolls on to the next provider, which succeeds."""
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_PROVIDERS", ["nscale", "together"]),
        patch(
            "bot.providers.requests.post",
            side_effect=[_img_err(500, "Internal Error"), _img_ok(b"fallback-image")],
        ) as mock_post,
    ):
        from bot.providers import generate_image

        assert generate_image("a cat") == b"fallback-image"
        assert mock_post.call_count == 2  # first provider down, second worked


def test_generate_image_billing_error_aborts_without_fallback():
    """A billing error (402) is global — no other provider fixes it, so the
    command fails fast without trying the fallback provider."""
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_PROVIDERS", ["nscale", "together"]),
        patch(
            "bot.providers.requests.post",
            return_value=_img_err(402, "You have exceeded your monthly credits"),
        ) as mock_post,
    ):
        from bot.providers import generate_image

        try:
            generate_image("a cat")
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "billing" in str(e)
        assert mock_post.call_count == 1  # did not try the fallback provider
