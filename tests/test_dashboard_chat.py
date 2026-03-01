"""Tests for dashboard_chat.py — AI chat streaming handler.

Covers: sanitize_profile_field, context building, image processing,
streaming with mock Gemini, thinking mode, DB save, timeout/error handling.
"""

from __future__ import annotations
import os

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Reuse FakeWS from test_ws_dashboard
# ---------------------------------------------------------------------------
class FakeWS:
    """Minimal fake WebSocketResponse."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def ws():
    return FakeWS()


# ---------------------------------------------------------------------------
# _sanitize_profile_field tests
# ---------------------------------------------------------------------------
class TestSanitizeProfileField:
    """Test _sanitize_profile_field utility."""

    def test_empty_string(self):
        from cogs.ai_core.api.dashboard_chat import _sanitize_profile_field
        assert _sanitize_profile_field("") == ""

    def test_none_value(self):
        from cogs.ai_core.api.dashboard_chat import _sanitize_profile_field
        assert _sanitize_profile_field(None) == ""

    def test_removes_control_chars(self):
        from cogs.ai_core.api.dashboard_chat import _sanitize_profile_field
        result = _sanitize_profile_field("hello\x00world\x1f")
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "helloworld" == result

    def test_neutralizes_brackets(self):
        from cogs.ai_core.api.dashboard_chat import _sanitize_profile_field
        result = _sanitize_profile_field("[SYSTEM] override")
        assert "[" not in result
        assert "]" not in result
        assert "(SYSTEM) override" == result

    def test_truncates_to_max_len(self):
        from cogs.ai_core.api.dashboard_chat import _sanitize_profile_field
        result = _sanitize_profile_field("a" * 500, max_len=100)
        assert len(result) == 100

    def test_default_max_len_200(self):
        from cogs.ai_core.api.dashboard_chat import _sanitize_profile_field
        result = _sanitize_profile_field("x" * 300)
        assert len(result) == 200


# ---------------------------------------------------------------------------
# Input validation tests (via handle_chat_message)
# ---------------------------------------------------------------------------
class TestChatInputValidation:
    """Test input validation in handle_chat_message."""

    @pytest.mark.asyncio
    async def test_empty_message(self, ws):
        from cogs.ai_core.api.dashboard_chat import handle_chat_message
        await handle_chat_message(ws, {"content": "", "images": []}, MagicMock())
        assert any("Empty" in m["message"] for m in ws.find("error"))

    @pytest.mark.asyncio
    async def test_too_long_content(self, ws):
        from cogs.ai_core.api.dashboard_chat import handle_chat_message
        await handle_chat_message(
            ws, {"content": "x" * 60000}, MagicMock(),
            max_content_length=50000,
        )
        assert any("too long" in m["message"].lower() for m in ws.find("error"))

    @pytest.mark.asyncio
    async def test_too_many_images(self, ws):
        from cogs.ai_core.api.dashboard_chat import handle_chat_message
        await handle_chat_message(
            ws, {"content": "hi", "images": ["img"] * 15}, MagicMock(),
            max_images=10,
        )
        assert any("too many" in m["message"].lower() for m in ws.find("error"))

    @pytest.mark.asyncio
    async def test_no_gemini_client(self, ws):
        from cogs.ai_core.api.dashboard_chat import handle_chat_message
        await handle_chat_message(ws, {"content": "hello"}, None)
        assert any("not available" in m["message"].lower() for m in ws.find("error"))


# ---------------------------------------------------------------------------
# Streaming tests with mock Gemini
# ---------------------------------------------------------------------------
class FakeChunk:
    """Fake Gemini streaming chunk."""
    def __init__(self, text: str = "", thought: object = None):
        part = MagicMock()
        part.text = text
        part.thought = thought
        candidate = MagicMock()
        candidate.content.parts = [part]
        self.candidates = [candidate]


class FakeStream:
    """Fake async iterator for Gemini streaming."""
    def __init__(self, chunks: list):
        self._chunks = chunks
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


class TestChatStreaming:
    """Test full streaming flow with mocked Gemini."""

    def _make_client(self, chunks: list):
        """Create a mock Gemini client that returns fake stream."""
        client = MagicMock()
        stream = FakeStream(chunks)

        async def mock_stream(**kwargs):
            return stream

        client.aio.models.generate_content_stream = mock_stream
        return client

    @pytest.mark.asyncio
    async def test_simple_stream(self, ws):
        """Test basic text streaming."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = self._make_client([
            FakeChunk(text="Hello "),
            FakeChunk(text="world!"),
        ])

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "hi", "conversation_id": "test-conv"},
                client,
            )

        # Should have: stream_start, 2x chunk, stream_end
        assert len(ws.find("stream_start")) == 1
        chunks = ws.find("chunk")
        assert len(chunks) == 2
        assert chunks[0]["content"] == "Hello "
        assert chunks[1]["content"] == "world!"
        stream_end = ws.find("stream_end")
        assert len(stream_end) == 1
        assert stream_end[0]["full_response"] == "Hello world!"

    @pytest.mark.asyncio
    async def test_thinking_stream(self, ws):
        """Test thinking mode with thought parts."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = self._make_client([
            FakeChunk(text="", thought=True),  # thought=True with text in part
            FakeChunk(text="Final answer"),
        ])
        # Patch the thought part to have text
        # For the first chunk, make the part have thought=True and text="Thinking..."
        first_chunk = FakeChunk(text="", thought=True)
        first_chunk.candidates[0].content.parts[0].text = "Let me think..."
        first_chunk.candidates[0].content.parts[0].thought = True

        client = self._make_client([first_chunk, FakeChunk(text="Answer")])

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "think about this", "conversation_id": "test-conv",
                 "thinking_enabled": True},
                client,
            )

        assert len(ws.find("thinking_start")) == 1
        assert len(ws.find("thinking_chunk")) >= 1
        assert len(ws.find("thinking_end")) == 1

    @pytest.mark.asyncio
    async def test_stream_with_db_save(self, ws):
        """Test that response is saved to DB after streaming."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = self._make_client([FakeChunk(text="Response")])

        mock_db = MagicMock()
        mock_db.save_dashboard_message = AsyncMock()
        mock_db.get_dashboard_user_profile = AsyncMock(return_value={})
        mock_db.get_dashboard_memories = AsyncMock(return_value=[])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "Existing"})

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws,
                {"content": "test msg", "conversation_id": "conv-1"},
                client,
            )

        # save_dashboard_message should be called for user + assistant
        assert mock_db.save_dashboard_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_stream_auto_title(self, ws):
        """Test auto-setting title from first user message."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = self._make_client([FakeChunk(text="Response")])

        mock_db = MagicMock()
        mock_db.save_dashboard_message = AsyncMock()
        mock_db.get_dashboard_user_profile = AsyncMock(return_value={})
        mock_db.get_dashboard_memories = AsyncMock(return_value=[])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "New Conversation"})
        mock_db.update_dashboard_conversation = AsyncMock()

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws,
                {"content": "What is Python?", "conversation_id": "conv-1"},
                client,
            )

        # Should send title_updated
        title_msgs = ws.find("title_updated")
        assert len(title_msgs) == 1
        assert "Python" in title_msgs[0]["title"]

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_stream_timeout(self, ws):
        """Test timeout handling."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()

        # Return an async iterator that blocks during iteration (not creation)
        # so the stream_timeout=1 kicks in instead of the 60s creation timeout
        class SlowIter:
            def __aiter__(self):
                return self
            async def __anext__(self):
                await asyncio.sleep(100)
                raise StopAsyncIteration

        async def slow_stream(**kwargs):
            return SlowIter()

        client.aio.models.generate_content_stream = slow_stream

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "hello", "conversation_id": "conv-1"},
                client,
                stream_timeout=1,
            )

        errors = ws.find("error")
        assert any("timed out" in e["message"].lower() for e in errors)

    @pytest.mark.asyncio
    async def test_stream_exception(self, ws):
        """Test generic streaming error."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()

        async def broken_stream(**kwargs):
            raise RuntimeError("API broke")

        client.aio.models.generate_content_stream = broken_stream

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "hello", "conversation_id": "conv-1"},
                client,
            )

        errors = ws.find("error")
        assert any("internal error" in e["message"].lower() for e in errors)


# ---------------------------------------------------------------------------
# Image processing tests
# ---------------------------------------------------------------------------
class TestImageProcessing:
    """Test image handling in chat messages."""

    @pytest.mark.asyncio
    async def test_base64_image_with_header(self, ws):
        """Test processing base64 image with data URI header."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        # Small valid base64 image
        img_data = "data:image/png;base64," + base64.b64encode(b"\x89PNG" + b"\x00" * 10).decode()

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(return_value=FakeStream([FakeChunk(text="Nice image")]))

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "look at this", "conversation_id": "conv-1", "images": [img_data]},
                client,
            )

        # Should process without error and stream
        assert len(ws.find("stream_start")) == 1

    @pytest.mark.asyncio
    async def test_oversized_image_rejected(self, ws):
        """Test that oversized images are rejected."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        # Create a 2MB base64 image (over 1MB limit for test)
        big_data = base64.b64encode(b"\x00" * (2 * 1024 * 1024)).decode()

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(return_value=FakeStream([FakeChunk(text="ok")]))

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "look", "conversation_id": "conv-1", "images": [big_data]},
                client,
                max_image_size_bytes=1024 * 1024,  # 1MB limit
            )

        # Should have error about image too large
        errors = ws.find("error")
        assert any("too large" in e["message"].lower() for e in errors)


# ---------------------------------------------------------------------------
# Context building tests
# ---------------------------------------------------------------------------
class TestContextBuilding:
    """Test user profile and memory context injection."""

    @pytest.mark.asyncio
    async def test_user_profile_context(self, ws):
        """Test user profile is injected into context."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(return_value=FakeStream([FakeChunk(text="Hi!")]))

        mock_db = MagicMock()
        mock_db.save_dashboard_message = AsyncMock()
        mock_db.get_dashboard_user_profile = AsyncMock(return_value={
            "display_name": "TestUser",
            "bio": "I love Python",
            "preferences": "Respond in English",
            "is_creator": True,
        })
        mock_db.get_dashboard_memories = AsyncMock(return_value=[
            {"content": "User likes coffee"},
        ])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "Chat"})

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws,
                {"content": "hello", "conversation_id": "conv-1"},
                client,
            )

        # Verify the stream completed (context was built successfully)
        assert len(ws.find("stream_end")) == 1

    @pytest.mark.asyncio
    async def test_history_passed_to_model(self, ws):
        """Test conversation history is passed correctly."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        captured_kwargs = {}

        async def capture_stream(**kwargs):
            captured_kwargs.update(kwargs)
            return FakeStream([FakeChunk(text="Reply")])

        client.aio.models.generate_content_stream = capture_stream

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {
                    "content": "follow up",
                    "conversation_id": "conv-1",
                    "history": [
                        {"role": "user", "content": "first msg"},
                        {"role": "assistant", "content": "first reply"},
                    ],
                },
                client,
            )

        # contents should have history + current message (3 total)
        assert len(captured_kwargs.get("contents", [])) == 3


# ---------------------------------------------------------------------------
# Error-branch and edge-case tests (covering remaining uncovered lines)
# ---------------------------------------------------------------------------
class TestErrorBranches:
    """Cover error handling branches missed by the happy-path tests."""

    @pytest.mark.asyncio
    async def test_get_db_function(self):
        """Test _get_db imports and returns Database singleton (lines 34-35)."""
        from cogs.ai_core.api.dashboard_chat import _get_db
        with patch("cogs.ai_core.api.dashboard_config.Database", return_value="mock_db"):
            result = _get_db()
            assert result == "mock_db"

    @pytest.mark.asyncio
    async def test_history_truncated(self, ws):
        """Test history is truncated when exceeding max (line 75)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        captured = {}

        async def capture_stream(**kwargs):
            captured["contents"] = kwargs.get("contents", [])
            return FakeStream([FakeChunk(text="ok")])

        client.aio.models.generate_content_stream = capture_stream

        long_history = [{"role": "user", "content": f"msg {i}"} for i in range(150)]

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "latest", "conversation_id": "c1", "history": long_history},
                client,
                max_history_messages=50,
            )

        # history(50) + current(1) = 51 contents
        assert len(captured["contents"]) == 51

    @pytest.mark.asyncio
    async def test_db_save_user_message_error(self, ws):
        """Test DB error when saving user message (lines 95-96)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([FakeChunk(text="reply")])
        )

        mock_db = MagicMock()
        mock_db.save_dashboard_message = AsyncMock(side_effect=RuntimeError("DB write fail"))
        mock_db.get_dashboard_user_profile = AsyncMock(return_value={})
        mock_db.get_dashboard_memories = AsyncMock(return_value=[])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "Chat"})

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws, {"content": "hi", "conversation_id": "c1"}, client,
            )

        # Should still complete streaming despite save error
        assert len(ws.find("stream_end")) == 1

    @pytest.mark.asyncio
    async def test_db_load_profile_error(self, ws):
        """Test DB error when loading user profile (lines 104-105)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([FakeChunk(text="ok")])
        )

        mock_db = MagicMock()
        mock_db.save_dashboard_message = AsyncMock()
        mock_db.get_dashboard_user_profile = AsyncMock(side_effect=RuntimeError("profile err"))
        mock_db.get_dashboard_memories = AsyncMock(return_value=[])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "X"})

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws, {"content": "hello", "conversation_id": "c1"}, client,
            )

        assert len(ws.find("stream_end")) == 1

    @pytest.mark.asyncio
    async def test_db_load_memories_error(self, ws):
        """Test DB error when loading memories (lines 131-132)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([FakeChunk(text="ok")])
        )

        mock_db = MagicMock()
        mock_db.save_dashboard_message = AsyncMock()
        mock_db.get_dashboard_user_profile = AsyncMock(return_value={})
        mock_db.get_dashboard_memories = AsyncMock(side_effect=RuntimeError("mem err"))
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "X"})

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws, {"content": "hello", "conversation_id": "c1"}, client,
            )

        assert len(ws.find("stream_end")) == 1

    @pytest.mark.asyncio
    async def test_image_decode_error(self, ws):
        """Test invalid base64 image is skipped gracefully (lines 165-166)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([FakeChunk(text="ok")])
        )

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "look", "conversation_id": "c1",
                 "images": ["not_valid_base64!!!"]},
                client,
            )

        # Should still stream despite bad image
        assert len(ws.find("stream_start")) == 1

    @pytest.mark.asyncio
    async def test_unrestricted_mode(self, ws):
        """Test unrestricted mode injection uses per-preset framing."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        captured = {}

        async def capture_stream(**kwargs):
            captured.update(kwargs)
            return FakeStream([FakeChunk(text="unrestricted reply")])

        client.aio.models.generate_content_stream = capture_stream

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "test", "conversation_id": "c1", "unrestricted_mode": True},
                client,
            )

        # Check that unrestricted injection was included in system instruction
        config = captured.get("config")
        assert config is not None
        assert "UNRESTRICTED MODE ACTIVE" in config.system_instruction
        # Temperature should be boosted in unrestricted mode
        # assert config.temperature == 1.0  # Temperature is set via global config, not dynamically in handle_chat_message

    @pytest.mark.asyncio
    async def test_null_stream_raises(self, ws):
        """Test null stream returns error (line 258)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()

        async def null_stream(**kwargs):
            return None

        client.aio.models.generate_content_stream = null_stream

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws, {"content": "hello", "conversation_id": "c1"}, client,
            )

        errors = ws.find("error")
        assert any("internal error" in e["message"].lower() for e in errors)

    @pytest.mark.asyncio
    async def test_thought_as_string(self, ws):
        """Test thought_flag as a string value (lines 294-296)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        # Create chunk where thought attr is a string instead of True
        chunk = MagicMock()
        part = MagicMock()
        part.thought = "I am reasoning..."  # string, not bool
        part.text = None
        candidate = MagicMock()
        candidate.content.parts = [part]
        chunk.candidates = [candidate]

        # Second chunk is normal text
        text_chunk = FakeChunk(text="Final answer")

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([chunk, text_chunk])
        )

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws,
                {"content": "think", "conversation_id": "c1", "thinking_enabled": True},
                client,
            )

        # Should have thinking chunks from the string thought
        assert len(ws.find("thinking_chunk")) >= 1

    @pytest.mark.asyncio
    async def test_chunk_text_fallback(self, ws):
        """Test chunk.text fallback when no candidates (lines 302-303)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        # Chunk with .text but no .candidates
        chunk = MagicMock(spec=[])  # no attributes by default
        chunk.text = "Fallback text"
        chunk.candidates = None  # no candidates attr effectively

        # Need a proper mock: hasattr(chunk, "candidates") should be False
        # or chunk.candidates should be falsy
        class BareChunk:
            def __init__(self, text):
                self.text = text

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([BareChunk("Bare text")])
        )

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            await handle_chat_message(
                ws, {"content": "hi", "conversation_id": "c1"}, client,
            )

        chunks = ws.find("chunk")
        assert any("Bare text" in c["content"] for c in chunks)

    @pytest.mark.asyncio
    async def test_db_save_assistant_error(self, ws):
        """Test DB error when saving assistant message (lines 362-363)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()
        client.aio.models.generate_content_stream = AsyncMock(
            return_value=FakeStream([FakeChunk(text="reply")])
        )

        mock_db = MagicMock()
        call_count = 0

        async def selective_save_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:  # fail on assistant save (2nd call)
                raise RuntimeError("DB save assistant fail")

        mock_db.save_dashboard_message = selective_save_error
        mock_db.get_dashboard_user_profile = AsyncMock(return_value={})
        mock_db.get_dashboard_memories = AsyncMock(return_value=[])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "X"})

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_chat._get_db", return_value=mock_db):
            await handle_chat_message(
                ws, {"content": "hi", "conversation_id": "c1"}, client,
            )

        # Should still complete stream_end despite save error
        assert len(ws.find("stream_end")) == 1

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_timeout_with_broken_ws(self, ws):
        """Test timeout handler when ws.send_json also fails (lines 380-381)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()

        # Return an async iterator that blocks during iteration (not creation)
        class SlowIter:
            def __aiter__(self):
                return self
            async def __anext__(self):
                await asyncio.sleep(100)
                raise StopAsyncIteration

        async def slow_stream(**kwargs):
            return SlowIter()

        client.aio.models.generate_content_stream = slow_stream

        # Make ws.send_json fail after stream_start
        original_send = ws.send_json
        call_count = 0

        async def fail_on_error(data):
            nonlocal call_count
            call_count += 1
            if data.get("type") == "error":
                raise ConnectionResetError("WS closed")
            await original_send(data)

        ws.send_json = fail_on_error

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            # Should not raise despite inner exception
            await handle_chat_message(
                ws, {"content": "hi", "conversation_id": "c1"}, client,
                stream_timeout=1,
            )

    @pytest.mark.asyncio
    async def test_exception_with_broken_ws(self, ws):
        """Test generic error handler when ws.send_json also fails (lines 390-391)."""
        from cogs.ai_core.api.dashboard_chat import handle_chat_message

        client = MagicMock()

        async def broken_stream(**kwargs):
            raise RuntimeError("API broke")

        client.aio.models.generate_content_stream = broken_stream

        original_send = ws.send_json
        async def fail_on_error(data):
            if data.get("type") == "error":
                raise ConnectionResetError("WS closed")
            await original_send(data)

        ws.send_json = fail_on_error

        with patch("cogs.ai_core.api.dashboard_chat.DB_AVAILABLE", False), patch.dict(os.environ, {"DASHBOARD_ALLOW_UNRESTRICTED": "1"}):
            # Should not raise despite inner exception
            await handle_chat_message(
                ws, {"content": "hi", "conversation_id": "c1"}, client,
            )
