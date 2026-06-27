"""Tests for dashboard_chat_claude.py retry behavior."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeWS:
    """Minimal fake WebSocketResponse."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    def find(self, msg_type: str) -> list[dict]:
        return [message for message in self.sent if message.get("type") == msg_type]


@pytest.fixture()
def ws() -> FakeWS:
    return FakeWS()


class FakeClaudeStream:
    """Fake Claude streaming response."""

    def __init__(self, events: list[object]):
        self._events = events
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def get_final_message(self):
        return None


class FakeClaudeStreamContext:
    """Async context manager that either raises or yields a fake Claude stream."""

    def __init__(self, outcome: Exception | list[object]):
        self._outcome = outcome

    async def __aenter__(self):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return FakeClaudeStream(self._outcome)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeClaudeClient:
    """Fake Claude client that can fail multiple times before succeeding."""

    def __init__(self, outcomes: list[Exception | list[object]]):
        self._outcomes = outcomes
        self._attempts = 0
        self.messages = SimpleNamespace(stream=self._stream)

    @property
    def attempts(self) -> int:
        return self._attempts

    def _stream(self, **kwargs):
        del kwargs
        if self._attempts >= len(self._outcomes):
            raise AssertionError("No more fake Claude outcomes configured")
        outcome = self._outcomes[self._attempts]
        self._attempts += 1
        return FakeClaudeStreamContext(outcome)


def _text_event(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


class TestClaudeDashboardRetry:
    @pytest.mark.asyncio
    async def test_chat_retries_past_three_attempts_until_success(self, ws: FakeWS):
        from cogs.ai_core.api.dashboard_chat_claude import handle_chat_message_claude

        client = FakeClaudeClient(
            [
                RuntimeError("busy-1"),
                RuntimeError("busy-2"),
                RuntimeError("busy-3"),
                RuntimeError("busy-4"),
                [_text_event("Recovered response")],
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch("cogs.ai_core.api.dashboard_chat_claude.DB_AVAILABLE", False),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude.build_user_context",
                new=AsyncMock(return_value=("User context", False)),
            ),
            patch("cogs.ai_core.api.dashboard_chat_claude._RETRYABLE_ERRORS", (RuntimeError,)),
            patch("cogs.ai_core.api.dashboard_chat_claude.asyncio.sleep", new=sleep_mock),
        ):
            await handle_chat_message_claude(
                cast(Any, ws),
                {"content": "hello", "conversation_id": "conv-1"},
                cast(Any, client),
                stream_timeout=1,
            )

        retry_chunks = [
            message for message in ws.find("chunk") if "retrying" in message["content"].lower()
        ]
        assert len(retry_chunks) == 4
        assert all("/3" not in message["content"] for message in retry_chunks)
        assert "(attempt 4)" in retry_chunks[-1]["content"]
        assert ws.find("stream_end")[0]["full_response"] == "Recovered response"
        assert client.attempts == 5
        assert [call.args[0] for call in sleep_mock.await_args_list] == [2, 4, 8, 16]

    @pytest.mark.asyncio
    async def test_ai_edit_retries_past_three_attempts_until_success(self, ws: FakeWS):
        from cogs.ai_core.api.dashboard_chat_claude import handle_ai_edit_message_claude

        client = FakeClaudeClient(
            [
                RuntimeError("busy-1"),
                RuntimeError("busy-2"),
                RuntimeError("busy-3"),
                RuntimeError("busy-4"),
                [_text_event("Edited response")],
            ]
        )
        sleep_mock = AsyncMock()
        mock_db = MagicMock()
        mock_db.get_dashboard_messages = AsyncMock(
            return_value=[
                {"id": 1, "role": "user", "content": "hello"},
                {"id": 2, "role": "assistant", "content": "original"},
            ]
        )
        mock_db.update_dashboard_message = AsyncMock()

        with (
            patch("cogs.ai_core.api.dashboard_chat_claude.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_chat_claude._get_db", return_value=mock_db),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude.build_user_context",
                new=AsyncMock(return_value=("User context", False)),
            ),
            patch("cogs.ai_core.api.dashboard_chat_claude._RETRYABLE_ERRORS", (RuntimeError,)),
            patch("cogs.ai_core.api.dashboard_chat_claude.asyncio.sleep", new=sleep_mock),
        ):
            await handle_ai_edit_message_claude(
                cast(Any, ws),
                {
                    "conversation_id": "conv-1",
                    "target_message_id": 2,
                    "instruction": "Make it shorter",
                },
                cast(Any, client),
                stream_timeout=1,
            )

        retry_chunks = [
            message for message in ws.find("chunk") if "retrying" in message["content"].lower()
        ]
        assert len(retry_chunks) == 4
        assert all("/3" not in message["content"] for message in retry_chunks)
        assert "(attempt 4)" in retry_chunks[-1]["content"]
        assert ws.find("stream_end")[0]["full_response"] == "Edited response"
        mock_db.update_dashboard_message.assert_awaited_once_with(
            2, "Edited response", expected_conversation_id="conv-1"
        )
        assert client.attempts == 5
        assert [call.args[0] for call in sleep_mock.await_args_list] == [2, 4, 8, 16]

    @pytest.mark.asyncio
    async def test_chat_rejects_only_unsupported_images(self, ws: FakeWS):
        from cogs.ai_core.api.dashboard_chat_claude import handle_chat_message_claude

        client = FakeClaudeClient([[_text_event("should not run")]])
        heic_image = f"data:image/heic;base64,{base64.b64encode(b'abc').decode('ascii')}"

        with (
            patch("cogs.ai_core.api.dashboard_chat_claude.DB_AVAILABLE", False),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude.build_user_context",
                new=AsyncMock(return_value=("User context", False)),
            ),
        ):
            await handle_chat_message_claude(
                cast(Any, ws),
                {
                    "content": "",
                    "conversation_id": "conv-1",
                    "images": [heic_image],
                },
                cast(Any, client),
                stream_timeout=1,
            )

        errors = ws.find("error")
        # Server now names the rejected MIME type explicitly so the user
        # knows to convert; check for either the legacy generic message
        # or the new HEIC-specific phrasing.
        assert any("image/heic" in message["message"].lower() for message in errors)
        assert any(
            "no supported text or images" in message["message"].lower() for message in errors
        )
        assert client.attempts == 0


class TestApplySearchReplace:
    """The SDK backend must delegate to the shared dashboard_common patcher.

    The patcher's behavior is covered against the canonical function in
    test_dashboard_chat_claude_cli_helpers.py. Here we pin that the SDK backend
    (CLAUDE_BACKEND=api) is wired to that same shared implementation so the two
    backends can't drift — they previously did, into the markup-overwrite bug.
    """

    def test_sdk_backend_uses_shared_patcher(self):
        from cogs.ai_core.api import dashboard_chat_claude
        from cogs.ai_core.api.dashboard_common import apply_search_replace

        assert dashboard_chat_claude._apply_search_replace is apply_search_replace

    def test_preserves_original_when_no_match(self):
        from cogs.ai_core.api.dashboard_common import apply_search_replace

        # Failed partial edit (blocks present, none applied) keeps the original
        # rather than persisting the raw <<<SEARCH/REPLACE>>> markup.
        patch_text = "<<<SEARCH\nMISSING\n>>>\n<<<REPLACE\nNEW\n>>>"
        assert apply_search_replace("nothing useful here", patch_text) == "nothing useful here"
