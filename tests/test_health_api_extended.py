"""Tests for health_api module."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


class TestBotHealthData:
    """Tests for BotHealthData class."""

    def test_health_data_creation(self):
        """Test creating BotHealthData."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        assert health.bot is None
        assert health.message_count == 0
        assert health.command_count == 0
        assert health.error_count == 0
        assert health.is_ready is False

    def test_increment_message(self):
        """Test incrementing message counter."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.increment_message()
        health.increment_message()
        
        assert health.message_count == 2

    def test_increment_command(self):
        """Test incrementing command counter."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.increment_command()
        
        assert health.command_count == 1

    def test_increment_error(self):
        """Test incrementing error counter."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.increment_error()
        
        assert health.error_count == 1

    def test_get_uptime(self):
        """Test getting uptime."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        uptime = health.get_uptime()
        
        assert isinstance(uptime, timedelta)
        assert uptime.total_seconds() >= 0

    def test_get_uptime_str(self):
        """Test getting formatted uptime string."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        uptime_str = health.get_uptime_str()
        
        assert isinstance(uptime_str, str)
        # Should contain 's' for seconds at minimum
        assert "s" in uptime_str

    def test_to_dict_structure(self):
        """Test to_dict returns proper structure."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        data = health.to_dict()
        
        assert "status" in data
        assert "timestamp" in data
        assert "uptime" in data
        assert "bot" in data
        assert "stats" in data
        assert "system" in data
        assert "heartbeat" in data

    def test_to_dict_bot_section(self):
        """Test to_dict bot section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        data = health.to_dict()
        
        bot_data = data["bot"]
        assert "ready" in bot_data
        assert "latency_ms" in bot_data
        assert "guilds" in bot_data
        assert "users" in bot_data

    def test_to_dict_stats_section(self):
        """Test to_dict stats section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.increment_message()
        health.increment_command()
        
        data = health.to_dict()
        stats = data["stats"]
        
        assert stats["messages_processed"] == 1
        assert stats["commands_executed"] == 1

    def test_is_healthy_not_ready(self):
        """Test is_healthy when not ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = False
        
        assert health.is_healthy() is False

    def test_is_healthy_stale_heartbeat(self):
        """Test is_healthy with stale heartbeat."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.last_heartbeat = datetime.now() - timedelta(seconds=120)
        
        assert health.is_healthy() is False

    def test_is_healthy_high_latency(self):
        """Test is_healthy with high latency."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 6000  # Over 5 second threshold
        
        assert health.is_healthy() is False

    def test_is_healthy_good_state(self):
        """Test is_healthy in good state."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.last_heartbeat = datetime.now()
        health.latency_ms = 100
        
        assert health.is_healthy() is True

    def test_update_from_bot(self):
        """Test update_from_bot."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.1
        mock_bot.guilds = [MagicMock(member_count=100), MagicMock(member_count=50)]
        mock_bot.cogs = {"AI": MagicMock(), "Music": MagicMock()}
        
        health.update_from_bot(mock_bot)
        
        assert health.is_ready is True
        assert health.latency_ms == 100.0
        assert health.guild_count == 2
        assert health.user_count == 150

    def test_get_ai_performance_stats_no_bot(self):
        """Test get_ai_performance_stats with no bot."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.bot = None
        
        result = health.get_ai_performance_stats()
        
        assert "error" in result


class TestConstants:
    """Tests for module constants."""

    def test_health_api_port(self):
        """Test HEALTH_API_PORT default."""
        from utils.monitoring.health_api import HEALTH_API_PORT
        
        assert isinstance(HEALTH_API_PORT, int)
        assert HEALTH_API_PORT > 0

    def test_health_api_host(self):
        """Test HEALTH_API_HOST default."""
        from utils.monitoring.health_api import HEALTH_API_HOST
        
        assert isinstance(HEALTH_API_HOST, str)


class TestGlobalHealthData:
    """Tests for global health_data instance."""

    def test_health_data_exists(self):
        """Test health_data global exists."""
        from utils.monitoring.health_api import health_data
        
        assert health_data is not None

    def test_health_data_is_correct_type(self):
        """Test health_data is BotHealthData."""
        from utils.monitoring.health_api import health_data, BotHealthData
        
        assert isinstance(health_data, BotHealthData)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_bot_health_data(self):
        """Test importing BotHealthData."""
        from utils.monitoring.health_api import BotHealthData
        assert BotHealthData is not None

    def test_import_health_data(self):
        """Test importing health_data."""
        from utils.monitoring.health_api import health_data
        assert health_data is not None

    def test_import_setup_health_hooks(self):
        """Test importing setup_health_hooks."""
        from utils.monitoring.health_api import setup_health_hooks
        assert setup_health_hooks is not None

    def test_import_start_health_api(self):
        """Test importing start_health_api."""
        from utils.monitoring.health_api import start_health_api
        assert start_health_api is not None

    def test_import_stop_health_api(self):
        """Test importing stop_health_api."""
        from utils.monitoring.health_api import stop_health_api
        assert stop_health_api is not None

    def test_import_update_health_loop(self):
        """Test importing update_health_loop."""
        from utils.monitoring.health_api import update_health_loop
        assert update_health_loop is not None


class TestSetupHealthHooks:
    """Tests for setup_health_hooks function."""

    def test_setup_health_hooks_runs(self):
        """Test setup_health_hooks runs without error."""
        from utils.monitoring.health_api import setup_health_hooks
        
        mock_bot = MagicMock()
        
        # Should not raise
        setup_health_hooks(mock_bot)


class TestUptimeFormatting:
    """Tests for uptime formatting."""

    def test_uptime_format_seconds_only(self):
        """Test uptime formatting with seconds only."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        # Set start time to now for ~0 seconds uptime
        health.start_time = datetime.now()
        
        uptime_str = health.get_uptime_str()
        
        assert "s" in uptime_str

    def test_uptime_format_minutes(self):
        """Test uptime formatting with minutes."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(minutes=5, seconds=30)
        
        uptime_str = health.get_uptime_str()
        
        assert "m" in uptime_str

    def test_uptime_format_hours(self):
        """Test uptime formatting with hours."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(hours=2, minutes=30)
        
        uptime_str = health.get_uptime_str()
        
        assert "h" in uptime_str

    def test_uptime_format_days(self):
        """Test uptime formatting with days."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(days=3, hours=5)
        
        uptime_str = health.get_uptime_str()
        
        assert "d" in uptime_str
