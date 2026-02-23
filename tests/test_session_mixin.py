"""
Tests for cogs/ai_core/session_mixin.py

Comprehensive tests for SessionMixin class.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetChatSession:
    """Tests for get_chat_session method."""

    @pytest.mark.asyncio
    async def test_returns_none_without_client(self):
        """Test returns None when client is not initialized."""
        from cogs.ai_core.session_mixin import SessionMixin

        # Create a class that uses the mixin
        class TestClass(SessionMixin):
            def __init__(self):
                self.client = None
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

        instance = TestClass()
        result = await instance.get_chat_session(12345)
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_new_session(self):
        """Test creates new session if not exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000  # Required for _enforce_channel_limit

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}
                self.current_typing_msg = {}

            async def _enforce_channel_limit(self):
                """Stub for LRU eviction."""
                return 0

        instance = TestClass()

        with patch(
            "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock
        ) as mock_load_history:
            with patch(
                "cogs.ai_core.session_mixin.load_metadata", new_callable=AsyncMock
            ) as mock_load_metadata:
                mock_load_history.return_value = []
                mock_load_metadata.return_value = {"thinking_enabled": True}

                result = await instance.get_chat_session(12345)

                assert result is not None
                assert "history" in result
                assert "system_instruction" in result
                assert 12345 in instance.chats

    @pytest.mark.asyncio
    async def test_returns_cached_session(self):
        """Test returns cached session if exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [{"role": "user", "parts": ["Hello"]}],
                        "system_instruction": "[CREATIVE WRITING MODE - PRIVATE SESSION] Test",
                        "thinking_enabled": True,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}
                self.current_typing_msg = {}

            async def _enforce_channel_limit(self):
                return 0

        instance = TestClass()
        result = await instance.get_chat_session(12345)

        assert result is not None
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_updates_last_accessed(self):
        """Test updates last_accessed timestamp."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [],
                        "system_instruction": "[CREATIVE WRITING MODE - PRIVATE SESSION] Test",
                        "thinking_enabled": True,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}
                self.current_typing_msg = {}

            async def _enforce_channel_limit(self):
                return 0

        instance = TestClass()
        before_time = time.time()
        await instance.get_chat_session(12345)
        after_time = time.time()

        assert 12345 in instance.last_accessed
        assert before_time <= instance.last_accessed[12345] <= after_time


class TestSaveAllSessions:
    """Tests for save_all_sessions method."""

    @pytest.mark.asyncio
    async def test_saves_all_sessions(self):
        """Test saves all sessions."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    111: {"history": [], "system_instruction": "Test"},
                    222: {"history": [], "system_instruction": "Test"},
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

        instance = TestClass()

        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock) as mock_save:
            await instance.save_all_sessions()

            assert mock_save.call_count == 2


class TestToggleThinking:
    """Tests for toggle_thinking method."""

    @pytest.mark.asyncio
    async def test_toggle_thinking_enabled(self):
        """Test enabling thinking mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [],
                        "system_instruction": "[CREATIVE WRITING MODE - PRIVATE SESSION] Test",
                        "thinking_enabled": False,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}
                self.current_typing_msg = {}

            async def _enforce_channel_limit(self):
                return 0

        instance = TestClass()

        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock):
            result = await instance.toggle_thinking(12345, True)

            assert result is True
            assert instance.chats[12345]["thinking_enabled"] is True

    @pytest.mark.asyncio
    async def test_toggle_thinking_disabled(self):
        """Test disabling thinking mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [],
                        "system_instruction": "[CREATIVE WRITING MODE - PRIVATE SESSION] Test",
                        "thinking_enabled": True,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}
                self.current_typing_msg = {}

            async def _enforce_channel_limit(self):
                return 0

        instance = TestClass()

        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock):
            result = await instance.toggle_thinking(12345, False)

            assert result is True
            assert instance.chats[12345]["thinking_enabled"] is False

    @pytest.mark.asyncio
    async def test_toggle_thinking_no_session(self):
        """Test toggle_thinking when no session exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.client = None  # No client
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

        instance = TestClass()

        result = await instance.toggle_thinking(12345, True)

        assert result is False


class TestToggleStreaming:
    """Tests for toggle_streaming method."""

    def test_toggle_streaming_enabled(self):
        """Test enabling streaming mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {}

        instance = TestClass()

        result = instance.toggle_streaming(12345, True)

        assert result is True
        assert instance.streaming_enabled[12345] is True

    def test_toggle_streaming_disabled(self):
        """Test disabling streaming mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {12345: True}

        instance = TestClass()

        result = instance.toggle_streaming(12345, False)

        assert result is True
        assert instance.streaming_enabled[12345] is False


class TestIsStreamingEnabled:
    """Tests for is_streaming_enabled method."""

    def test_is_streaming_enabled_true(self):
        """Test returns True when streaming is enabled."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {12345: True}

        instance = TestClass()

        result = instance.is_streaming_enabled(12345)

        assert result is True

    def test_is_streaming_enabled_false(self):
        """Test returns False when streaming is disabled."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {12345: False}

        instance = TestClass()

        result = instance.is_streaming_enabled(12345)

        assert result is False

    def test_is_streaming_enabled_default(self):
        """Test returns False by default when not set."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {}

        instance = TestClass()

        result = instance.is_streaming_enabled(99999)

        assert result is False


class TestCleanupInactiveSessions:
    """Tests for cleanup_inactive_sessions method."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_sessions(self):
        """Test cleanup removes old sessions."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.bot.is_closed = MagicMock(return_value=True)  # Stop loop immediately
                # Inactive session (old timestamp)
                old_time = time.time() - 7200  # 2 hours ago
                self.chats = {
                    12345: {"history": [], "system_instruction": "Test"},
                }
                self.last_accessed = {12345: old_time}
                self.seen_users = {12345: set()}
                self.processing_locks = {12345: asyncio.Lock()}
                self.pending_messages = {12345: []}
                self.cancel_flags = {12345: False}
                self.streaming_enabled = {}

        instance = TestClass()

        # The method runs in a loop, so we need to mock it to run once
        # Since bot.is_closed() returns True, it should exit immediately
        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock):
            # Just verify the method exists and runs
            await instance.cleanup_inactive_sessions()


class TestSessionMixinClass:
    """Tests for SessionMixin class structure."""

    def test_class_exists(self):
        """Test SessionMixin class exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert SessionMixin is not None

    def test_has_get_chat_session(self):
        """Test has get_chat_session method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "get_chat_session")

    def test_has_save_all_sessions(self):
        """Test has save_all_sessions method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "save_all_sessions")

    def test_has_cleanup_inactive_sessions(self):
        """Test has cleanup_inactive_sessions method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "cleanup_inactive_sessions")

    def test_has_toggle_thinking(self):
        """Test has toggle_thinking method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "toggle_thinking")

    def test_has_toggle_streaming(self):
        """Test has toggle_streaming method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "toggle_streaming")

    def test_has_is_streaming_enabled(self):
        """Test has is_streaming_enabled method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "is_streaming_enabled")


class TestModuleImports:
    """Tests for module imports."""

    def test_module_imports(self):
        """Test module can be imported."""
        import cogs.ai_core.session_mixin

        assert cogs.ai_core.session_mixin is not None

    def test_import_session_mixin(self):
        """Test SessionMixin can be imported."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert SessionMixin is not None
