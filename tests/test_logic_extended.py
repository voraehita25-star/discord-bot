"""
Extended tests for AI Logic module.
Tests constants, imports, and configuration.
"""




from unittest.mock import AsyncMock, MagicMock, patch
import pytest

class TestLogicModuleImports:
    """Tests for logic module imports."""

    def test_url_fetcher_available_defined(self):
        """Test URL_FETCHER_AVAILABLE is defined."""
        from cogs.ai_core.logic import URL_FETCHER_AVAILABLE

        assert isinstance(URL_FETCHER_AVAILABLE, bool)

    def test_guardrails_available_defined(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        from cogs.ai_core.logic import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)


class TestPerformanceImports:
    """Tests for performance related imports."""

    def test_performance_tracker_import(self):
        """Test PerformanceTracker is imported."""
        from cogs.ai_core.logic import PerformanceTracker

        assert PerformanceTracker is not None

    def test_request_deduplicator_import(self):
        """Test RequestDeduplicator is imported."""
        from cogs.ai_core.logic import RequestDeduplicator

        assert RequestDeduplicator is not None


class TestMixinImports:
    """Tests for mixin imports."""

    def test_response_mixin_import(self):
        """Test ResponseMixin is imported."""
        from cogs.ai_core.logic import ResponseMixin

        assert ResponseMixin is not None

    def test_session_mixin_import(self):
        """Test SessionMixin is imported."""
        from cogs.ai_core.logic import SessionMixin

        assert SessionMixin is not None


class TestResponseSenderImport:
    """Tests for ResponseSender import."""

    def test_response_sender_import(self):
        """Test ResponseSender is imported."""
        from cogs.ai_core.logic import ResponseSender

        assert ResponseSender is not None


class TestMessageQueueImport:
    """Tests for MessageQueue import."""

    def test_message_queue_import(self):
        """Test MessageQueue is imported."""
        from cogs.ai_core.logic import MessageQueue

        assert MessageQueue is not None


class TestStorageImports:
    """Tests for storage imports."""

    def test_save_history_import(self):
        """Test save_history is imported."""
        from cogs.ai_core.logic import save_history

        assert callable(save_history)

    def test_update_message_id_import(self):
        """Test update_message_id is imported."""
        from cogs.ai_core.logic import update_message_id

        assert callable(update_message_id)


class TestVoiceImports:
    """Tests for voice imports."""

    def test_voice_join_import(self):
        """Test voice_join is imported."""
        from cogs.ai_core.logic import voice_join

        assert voice_join is not None

    def test_voice_leave_import(self):
        """Test voice_leave is imported."""
        from cogs.ai_core.logic import voice_leave

        assert voice_leave is not None

    def test_voice_parse_command_import(self):
        """Test voice_parse_command is imported."""
        from cogs.ai_core.logic import voice_parse_command

        assert voice_parse_command is not None


class TestEmojiImports:
    """Tests for emoji imports."""

    def test_convert_discord_emojis_import(self):
        """Test convert_discord_emojis is imported."""
        from cogs.ai_core.logic import convert_discord_emojis

        assert callable(convert_discord_emojis)

    def test_extract_discord_emojis_import(self):
        """Test extract_discord_emojis is imported."""
        from cogs.ai_core.logic import extract_discord_emojis

        assert callable(extract_discord_emojis)

    def test_fetch_emoji_images_import(self):
        """Test fetch_emoji_images is imported."""
        from cogs.ai_core.logic import fetch_emoji_images

        assert callable(fetch_emoji_images)


class TestApiHandlerImports:
    """Tests for API handler imports."""

    def test_build_api_config_import(self):
        """Test build_api_config is imported."""
        from cogs.ai_core.logic import build_api_config

        assert callable(build_api_config)

    def test_call_gemini_api_import(self):
        """Test call_gemini_api is imported."""
        from cogs.ai_core.logic import call_gemini_api

        assert callable(call_gemini_api)

    def test_detect_search_intent_import(self):
        """Test detect_search_intent is imported."""
        from cogs.ai_core.logic import detect_search_intent

        assert callable(detect_search_intent)


class TestMediaProcessorImports:
    """Tests for media processor imports."""

    def test_convert_gif_to_video_import(self):
        """Test convert_gif_to_video is imported."""
        from cogs.ai_core.logic import convert_gif_to_video

        assert callable(convert_gif_to_video)

    def test_is_animated_gif_import(self):
        """Test is_animated_gif is imported."""
        from cogs.ai_core.logic import is_animated_gif

        assert callable(is_animated_gif)

    def test_load_character_image_import(self):
        """Test load_character_image is imported."""
        from cogs.ai_core.logic import load_character_image

        assert callable(load_character_image)

    def test_pil_to_inline_data_import(self):
        """Test pil_to_inline_data is imported."""
        from cogs.ai_core.logic import pil_to_inline_data

        assert callable(pil_to_inline_data)


class TestMemoryImports:
    """Tests for memory related imports."""

    def test_memory_consolidator_import(self):
        """Test memory_consolidator is imported."""
        from cogs.ai_core.logic import memory_consolidator

        assert memory_consolidator is not None

    def test_entity_memory_import(self):
        """Test entity_memory is imported."""
        from cogs.ai_core.logic import entity_memory

        assert entity_memory is not None

    def test_rag_system_import(self):
        """Test rag_system is imported."""
        from cogs.ai_core.logic import rag_system

        assert rag_system is not None

    def test_state_tracker_import(self):
        """Test state_tracker is imported."""
        from cogs.ai_core.logic import state_tracker

        assert state_tracker is not None

    def test_summarizer_import(self):
        """Test summarizer is imported."""
        from cogs.ai_core.logic import summarizer

        assert summarizer is not None


