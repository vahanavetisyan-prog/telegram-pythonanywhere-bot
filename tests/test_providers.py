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


def test_generate_image_returns_bytes_on_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/png"}
    mock_resp.content = b"\x89PNG-bytes"
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_API_BASE", "https://router.example/models"),
        patch("bot.providers.IMAGE_MODEL", "some/model"),
        patch("bot.providers.requests.post", return_value=mock_resp) as mock_post,
    ):
        from bot.providers import generate_image

        assert generate_image("a red apple") == b"\x89PNG-bytes"
        # URL is joined without a double slash, and the prompt is sent as inputs
        args, kwargs = mock_post.call_args
        assert args[0] == "https://router.example/models/some/model"
        assert kwargs["json"] == {"inputs": "a red apple"}
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
    loading = MagicMock()
    loading.status_code = 503
    loading.headers = {"content-type": "application/json"}
    loading.json.return_value = {"error": "Model is currently loading"}

    ok = MagicMock()
    ok.status_code = 200
    ok.headers = {"content-type": "image/png"}
    ok.content = b"warm-image"

    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.time.sleep") as mock_sleep,
        patch(
            "bot.providers.requests.post", side_effect=[loading, ok]
        ) as mock_post,
    ):
        from bot.providers import generate_image

        assert generate_image("a cat") == b"warm-image"
        assert mock_post.call_count == 2
        mock_sleep.assert_called()  # waited between the cold 503 and the retry


def test_generate_image_raises_immediately_on_fatal_error():
    """A non-retryable error (e.g. bad token → 401) fails fast with the
    provider's message, without retrying."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"error": "Invalid credentials"}
    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.time.sleep") as mock_sleep,
        patch("bot.providers.requests.post", return_value=mock_resp) as mock_post,
    ):
        from bot.providers import generate_image

        try:
            generate_image("a cat")
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "Invalid credentials" in str(e)
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()


def test_generate_image_falls_back_to_next_model_on_model_error():
    """A per-model error (404 / not-supported) rolls on to the next fallback
    model; the second model's image bytes are returned."""
    unavailable = MagicMock()
    unavailable.status_code = 404
    unavailable.headers = {"content-type": "application/json"}
    unavailable.json.return_value = {"error": "Model not found"}

    ok = MagicMock()
    ok.status_code = 200
    ok.headers = {"content-type": "image/png"}
    ok.content = b"fallback-image"

    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_MODEL", "primary/model"),
        patch("bot.providers.requests.post", side_effect=[unavailable, ok]) as mock_post,
    ):
        from bot.providers import generate_image

        assert generate_image("a cat") == b"fallback-image"
        assert mock_post.call_count == 2  # primary failed, fallback succeeded


def test_generate_image_billing_error_aborts_without_fallback():
    """A billing error (402) is global — no other model would fix it, so the
    command fails fast without trying fallback models."""
    broke = MagicMock()
    broke.status_code = 402
    broke.headers = {"content-type": "application/json"}
    broke.json.return_value = {"error": "You have exceeded your monthly credits"}

    with (
        patch("bot.providers.HF_TOKEN", "tok"),
        patch("bot.providers.IMAGE_MODEL", "primary/model"),
        patch("bot.providers.requests.post", return_value=broke) as mock_post,
    ):
        from bot.providers import generate_image

        try:
            generate_image("a cat")
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "billing" in str(e)
        assert mock_post.call_count == 1  # did not try any fallback model
