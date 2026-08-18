"""
Tests for cogs.ai_core.data.constants module.
"""

import os
from unittest.mock import patch


class TestSafeIntEnv:
    """Tests for _safe_int_env function."""

    def test_safe_int_env_with_digit(self):
        """Test _safe_int_env with digit value."""
        from cogs.ai_core.data.constants import _safe_int_env

        with patch.dict(os.environ, {"TEST_INT": "123"}):
            result = _safe_int_env("TEST_INT")
            assert result == 123

    def test_safe_int_env_with_default(self):
        """Test _safe_int_env returns default for missing key."""
        from cogs.ai_core.data.constants import _safe_int_env

        result = _safe_int_env("NONEXISTENT_KEY_12345", default=42)
        assert result == 42

    def test_safe_int_env_with_non_digit(self):
        """Test _safe_int_env returns default for non-digit value."""
        from cogs.ai_core.data.constants import _safe_int_env

        with patch.dict(os.environ, {"TEST_STR": "not_a_number"}):
            result = _safe_int_env("TEST_STR", default=10)
            assert result == 10

    def test_safe_int_env_empty_string(self):
        """Test _safe_int_env with empty string returns default."""
        from cogs.ai_core.data.constants import _safe_int_env

        with patch.dict(os.environ, {"TEST_EMPTY": ""}):
            result = _safe_int_env("TEST_EMPTY", default=5)
            assert result == 5


class TestGuildIds:
    """Tests for guild ID constants."""

    def test_guild_id_main_exists(self):
        """Test GUILD_ID_MAIN is defined."""
        from cogs.ai_core.data.constants import GUILD_ID_MAIN

        assert isinstance(GUILD_ID_MAIN, int)

    def test_guild_id_restricted_exists(self):
        """Test GUILD_ID_RESTRICTED is defined."""
        from cogs.ai_core.data.constants import GUILD_ID_RESTRICTED

        assert isinstance(GUILD_ID_RESTRICTED, int)

    def test_guild_id_rp_exists(self):
        """Test GUILD_ID_RP is defined."""
        from cogs.ai_core.data.constants import GUILD_ID_RP

        assert isinstance(GUILD_ID_RP, int)

    def test_guild_id_command_only_exists(self):
        """Test GUILD_ID_COMMAND_ONLY is defined."""
        from cogs.ai_core.data.constants import GUILD_ID_COMMAND_ONLY

        assert isinstance(GUILD_ID_COMMAND_ONLY, int)


class TestChannelIds:
    """Tests for channel ID constants."""

    def test_channel_id_allowed_exists(self):
        """Test CHANNEL_ID_ALLOWED is defined."""
        from cogs.ai_core.data.constants import CHANNEL_ID_ALLOWED

        assert isinstance(CHANNEL_ID_ALLOWED, int)

    def test_channel_id_rp_output_exists(self):
        """Test CHANNEL_ID_RP_OUTPUT is defined."""
        from cogs.ai_core.data.constants import CHANNEL_ID_RP_OUTPUT

        assert isinstance(CHANNEL_ID_RP_OUTPUT, int)

    def test_channel_id_rp_command_exists(self):
        """Test CHANNEL_ID_RP_COMMAND is defined."""
        from cogs.ai_core.data.constants import CHANNEL_ID_RP_COMMAND

        assert isinstance(CHANNEL_ID_RP_COMMAND, int)


class TestUserIds:
    """Tests for user ID constants."""

    def test_creator_id_exists(self):
        """Test CREATOR_ID is defined."""
        from cogs.ai_core.data.constants import CREATOR_ID

        assert isinstance(CREATOR_ID, int)


class TestApiConfiguration:
    """Tests for API configuration constants."""

    def test_gemini_api_key_exists(self):
        """Test GEMINI_API_KEY is defined."""
        from cogs.ai_core.data.constants import GEMINI_API_KEY

        assert isinstance(GEMINI_API_KEY, str)

    def test_claude_model_exists(self):
        """Test CLAUDE_MODEL is defined."""
        from cogs.ai_core.data.constants import CLAUDE_MODEL

        assert isinstance(CLAUDE_MODEL, str)