class TestToolsImport:
    """Tests for tools imports."""

    def test_execute_tool_call_import(self):
        """Test execute_tool_call is imported."""
        from cogs.ai_core.logic import execute_tool_call

        assert callable(execute_tool_call)

    def test_send_as_webhook_import(self):
        """Test send_as_webhook is imported."""
        from cogs.ai_core.logic import send_as_webhook

        assert callable(send_as_webhook)


class TestServerCharactersImport:
    """Tests for SERVER_CHARACTER_NAMES import."""

    def test_server_characters_import(self):
        """Test SERVER_CHARACTER_NAMES is imported."""
        from cogs.ai_core.logic import SERVER_CHARACTER_NAMES

        assert SERVER_CHARACTER_NAMES is not None


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_docstring_mentions_ai(self):
        """Test logic module docstring mentions AI."""
        from cogs.ai_core import logic

        assert "AI" in logic.__doc__


class TestConstantsImports:
    """Tests for constants imports."""

    def test_creator_id_import(self):
        """Test CREATOR_ID is imported."""
        from cogs.ai_core.logic import CREATOR_ID

        assert CREATOR_ID is not None

    def test_gemini_model_import(self):
        """Test GEMINI_MODEL is imported."""
        from cogs.ai_core.logic import GEMINI_MODEL

        assert GEMINI_MODEL is not None

    def test_guild_id_rp_import(self):
        """Test GUILD_ID_RP is imported."""
        from cogs.ai_core.logic import GUILD_ID_RP

        assert GUILD_ID_RP is not None

    def test_max_history_items_import(self):
        """Test MAX_HISTORY_ITEMS is imported."""
        from cogs.ai_core.logic import MAX_HISTORY_ITEMS

        assert isinstance(MAX_HISTORY_ITEMS, int)

    def test_lock_timeout_import(self):
        """Test LOCK_TIMEOUT is imported."""
        from cogs.ai_core.logic import LOCK_TIMEOUT

        assert LOCK_TIMEOUT is not None


# ======================================================================
# Merged from test_logic_module.py
# ======================================================================

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

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            assert manager.bot == mock_bot
            assert manager.chats == {}
            assert manager.last_accessed == {}
            assert manager.seen_users == {}

    def test_chat_manager_has_message_queue(self):
        """Test ChatManager has message queue."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            assert manager._message_queue is not None

    def test_chat_manager_has_performance_tracker(self):
        """Test ChatManager has performance tracker."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            assert manager._performance is not None

    def test_chat_manager_has_deduplicator(self):
        """Test ChatManager has request deduplicator."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            assert manager._deduplicator is not None


class TestChatManagerMethods:
    """Tests for ChatManager methods."""

    def test_get_performance_stats(self):
        """Test get_performance_stats."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            stats = manager.get_performance_stats()

            assert isinstance(stats, dict)

    def test_record_timing(self):
        """Test record_timing."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            # Should not raise
            manager.record_timing("test_step", 0.5)

    def test_cleanup_pending_requests(self):
        """Test cleanup_pending_requests."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            result = manager.cleanup_pending_requests()

            assert isinstance(result, int)
            assert result >= 0

    def test_parse_voice_command_join(self):
        """Test parse_voice_command for join."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            # Test parsing voice command - actual behavior depends on voice module
            action, channel_id = manager.parse_voice_command("join voice channel 123456789012345678")

            # Result depends on voice module implementation
            assert action is None or isinstance(action, str)

    def test_process_response_text_basic(self):
        """Test _process_response_text basic processing."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            result = manager._process_response_text("Hello world", None, "")

            assert result == "Hello world"

    def test_process_response_text_removes_quote(self):
        """Test _process_response_text removes > before quotes."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            result = manager._process_response_text('> "Hello"', None, "")

            assert result == '"Hello"'

    def test_process_response_text_adds_search_indicator(self):
        """Test _process_response_text adds search indicator."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            result = manager._process_response_text("Hello", None, "🔍 ")

            assert result == "🔍 Hello"

    def test_is_animated_gif(self):
        """Test _is_animated_gif method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
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

        with patch('cogs.ai_core.logic.GEMINI_API_KEY', ""):
            manager = ChatManager(mock_bot)

            assert manager.client is None

    def test_setup_ai_with_api_key(self):
        """Test setup_ai with API key."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()
        mock_client = MagicMock()

        with patch('cogs.ai_core.logic.GEMINI_API_KEY', "test-key"):
            with patch('cogs.ai_core.logic.genai.Client', return_value=mock_client):
                manager = ChatManager(mock_bot)

                assert manager.client == mock_client


class TestAsyncMethods:
    """Tests for async methods."""

    @pytest.mark.asyncio
    async def test_join_voice_channel(self):
        """Test join_voice_channel method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            with patch('cogs.ai_core.logic.voice_join', new_callable=AsyncMock) as mock_join:
                mock_join.return_value = (True, "Joined")

                success, msg = await manager.join_voice_channel(123)

                assert success is True
                mock_join.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_voice_channel(self):
        """Test leave_voice_channel method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)

            with patch('cogs.ai_core.logic.voice_leave', new_callable=AsyncMock) as mock_leave:
                mock_leave.return_value = (True, "Left")

                success, msg = await manager.leave_voice_channel(123)

                assert success is True
                mock_leave.assert_called_once()

    @pytest.mark.asyncio
    async def test_detect_search_intent(self):
        """Test _detect_search_intent method."""
        from cogs.ai_core.logic import ChatManager

        mock_bot = MagicMock()

        with patch.object(ChatManager, 'setup_ai'):
            manager = ChatManager(mock_bot)
            manager.client = MagicMock()
            manager.target_model = "test-model"

            with patch('cogs.ai_core.logic.detect_search_intent', new_callable=AsyncMock) as mock_detect:
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
