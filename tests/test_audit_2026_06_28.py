"""Regression tests for the 2026-06-28 deep-audit fixes.

Covers two confirmed findings:

* py-ai-cli — ``handle_ai_edit_message_claude_cli`` coerces a non-string
  ``instruction`` instead of crashing with ``AttributeError`` at the unguarded
  function head. A truthy non-string (e.g. ``{"instruction": 123}``) survived
  the old ``(data.get("instruction") or "").strip()`` and blew up on ``.strip()``
  before any error frame reached the dashboard. Mirrors the SDK backend
  (``dashboard_chat_claude.py``), which already guarded this exact case.

* py-ai-api — ``_format_model_display`` strips a trailing context-window tag
  (e.g. ``[1m]``) so the repo-default model id renders as ``Claude Opus 4.8``
  rather than the garbled ``Claude Opus 8[1M] 4`` (the ``8[1m]`` token is not
  all-digits, so the numeric/word split mis-filed it).
"""

from __future__ import annotations

import pytest

from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
from cogs.ai_core.api.dashboard_chat_claude import _format_model_display


class _FakeWS:
    """Minimal fake aiohttp WebSocketResponse recording every frame."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict, **kwargs) -> None:  # kwargs: aiohttp accepts dumps=
        self.sent.append(data)

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


class TestAiEditInstructionCoercion:
    """A non-string ``instruction`` must not crash the AI-edit handler head."""

    @pytest.mark.asyncio
    async def test_non_string_int_instruction_does_not_crash(self) -> None:
        # 123 is truthy, so the old `(data.get("instruction") or "").strip()`
        # called .strip() on an int -> AttributeError, before any error frame.
        # An invalid conversation_id makes the handler return right after the
        # coercion, exercising the head without DB/subprocess mocks.
        ws = _FakeWS()
        data = {
            "instruction": 123,
            "conversation_id": "bad id!!",  # space + ! fail the id allowlist
            "target_message_id": "m1",
        }
        await cli_mod.handle_ai_edit_message_claude_cli(ws, data, None)
        errors = ws.find("error")
        assert errors, "handler must emit a clean error frame, not crash"
        assert "Invalid conversation ID" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_non_string_list_instruction_does_not_crash(self) -> None:
        ws = _FakeWS()
        data = {
            "instruction": ["x"],
            "conversation_id": "also bad!!",
            "target_message_id": "m1",
        }
        await cli_mod.handle_ai_edit_message_claude_cli(ws, data, None)
        assert ws.find("error"), "a list instruction must not crash the head"


class TestFormatModelDisplay:
    """_format_model_display drops the ``[1m]`` tag and rejoins the version."""

    def test_strips_context_window_tag(self) -> None:
        assert _format_model_display("claude-opus-4-8[1m]") == "Claude Opus 4.8"

    def test_strips_tag_for_sonnet(self) -> None:
        assert _format_model_display("claude-sonnet-4-6[1m]") == "Claude Sonnet 4.6"

    def test_plain_versioned_id_unchanged(self) -> None:
        assert _format_model_display("claude-opus-4-7") == "Claude Opus 4.7"

    def test_no_numeric_trailer(self) -> None:
        assert _format_model_display("claude-sonnet") == "Claude Sonnet"
