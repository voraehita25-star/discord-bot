"""Regression tests for Claude retry behavior in api_handler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeClaudeResponse:
    """Minimal Claude response with a single text block."""

    def __init__(self, text: str):
        self.content = [SimpleNamespace(type="text", text=text)]


class FakeTextStream:
    """Async iterator for fake Claude streaming chunks."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


class FakeStreamContext:
    """Async context manager for Claude streaming."""

    def __init__(self, chunks: list[str]):
        self.text_stream = FakeTextStream(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestClaudeCoreRetry:
    @pytest.mark.asyncio
    async def test_call_claude_api_retries_past_five_transient_failures(self):
        """Test that call_claude_api retries up to _CLAUDE_MAX_API_RETRIES (8) times."""
        from cogs.ai_core.api.api_handler import call_claude_api

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=[
                TimeoutError("timeout-1"),
                TimeoutError("timeout-2"),
                TimeoutError("timeout-3"),
                TimeoutError("timeout-4"),
                TimeoutError("timeout-5"),
                TimeoutError("timeout-6"),
                FakeClaudeResponse("Recovered text"),
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch(
                "cogs.ai_core.api.api_handler.convert_to_claude_messages",
                return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            ),
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False),
            patch(
                "cogs.ai_core.api.api_handler.ERROR_RECOVERY_AVAILABLE",
                False,
            ),
            patch("cogs.ai_core.api.api_handler.PERF_TRACKER_AVAILABLE", False),
            patch("cogs.ai_core.api.api_handler.asyncio.sleep", new=sleep_mock),
        ):
            result = await call_claude_api(
                client,
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hello"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
            )

        assert result[0] == "Recovered text"
        assert client.messages.create.await_count == 7
        assert [call.args[0] for call in sleep_mock.await_args_list] == [
            1.0,
            2.0,
            4.0,
            8.0,
            16.0,
            30.0,
        ]

    @pytest.mark.asyncio
    async def test_call_claude_api_streaming_retries_then_falls_back(self):
        """Test that streaming retries are bounded and fall back after exhaustion."""
        from cogs.ai_core.api.api_handler import (
            _CLAUDE_MAX_STREAM_RETRIES,
            call_claude_api_streaming,
        )

        client = MagicMock()
        client.messages = MagicMock()
        # All attempts fail — should exhaust retries and fall back
        client.messages.stream = MagicMock(
            side_effect=[OSError(f"busy-{i}") for i in range(1, _CLAUDE_MAX_STREAM_RETRIES + 2)]
        )

        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel = MagicMock()
        send_channel.send = AsyncMock(return_value=placeholder)
        fallback_mock = AsyncMock(return_value=("fallback text", "", []))
        sleep_mock = AsyncMock()

        with (
            patch(
                "cogs.ai_core.api.api_handler.convert_to_claude_messages",
                return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            ),
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False),
            patch(
                "cogs.ai_core.api.api_handler.asyncio.sleep",
                new=sleep_mock,
            ),
        ):
            result = await call_claude_api_streaming(
                client,
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hello"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
                send_channel,
                fallback_func=fallback_mock,
            )

        # Should fall back after exhausting retries
        assert result[0] == "fallback text"
        fallback_mock.assert_awaited_once()
        assert client.messages.stream.call_count == _CLAUDE_MAX_STREAM_RETRIES

    @pytest.mark.asyncio
    async def test_call_claude_api_streaming_recovers_within_limit(self):
        """Test that streaming succeeds if recovery happens before max retries."""
        from cogs.ai_core.api.api_handler import call_claude_api_streaming

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.stream = MagicMock(
            side_effect=[
                OSError("busy-1"),
                OSError("busy-2"),
                FakeStreamContext(["Recovered via stream"]),
            ]
        )

        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel = MagicMock()
        send_channel.send = AsyncMock(return_value=placeholder)
        fallback_mock = AsyncMock(side_effect=AssertionError("fallback should not run"))
        sleep_mock = AsyncMock()

        with (
            patch(
                "cogs.ai_core.api.api_handler.convert_to_claude_messages",
                return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            ),
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False),
            patch(
                "cogs.ai_core.api.api_handler.asyncio.sleep",
                new=sleep_mock,
            ),
        ):
            result = await call_claude_api_streaming(
                client,
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hello"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
                send_channel,
                fallback_func=fallback_mock,
            )

        assert result[0] == "Recovered via stream"
        assert client.messages.stream.call_count == 3
        fallback_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_streaming_rechecks_breaker_each_attempt_and_short_circuits(self):
        """FINDING 2: the streaming retry loop must re-check the circuit breaker
        on EVERY attempt, mirroring call_claude_api. _CLAUDE_MAX_STREAM_RETRIES
        (6) exceeds the breaker threshold (5) and each failed attempt records a
        failure, so a request's own retries can open the breaker mid-loop; the
        next attempt must short-circuit rather than fire at the sick endpoint."""
        from cogs.ai_core.api.api_handler import (
            _CLAUDE_MAX_STREAM_RETRIES,
            call_claude_api_streaming,
        )

        class FakeBreaker:
            """Minimal breaker mirroring the real failure-threshold semantics."""

            threshold = 5

            def __init__(self):
                self.failures = 0

            def can_execute(self):
                return self.failures < self.threshold

            def record_failure(self):
                self.failures += 1

            def record_success(self):
                self.failures = 0

        breaker = FakeBreaker()

        client = MagicMock()
        client.messages = MagicMock()
        # Every attempt fails transiently, driving record_failure() each time.
        client.messages.stream = MagicMock(
            side_effect=[OSError(f"busy-{i}") for i in range(1, _CLAUDE_MAX_STREAM_RETRIES + 2)]
        )

        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel = MagicMock()
        send_channel.send = AsyncMock(return_value=placeholder)
        # If the per-attempt re-check were missing, the loop would exhaust and
        # fall back here instead of short-circuiting — so the fallback firing is
        # itself the regression signal.
        fallback_mock = AsyncMock(side_effect=AssertionError("must short-circuit, not fall back"))
        sleep_mock = AsyncMock()

        with (
            patch(
                "cogs.ai_core.api.api_handler.convert_to_claude_messages",
                return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            ),
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", True),
            patch("cogs.ai_core.api.api_handler.gemini_circuit", breaker),
            patch("cogs.ai_core.api.api_handler.asyncio.sleep", new=sleep_mock),
        ):
            result = await call_claude_api_streaming(
                client,
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hello"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
                send_channel,
                fallback_func=fallback_mock,
            )

        # The breaker opens after the 5th failed attempt; attempt 6 short-circuits
        # to the "pause/recover" message rather than hitting the endpoint again.
        assert result[0] == "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่"
        assert client.messages.stream.call_count == FakeBreaker.threshold
        assert client.messages.stream.call_count < _CLAUDE_MAX_STREAM_RETRIES
        fallback_mock.assert_not_awaited()