class TestHistoryLimits:
    """Tests for history limit constants."""

    def test_history_limit_default(self):
        """Test HISTORY_LIMIT_DEFAULT is defined."""
        from cogs.ai_core.data.constants import HISTORY_LIMIT_DEFAULT

        assert HISTORY_LIMIT_DEFAULT == 1500

    def test_history_limit_main(self):
        """Test HISTORY_LIMIT_MAIN is defined."""
        from cogs.ai_core.data.constants import HISTORY_LIMIT_MAIN

        assert HISTORY_LIMIT_MAIN == 8000

    def test_history_limit_rp(self):
        """Test HISTORY_LIMIT_RP is defined."""
        from cogs.ai_core.data.constants import HISTORY_LIMIT_RP

        assert HISTORY_LIMIT_RP == 30000


class TestProcessingTimeouts:
    """Tests for processing timeout constants."""

    def test_lock_timeout(self):
        """Test LOCK_TIMEOUT is defined and exceeds API_TIMEOUT.

        LOCK_TIMEOUT must be longer than API_TIMEOUT so a slow API call
        doesn't cause queued messages to be dropped.
        """
        from cogs.ai_core.data.constants import API_TIMEOUT, LOCK_TIMEOUT

        assert LOCK_TIMEOUT == 180.0
        assert LOCK_TIMEOUT > API_TIMEOUT

    def test_api_timeout(self):
        """Test API_TIMEOUT is defined."""
        from cogs.ai_core.data.constants import API_TIMEOUT

        assert API_TIMEOUT == 120.0

    def test_streaming_timeout_initial(self):
        """Test STREAMING_TIMEOUT_INITIAL is defined."""
        from cogs.ai_core.data.constants import STREAMING_TIMEOUT_INITIAL

        assert STREAMING_TIMEOUT_INITIAL == 120.0

    def test_streaming_timeout_chunk(self):
        """Test STREAMING_TIMEOUT_CHUNK is defined."""
        from cogs.ai_core.data.constants import STREAMING_TIMEOUT_CHUNK

        assert STREAMING_TIMEOUT_CHUNK == 45.0


class TestContentLimits:
    """Tests for content limit constants."""

    def test_max_history_items(self):
        """Test MAX_HISTORY_ITEMS is defined (env-driven, default raised to 8000)."""
        from cogs.ai_core.data.constants import MAX_HISTORY_ITEMS

        assert MAX_HISTORY_ITEMS == 8000

    def test_extraction_max_chars_per_message(self):
        """Raised from a hard-coded 500 so a long RP post is read past its first quarter."""
        from cogs.ai_core.data.constants import EXTRACTION_MAX_CHARS_PER_MESSAGE

        assert EXTRACTION_MAX_CHARS_PER_MESSAGE == 4000

    def test_dead_constants_are_gone(self):
        """The unused-constant sweep: these had no consumer outside their own tests."""
        from cogs.ai_core.data import constants

        for name in (
            "DB_QUERY_TIMEOUT",
            "DEFAULT_LIST_MEMBERS_LIMIT",
            "DISCORD_MESSAGE_LIMIT",
            "HEALTH_CHECK_TIMEOUT",
            "MAX_ROLE_NAME_LENGTH",
            "MAX_STALL_TIME",
            "MAX_TEXT_TRUNCATE_LENGTH",
            "MUSIC_DISCONNECT_DELAY",
            "MUSIC_LOCK_TIMEOUT",
            "PROCESS_KILL_TIMEOUT",
            "SHUTDOWN_TIMEOUT",
            "STALE_LOCK_MAX_AGE_SECONDS",
            "SUMMARIZATION_TEMPERATURE",
            "TEXT_TRUNCATE_HEAD",
            "TEXT_TRUNCATE_TAIL",
            "UNUSED_LOCK_MAX_AGE_SECONDS",
            "WEBHOOK_SEND_TIMEOUT",
        ):
            assert not hasattr(constants, name), f"{name} came back — is it used now?"


class TestPerformanceTracking:
    """Tests for performance tracking constants."""

    def test_performance_samples_max(self):
        """Test PERFORMANCE_SAMPLES_MAX is defined."""
        from cogs.ai_core.data.constants import PERFORMANCE_SAMPLES_MAX

        assert PERFORMANCE_SAMPLES_MAX == 100
