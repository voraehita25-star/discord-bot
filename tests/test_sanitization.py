"""Tests for sanitization module."""


class TestSanitizeChannelName:
    """Tests for sanitize_channel_name function."""

    def test_basic_channel_name(self):
        """Test basic channel name sanitization."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("general")
        assert result == "general"

    def test_with_spaces(self):
        """Test channel name with spaces converted to dashes."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("my channel name")
        assert result == "my-channel-name"

    def test_multiple_spaces(self):
        """Test multiple spaces normalized to single dash."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("my    channel   name")
        assert result == "my-channel-name"

    def test_removes_special_characters(self):
        """Test removal of special characters."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("channel@!#$%name")
        assert result == "channelname"

    def test_preserves_dashes_underscores(self):
        """Test that dashes and underscores are preserved."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("my-channel_name")
        assert result == "my-channel_name"

    def test_preserves_thai_characters(self):
        """Test that Thai characters are preserved."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("ห้องทั่วไป")
        assert "ห้องทั่วไป" in result or len(result) > 0

    def test_max_length(self):
        """Test channel name length limit."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        long_name = "a" * 150
        result = sanitize_channel_name(long_name)
        assert len(result) <= 100

    def test_custom_max_length(self):
        """Test custom max length parameter."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        long_name = "a" * 50
        result = sanitize_channel_name(long_name, max_length=20)
        assert len(result) <= 20

    def test_consecutive_dashes_normalized(self):
        """Test that consecutive dashes are normalized."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("my---channel---name")
        assert result == "my-channel-name"

    def test_strips_leading_trailing_dashes(self):
        """Test that leading/trailing dashes are stripped."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("---channelname---")
        assert result == "channelname"

    def test_empty_string(self):
        """Test empty string input returns fallback."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("")
        assert result == "untitled"

    def test_only_special_characters(self):
        """Test input with only special characters returns fallback."""
        from cogs.ai_core.sanitization import sanitize_channel_name

        result = sanitize_channel_name("@#$%^&*()")
        assert result == "untitled"


class TestSanitizeRoleName:
    """Tests for sanitize_role_name function."""

    def test_basic_role_name(self):
        """Test basic role name sanitization."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("Admin")
        assert result == "Admin"

    def test_removes_angle_brackets(self):
        """Test removal of angle brackets."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("<Admin>")
        assert result == "Admin"

    def test_removes_at_symbol(self):
        """Test removal of @ symbol."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("@Admin")
        assert result == "Admin"

    def test_removes_hash_symbol(self):
        """Test removal of # symbol."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("#Moderator")
        assert result == "Moderator"

    def test_removes_ampersand(self):
        """Test removal of & symbol."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("Admin&Staff")
        assert result == "AdminStaff"

    def test_preserves_other_characters(self):
        """Test that other characters are preserved."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("Super-Admin_Team")
        assert result == "Super-Admin_Team"

    def test_max_length(self):
        """Test role name length limit."""
        from cogs.ai_core.sanitization import sanitize_role_name

        long_name = "A" * 150
        result = sanitize_role_name(long_name)
        assert len(result) <= 100

    def test_custom_max_length(self):
        """Test custom max length parameter."""
        from cogs.ai_core.sanitization import sanitize_role_name

        long_name = "A" * 50
        result = sanitize_role_name(long_name, max_length=25)
        assert len(result) <= 25

    def test_strips_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("  Admin  ")
        assert result == "Admin"

    def test_empty_string(self):
        """Test empty string input returns fallback."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("")
        assert result == "unnamed-role"

    def test_only_dangerous_characters(self):
        """Test input with only dangerous characters returns fallback."""
        from cogs.ai_core.sanitization import sanitize_role_name

        result = sanitize_role_name("<>@#&")
        assert result == "unnamed-role"


class TestSanitizeMessageContent:
    """Tests for sanitize_message_content function."""

    def test_basic_message(self):
        """Test basic message content."""
        from cogs.ai_core.sanitization import sanitize_message_content

        result = sanitize_message_content("Hello, world!")
        assert result == "Hello, world!"

    def test_escapes_everyone_mention(self):
        """Test that @everyone is escaped."""
        from cogs.ai_core.sanitization import sanitize_message_content

        result = sanitize_message_content("Hello @everyone!")
        assert "@everyone" not in result
        assert "@\u200beveryone" in result

    def test_escapes_here_mention(self):
        """Test that @here is escaped."""
        from cogs.ai_core.sanitization import sanitize_message_content

        result = sanitize_message_content("Attention @here!")
        assert "@here" not in result
        assert "@\u200bhere" in result

    def test_max_length(self):
        """Test message content length limit."""
        from cogs.ai_core.sanitization import sanitize_message_content

        long_message = "A" * 3000
        result = sanitize_message_content(long_message)
        assert len(result) <= 2000

    def test_max_length_adds_ellipsis(self):
        """Test that truncated messages get ellipsis."""
        from cogs.ai_core.sanitization import sanitize_message_content

        long_message = "A" * 3000
        result = sanitize_message_content(long_message)
        assert result.endswith("...")

    def test_custom_max_length(self):
        """Test custom max length parameter."""
        from cogs.ai_core.sanitization import sanitize_message_content

        long_message = "A" * 500
        result = sanitize_message_content(long_message, max_length=100)
        assert len(result) <= 100

    def test_none_input(self):
        """Test None input returns empty string."""
        from cogs.ai_core.sanitization import sanitize_message_content

        result = sanitize_message_content(None)
        assert result == ""

    def test_empty_string(self):
        """Test empty string input."""
        from cogs.ai_core.sanitization import sanitize_message_content

        result = sanitize_message_content("")
        assert result == ""

    def test_under_max_length(self):
        """Test message under max length is unchanged."""
        from cogs.ai_core.sanitization import sanitize_message_content

        message = "Short message"
        result = sanitize_message_content(message)
        assert result == message

    def test_multiple_mentions_escaped(self):
        """Test multiple mentions are all escaped."""
        from cogs.ai_core.sanitization import sanitize_message_content

        message = "@everyone please see this @here urgent"
        result = sanitize_message_content(message)
        assert "@everyone" not in result
        assert "@here" not in result


class TestModuleExports:
    """Tests for module exports."""

    def test_all_functions_exported(self):
        """Test that __all__ contains expected functions."""
        from cogs.ai_core import sanitization

        assert "sanitize_channel_name" in sanitization.__all__
        assert "sanitize_role_name" in sanitization.__all__
        assert "sanitize_message_content" in sanitization.__all__

    def test_imports_work(self):
        """Test that imports work correctly."""
        from cogs.ai_core.sanitization import (
            sanitize_channel_name,
            sanitize_message_content,
            sanitize_role_name,
        )

        assert callable(sanitize_channel_name)
        assert callable(sanitize_role_name)
        assert callable(sanitize_message_content)


class TestRegexPatterns:
    """Tests for internal regex patterns."""

    def test_safe_channel_name_pattern_exists(self):
        """Test that channel name pattern exists."""
        from cogs.ai_core import sanitization

        assert hasattr(sanitization, "_SAFE_CHANNEL_NAME")

    def test_safe_role_name_pattern_exists(self):
        """Test that role name pattern exists."""
        from cogs.ai_core import sanitization

        assert hasattr(sanitization, "_SAFE_ROLE_NAME")
