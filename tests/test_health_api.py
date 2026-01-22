"""
Tests for utils.monitoring.health_api module.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


class TestHealthApiConstants:
    """Tests for health API constants."""

    def test_default_port(self):
        """Test default health API port."""
        with patch.dict("os.environ", {}, clear=True):
            # Re-import to get defaults
            import importlib
            import utils.monitoring.health_api
            importlib.reload(utils.monitoring.health_api)
            
            # Default port should be 8080
            assert utils.monitoring.health_api.HEALTH_API_PORT == 8080

    def test_default_host(self):
        """Test default health API host."""
        from utils.monitoring.health_api import HEALTH_API_HOST
        
        assert HEALTH_API_HOST == "0.0.0.0"


class TestBotHealthData:
    """Tests for BotHealthData class."""

    def test_init_sets_start_time(self):
        """Test initialization sets start time."""
        from utils.monitoring.health_api import BotHealthData
        
        before = datetime.now()
        health = BotHealthData()
        after = datetime.now()
        
        assert before <= health.start_time <= after

    def test_init_default_values(self):
        """Test initialization default values."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        assert health.bot is None
        assert health.message_count == 0
        assert health.command_count == 0
        assert health.error_count == 0
        assert health.is_ready is False
        assert health.latency_ms == 0.0
        assert health.guild_count == 0
        assert health.user_count == 0
        assert health.cogs_loaded == []

    def test_increment_message(self):
        """Test increment_message increases counter."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        assert health.message_count == 0
        
        health.increment_message()
        assert health.message_count == 1
        
        health.increment_message()
        health.increment_message()
        assert health.message_count == 3

    def test_increment_command(self):
        """Test increment_command increases counter."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        assert health.command_count == 0
        
        health.increment_command()
        assert health.command_count == 1

    def test_increment_error(self):
        """Test increment_error increases counter."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        assert health.error_count == 0
        
        health.increment_error()
        assert health.error_count == 1

    def test_get_uptime(self):
        """Test get_uptime returns timedelta."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        uptime = health.get_uptime()
        
        assert isinstance(uptime, timedelta)
        assert uptime.total_seconds() >= 0

    def test_get_uptime_str_seconds(self):
        """Test get_uptime_str formats seconds correctly."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(seconds=30)
        
        result = health.get_uptime_str()
        assert "s" in result

    def test_get_uptime_str_minutes(self):
        """Test get_uptime_str formats minutes correctly."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(minutes=5, seconds=30)
        
        result = health.get_uptime_str()
        assert "m" in result

    def test_get_uptime_str_hours(self):
        """Test get_uptime_str formats hours correctly."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(hours=2, minutes=30)
        
        result = health.get_uptime_str()
        assert "h" in result

    def test_get_uptime_str_days(self):
        """Test get_uptime_str formats days correctly."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(days=3, hours=5)
        
        result = health.get_uptime_str()
        assert "d" in result

    def test_update_from_bot_not_ready(self):
        """Test update_from_bot when bot is not ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False
        
        health.update_from_bot(mock_bot)
        
        assert health.bot is mock_bot
        assert health.is_ready is False

    def test_update_from_bot_ready(self):
        """Test update_from_bot when bot is ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05  # 50ms
        
        mock_guild1 = MagicMock()
        mock_guild1.member_count = 100
        mock_guild2 = MagicMock()
        mock_guild2.member_count = 200
        mock_bot.guilds = [mock_guild1, mock_guild2]
        
        mock_bot.cogs.keys.return_value = ["MusicCog", "AICog"]
        
        health.update_from_bot(mock_bot)
        
        assert health.is_ready is True
        assert health.latency_ms == 50.0
        assert health.guild_count == 2
        assert health.user_count == 300
        assert "MusicCog" in health.cogs_loaded
        assert "AICog" in health.cogs_loaded

    def test_to_dict_returns_dict(self):
        """Test to_dict returns dictionary with expected keys."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        result = health.to_dict()
        
        assert isinstance(result, dict)
        assert "status" in result
        assert "timestamp" in result
        assert "uptime" in result
        assert "uptime_seconds" in result
        assert "bot" in result

    def test_to_dict_status_starting_when_not_ready(self):
        """Test to_dict shows 'starting' status when not ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = False
        
        result = health.to_dict()
        assert result["status"] == "starting"

    def test_to_dict_status_healthy_when_ready(self):
        """Test to_dict shows 'healthy' status when ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        
        result = health.to_dict()
        assert result["status"] == "healthy"

    def test_to_dict_bot_section(self):
        """Test to_dict includes bot section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 45.5
        
        result = health.to_dict()
        
        assert "bot" in result
        assert result["bot"]["ready"] is True
        assert result["bot"]["latency_ms"] == 45.5


class TestHealthDataSingleton:
    """Tests for health_data global instance."""

    def test_health_data_exists(self):
        """Test that global health_data instance exists."""
        from utils.monitoring.health_api import health_data
        
        assert health_data is not None

    def test_health_data_is_bothealthdata(self):
        """Test that health_data is BotHealthData instance."""
        from utils.monitoring.health_api import BotHealthData, health_data
        
        assert isinstance(health_data, BotHealthData)
