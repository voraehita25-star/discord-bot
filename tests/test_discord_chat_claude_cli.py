"""Tests for the Discord-side Claude CLI integration.

These tests cover the unit-level pieces that don't require spawning the
real ``claude`` binary. The subprocess interaction itself is exercised
end-to-end by the dashboard CLI tests; here we focus on the Discord-
specific surface: prompt flattening, channel-scoped session tracking,
and the SDK-shape return contract that ``logic.py`` depends on.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The module imports dashboard_chat_claude_cli at top level, which in turn
# resolves ``CLAUDE_MODEL`` from env. Keep both env vars set before any
# import of the modules under test so the configuration matches what the
# bot actually runs with in CLI mode.
os.environ.setdefault("CLAUDE_BACKEND", "cli")
os.environ.setdefault("CLAUDE_MODEL", "claude-opus-4-7")

from cogs.ai_core.api import discord_chat_claude_cli as cli_mod
from cogs.ai_core.api.discord_chat_claude_cli import (
    _CHANNEL_SESSIONS,
    _flatten_contents_to_prompt,
    _get_channel_lock,
    call_claude_cli,
    call_claude_cli_streaming,
    reset_channel_session,
)


@pytest.fixture(autouse=True)
def _clean_channel_state() -> Any:
    """Reset module-level state between tests so a leaked session_id
    from one test can't shadow the next test's freshness expectation."""
    _CHANNEL_SESSIONS.clear()
    cli_mod._CHANNEL_LOCKS.clear()
    yield
    _CHANNEL_SESSIONS.clear()
    cli_mod._CHANNEL_LOCKS.clear()


class TestFlattenContentsToPrompt:
    def test_empty_contents_returns_empty_when_no_system(self) -> None:
        assert _flatten_contents_to_prompt([], "") == ""

    def test_system_only_includes_section_header(self) -> None:
        out = _flatten_contents_to_prompt([], "You are helpful.")
        assert "# System" in out
        assert "You are helpful." in out

    def test_single_user_message_no_history_block(self) -> None:
        contents = [{"role": "user", "parts": ["Hello"]}]
        out = _flatten_contents_to_prompt(contents, "")
        # No prior turns → no history section, just the current message.
        assert "# Conversation history" not in out
        assert "# Current user message" in out
        assert "User: Hello" in out

    def test_history_then_current_message(self) -> None:
        contents = [
            {"role": "user", "parts": ["Question 1"]},
            {"role": "model", "parts": ["Answer 1"]},
            {"role": "user", "parts": ["Question 2"]},
        ]
        out = _flatten_contents_to_prompt(contents, "sys")
        assert "# System" in out
        assert "# Conversation history" in out
        assert "User: Question 1" in out
        assert "Assistant: Answer 1" in out
        assert "# Current user message" in out
        assert "User: Question 2" in out
        # History order is preserved (oldest first).
        q1_idx = out.index("Question 1")
        a1_idx = out.index("Answer 1")
        q2_idx = out.index("Question 2")
        assert q1_idx < a1_idx < q2_idx

    def test_dict_text_parts_extracted(self) -> None:
        contents = [
            {"role": "user", "parts": [{"text": "Wrapped in dict"}]},
        ]
        out = _flatten_contents_to_prompt(contents, "")
        assert "Wrapped in dict" in out

    def test_inline_media_replaced_with_placeholder(self) -> None:
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": "Look at this"},
                    {"inline_data": {"mime_type": "image/png", "data": "AAA="}},
                ],
            },
        ]
        out = _flatten_contents_to_prompt(contents, "")
        assert "Look at this" in out
        # The image is dropped with an explicit placeholder so the model
        # knows non-text content existed at that position.
        assert "[attachment omitted: image/png]" in out

    def test_oversized_prompt_is_truncated_keeping_tail(self) -> None:
        # Build a history that vastly exceeds the cap. The CURRENT
        # message must survive intact (it's the question being asked).
        huge_history = [
            {"role": "user", "parts": ["X" * 1000]} for _ in range(500)
        ]
        contents = [
            *huge_history,
            {"role": "user", "parts": ["FINAL_QUESTION_SENTINEL"]},
        ]
        out = _flatten_contents_to_prompt(contents, "")
        # Truncation marker appears at the front.
        assert "[...older context truncated...]" in out
        # The current question survives.
        assert "FINAL_QUESTION_SENTINEL" in out
        # The prompt is within the cap budget.
        assert len(out) <= cli_mod._DISCORD_PROMPT_MAX_CHARS + 100  # tolerance


class TestChannelSessionTracking:
    def test_reset_clears_specific_channel(self) -> None:
        _CHANNEL_SESSIONS[1] = "session-a"
        _CHANNEL_SESSIONS[2] = "session-b"
        reset_channel_session(1)
        assert 1 not in _CHANNEL_SESSIONS
        assert _CHANNEL_SESSIONS[2] == "session-b"

    def test_reset_missing_channel_is_idempotent(self) -> None:
        # No KeyError on resetting a channel we never tracked.
        reset_channel_session(999)
        assert 999 not in _CHANNEL_SESSIONS


class TestChannelLockReuse:
    @pytest.mark.asyncio
    async def test_same_channel_returns_same_lock(self) -> None:
        a = _get_channel_lock(42)
        b = _get_channel_lock(42)
        assert a is b

    @pytest.mark.asyncio
    async def test_different_channels_get_different_locks(self) -> None:
        a = _get_channel_lock(42)
        b = _get_channel_lock(43)
        assert a is not b


class TestStreamingBackendNotReady:
    @pytest.mark.asyncio
    async def test_streaming_sends_friendly_error_when_cli_missing(self) -> None:
        send_channel = MagicMock()
        send_channel.send = AsyncMock()
        with patch.object(cli_mod, "is_cli_backend_ready", return_value=(False, "claude not on PATH")):
            text, indicator, calls = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=1,
            )
        assert text == ""
        assert indicator == ""
        assert calls == []
        # User-visible message is sent so the channel isn't silent.
        send_channel.send.assert_awaited_once()
        sent_text = send_channel.send.call_args.args[0]
        assert "Claude CLI" in sent_text
        assert "claude not on PATH" in sent_text

    @pytest.mark.asyncio
    async def test_non_streaming_returns_empty_when_cli_missing(self) -> None:
        with patch.object(cli_mod, "is_cli_backend_ready", return_value=(False, "missing")):
            text, indicator, calls = await call_claude_cli(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                channel_id=1,
            )
        assert (text, indicator, calls) == ("", "", [])


class TestStreamingSuccessPath:
    """Mock the subprocess primitives and verify the callback contract."""

    @pytest.mark.asyncio
    async def test_streaming_accumulates_deltas_and_returns_full_text(self) -> None:
        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            # Simulate the streaming callbacks the real subprocess would fire.
            await on_text_delta("Hello, ")
            await on_text_delta("world!")
            return "new-session-xyz", {"input_tokens": 5, "output_tokens": 3}

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, indicator, calls = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={"system_instruction": "be brief"},
                send_channel=send_channel,
                channel_id=100,
            )
        assert text == "Hello, world!"
        assert indicator == ""
        assert calls == []
        # Placeholder was sent and then deleted at the end.
        send_channel.send.assert_awaited_once()
        placeholder.delete.assert_awaited_once()
        # Session id was tracked for next turn.
        assert _CHANNEL_SESSIONS[100] == "new-session-xyz"

    @pytest.mark.asyncio
    async def test_streaming_runs_with_max_effort_thinking(self) -> None:
        """Regression: Discord CLI replies must build argv with `--effort max`
        (enable_thinking=True), so the bot reasons at max effort like a
        dashboard conversation with thinking on. We must NOT pass custom betas:
        the subscription-mode CLI rejects them with a stderr warning that masks
        real stdout errors."""
        captured_argv: list[str] = []
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel = MagicMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            captured_argv.extend(argv)
            await on_text_delta("ok")
            return "sess-think", None

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={"system_instruction": "be brief"},
                send_channel=send_channel,
                channel_id=101,
            )
        assert "--effort" in captured_argv
        assert "max" in captured_argv
        assert "--betas" not in captured_argv
        assert "interleaved-thinking" not in captured_argv

    @pytest.mark.asyncio
    async def test_cancellation_returns_empty_even_with_partial_text(self) -> None:
        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        cancel_flags: dict[int, bool] = {}

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            await on_text_delta("partial...")
            # Mid-stream cancellation: the cancel-flag dict is flipped
            # from another coroutine in production; we set it directly here.
            cancel_flags[200] = True
            await on_text_delta(" still emitting after cancel")
            return "session-id", None

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, indicator, calls = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=200,
                cancel_flags=cancel_flags,
            )
        # Contract: cancellation returns empty regardless of accumulated text.
        assert text == ""
        assert indicator == ""
        assert calls == []

    @pytest.mark.asyncio
    async def test_stale_session_retries_with_fresh_id_once(self) -> None:
        from cogs.ai_core.api.dashboard_chat_claude_cli import _StaleSessionError

        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        # Pre-seed a stale session id so the first attempt uses --resume
        # and trips the stale-session path.
        _CHANNEL_SESSIONS[300] = "stale-session"

        attempts: list[str | None] = []

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            # Detect whether --resume <id> is present in argv to record
            # which attempt this call represents.
            try:
                resume_idx = argv.index("--resume")
                attempts.append(argv[resume_idx + 1])
            except ValueError:
                attempts.append(None)
            if len(attempts) == 1:
                raise _StaleSessionError("stale")
            # Second attempt (fresh): emit text + return new session id.
            await on_text_delta("recovered")
            return "fresh-session", None

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, _, _ = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=300,
            )
        # First attempt used the stale session id; second attempt used None.
        assert attempts == ["stale-session", None]
        # The retry succeeded and the new session was recorded.
        assert text == "recovered"
        assert _CHANNEL_SESSIONS[300] == "fresh-session"

    @pytest.mark.asyncio
    async def test_orphan_system_reminder_tag_is_stripped(self) -> None:
        """Regression: the model occasionally bleeds Claude Code's
        internal ``<system-reminder>`` housekeeping XML into ``claude -p``
        output (same Claude Opus weights power both the interactive
        Claude Code shell and our subprocess). The Discord path must
        strip these tags before reaching the user.
        """
        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            # Real-world failure mode: an orphan closing tag at the tail.
            await on_text_delta("Hello! How are you?</system-reminder>")
            return "sess-y", None

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, _, _ = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=600,
            )
        assert "</system-reminder>" not in text
        assert "<system-reminder>" not in text
        assert "Hello! How are you?" in text

    @pytest.mark.asyncio
    async def test_balanced_system_reminder_block_is_stripped(self) -> None:
        """A balanced ``<system-reminder>...</system-reminder>`` block in
        the model's output must be removed in its entirety — the body
        is Claude Code internal housekeeping, not user-visible content.
        """
        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            await on_text_delta(
                "Sure! <system-reminder>do not say X</system-reminder>"
                "Here is the answer."
            )
            return "sess-z", None

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, _, _ = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=601,
            )
        assert "<system-reminder>" not in text
        assert "</system-reminder>" not in text
        assert "do not say X" not in text
        # The surrounding user-visible content must survive.
        assert "Sure!" in text
        assert "Here is the answer." in text

    @pytest.mark.asyncio
    async def test_leading_timestamp_is_stripped_from_response(self) -> None:
        """Regression: the model occasionally mimics the
        ``[ISO-timestamp]`` prefix we put on historical user turns and
        emits its own response prefixed with a timestamp. The Discord
        path must strip that leading prefix before returning so the
        user doesn't see literal ``[2026-05-20T13:18:47+07:00]`` text
        echoed back from Claude.
        """
        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            # Simulate the failure: model emits a timestamp prefix
            # followed by the real reply.
            await on_text_delta("[2026-05-20T13:18:47+07:00] Hello there!")
            return "sess-x", None

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, _, _ = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=500,
            )
        # The timestamp prefix is stripped; the actual reply survives.
        assert not text.startswith("[2026")
        assert "Hello there!" in text

    @pytest.mark.asyncio
    async def test_prompt_includes_formatting_rules(self) -> None:
        """The flattened prompt must carry the ``Do NOT include such
        timestamp prefixes`` instruction so the model has explicit
        guidance to NOT mimic the timestamp format in its reply.
        """
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        out = _flatten_contents_to_prompt(
            [{"role": "user", "parts": ["hi"]}],
            "You are helpful.",
        )
        assert "# Formatting rules" in out
        assert "Do NOT include such timestamp prefixes" in out

    @pytest.mark.asyncio
    async def test_timeout_surfaces_thai_message_with_partial(self) -> None:
        send_channel = MagicMock()
        placeholder = MagicMock()
        placeholder.edit = AsyncMock()
        placeholder.delete = AsyncMock()
        send_channel.send = AsyncMock(return_value=placeholder)

        async def fake_subprocess(
            argv: list[str],
            stdin_payload: str,
            *,
            on_text_delta: Any,
            on_thinking_delta: Any,
            on_thinking_block_start: Any = None,
            on_thinking_block_stop: Any = None,
            timeout: float,
        ) -> tuple[str, dict[str, Any] | None]:
            await on_text_delta("Some words before timeout")
            raise TimeoutError

        with (
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_run_claude_subprocess", side_effect=fake_subprocess),
            patch(
                "cogs.ai_core.api.dashboard_chat_claude_cli._resolve_claude_executable",
                return_value="/usr/bin/claude",
            ),
        ):
            text, _, _ = await call_claude_cli_streaming(
                contents=[{"role": "user", "parts": ["hi"]}],
                config_params={},
                send_channel=send_channel,
                channel_id=400,
            )
        # Partial accumulated text is preserved + truncation marker appended.
        assert "Some words before timeout" in text
        assert "ตัด" in text  # truncation marker uses Thai


class TestLogicIntegration:
    """Sanity-check that ``logic.ChatManager`` reacts to ``cli_mode``."""

    def test_setup_ai_sets_cli_mode_flag_when_cli_backend(self) -> None:
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()
        manager = ChatManager(mock_bot)
        with patch.dict(os.environ, {"CLAUDE_BACKEND": "cli"}):
            manager.setup_ai()
        assert manager.cli_mode is True
        assert manager.client is None
        assert manager.target_model is not None  # CLAUDE_MODEL fallback

    @pytest.mark.asyncio
    async def test_detect_search_intent_skipped_in_cli_mode(self) -> None:
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()
        manager = ChatManager(mock_bot)
        manager.cli_mode = True
        manager.client = None
        # Should return False without trying to call the SDK.
        result = await manager._detect_search_intent("does this need a search?")
        assert result is False

    @pytest.mark.asyncio
    async def test_dm_uses_full_faust_persona_not_brief_dm_addendum(self) -> None:
        """DM mode must use the full ``FAUST_INSTRUCTION`` (full persona,
        ~6 KB) rather than the brief ``FAUST_DM_INSTRUCTION`` (~600 B
        addendum). Per user direction, DM and guild channels share the
        same identity so behaviour is consistent across contexts.
        """
        from cogs.ai_core.data import FAUST_DM_INSTRUCTION, FAUST_INSTRUCTION
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()
        manager = ChatManager(mock_bot)
        manager.cli_mode = True
        manager.client = None

        with (
            patch("cogs.ai_core.session_mixin.load_history", new=AsyncMock(return_value=[])),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new=AsyncMock(return_value={"thinking_enabled": True}),
            ),
        ):
            data = await manager.get_chat_session(channel_id=9999, guild_id=None)
        assert data is not None
        system = data["system_instruction"]
        # The full persona block must be present.
        assert FAUST_INSTRUCTION in system, "DM must carry the full Faust persona"
        # The DM addendum is NOT the system instruction in DM mode any
        # more — only the full FAUST_INSTRUCTION drives DM behaviour.
        # (The constant still exists for backward compat, but it's no
        # longer used as the active prompt.)
        assert system != FAUST_DM_INSTRUCTION

    @pytest.mark.asyncio
    async def test_get_chat_session_works_in_cli_mode_without_client(self) -> None:
        """Regression: SessionMixin used to gate on ``self.client`` alone,
        which made every Discord message in CLI mode log
        'Could not create chat session.' and return early. The gate must
        also accept ``cli_mode=True`` even when the SDK client is None.
        """
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()
        manager = ChatManager(mock_bot)
        manager.cli_mode = True
        manager.client = None

        # Stub the disk-loading helpers so the test doesn't touch real
        # DB / JSON files. ``get_chat_session`` calls ``load_history``
        # and ``load_metadata`` from ``cogs.ai_core.storage``.
        with (
            patch("cogs.ai_core.session_mixin.load_history", new=AsyncMock(return_value=[])),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new=AsyncMock(return_value={"thinking_enabled": True}),
            ),
        ):
            data = await manager.get_chat_session(channel_id=12345, guild_id=None)
        assert data is not None, "CLI mode must produce a chat session even without SDK client"
        assert "system_instruction" in data
        assert "history" in data
