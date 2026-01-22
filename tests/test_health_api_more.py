"""
Additional tests for Health API BotHealthData class.
Tests increment methods, uptime, and status values.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


class TestBotHealthDataCounters:
    """Additional tests for BotHealthData counters."""

    def test_counters_independent(self):
        """Test counters are independent of each other."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        health.increment_message()
        health.increment_message()
        health.increment_command()
        health.increment_error()
        
        assert health.message_count == 2
        assert health.command_count == 1
        assert health.error_count == 1
        
    def test_counters_large_values(self):
        """Test counters can handle large values."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        health.message_count = 1000000
        health.increment_message()
        
        assert health.message_count == 1000001


class TestBotHealthDataBotAttribute:
    """Tests for bot attribute management."""

    def test_bot_none_initially(self):
        """Test bot is None initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        assert health.bot is None
        
    def test_bot_set_after_update(self):
        """Test bot is set after update_from_bot."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False
        
        health.update_from_bot(mock_bot)
        
        assert health.bot is mock_bot


class TestBotHealthDataCogsLoaded:
    """Tests for cogs_loaded attribute."""

    def test_cogs_loaded_empty_initially(self):
        """Test cogs_loaded is empty initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        assert health.cogs_loaded == []
        
    def test_cogs_loaded_populated_when_ready(self):
        """Test cogs_loaded is populated when bot is ready."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = []
        mock_bot.cogs = {"Music": MagicMock(), "AI": MagicMock()}
        
        health.update_from_bot(mock_bot)
        
        assert "Music" in health.cogs_loaded
        assert "AI" in health.cogs_loaded


class TestBotHealthDataLatency:
    """Tests for latency attribute."""

    def test_latency_zero_initially(self):
        """Test latency is zero initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        assert health.latency_ms == 0.0
        
    def test_latency_converted_from_seconds(self):
        """Test latency is converted from seconds to ms."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.1  # 100ms
        mock_bot.guilds = []
        mock_bot.cogs = {}
        
        health.update_from_bot(mock_bot)
        
        assert health.latency_ms == 100.0


class TestBotHealthDataGuilds:
    """Tests for guild-related attributes."""

    def test_guild_count_zero_initially(self):
        """Test guild_count is zero initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        assert health.guild_count == 0
        
    def test_user_count_zero_initially(self):
        """Test user_count is zero initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        assert health.user_count == 0
        
    def test_guild_count_calculated(self):
        """Test guild_count is calculated from guilds."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = [MagicMock(member_count=50), MagicMock(member_count=100), MagicMock(member_count=25)]
        mock_bot.cogs = {}
        
        health.update_from_bot(mock_bot)
        
        assert health.guild_count == 3
        assert health.user_count == 175


class TestBotHealthDataUptimeEdgeCases:
    """Edge case tests for uptime methods."""

    def test_uptime_str_zero_seconds(self):
        """Test uptime_str with zero seconds."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        health.start_time = datetime.now()
        
        uptime_str = health.get_uptime_str()
        
        assert "s" in uptime_str
        
    def test_uptime_seconds_returns_int(self):
        """Test uptime_seconds in to_dict is int."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        
        result = health.to_dict()
        
        assert isinstance(result["uptime_seconds"], int)


class TestBotHealthDataNullMemberCount:
    """Tests for handling None member_count."""

    def test_handles_null_member_count(self):
        """Test handles guild with None member_count."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return
            
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = [MagicMock(member_count=None), MagicMock(member_count=100)]
        mock_bot.cogs = {}
        
        health.update_from_bot(mock_bot)
        
        # Should handle None gracefully (treated as 0)
        assert health.user_count == 100
