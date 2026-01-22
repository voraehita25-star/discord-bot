"""
Tests for cogs.ai_core.data.constants module.
"""

import os
from unittest.mock import patch

import pytest


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

    def test_gemini_model_exists(self):
        """Test GEMINI_MODEL is defined."""
        from cogs.ai_core.data.constants import GEMINI_MODEL
        assert isinstance(GEMINI_MODEL, str)


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
        """Test LOCK_TIMEOUT is defined."""
        from cogs.ai_core.data.constants import LOCK_TIMEOUT
        assert LOCK_TIMEOUT == 120.0

    def test_api_timeout(self):
        """Test API_TIMEOUT is defined."""
        from cogs.ai_core.data.constants import API_TIMEOUT
        assert API_TIMEOUT == 120.0

    def test_streaming_timeout_initial(self):
        """Test STREAMING_TIMEOUT_INITIAL is defined."""
        from cogs.ai_core.data.constants import STREAMING_TIMEOUT_INITIAL
        assert STREAMING_TIMEOUT_INITIAL == 30.0

    def test_streaming_timeout_chunk(self):
        """Test STREAMING_TIMEOUT_CHUNK is defined."""
        from cogs.ai_core.data.constants import STREAMING_TIMEOUT_CHUNK
        assert STREAMING_TIMEOUT_CHUNK == 10.0

    def test_max_stall_time(self):
        """Test MAX_STALL_TIME is defined."""
        from cogs.ai_core.data.constants import MAX_STALL_TIME
        assert MAX_STALL_TIME == 60.0


class TestContentLimits:
    """Tests for content limit constants."""

    def test_max_history_items(self):
        """Test MAX_HISTORY_ITEMS is defined."""
        from cogs.ai_core.data.constants import MAX_HISTORY_ITEMS
        assert MAX_HISTORY_ITEMS == 2000

    def test_max_text_truncate_length(self):
        """Test MAX_TEXT_TRUNCATE_LENGTH is defined."""
        from cogs.ai_core.data.constants import MAX_TEXT_TRUNCATE_LENGTH
        assert MAX_TEXT_TRUNCATE_LENGTH == 10000

    def test_text_truncate_head(self):
        """Test TEXT_TRUNCATE_HEAD is defined."""
        from cogs.ai_core.data.constants import TEXT_TRUNCATE_HEAD
        assert TEXT_TRUNCATE_HEAD == 5000

    def test_text_truncate_tail(self):
        """Test TEXT_TRUNCATE_TAIL is defined."""
        from cogs.ai_core.data.constants import TEXT_TRUNCATE_TAIL
        assert TEXT_TRUNCATE_TAIL == 3000


class TestPerformanceTracking:
    """Tests for performance tracking constants."""

    def test_performance_samples_max(self):
        """Test PERFORMANCE_SAMPLES_MAX is defined."""
        from cogs.ai_core.data.constants import PERFORMANCE_SAMPLES_MAX
        assert PERFORMANCE_SAMPLES_MAX == 100


class TestGameSearchKeywords:
    """Tests for game search keywords."""

    def test_game_search_keywords_is_list(self):
        """Test GAME_SEARCH_KEYWORDS is a list."""
        from cogs.ai_core.data.constants import GAME_SEARCH_KEYWORDS
        assert isinstance(GAME_SEARCH_KEYWORDS, list)

    def test_game_search_keywords_contains_limbus(self):
        """Test GAME_SEARCH_KEYWORDS contains limbus."""
        from cogs.ai_core.data.constants import GAME_SEARCH_KEYWORDS
        assert "limbus" in GAME_SEARCH_KEYWORDS

    def test_game_search_keywords_contains_identity(self):
        """Test GAME_SEARCH_KEYWORDS contains identity."""
        from cogs.ai_core.data.constants import GAME_SEARCH_KEYWORDS
        assert "identity" in GAME_SEARCH_KEYWORDS

    def test_game_search_keywords_contains_sinner_names(self):
        """Test GAME_SEARCH_KEYWORDS contains sinner names."""
        from cogs.ai_core.data.constants import GAME_SEARCH_KEYWORDS
        assert "faust" in GAME_SEARCH_KEYWORDS
        assert "dante" in GAME_SEARCH_KEYWORDS
        assert "yi sang" in GAME_SEARCH_KEYWORDS

    def test_game_search_keywords_contains_thai(self):
        """Test GAME_SEARCH_KEYWORDS contains Thai keywords."""
        from cogs.ai_core.data.constants import GAME_SEARCH_KEYWORDS
        assert "ตัวละคร" in GAME_SEARCH_KEYWORDS
        assert "สกิล" in GAME_SEARCH_KEYWORDS
