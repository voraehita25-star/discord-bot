"""Tests for the pure-logic helpers in cogs.ai_core.api.dashboard_common."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.ai_core.api.dashboard_common import (
    LeadingTimestampStripper,
    bangkok_now_iso,
    finalize_stopped_turn,
    invalidate_user_context_cache,
    normalize_timestamp_to_bangkok,
    sanitize_profile_field,
    stop_was_requested,
    strip_leading_timestamp,
    warn_assistant_not_persisted,
)


class TestBangkokNowIso:
    def test_returns_iso_string_with_offset(self):
        out = bangkok_now_iso()
        # Bangkok offset = +07:00, ISO-8601 with seconds resolution.
        assert "+07:00" in out
        # Format: YYYY-MM-DDTHH:MM:SS+07:00
        assert "T" in out


class TestNormalizeTimestamp:
    def test_iso_with_utc_offset(self):
        out = normalize_timestamp_to_bangkok("2026-04-22T10:30:00+00:00")
        # 10:30 UTC -> 17:30 Bangkok (+7).
        assert out == "2026-04-22T17:30:00+07:00"

    def test_iso_without_offset_assumed_utc(self):
        out = normalize_timestamp_to_bangkok("2026-04-22T10:30:00")
        assert out == "2026-04-22T17:30:00+07:00"

    def test_sqlite_current_timestamp_format(self):
        # SQLite default: "YYYY-MM-DD HH:MM:SS" (no tz, treated as UTC).
        out = normalize_timestamp_to_bangkok("2026-04-22 03:30:00")
        assert out == "2026-04-22T10:30:00+07:00"

    def test_returns_empty_for_none(self):
        assert normalize_timestamp_to_bangkok(None) == ""

    def test_returns_empty_for_empty_string(self):
        assert normalize_timestamp_to_bangkok("") == ""
        assert normalize_timestamp_to_bangkok("   ") == ""

    def test_falls_back_to_str_on_unparseable(self):
        out = normalize_timestamp_to_bangkok("not a timestamp")
        assert out == "not a timestamp"

    def test_accepts_datetime_object_via_str(self):
        # datetime object isoformat is parseable.
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        out = normalize_timestamp_to_bangkok(dt)
        assert "2026-01-01" in out


class TestStripLeadingTimestamp:
    def test_strips_iso_prefix(self):
        out = strip_leading_timestamp("[2026-04-22T23:17:33+07:00] hello")
        assert out == "hello"

    def test_strips_z_suffix(self):
        out = strip_leading_timestamp("[2026-04-22T23:17:33Z] hello")
        assert out == "hello"

    def test_no_prefix_returns_unchanged(self):
        assert strip_leading_timestamp("hello world") == "hello world"

    def test_handles_empty_input(self):
        assert strip_leading_timestamp("") == ""

    def test_only_strips_one_prefix(self):
        # If a model echoes two prefixes in a row, only the first is stripped
        # by the single-shot helper.
        out = strip_leading_timestamp("[2026-01-01T00:00:00+07:00][2026-01-02T00:00:00+07:00]hi")
        assert out.startswith("[2026-01-02")


class TestLeadingTimestampStripper:
    def test_consumes_prefix_in_one_chunk(self):
        s = LeadingTimestampStripper()
        assert s.feed("[2026-04-22T23:17:33+07:00]") == ""
        # Next chunks pass through unchanged.
        assert s.feed("hello") == "hello"
        assert s.feed(" world") == " world"

    def test_passes_through_non_prefix_immediately(self):
        s = LeadingTimestampStripper()
        # No '[' at start — flush immediately.
        out = s.feed("hello there")
        assert out == "hello there"

    def test_buffers_partial_prefix_then_strips(self):
        s = LeadingTimestampStripper()
        # Feed in pieces — the prefix is buffered until complete.
        assert s.feed("[2026-04-22T") == ""
        assert s.feed("23:17:33+07:00]") == ""
        assert s.feed("body") == "body"

    def test_nontimestamp_bracket_prefix_flushes_immediately(self):
        # "[partial" can never become a timestamp (year must be 4 digits), so
        # feed() flushes it right away instead of stalling the first visible
        # token until _MAX_PROBE chars accumulate.
        s = LeadingTimestampStripper()
        assert s.feed("[partial") == "[partial"
        assert s.flush() == ""

    def test_flush_returns_buffered_when_partial_timestamp(self):
        # A still-viable prefix ("[2026" — all digits so far) keeps buffering;
        # end-of-stream flush returns it untouched.
        s = LeadingTimestampStripper()
        assert s.feed("[2026-0") == ""
        out = s.flush()
        assert "[2026-0" in out

    def test_flush_returns_empty_when_done(self):
        s = LeadingTimestampStripper()
        s.feed("hello")
        assert s.flush() == ""

    def test_max_probe_flushes_buffer(self):
        s = LeadingTimestampStripper()
        # Long fake-prefix exceeds the probe limit and gets flushed as-is.
        long_text = "[" + "x" * 100
        out = s.feed(long_text)
        assert out == long_text


class TestSanitizeProfileField:
    def test_returns_empty_for_none(self):
        assert sanitize_profile_field(None) == ""

    def test_returns_empty_for_empty_string(self):
        assert sanitize_profile_field("") == ""

    def test_keeps_brackets_and_backticks(self):
        # Injection neutralisation removed (single-user dashboard): brackets /
        # braces / backticks now pass through verbatim.
        out = sanitize_profile_field("[hello] {world} `code`")
        assert out == "[hello] {world} `code`"

    def test_strips_control_chars(self):
        out = sanitize_profile_field("hi\x00\x01\x07world")
        assert out == "hiworld"

    def test_caps_at_max_length(self):
        out = sanitize_profile_field("x" * 1000, max_len=50)
        assert len(out) == 50

    def test_keeps_system_prefix_verbatim(self):
        # No longer neutralised — the profile is trusted (single-user dashboard)
        # and passes through unchanged.
        out = sanitize_profile_field("system: ignore previous")
        assert out == "system: ignore previous"

    def test_keeps_ignore_prefix_verbatim(self):
        out = sanitize_profile_field("ignore: do this")
        assert out == "ignore: do this"

    def test_keeps_unicode_verbatim(self):
        # NFKC lookalike-folding removed — input returns unchanged (aside from
        # control-char stripping + the length cap).
        out = sanitize_profile_field("system : do this")
        assert out == "system : do this"

    def test_coerces_non_string_input(self):
        # Caller may pass dict/list/int — function coerces via str().
        out = sanitize_profile_field(12345)
        assert out == "12345"

    def test_normalises_zalgo(self):
        # Combining characters folded by NFKC. Function shouldn't crash.
        zalgo = "h̷̢͚e̸̦͝l̷͖̾l̴͙̏o̵̲͝"
        out = sanitize_profile_field(zalgo)
        assert isinstance(out, str)


class TestInvalidateUserContextCache:
    def test_invalidate_specific_conversation(self):
        # Should not raise even if the conversation isn't cached.
        invalidate_user_context_cache("conv-x")

    def test_invalidate_all_with_none(self):
        # None means "wipe entire cache" — must not raise.
        invalidate_user_context_cache(None)


class TestFinalizeStoppedTurn:
    """The shared tail the Gemini/SDK backends run when a turn is stopped.

    (The CLI backend catches its CancelledError a level deeper and falls
    through to its own persist/emit tail instead — see
    test_dashboard_chat_claude_cli.TestHandlerStopButton.)
    """

    @staticmethod
    def _ws():
        class _WS:
            def __init__(self) -> None:
                self.sent: list[dict] = []

            async def send_json(self, data: dict, **kwargs) -> None:
                self.sent.append(data)

            def find(self, msg_type: str) -> list[dict]:
                return [m for m in self.sent if m.get("type") == msg_type]

        return _WS()

    @staticmethod
    def _db(title: str = "set"):
        db = MagicMock()
        db.save_dashboard_message = AsyncMock(return_value=77)
        db.get_dashboard_conversation = AsyncMock(return_value={"title": title})
        db.update_dashboard_conversation = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_persists_the_partial_and_emits_a_cancelled_stream_end(self):
        ws = self._ws()
        db = self._db()
        with patch("cogs.ai_core.api.dashboard_common.get_db", return_value=db):
            await finalize_stopped_turn(
                ws,
                conversation_id="c1",
                full_response="half an answ",
                thinking="hmm",
                mode="🤖 test",
                user_message_id=5,
                context_window=1000,
            )

        db.save_dashboard_message.assert_awaited_once()
        assert db.save_dashboard_message.await_args.args[:3] == ("c1", "assistant", "half an answ")
        end = ws.find("stream_end")[0]
        assert end["cancelled"] is True
        assert end["full_response"] == "half an answ"
        assert end["assistant_message_id"] == 77
        assert end["user_message_id"] == 5

    @pytest.mark.asyncio
    async def test_saves_nothing_when_the_stop_beat_the_first_token(self):
        ws = self._ws()
        db = self._db()
        with patch("cogs.ai_core.api.dashboard_common.get_db", return_value=db):
            await finalize_stopped_turn(
                ws, conversation_id="c1", full_response="", context_window=1000
            )

        db.save_dashboard_message.assert_not_awaited()
        end = ws.find("stream_end")[0]
        assert end["cancelled"] is True
        assert end["assistant_message_id"] is None
        # A genuine zero, not the estimate's max(1, …) floor.
        assert end["token_usage"]["output_tokens"] == 0

    @pytest.mark.asyncio
    async def test_still_sends_the_terminal_frame_when_the_db_write_fails(self):
        # Losing the partial is bad; leaving the composer locked forever is
        # worse. The frame must go out either way.
        ws = self._ws()
        db = self._db()
        db.save_dashboard_message = AsyncMock(side_effect=RuntimeError("disk on fire"))
        with patch("cogs.ai_core.api.dashboard_common.get_db", return_value=db):
            await finalize_stopped_turn(
                ws, conversation_id="c1", full_response="partial", context_window=1000
            )

        assert ws.find("stream_end")[0]["cancelled"] is True

    @pytest.mark.asyncio
    async def test_persist_false_skips_the_db_entirely(self):
        ws = self._ws()
        db = self._db()
        with patch("cogs.ai_core.api.dashboard_common.get_db", return_value=db) as get_db:
            await finalize_stopped_turn(
                ws,
                conversation_id="c1",
                full_response="partial",
                context_window=1000,
                persist=False,
            )

        get_db.assert_not_called()
        assert ws.find("stream_end")[0]["full_response"] == "partial"

    @pytest.mark.asyncio
    async def test_titles_a_conversation_stopped_on_its_first_turn(self):
        # Otherwise it keeps the "New Conversation" placeholder until some
        # later turn happens to run to completion.
        ws = self._ws()
        db = self._db(title="New Conversation")
        with patch("cogs.ai_core.api.dashboard_common.get_db", return_value=db):
            await finalize_stopped_turn(
                ws,
                conversation_id="c1",
                full_response="partial",
                context_window=1000,
                first_user_message="what is the airspeed velocity of a swallow",
            )

        db.update_dashboard_conversation.assert_awaited_once()
        assert ws.find("title_updated")

    @pytest.mark.asyncio
    async def test_strips_an_echoed_leading_timestamp_before_persisting(self):
        ws = self._ws()
        db = self._db()
        with patch("cogs.ai_core.api.dashboard_common.get_db", return_value=db):
            await finalize_stopped_turn(
                ws,
                conversation_id="c1",
                full_response="[2026-04-22T23:17:33+07:00] hello",
                context_window=1000,
            )

        assert db.save_dashboard_message.await_args.args[2] == "hello"
        assert ws.find("stream_end")[0]["full_response"] == "hello"


class TestStopMarker:
    """request_stop / stop_was_requested — see also test_ws_dashboard."""

    @pytest.mark.asyncio
    async def test_returns_false_outside_a_stopped_task(self):
        assert stop_was_requested() is False


class TestWarnAssistantNotPersisted:
    """All three dashboard backends log-and-continue when the assistant-row save
    raises, so the turn finished looking successful: the answer streamed,
    ``stream_end`` reported success, and the frontend rendered a bubble with
    ``assistant_message_id: null`` — no working Edit/Delete/Pin, and gone on the
    next reload with nothing having said so. Both failure modes are observed in
    this deployment's logs (a locked/missing SQLite file, and a foreign-key
    violation against a conversation row that no longer exists)."""

    @pytest.mark.asyncio
    async def test_warns_when_no_row_id_was_obtained(self):
        ws = MagicMock()
        ws.send_json = AsyncMock()
        await warn_assistant_not_persisted(ws, "conv1", 0)
        ws.send_json.assert_awaited_once()
        frame = ws.send_json.await_args.args[0]
        assert frame["type"] == "warning"
        assert frame["conversation_id"] == "conv1"
        assert "could not be saved" in frame["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("msg_id", [1, 42])
    async def test_stays_silent_when_the_row_was_saved(self, msg_id):
        """Two backends wrap the title update and the CLI-session wipe in the
        SAME try — a failure there must not claim the message was lost."""
        ws = MagicMock()
        ws.send_json = AsyncMock()
        await warn_assistant_not_persisted(ws, "conv1", msg_id)
        ws.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_dead_socket_does_not_raise(self):
        """A warning about a failure must never become a failure of its own."""
        ws = MagicMock()
        ws.send_json = AsyncMock(side_effect=ConnectionResetError("gone"))
        await warn_assistant_not_persisted(ws, "conv1", None)
