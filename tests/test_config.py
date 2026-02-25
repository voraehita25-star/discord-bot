"""
Tests for config.py module.
"""

import os
from unittest.mock import patch


class TestSafeIntEnv:
    """Tests for _safe_int_env function."""

    def test_returns_int_from_valid_env(self):
        """Test that valid integer string is parsed correctly."""
        from config import _safe_int_env

        with patch.dict(os.environ, {"TEST_INT": "42"}):
            result = _safe_int_env("TEST_INT", 0)
            assert result == 42

    def test_returns_default_on_missing_env(self):
        """Test that default is returned when env var is not set."""
        from config import _safe_int_env

        # Ensure the var doesn't exist
        env = os.environ.copy()
        env.pop("NONEXISTENT_VAR", None)
        with patch.dict(os.environ, env, clear=True):
            result = _safe_int_env("NONEXISTENT_VAR", 999)
            assert result == 999

    def test_returns_default_on_invalid_int(self):
        """Test that default is returned when value is not a valid int."""
        from config import _safe_int_env

        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            result = _safe_int_env("TEST_INT", 100)
            assert result == 100

    def test_returns_default_on_empty_string(self):
        """Test that default is returned when value is empty string."""
        from config import _safe_int_env

        with patch.dict(os.environ, {"TEST_INT": ""}):
            result = _safe_int_env("TEST_INT", 50)
            assert result == 50

    def test_returns_negative_int(self):
        """Test that negative integers are parsed correctly."""
        from config import _safe_int_env

        with patch.dict(os.environ, {"TEST_INT": "-123"}):
            result = _safe_int_env("TEST_INT", 0)
            assert result == -123


class TestBotSettings:
    """Tests for BotSettings dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        from config import BotSettings

        with patch.dict(os.environ, {}, clear=True):
            settings = BotSettings()

            assert settings.discord_token == ""
            assert settings.gemini_api_key is None
            assert settings.gemini_model == "gemini-3.1-pro-preview"
            assert settings.auto_disconnect_delay == 180
            assert settings.default_volume == 0.5
            assert settings.max_queue_size == 500
            assert settings.ai_history_limit_default == 5000
            assert settings.ai_history_limit_main == 10000
            assert settings.ai_history_limit_rp == 20000
            assert settings.ai_session_timeout == 3600

    def test_env_values_loaded(self):
        """Test that environment values are loaded correctly."""
        from config import BotSettings

        test_env = {
            "DISCORD_TOKEN": "test_token_123",
            "GEMINI_API_KEY": "test_gemini_key",
            "GEMINI_MODEL": "gemini-3.1-pro-preview",
            "GUILD_ID_MAIN": "123456789",
            "CREATOR_ID": "987654321",
        }

        with patch.dict(os.environ, test_env, clear=True):
            settings = BotSettings()

            assert settings.discord_token == "test_token_123"
            assert settings.gemini_api_key == "test_gemini_key"
            assert settings.gemini_model == "gemini-3.1-pro-preview"
            assert settings.guild_id_main == 123456789
            assert settings.creator_id == 987654321

    def test_spotify_credentials(self):
        """Test Spotify credential loading."""
        from config import BotSettings

        test_env = {
            "SPOTIPY_CLIENT_ID": "spotify_client_id",
            "SPOTIPY_CLIENT_SECRET": "spotify_secret",
        }

        with patch.dict(os.environ, test_env, clear=True):
            settings = BotSettings()

            assert settings.spotipy_client_id == "spotify_client_id"
            assert settings.spotipy_client_secret == "spotify_secret"

    def test_guild_ids(self):
        """Test guild ID loading."""
        from config import BotSettings

        test_env = {
            "GUILD_ID_MAIN": "111",
            "GUILD_ID_RESTRICTED": "222",
            "GUILD_ID_RP": "333",
            "GUILD_ID_COMMAND_ONLY": "444",
        }

        with patch.dict(os.environ, test_env, clear=True):
            settings = BotSettings()

            assert settings.guild_id_main == 111
            assert settings.guild_id_restricted == 222
            assert settings.guild_id_rp == 333
            assert settings.guild_id_command_only == 444

    def test_channel_ids(self):
        """Test channel ID loading."""
        from config import BotSettings

        test_env = {
            "CHANNEL_ID_ALLOWED": "555",
            "CHANNEL_ID_RP_OUTPUT": "666",
            "CHANNEL_ID_RP_COMMAND": "777",
        }

        with patch.dict(os.environ, test_env, clear=True):
            settings = BotSettings()

            assert settings.channel_id_allowed == 555
            assert settings.channel_id_rp_output == 666
            assert settings.channel_id_rp_command == 777

    def test_post_init_creates_directories(self, tmp_path, monkeypatch):
        """Test that __post_init__ creates required directories."""
        from config import BotSettings

        data_dir = str(tmp_path / "data")
        temp_dir = str(tmp_path / "temp")
        logs_dir = str(tmp_path / "logs")

        settings = BotSettings(
            data_dir=data_dir,
            temp_dir=temp_dir,
            logs_dir=logs_dir,
        )

        from pathlib import Path
        assert Path(data_dir).exists()
        assert Path(temp_dir).exists()
        assert Path(logs_dir).exists()

    def test_ai_history_limits(self):
        """Test AI history limit values."""
        from config import BotSettings

        settings = BotSettings()

        # Check that RP has highest limit
        assert settings.ai_history_limit_rp > settings.ai_history_limit_main
        assert settings.ai_history_limit_main > settings.ai_history_limit_default


class TestGlobalSettings:
    """Tests for global settings instance."""

    def test_global_settings_exists(self):
        """Test that global settings instance is created."""
        from config import settings

        assert settings is not None
        assert hasattr(settings, "discord_token")
        assert hasattr(settings, "gemini_api_key")

    def test_global_settings_is_botsettings(self):
        """Test that global settings is a BotSettings instance."""
        from config import BotSettings, settings

        assert isinstance(settings, BotSettings)
