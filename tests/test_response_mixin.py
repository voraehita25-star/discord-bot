# pylint: disable=protected-access
"""
Unit Tests for Response Mixin Module.
Tests response processing, history retrieval, and pattern matching.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPatterns:
    """Tests for precompiled regex patterns."""

    def test_pattern_quote_matches(self):
        """Test PATTERN_QUOTE matches quote patterns."""
        from cogs.ai_core.response.response_mixin import PATTERN_QUOTE

        text = '> "Hello world"'
        match = PATTERN_QUOTE.search(text)
        assert match is not None
        assert match.group(1) == '"'

    def test_pattern_quote_single_quote(self):
        """Test PATTERN_QUOTE matches single quotes."""
        from cogs.ai_core.response.response_mixin import PATTERN_QUOTE

        text = "> 'Hello world'"
        match = PATTERN_QUOTE.search(text)
        assert match is not None
        assert match.group(1) == "'"

    def test_pattern_spaced_matches(self):
        """Test PATTERN_SPACED matches spaced patterns."""
        from cogs.ai_core.response.response_mixin import PATTERN_SPACED

        text = '>   "Hello"'
        match = PATTERN_SPACED.search(text)
        assert match is not None

    def test_pattern_channel_id_matches(self):
        """Test PATTERN_CHANNEL_ID matches channel IDs."""
        from cogs.ai_core.response.response_mixin import PATTERN_CHANNEL_ID

        text = "Show history for 12345678901234567"
        match = PATTERN_CHANNEL_ID.search(text)
        assert match is not None
        assert match.group(1) == "12345678901234567"

    def test_pattern_channel_id_no_match_short(self):
        """Test PATTERN_CHANNEL_ID doesn't match short numbers."""
        from cogs.ai_core.response.response_mixin import PATTERN_CHANNEL_ID

        text = "Show history for 12345"
        match = PATTERN_CHANNEL_ID.search(text)
        assert match is None


class TestKeywords:
    """Tests for keyword lists."""

    def test_history_keywords_exist(self):
        """Test HISTORY_KEYWORDS list exists and has items."""
        from cogs.ai_core.response.response_mixin import HISTORY_KEYWORDS

        assert isinstance(HISTORY_KEYWORDS, list)
        assert len(HISTORY_KEYWORDS) > 0
        assert "history" in HISTORY_KEYWORDS
        assert "ประวัติ" in HISTORY_KEYWORDS

    def test_list_keywords_exist(self):
        """Test LIST_KEYWORDS list exists and has items."""
        from cogs.ai_core.response.response_mixin import LIST_KEYWORDS

        assert isinstance(LIST_KEYWORDS, list)
        assert len(LIST_KEYWORDS) > 0
        assert "list" in LIST_KEYWORDS


class TestResponseMixinMethods:
    """Tests for ResponseMixin class methods."""

    def create_mixin_instance(self):
        """Create a mock ResponseMixin instance."""
        from cogs.ai_core.response.response_mixin import ResponseMixin

        class MockManager(ResponseMixin):
            def __init__(self):
                self.bot = MagicMock()
                self.bot.voice_clients = []

        return MockManager()

    def test_extract_channel_id_request_found(self):
        """Test _extract_channel_id_request finds channel ID."""
        mixin = self.create_mixin_instance()

        result = mixin._extract_channel_id_request("ดูประวัติ 12345678901234567")

        assert result == 12345678901234567

    def test_extract_channel_id_request_not_found(self):
        """Test _extract_channel_id_request returns None without ID."""
        mixin = self.create_mixin_instance()

        result = mixin._extract_channel_id_request("ดูประวัติ")

        assert result is None

    def test_extract_channel_id_request_no_keyword(self):
        """Test _extract_channel_id_request returns None without keyword."""
        mixin = self.create_mixin_instance()

        result = mixin._extract_channel_id_request("random text 12345678901234567")

        assert result is None

    def test_is_asking_about_channels_true(self):
        """Test _is_asking_about_channels returns True for channel queries."""
        mixin = self.create_mixin_instance()

        assert mixin._is_asking_about_channels("มีช่องไหนบ้าง") is True
        assert mixin._is_asking_about_channels("show all channel") is True
        assert mixin._is_asking_about_channels("list รายการ") is True

    def test_is_asking_about_channels_false(self):
        """Test _is_asking_about_channels returns False for normal messages."""
        mixin = self.create_mixin_instance()

        assert mixin._is_asking_about_channels("Hello") is False
        assert mixin._is_asking_about_channels("random text") is False

    def test_get_voice_status_no_connections(self):
        """Test _get_voice_status with no voice connections."""
        mixin = self.create_mixin_instance()
        mixin.bot.voice_clients = []

        result = mixin._get_voice_status()

        assert "ไม่ได้เชื่อมต่อ" in result

    def test_get_voice_status_with_connection(self):
        """Test _get_voice_status with active voice connection."""
        mixin = self.create_mixin_instance()

        # Create mock voice client
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.guild = MagicMock()
        mock_vc.guild.name = "Test Server"
        mock_vc.guild.id = 123
        mock_vc.channel = MagicMock()
        mock_vc.channel.name = "music"
        mock_vc.channel.members = []

        mixin.bot.voice_clients = [mock_vc]
        mixin.bot.get_cog.return_value = None

        result = mixin._get_voice_status()

        assert "Test Server" in result
        assert "music" in result

    def test_get_voice_status_playing(self):
        """Test _get_voice_status when playing music."""
        mixin = self.create_mixin_instance()

        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = True
        mock_vc.is_paused.return_value = False
        mock_vc.guild = MagicMock()
        mock_vc.guild.name = "Test Server"
        mock_vc.guild.id = 123
        mock_vc.channel = MagicMock()
        mock_vc.channel.name = "music"
        mock_vc.channel.members = []

        mixin.bot.voice_clients = [mock_vc]
        mixin.bot.get_cog.return_value = None

        result = mixin._get_voice_status()

        assert "กำลังเล่นเพลง" in result

    def test_process_response_text_basic(self):
        """Test _process_response_text basic processing."""
        mixin = self.create_mixin_instance()

        result = mixin._process_response_text("Hello world", None, "")

        assert result == "Hello world"

    def test_process_response_text_with_search_indicator(self):
        """Test _process_response_text adds search indicator."""
        mixin = self.create_mixin_instance()

        result = mixin._process_response_text("Hello world", None, "🔍 ")

        assert result.startswith("🔍 ")

    def test_process_response_text_fixes_quotes(self):
        """Test _process_response_text fixes quote patterns."""
        mixin = self.create_mixin_instance()

        # The pattern > "Hello" should become "Hello"
        text = '> "Hello"'
        result = mixin._process_response_text(text, None, "")

        assert result == '"Hello"'


