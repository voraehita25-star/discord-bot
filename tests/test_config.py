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
            assert settings.claude_model == "claude-opus-5"
            assert settings.auto_disconnect_delay == 180
            assert settings.default_volume == 0.5
            assert settings.max_queue_size == 500
            assert settings.ai_session_timeout == 3600

    def test_env_values_loaded(self):
        """Test that environment values are loaded correctly."""
        from config import BotSettings

        test_env = {
            "DISCORD_TOKEN": "test_token_123",
            "ANTHROPIC_API_KEY": "test_anthropic_key",
            "GEMINI_API_KEY": "test_gemini_key",
            "CLAUDE_MODEL": "claude-opus-4-7",
            "GUILD_ID_MAIN": "123456789",
            "CREATOR_ID": "987654321",
        }

        with patch.dict(os.environ, test_env, clear=True):
            settings = BotSettings()

            assert settings.discord_token == "test_token_123"
            assert settings.anthropic_api_key == "test_anthropic_key"
            assert settings.gemini_api_key == "test_gemini_key"
            assert settings.claude_model == "claude-opus-4-7"
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
        """Test that __post_init__ creates required directories when BOT_RUNNING is set."""
        from config import BotSettings

        data_dir = str(tmp_path / "data")
        temp_dir = str(tmp_path / "temp")
        logs_dir = str(tmp_path / "logs")

        monkeypatch.setenv("BOT_RUNNING", "1")
        BotSettings(
            data_dir=data_dir,
            temp_dir=temp_dir,
            logs_dir=logs_dir,
        )

        from pathlib import Path

        assert Path(data_dir).exists()
        assert Path(temp_dir).exists()
        assert Path(logs_dir).exists()


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


class TestReclaimDotenvOverrides:
    """Tests for reclaim_dotenv_overrides.

    Guards the launch path where Claude Code exports CLAUDE_EFFORT into the
    environment of the bot process it spawns: load_dotenv() leaves an
    already-set variable alone, so .env would lose without this reclaim.
    """

    def _write_env(self, tmp_path, body: str):
        env_file = tmp_path / ".env"
        env_file.write_text(body, encoding="utf-8")
        return env_file

    def test_dotenv_wins_over_inherited_value(self, tmp_path):
        """An inherited CLAUDE_EFFORT is replaced by the .env value."""
        from config import reclaim_dotenv_overrides

        env_file = self._write_env(tmp_path, "CLAUDE_EFFORT=max\n")
        with patch.dict(os.environ, {"CLAUDE_EFFORT": "high"}):
            reclaimed = reclaim_dotenv_overrides(env_file)

            assert reclaimed == {"CLAUDE_EFFORT": "max"}
            assert os.environ["CLAUDE_EFFORT"] == "max"

    def test_sets_key_absent_from_environment(self, tmp_path):
        """With nothing inherited the .env value is still applied."""
        from config import reclaim_dotenv_overrides

        env_file = self._write_env(tmp_path, "CLAUDE_EFFORT=max\n")
        env = os.environ.copy()
        env.pop("CLAUDE_EFFORT", None)
        with patch.dict(os.environ, env, clear=True):
            assert reclaim_dotenv_overrides(env_file) == {"CLAUDE_EFFORT": "max"}
            assert os.environ["CLAUDE_EFFORT"] == "max"

    def test_reports_nothing_when_values_already_agree(self, tmp_path):
        """No reclaim is reported when the environment already matches .env."""
        from config import reclaim_dotenv_overrides

        env_file = self._write_env(tmp_path, "CLAUDE_EFFORT=max\n")
        with patch.dict(os.environ, {"CLAUDE_EFFORT": "max"}):
            assert reclaim_dotenv_overrides(env_file) == {}
            assert os.environ["CLAUDE_EFFORT"] == "max"

    def test_key_missing_from_dotenv_leaves_environment_alone(self, tmp_path):
        """A key absent from .env keeps whatever the environment provided."""
        from config import reclaim_dotenv_overrides

        env_file = self._write_env(tmp_path, "DISCORD_TOKEN=irrelevant\n")
        with patch.dict(os.environ, {"CLAUDE_EFFORT": "high"}):
            assert reclaim_dotenv_overrides(env_file) == {}
            assert os.environ["CLAUDE_EFFORT"] == "high"

    def test_unowned_keys_are_not_reclaimed(self, tmp_path):
        """Ordinary config keeps normal precedence — the real environment wins.

        Only the explicitly owned keys are forced; deploys and CI must still be
        able to override everything else from the environment.
        """
        from config import reclaim_dotenv_overrides

        env_file = self._write_env(
            tmp_path, "CLAUDE_EFFORT=max\nCLAUDE_MODEL=from-dotenv\nCLAUDE_BACKEND=cli\n"
        )
        with patch.dict(
            os.environ,
            {
                "CLAUDE_EFFORT": "high",
                "CLAUDE_MODEL": "from-environment",
                "CLAUDE_BACKEND": "api",
            },
        ):
            assert reclaim_dotenv_overrides(env_file) == {"CLAUDE_EFFORT": "max"}
            assert os.environ["CLAUDE_MODEL"] == "from-environment"
            assert os.environ["CLAUDE_BACKEND"] == "api"

    def test_missing_dotenv_file_is_not_an_error(self, tmp_path):
        """A deploy with no .env on disk must not crash startup."""
        from config import reclaim_dotenv_overrides

        with patch.dict(os.environ, {"CLAUDE_EFFORT": "high"}):
            assert reclaim_dotenv_overrides(tmp_path / "does-not-exist.env") == {}
            assert os.environ["CLAUDE_EFFORT"] == "high"