class TestEmptyResponseThinkingFallback:
    """The empty-response fallback must actually DISABLE thinking.

    ``build_api_config`` encodes "thinking off" as an explicit
    ``{"type": "disabled"}`` on the generations that reason by default
    (Opus 5 / Sonnet 5 — see ``data/model_caps.py``). Dropping the key there
    means "use the default", i.e. adaptive thinking ON — so the fallback used
    to do the exact opposite of what it logs, and let ``effort`` un-clamp from
    ``high`` back to ``xhigh`` on the retry. These pin the corrected contract
    per generation.
    """

    @staticmethod
    def _client_empty_then_text():
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=[FakeClaudeResponse(""), FakeClaudeResponse("second try")]
        )
        return client

    @staticmethod
    def _patches(sleep_mock):
        return (
            patch(
                "cogs.ai_core.api.api_handler.convert_to_claude_messages",
                return_value=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            ),
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False),
            patch("cogs.ai_core.api.api_handler.ERROR_RECOVERY_AVAILABLE", False),
            patch("cogs.ai_core.api.api_handler.PERF_TRACKER_AVAILABLE", False),
            patch("cogs.ai_core.api.api_handler.CLAUDE_EFFORT", "xhigh"),
            patch("cogs.ai_core.api.api_handler.asyncio.sleep", new=sleep_mock),
        )

    async def _run(self, model: str, thinking: dict | None):
        from cogs.ai_core.api.api_handler import call_claude_api

        client = self._client_empty_then_text()
        config: dict = {"system_instruction": "Test", "max_tokens": 100}
        if thinking is not None:
            config["thinking"] = thinking
        sleep_mock = AsyncMock()

        p1, p2, p3, p4, p5, p6 = self._patches(sleep_mock)
        with p1, p2, p3, p4, p5, p6:
            result = await call_claude_api(
                client,
                model,
                [{"role": "user", "parts": [{"text": "hi"}]}],
                config,
            )

        assert result[0] == "second try"
        assert client.messages.create.await_count == 2
        return [call.kwargs for call in client.messages.create.await_args_list]

    @pytest.mark.asyncio
    async def test_opus5_disabled_thinking_stays_disabled_on_retry(self):
        first, retry = await self._run("claude-opus-5", {"type": "disabled"})
        # Attempt 1 honours the caller's explicit disable + the required clamp.
        assert first["thinking"] == {"type": "disabled"}
        assert first["output_config"] == {"effort": "high"}
        # The retry must NOT drop the key — dropping it re-enables adaptive
        # thinking on Opus 5 and un-clamps effort back to xhigh.
        assert retry["thinking"] == {"type": "disabled"}
        assert retry["output_config"] == {"effort": "high"}

    @pytest.mark.asyncio
    async def test_opus5_adaptive_thinking_is_disabled_on_retry(self):
        first, retry = await self._run("claude-opus-5", {"type": "adaptive"})
        assert first["thinking"] == {"type": "adaptive"}
        assert first["output_config"] == {"effort": "xhigh"}
        # Adaptive -> explicitly disabled (popping would leave adaptive on).
        assert retry["thinking"] == {"type": "disabled"}
        assert retry["output_config"] == {"effort": "high"}

    @pytest.mark.asyncio
    async def test_pre_opus5_generation_drops_the_field_on_retry(self):
        # On Opus 4.8 and earlier, omitting `thinking` genuinely means "off",
        # and an explicit disable is not part of that generation's contract —
        # so the fallback still removes the key there.
        first, retry = await self._run("claude-opus-4-8", {"type": "adaptive"})
        assert first["thinking"] == {"type": "adaptive"}
        assert "thinking" not in retry
        assert retry["output_config"] == {"effort": "xhigh"}

    @pytest.mark.asyncio
    async def test_always_on_model_drops_the_field_on_retry(self):
        # Fable/Mythos 400 on an explicit disable, so the key must be removed
        # rather than set — the turn simply keeps thinking.
        first, retry = await self._run("claude-fable-5", {"type": "adaptive"})
        assert first["thinking"] == {"type": "adaptive"}
        assert "thinking" not in retry