class TestResponseMixinAsync:
    """Async tests for ResponseMixin."""

    def create_mixin_instance(self):
        """Create a mock ResponseMixin instance."""
        from cogs.ai_core.response.response_mixin import ResponseMixin

        class MockManager(ResponseMixin):
            def __init__(self):
                self.bot = MagicMock()

        return MockManager()

    @pytest.mark.asyncio
    async def test_get_chat_history_index_empty(self):
        """Test _get_chat_history_index with no history."""
        mixin = self.create_mixin_instance()

        with patch('cogs.ai_core.response.response_mixin.get_all_channels_summary') as mock_get:
            mock_get.return_value = []

            result = await mixin._get_chat_history_index()

            assert "ไม่มีประวัติ" in result

    @pytest.mark.asyncio
    async def test_get_chat_history_index_with_data(self):
        """Test _get_chat_history_index with data."""
        mixin = self.create_mixin_instance()

        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.guild = MagicMock()
        mock_channel.guild.name = "Test Guild"
        mixin.bot.get_channel.return_value = mock_channel

        with patch('cogs.ai_core.response.response_mixin.get_all_channels_summary') as mock_get:
            mock_get.return_value = [
                {"channel_id": 123456789, "message_count": 10}
            ]

            result = await mixin._get_chat_history_index()

            assert "รายการ Channel" in result
            assert "123456789" in result

    @pytest.mark.asyncio
    async def test_get_requested_history_not_found(self):
        """Test _get_requested_history when channel not found."""
        mixin = self.create_mixin_instance()

        with patch('cogs.ai_core.response.response_mixin.get_channel_history_preview') as mock_get:
            mock_get.return_value = None

            result = await mixin._get_requested_history(123456789)

            assert "ไม่พบประวัติ" in result

    @pytest.mark.asyncio
    async def test_get_requested_history_success(self):
        """Test _get_requested_history with valid data."""
        mixin = self.create_mixin_instance()

        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.guild = MagicMock()
        mock_channel.guild.name = "Test Guild"
        mixin.bot.get_channel.return_value = mock_channel

        with patch('cogs.ai_core.response.response_mixin.get_channel_history_preview') as mock_get:
            mock_get.return_value = [
                {"role": "user", "content": "Hello"},
                {"role": "model", "content": "Hi there!"},
            ]

            result = await mixin._get_requested_history(123456789)

            assert "Test Guild" in result
            assert "[U] Hello" in result
            assert "[AI] Hi there!" in result

    @pytest.mark.asyncio
    async def test_get_requested_history_error(self):
        """Test _get_requested_history handles errors."""
        mixin = self.create_mixin_instance()

        with patch('cogs.ai_core.response.response_mixin.get_channel_history_preview') as mock_get:
            mock_get.side_effect = OSError("Database error")

            result = await mixin._get_requested_history(123456789)

            assert "ข้อผิดพลาด" in result
