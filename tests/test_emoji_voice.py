"""
Unit Tests for Emoji and Voice Modules.
Tests for extracted modules from logic.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestEmojiModule:
    """Test Discord emoji processing functions."""

    def test_convert_discord_emojis_static(self) -> None:
        """Test converting static Discord emojis."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "Hello <:smile:123456789> world"
        result = convert_discord_emojis(text)

        assert "[:smile:]" in result
        assert "<:smile:123456789>" not in result

    def test_convert_discord_emojis_animated(self) -> None:
        """Test converting animated Discord emojis."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "Dancing <a:dance:987654321> emoji"
        result = convert_discord_emojis(text)

        assert "[:dance:]" in result
        assert "<a:dance:987654321>" not in result

    def test_convert_discord_emojis_multiple(self) -> None:
        """Test converting multiple emojis."""
        from cogs.ai_core.emoji import convert_discord_emojis

        text = "<:a:1> <:b:2> <a:c:3>"
        result = convert_discord_emojis(text)

        assert "[:a:]" in result
        assert "[:b:]" in result
        assert "[:c:]" in result

    def test_extract_discord_emojis_basic(self) -> None:
        """Test extracting emoji info."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "Hello <:smile:123456789012345678>"
        result = extract_discord_emojis(text)

        assert len(result) == 1
        assert result[0]["name"] == "smile"
        assert result[0]["id"] == "123456789012345678"
        assert result[0]["animated"] is False
        assert "url" in result[0]

    def test_extract_discord_emojis_animated(self) -> None:
        """Test extracting animated emoji."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "<a:dance:12345678901234567>"
        result = extract_discord_emojis(text)

        assert len(result) == 1
        assert result[0]["animated"] is True
        assert ".gif" in result[0]["url"]

    def test_extract_discord_emojis_dedup(self) -> None:
        """Test duplicate emoji filtering."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "<:same:123> text <:same:123>"
        result = extract_discord_emojis(text)

        # Should only return 1 (deduplicated)
        assert len(result) == 1

    def test_extract_discord_emojis_no_match(self) -> None:
        """Test with no emojis."""
        from cogs.ai_core.emoji import extract_discord_emojis

        text = "No emojis here"
        result = extract_discord_emojis(text)

        assert len(result) == 0


class TestVoiceModule:
    """Test voice channel management functions."""

    def test_parse_voice_command_join(self) -> None:
        """Test parsing join voice command."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("เข้า vc")

        assert action == "join"
        assert channel_id is None

    def test_parse_voice_command_join_with_id(self) -> None:
        """Test parsing join with channel ID."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("join vc 12345678901234567890")

        assert action == "join"
        assert channel_id == 12345678901234567890

    def test_parse_voice_command_leave(self) -> None:
        """Test parsing leave command."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("ออกจาก vc")

        assert action == "leave"
        assert channel_id is None

    def test_parse_voice_command_leave_english(self) -> None:
        """Test parsing leave in English."""
        from cogs.ai_core.voice import parse_voice_command

        action, _ = parse_voice_command("leave vc please")

        assert action == "leave"

    def test_parse_voice_command_none(self) -> None:
        """Test no voice command detected."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("Hello there")

        assert action is None
        assert channel_id is None

    def test_parse_voice_command_disconnect(self) -> None:
        """Test disconnect command."""
        from cogs.ai_core.voice import parse_voice_command

        action, _ = parse_voice_command("disconnect from voice")

        assert action == "leave"

    def test_get_voice_status_no_clients(self) -> None:
        """Test voice status with no connections."""
        from cogs.ai_core.voice import get_voice_status

        mock_bot = MagicMock()
        mock_bot.voice_clients = []

        result = get_voice_status(mock_bot)

        assert "ไม่ได้เชื่อมต่อ" in result


# Run tests with: python -m pytest tests/test_emoji_voice.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
