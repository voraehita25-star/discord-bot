"""
Tests for cogs/ai_core/response/response_sender.py

Comprehensive tests for ResponseSender class.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestSendResultDataclass:
    """Tests for SendResult dataclass."""

    def test_send_result_defaults(self):
        """Test SendResult default values."""
        from cogs.ai_core.response.response_sender import SendResult

        result = SendResult(success=True)

        assert result.success is True
        assert result.message_id is None
        assert result.error is None
        assert result.sent_via == "direct"
        assert result.character_name is None
        assert result.chunk_count == 1

    def test_send_result_with_values(self):
        """Test SendResult with custom values."""
        from cogs.ai_core.response.response_sender import SendResult

        result = SendResult(
            success=True,
            message_id=12345,
            sent_via="webhook",
            character_name="TestBot",
            chunk_count=3,
        )

        assert result.success is True
        assert result.message_id == 12345
        assert result.sent_via == "webhook"
        assert result.character_name == "TestBot"
        assert result.chunk_count == 3

    def test_send_result_with_error(self):
        """Test SendResult with error."""
        from cogs.ai_core.response.response_sender import SendResult

        result = SendResult(success=False, error="Network error")

        assert result.success is False
        assert result.error == "Network error"


class TestResponseSenderInit:
    """Tests for ResponseSender initialization."""

    def test_init_defaults(self):
        """Test init with default values."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()

        assert sender.webhook_cache is None
        assert sender.avatar_manager is None

    def test_init_with_managers(self):
        """Test init with managers."""
        from cogs.ai_core.response.response_sender import ResponseSender

        mock_cache = MagicMock()
        mock_avatar = MagicMock()

        sender = ResponseSender(webhook_cache=mock_cache, avatar_manager=mock_avatar)

        assert sender.webhook_cache is mock_cache
        assert sender.avatar_manager is mock_avatar


class TestResponseSenderExtractCharacterTag:
    """Tests for extract_character_tag method."""

    def test_extract_no_tag(self):
        """Test extracting when no tag present."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        name, content = sender.extract_character_tag("Hello world!")

        assert name is None
        assert content == "Hello world!"

    def test_extract_with_tag(self):
        """Test extracting character tag."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        name, content = sender.extract_character_tag("[Alice]: Hello world!")

        assert name == "Alice"
        assert content == "Hello world!"

    def test_extract_tag_with_spaces(self):
        """Test extracting tag with spaces in name."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        name, content = sender.extract_character_tag("[Dr. Bob Smith]: Greetings!")

        assert name == "Dr. Bob Smith"
        assert content == "Greetings!"

    def test_extract_tag_empty_content(self):
        """Test extracting tag with empty content after."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        name, content = sender.extract_character_tag("[Test]: ")

        assert name == "Test"
        assert content == ""


class TestResponseSenderSplitContent:
    """Tests for split_content method."""

    def test_split_short_content(self):
        """Test splitting content that fits."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        chunks = sender.split_content("Hello world!", max_length=2000)

        assert len(chunks) == 1
        assert chunks[0] == "Hello world!"

    def test_split_long_content(self):
        """Test splitting long content."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        # Create content that exceeds limit
        content = "Word " * 500  # ~2500 chars
        chunks = sender.split_content(content, max_length=1000)

        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 1000

    def test_split_at_paragraph(self):
        """Test splitting prefers paragraph breaks."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        content = "A" * 800 + "\n\n" + "B" * 800
        chunks = sender.split_content(content, max_length=1000)

        # Should split at the paragraph break
        assert len(chunks) >= 2

    def test_split_at_sentence(self):
        """Test splitting at sentence breaks."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        content = "A" * 700 + ". " + "B" * 700
        chunks = sender.split_content(content, max_length=800)

        assert len(chunks) >= 2


class TestResponseSenderFindSplitPoint:
    """Tests for _find_split_point method."""

    def test_find_split_paragraph(self):
        """Test finding paragraph split point."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        text = "Hello world\n\nSecond paragraph here"
        split = sender._find_split_point(text, 20)

        # Should find the paragraph break
        assert split > 0
        assert split <= 20

    def test_find_split_sentence(self):
        """Test finding sentence split point."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        text = "First sentence. Second sentence here"
        split = sender._find_split_point(text, 20)

        assert split > 0
        assert split <= 20

    def test_find_split_word(self):
        """Test finding word split point."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        text = "Hello world foo bar baz"
        split = sender._find_split_point(text, 15)

        assert split > 0
        assert split <= 15

    def test_find_split_hard_break(self):
        """Test hard break when no good split point."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        text = "A" * 100  # No spaces or breaks
        split = sender._find_split_point(text, 50)

        # Should be exactly max_length
        assert split == 50


class TestResponseSenderSendResponse:
    """Tests for send_response method."""

    @pytest.mark.asyncio
    async def test_send_empty_content(self):
        """Test sending empty content fails."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        channel = MagicMock()

        result = await sender.send_response(channel, "")

        assert result.success is False
        assert "Empty content" in result.error

    @pytest.mark.asyncio
    async def test_send_whitespace_content(self):
        """Test sending whitespace content fails."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        channel = MagicMock()

        result = await sender.send_response(channel, "   ")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_extracts_character_tag(self):
        """Test send extracts character tag."""
        from cogs.ai_core.response.response_sender import ResponseSender

        sender = ResponseSender()
        channel = MagicMock()
        channel.send = AsyncMock(return_value=MagicMock(id=123))

        result = await sender.send_response(
            channel, "[Alice]: Hello!", use_webhook=False
        )

        # Should have used Alice as character name
        assert result.success is True


class TestModuleConstants:
    """Tests for module constants."""

    def test_max_discord_length(self):
        """Test MAX_DISCORD_LENGTH constant."""
        from cogs.ai_core.response.response_sender import MAX_DISCORD_LENGTH

        assert MAX_DISCORD_LENGTH == 2000

    def test_webhook_send_timeout(self):
        """Test WEBHOOK_SEND_TIMEOUT constant."""
        from cogs.ai_core.response.response_sender import WEBHOOK_SEND_TIMEOUT

        assert WEBHOOK_SEND_TIMEOUT > 0


class TestRegexPatterns:
    """Tests for compiled regex patterns."""

    def test_character_tag_pattern(self):
        """Test CHARACTER_TAG_PATTERN matches correctly."""
        from cogs.ai_core.response.response_sender import CHARACTER_TAG_PATTERN

        match = CHARACTER_TAG_PATTERN.match("[Alice]: Hello")
        assert match is not None
        assert match.group(1) == "Alice"

    def test_character_tag_pattern_no_match(self):
        """Test CHARACTER_TAG_PATTERN doesn't match invalid."""
        from cogs.ai_core.response.response_sender import CHARACTER_TAG_PATTERN

        match = CHARACTER_TAG_PATTERN.match("Not a tag: Hello")
        assert match is None

    def test_url_pattern(self):
        """Test URL_PATTERN matches URLs."""
        from cogs.ai_core.response.response_sender import URL_PATTERN

        assert URL_PATTERN.search("Check https://example.com out")
        assert URL_PATTERN.search("Visit http://test.com")

    def test_mention_pattern(self):
        """Test MENTION_PATTERN matches Discord mentions."""
        from cogs.ai_core.response.response_sender import MENTION_PATTERN

        match = MENTION_PATTERN.search("Hello <@123456789>")
        assert match is not None
        assert match.group(1) == "123456789"
