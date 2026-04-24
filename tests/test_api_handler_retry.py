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
        client.messages.create = AsyncMock(side_effect=[
            TimeoutError("timeout-1"),
            TimeoutError("timeout-2"),
            TimeoutError("timeout-3"),
            TimeoutError("timeout-4"),
            TimeoutError("timeout-5"),
            TimeoutError("timeout-6"),
            FakeClaudeResponse("Recovered text"),
        ])
        sleep_mock = AsyncMock()

        with patch(
            "cogs.ai_core.api.api_handler.convert_to_claude_messages",
            return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        ), patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False), patch(
            "cogs.ai_core.api.api_handler.ERROR_RECOVERY_AVAILABLE",
            False,
        ), patch("cogs.ai_core.api.api_handler.PERF_TRACKER_AVAILABLE", False), patch("cogs.ai_core.api.api_handler.asyncio.sleep", new=sleep_mock):
            result = await call_claude_api(
                client,
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hello"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
            )

        assert result[0] == "Recovered text"
        assert client.messages.create.await_count == 7
        assert [call.args[0] for call in sleep_mock.await_args_list] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]

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

        with patch(
            "cogs.ai_core.api.api_handler.convert_to_claude_messages",
            return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        ), patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False), patch(
            "cogs.ai_core.api.api_handler.asyncio.sleep",
            new=sleep_mock,
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
        client.messages.stream = MagicMock(side_effect=[
            OSError("busy-1"),
            OSError("busy-2"),
            FakeStreamContext(["Recovered via stream"]),
        ])

        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel = MagicMock()
        send_channel.send = AsyncMock(return_value=placeholder)
        fallback_mock = AsyncMock(side_effect=AssertionError("fallback should not run"))
        sleep_mock = AsyncMock()

        with patch(
            "cogs.ai_core.api.api_handler.convert_to_claude_messages",
            return_value=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        ), patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", False), patch(
            "cogs.ai_core.api.api_handler.asyncio.sleep",
            new=sleep_mock,
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
