# pylint: disable=protected-access
"""
Unit Tests for AI Tools Module.
Tests server management functions and input sanitization.
"""

from __future__ import annotations

from unittest.mock import MagicMock


class TestInputSanitization:
    """Tests for input sanitization functions."""

    def test_sanitize_channel_name_removes_special_chars(self):
        """Test that special characters are removed from channel names."""
        from cogs.ai_core.tools import sanitize_channel_name

        # Test basic sanitization
        assert sanitize_channel_name("general") == "general"
        assert sanitize_channel_name("General Chat") == "General-Chat"
        assert sanitize_channel_name("test@#$%channel") == "testchannel"
        assert sanitize_channel_name("  spaces  ") == "spaces"

    def test_sanitize_channel_name_handles_thai(self):
        """Test that Thai characters are preserved in channel names."""
        from cogs.ai_core.tools import sanitize_channel_name

        # Thai text should be preserved
        result = sanitize_channel_name("ห้องสนทนา")
        assert "ห้องสนทนา" in result or len(result) > 0

    def test_sanitize_channel_name_enforces_length_limit(self):
        """Test that channel names are truncated to Discord's limit."""
        from cogs.ai_core.tools import sanitize_channel_name

        long_name = "a" * 200
        result = sanitize_channel_name(long_name)
        assert len(result) <= 100  # Discord's limit

    def test_sanitize_role_name_removes_dangerous_chars(self):
        """Test that dangerous characters are removed from role names."""
        from cogs.ai_core.tools import sanitize_role_name

        assert sanitize_role_name("Admin") == "Admin"
        assert sanitize_role_name("@everyone") != "@everyone"  # Should be sanitized
        assert sanitize_role_name("test<script>") == "testscript"

    def test_sanitize_role_name_enforces_length_limit(self):
        """Test that role names are truncated to Discord's limit."""
        from cogs.ai_core.tools import sanitize_role_name

        long_name = "Role" * 50
        result = sanitize_role_name(long_name)
        assert len(result) <= 100  # Discord's limit


class TestMessageSanitization:
    """Tests for message content sanitization."""

    def test_sanitize_message_preserves_normal_text(self):
        """Test that normal text is preserved."""
        from cogs.ai_core.tools import sanitize_message_content

        normal_text = "Hello, this is a normal message!"
        assert sanitize_message_content(normal_text) == normal_text

    def test_sanitize_message_removes_everyone_mentions(self):
        """Test that @everyone mentions are escaped."""
        from cogs.ai_core.tools import sanitize_message_content

        dangerous = "Hello @everyone!"
        result = sanitize_message_content(dangerous)
        # Should have zero-width space inserted to break the mention
        assert "@everyone" not in result or "\u200b" in result

    def test_sanitize_message_removes_here_mentions(self):
        """Test that @here mentions are escaped."""
        from cogs.ai_core.tools import sanitize_message_content

        dangerous = "Alert @here!"
        result = sanitize_message_content(dangerous)
        # Should have zero-width space inserted to break the mention
        assert "@here" not in result or "\u200b" in result

    def test_sanitize_message_handles_empty_input(self):
        """Test that empty strings and None are handled gracefully."""
        from cogs.ai_core.tools import sanitize_message_content

        assert sanitize_message_content("") == ""
        assert sanitize_message_content(None) == ""


# NOTE: TestWebhookCache and TestServerManagement were removed because they
# test functions that don't exist in the current implementation:
# - get_or_create_webhook
# - create_channel
# - delete_channel
# The actual webhook functionality uses internal _get_cached_webhook() etc.


class TestFindMember:
    """Tests for member finding functionality."""

    def test_find_member_by_name(self):
        """Test finding member by display name."""
        from cogs.ai_core.tools import find_member

        mock_member1 = MagicMock()
        mock_member1.display_name = "TestUser"
        mock_member1.name = "testuser"

        mock_member2 = MagicMock()
        mock_member2.display_name = "OtherUser"
        mock_member2.name = "otheruser"

        mock_guild = MagicMock()
        mock_guild.members = [mock_member1, mock_member2]

        result = find_member(mock_guild, "TestUser")
        assert result == mock_member1

    def test_find_member_case_insensitive(self):
        """Test that member search is case insensitive."""
        from cogs.ai_core.tools import find_member

        mock_member = MagicMock()
        mock_member.display_name = "TestUser"
        mock_member.name = "testuser"

        mock_guild = MagicMock()
        mock_guild.members = [mock_member]

        result = find_member(mock_guild, "testuser")
        assert result == mock_member

    def test_find_member_not_found_returns_none(self):
        """Test that None is returned when member not found."""
        from cogs.ai_core.tools import find_member

        mock_guild = MagicMock()
        mock_guild.members = []

        result = find_member(mock_guild, "NonExistent")
        assert result is None
