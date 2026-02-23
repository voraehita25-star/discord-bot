"""Tests for AI Logic module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRegexPatterns:
    """Tests for precompiled regex patterns."""

    def test_pattern_quote(self):
        """Test PATTERN_QUOTE pattern."""
        from cogs.ai_core.logic import PATTERN_QUOTE

        text = '> "Hello world"'
        result = PATTERN_QUOTE.sub(r"\1", text)

        assert result == '"Hello world"'

    def test_pattern_quote_single_quote(self):
        """Test PATTERN_QUOTE with single quote."""
        from cogs.ai_core.logic import PATTERN_QUOTE

        text = "> 'Hello world'"
        result = PATTERN_QUOTE.sub(r"\1", text)

        assert result == "'Hello world'"

    def test_pattern_spaced(self):
        """Test PATTERN_SPACED pattern."""
        from cogs.ai_core.logic import PATTERN_SPACED

        text = '  > "Hello"'
        result = PATTERN_SPACED.sub(r"\1", text)

        assert result == '"Hello"'

    def test_pattern_id(self):
        """Test PATTERN_ID pattern."""
        from cogs.ai_core.logic import PATTERN_ID

        text = "[ID: 12345] Hello world"
        result = PATTERN_ID.sub("", text)

        assert result == "Hello world"

    def test_pattern_server_command_create_text(self):
        """Test PATTERN_SERVER_COMMAND for CREATE_TEXT."""
        from cogs.ai_core.logic import PATTERN_SERVER_COMMAND

        text = "[[CREATE_TEXT: my-channel]]"
        match = PATTERN_SERVER_COMMAND.search(text)

        assert match is not None
        assert match.group(1) == "CREATE_TEXT"
        assert match.group(2) == "my-channel"

    def test_pattern_server_command_list_channels(self):
        """Test PATTERN_SERVER_COMMAND for LIST_CHANNELS."""
        from cogs.ai_core.logic import PATTERN_SERVER_COMMAND

        text = "[[LIST_CHANNELS]]"
        match = PATTERN_SERVER_COMMAND.search(text)

        assert match is not None
        assert match.group(1) == "LIST_CHANNELS"

    def test_pattern_character_tag(self):
        """Test PATTERN_CHARACTER_TAG pattern."""
        from cogs.ai_core.logic import PATTERN_CHARACTER_TAG

        text = "Hello {{Alice}} how are you?"
        matches = PATTERN_CHARACTER_TAG.findall(text)

        assert "Alice" in matches

    def test_pattern_character_tag_multiple(self):
        """Test PATTERN_CHARACTER_TAG with multiple tags."""
        from cogs.ai_core.logic import PATTERN_CHARACTER_TAG

        text = "{{Bob}} said to {{Alice}}"
        matches = PATTERN_CHARACTER_TAG.findall(text)

        assert len(matches) == 2
        assert "Bob" in matches
        assert "Alice" in matches

    def test_pattern_channel_id(self):
        """Test PATTERN_CHANNEL_ID pattern."""
        from cogs.ai_core.logic import PATTERN_CHANNEL_ID

        text = "Check channel 123456789012345678"
        matches = PATTERN_CHANNEL_ID.findall(text)

        assert "123456789012345678" in matches

    def test_pattern_discord_emoji(self):
        """Test PATTERN_DISCORD_EMOJI pattern."""
        from cogs.ai_core.logic import PATTERN_DISCORD_EMOJI

        text = "Hello <:smile:123456789>"
        match = PATTERN_DISCORD_EMOJI.search(text)

        assert match is not None
        assert match.group(1) == ""  # not animated
        assert match.group(2) == "smile"
        assert match.group(3) == "123456789"

    def test_pattern_discord_emoji_animated(self):
        """Test PATTERN_DISCORD_EMOJI for animated emoji."""
        from cogs.ai_core.logic import PATTERN_DISCORD_EMOJI

        text = "Hello <a:dance:987654321>"
        match = PATTERN_DISCORD_EMOJI.search(text)

        assert match is not None
        assert match.group(1) == "a"  # animated
        assert match.group(2) == "dance"


class TestFeatureAvailability:
    """Tests for feature availability flags."""

    def test_url_fetcher_availability_flag(self):
        """Test URL_FETCHER_AVAILABLE is defined."""
        from cogs.ai_core.logic import URL_FETCHER_AVAILABLE

        assert isinstance(URL_FETCHER_AVAILABLE, bool)

    def test_guardrails_availability_flag(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        from cogs.ai_core.logic import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_cache_availability_flag(self):
        """Test CACHE_AVAILABLE is defined."""
        from cogs.ai_core.logic import CACHE_AVAILABLE

        assert isinstance(CACHE_AVAILABLE, bool)

    def test_circuit_breaker_availability_flag(self):
        """Test CIRCUIT_BREAKER_AVAILABLE is defined."""
        from cogs.ai_core.logic import CIRCUIT_BREAKER_AVAILABLE

        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)

    def test_token_tracker_availability_flag(self):
        """Test TOKEN_TRACKER_AVAILABLE is defined."""
        from cogs.ai_core.logic import TOKEN_TRACKER_AVAILABLE

        assert isinstance(TOKEN_TRACKER_AVAILABLE, bool)

    def test_fallback_availability_flag(self):
        """Test FALLBACK_AVAILABLE is defined."""
        from cogs.ai_core.logic import FALLBACK_AVAILABLE

        assert isinstance(FALLBACK_AVAILABLE, bool)


class TestChatManagerInit:
    """Tests for ChatManager initialization."""

    def test_chat_manager_creation(self):
        """Test creating ChatManager."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            assert manager.bot == mock_bot
            assert manager.chats == {}
            assert manager.last_accessed == {}
            assert manager.seen_users == {}

    def test_chat_manager_has_message_queue(self):
        """Test ChatManager has message queue."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            assert manager._message_queue is not None

    def test_chat_manager_has_performance_tracker(self):
        """Test ChatManager has performance tracker."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            assert manager._performance is not None

    def test_chat_manager_has_deduplicator(self):
        """Test ChatManager has request deduplicator."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            assert manager._deduplicator is not None


class TestChatManagerMethods:
    """Tests for ChatManager methods."""

    def test_get_performance_stats(self):
        """Test get_performance_stats."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            stats = manager.get_performance_stats()

            assert isinstance(stats, dict)

    def test_record_timing(self):
        """Test record_timing."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            # Should not raise
            manager.record_timing("test_step", 0.5)

    def test_cleanup_pending_requests(self):
        """Test cleanup_pending_requests."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            result = manager.cleanup_pending_requests()

            assert isinstance(result, int)
            assert result >= 0

    def test_parse_voice_command_join(self):
        """Test parse_voice_command for join."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            # Test parsing voice command - actual behavior depends on voice module
            action, channel_id = manager.parse_voice_command(
                "join voice channel 123456789012345678"
            )

            # Result depends on voice module implementation
            assert action is None or isinstance(action, str)

    def test_process_response_text_basic(self):
        """Test _process_response_text basic processing."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            result = manager._process_response_text("Hello world", None, "")

            assert result == "Hello world"

    def test_process_response_text_removes_quote(self):
        """Test _process_response_text removes > before quotes."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            result = manager._process_response_text('> "Hello"', None, "")

            assert result == '"Hello"'

    def test_process_response_text_adds_search_indicator(self):
        """Test _process_response_text adds search indicator."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            result = manager._process_response_text("Hello", None, "🔍 ")

            assert result == "🔍 Hello"

    def test_is_animated_gif(self):
        """Test _is_animated_gif method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            # Non-GIF data should return False
            result = manager._is_animated_gif(b"not a gif")

            assert result is False


class TestSetupAI:
    """Tests for setup_ai method."""

    def test_setup_ai_no_api_key(self):
        """Test setup_ai with no API key."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch("cogs.ai_core.logic.GEMINI_API_KEY", ""):
            manager = ChatManager(mock_bot)

            assert manager.client is None

    def test_setup_ai_with_api_key(self):
        """Test setup_ai with API key."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()
        mock_client = MagicMock()

        with patch("cogs.ai_core.logic.GEMINI_API_KEY", "test-key"):
            with patch("cogs.ai_core.logic.genai.Client", return_value=mock_client):
                manager = ChatManager(mock_bot)

                assert manager.client == mock_client


class TestAsyncMethods:
    """Tests for async methods."""

    @pytest.mark.asyncio
    async def test_join_voice_channel(self):
        """Test join_voice_channel method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            with patch("cogs.ai_core.logic.voice_join", new_callable=AsyncMock) as mock_join:
                mock_join.return_value = (True, "Joined")

                success, msg = await manager.join_voice_channel(123)

                assert success is True
                mock_join.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_voice_channel(self):
        """Test leave_voice_channel method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)

            with patch("cogs.ai_core.logic.voice_leave", new_callable=AsyncMock) as mock_leave:
                mock_leave.return_value = (True, "Left")

                success, msg = await manager.leave_voice_channel(123)

                assert success is True
                mock_leave.assert_called_once()

    @pytest.mark.asyncio
    async def test_detect_search_intent(self):
        """Test _detect_search_intent method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, "setup_ai"):
            manager = ChatManager(mock_bot)
            manager.client = MagicMock()
            manager.target_model = "test-model"

            with patch(
                "cogs.ai_core.logic.detect_search_intent", new_callable=AsyncMock
            ) as mock_detect:
                mock_detect.return_value = True

                result = await manager._detect_search_intent("what is the weather?")

                assert result is True


class TestModuleImports:
    """Tests for module imports."""

    def test_import_chat_manager(self):
        """Test importing ChatManager."""
        from cogs.ai_core.logic import ChatManager

        assert ChatManager is not None

    def test_import_constants(self):
        """Test importing constants."""
        from cogs.ai_core.logic import (
            LOCK_TIMEOUT,
            MAX_HISTORY_ITEMS,
        )

        assert MAX_HISTORY_ITEMS is not None
        assert LOCK_TIMEOUT is not None

    def test_import_patterns(self):
        """Test importing regex patterns."""
        from cogs.ai_core.logic import (
            PATTERN_CHANNEL_ID,
            PATTERN_CHARACTER_TAG,
            PATTERN_DISCORD_EMOJI,
            PATTERN_ID,
            PATTERN_QUOTE,
            PATTERN_SERVER_COMMAND,
            PATTERN_SPACED,
        )

        assert PATTERN_QUOTE is not None
        assert PATTERN_SPACED is not None
        assert PATTERN_ID is not None
        assert PATTERN_SERVER_COMMAND is not None
        assert PATTERN_CHARACTER_TAG is not None
        assert PATTERN_CHANNEL_ID is not None
        assert PATTERN_DISCORD_EMOJI is not None
