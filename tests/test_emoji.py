"""
Tests for cogs.ai_core.emoji module.
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestConvertDiscordEmojis:
    """Tests for convert_discord_emojis function."""

    def test_converts_static_emoji(self):
        """Test static emoji conversion."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "Hello <:smile:123456789> world"
        result = convert_discord_emojis(text)

        assert result == "Hello [:smile:] world"

    def test_converts_animated_emoji(self):
        """Test animated emoji conversion."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "Dancing <a:dance:987654321> time"
        result = convert_discord_emojis(text)

        assert result == "Dancing [:dance:] time"

    def test_converts_multiple_emojis(self):
        """Test multiple emoji conversion."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "<:happy:111> and <a:sad:222> and <:neutral:333>"
        result = convert_discord_emojis(text)

        assert result == "[:happy:] and [:sad:] and [:neutral:]"

    def test_no_change_for_text_without_emojis(self):
        """Test text without emojis is unchanged."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "Just regular text here"
        result = convert_discord_emojis(text)

        assert result == text

    def test_preserves_unicode_emojis(self):
        """Test that unicode emojis are not affected."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "Hello 😊 <:custom:123> world 🎉"
        result = convert_discord_emojis(text)

        assert result == "Hello 😊 [:custom:] world 🎉"


class TestExtractDiscordEmojis:
    """Tests for extract_discord_emojis function."""

    def test_extracts_static_emoji(self):
        """Test extracting static emoji info."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "Hello <:smile:123456789>"
        result = extract_discord_emojis(text)

        assert len(result) == 1
        assert result[0]["name"] == "smile"
        assert result[0]["id"] == "123456789"
        assert result[0]["animated"] is False
        assert "png" in result[0]["url"]

    def test_extracts_animated_emoji(self):
        """Test extracting animated emoji info."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "Dancing <a:dance:987654321>"
        result = extract_discord_emojis(text)

        assert len(result) == 1
        assert result[0]["name"] == "dance"
        assert result[0]["id"] == "987654321"
        assert result[0]["animated"] is True
        assert "gif" in result[0]["url"]

    def test_extracts_multiple_unique_emojis(self):
        """Test extracting multiple unique emojis."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "<:one:111> <a:two:222> <:three:333>"
        result = extract_discord_emojis(text)

        assert len(result) == 3
        assert result[0]["name"] == "one"
        assert result[1]["name"] == "two"
        assert result[2]["name"] == "three"

    def test_deduplicates_emojis(self):
        """Test that duplicate emojis are deduplicated."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "<:same:123> <:same:123> <:same:123>"
        result = extract_discord_emojis(text)

        assert len(result) == 1

    def test_returns_empty_for_no_emojis(self):
        """Test empty list for text without emojis."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "No emojis here"
        result = extract_discord_emojis(text)

        assert result == []

    def test_correct_cdn_url_format(self):
        """Test that CDN URL format is correct."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "<:test:12345>"
        result = extract_discord_emojis(text)

        expected_url = "https://cdn.discordapp.com/emojis/12345.png?size=64"
        assert result[0]["url"] == expected_url


class TestPatternDiscordEmoji:
    """Tests for PATTERN_DISCORD_EMOJI regex."""

    def test_pattern_matches_static(self):
        """Test pattern matches static emoji."""
        from cogs.ai_core.emoji import PATTERN_DISCORD_EMOJI

        match = PATTERN_DISCORD_EMOJI.search("<:name:123>")
        assert match is not None
        assert match.group(1) == ""  # Not animated
        assert match.group(2) == "name"
        assert match.group(3) == "123"

    def test_pattern_matches_animated(self):
        """Test pattern matches animated emoji."""
        from cogs.ai_core.emoji import PATTERN_DISCORD_EMOJI

        match = PATTERN_DISCORD_EMOJI.search("<a:name:123>")
        assert match is not None
        assert match.group(1) == "a"  # Animated
        assert match.group(2) == "name"
        assert match.group(3) == "123"

    def test_pattern_finds_all(self):
        """Test pattern finds all emojis in text."""
        from cogs.ai_core.emoji import PATTERN_DISCORD_EMOJI

        text = "<:one:1> text <a:two:2> more <:three:3>"
        matches = list(PATTERN_DISCORD_EMOJI.finditer(text))

        assert len(matches) == 3


class TestFetchEmojiImages:
    """Tests for fetch_emoji_images function."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_fetch_limits_to_five(self):
        """Test that fetch is limited to 5 emojis."""
        from cogs.ai_core.emoji import fetch_emoji_images

        emojis = [
            {"name": f"emoji{i}", "url": f"http://example.com/{i}.png", "animated": False}
            for i in range(10)
        ]

        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 404  # Return 404 so no actual processing
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_response

            mock_session_instance = AsyncMock()
            mock_session_instance.get.return_value = mock_context
            mock_session.return_value.__aenter__.return_value = mock_session_instance

            await fetch_emoji_images(emojis)

            # Should only try to fetch 5 emojis
            assert mock_session_instance.get.call_count == 5

    @pytest.mark.asyncio
    async def test_returns_empty_on_empty_input(self):
        """Test empty input returns empty list."""
        from cogs.ai_core.emoji import fetch_emoji_images

        result = await fetch_emoji_images([])
        assert result == []

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_handles_failed_requests(self):
        """Test that failed requests don't crash."""
        from cogs.ai_core.emoji import fetch_emoji_images

        emojis = [{"name": "test", "url": "http://invalid.url", "animated": False}]

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.get.side_effect = Exception("Network error")
            mock_session.return_value.__aenter__.return_value = mock_session_instance

            result = await fetch_emoji_images(emojis)
            assert result == []
