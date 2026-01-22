"""
Tests for utils/monitoring/health_api.py module.
Tests the health API, BotHealthData, and HTTP endpoints.
"""

import datetime
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest


# ==================== TestHealthApiConstants ====================


class TestHealthApiConstants:
    """Test module constants."""

    def test_health_api_port_default(self):
        """Test default health API port."""
        with patch.dict('os.environ', {}, clear=True):
            # Force reimport with cleared env
            import importlib
            import utils.monitoring.health_api as health_api_module
            importlib.reload(health_api_module)
            
            # Default should be 8080
            assert health_api_module.HEALTH_API_PORT == 8080
    
    def test_health_api_host_default(self):
        """Test default health API host."""
        with patch.dict('os.environ', {}, clear=True):
            import importlib
            import utils.monitoring.health_api as health_api_module
            importlib.reload(health_api_module)
            
            # Default should be 0.0.0.0
            assert health_api_module.HEALTH_API_HOST == "0.0.0.0"


# ==================== TestBotHealthDataInit ====================


class TestBotHealthDataInit:
    """Test BotHealthData initialization."""

    def test_init_defaults(self):
        """Test BotHealthData default values."""
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
    
    def test_init_has_start_time(self):
        """Test BotHealthData has start time."""
        from utils.monitoring.health_api import BotHealthData
        
        before = datetime.datetime.now()
        health = BotHealthData()
        after = datetime.datetime.now()
        
        assert before <= health.start_time <= after
    
    def test_init_has_last_heartbeat(self):
        """Test BotHealthData has last heartbeat."""
        from utils.monitoring.health_api import BotHealthData
        
        before = datetime.datetime.now()
        health = BotHealthData()
        after = datetime.datetime.now()
        
        assert before <= health.last_heartbeat <= after


# ==================== TestBotHealthDataUpdateFromBot ====================


class TestBotHealthDataUpdateFromBot:
    """Test BotHealthData update from bot."""

    def test_update_from_bot_stores_bot(self):
        """Test update stores bot reference."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False
        
        health.update_from_bot(mock_bot)
        
        assert health.bot == mock_bot
    
    def test_update_from_bot_updates_heartbeat(self):
        """Test update updates heartbeat."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        old_heartbeat = health.last_heartbeat
        
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False
        
        import time
        time.sleep(0.01)
        health.update_from_bot(mock_bot)
        
        assert health.last_heartbeat >= old_heartbeat
    
    def test_update_from_bot_when_ready(self):
        """Test update when bot is ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        mock_guild1 = MagicMock()
        mock_guild1.member_count = 100
        mock_guild2 = MagicMock()
        mock_guild2.member_count = 50
        
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05  # 50ms
        mock_bot.guilds = [mock_guild1, mock_guild2]
        mock_bot.cogs = {"AI": MagicMock(), "Music": MagicMock()}
        
        health.update_from_bot(mock_bot)
        
        assert health.is_ready is True
        assert health.latency_ms == 50.0
        assert health.guild_count == 2
        assert health.user_count == 150
        assert health.cogs_loaded == ["AI", "Music"]


# ==================== TestBotHealthDataIncrementers ====================


class TestBotHealthDataIncrementers:
    """Test BotHealthData counter incrementers."""

    def test_increment_message(self):
        """Test incrementing message count."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        assert health.message_count == 0
        
        health.increment_message()
        assert health.message_count == 1
        
        health.increment_message()
        assert health.message_count == 2
    
    def test_increment_command(self):
        """Test incrementing command count."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        assert health.command_count == 0
        
        health.increment_command()
        assert health.command_count == 1
    
    def test_increment_error(self):
        """Test incrementing error count."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        assert health.error_count == 0
        
        health.increment_error()
        assert health.error_count == 1


# ==================== TestBotHealthDataUptime ====================


class TestBotHealthDataUptime:
    """Test BotHealthData uptime methods."""

    def test_get_uptime_returns_timedelta(self):
        """Test get_uptime returns timedelta."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        uptime = health.get_uptime()
        
        assert isinstance(uptime, timedelta)
    
    def test_get_uptime_str_format_seconds(self):
        """Test uptime string format for seconds."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.datetime.now() - timedelta(seconds=30)
        
        uptime_str = health.get_uptime_str()
        
        assert "s" in uptime_str
        assert "30" in uptime_str or "29" in uptime_str or "31" in uptime_str
    
    def test_get_uptime_str_format_minutes(self):
        """Test uptime string format for minutes."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.datetime.now() - timedelta(minutes=5, seconds=30)
        
        uptime_str = health.get_uptime_str()
        
        assert "m" in uptime_str
        assert "5" in uptime_str
    
    def test_get_uptime_str_format_hours(self):
        """Test uptime string format for hours."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.datetime.now() - timedelta(hours=2, minutes=30)
        
        uptime_str = health.get_uptime_str()
        
        assert "h" in uptime_str
        assert "2" in uptime_str
    
    def test_get_uptime_str_format_days(self):
        """Test uptime string format for days."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.start_time = datetime.datetime.now() - timedelta(days=3, hours=5)
        
        uptime_str = health.get_uptime_str()
        
        assert "d" in uptime_str
        assert "3" in uptime_str


# ==================== TestBotHealthDataToDict ====================


class TestBotHealthDataToDict:
    """Test BotHealthData to_dict method."""

    def test_to_dict_returns_dict(self):
        """Test to_dict returns dictionary."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 10.5
            mock_proc.return_value.memory_info.return_value.rss = 100 * 1024 * 1024
            mock_proc.return_value.num_threads.return_value = 4
            
            data = health.to_dict()
        
        assert isinstance(data, dict)
    
    def test_to_dict_has_status(self):
        """Test to_dict includes status."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert "status" in data
        assert data["status"] == "starting"  # is_ready is False by default
    
    def test_to_dict_has_bot_section(self):
        """Test to_dict includes bot section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert "bot" in data
        assert "ready" in data["bot"]
        assert "latency_ms" in data["bot"]
        assert "guilds" in data["bot"]
    
    def test_to_dict_has_stats_section(self):
        """Test to_dict includes stats section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.message_count = 100
        health.command_count = 50
        health.error_count = 5
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert "stats" in data
        assert data["stats"]["messages_processed"] == 100
        assert data["stats"]["commands_executed"] == 50
        assert data["stats"]["errors"] == 5
    
    def test_to_dict_has_system_section(self):
        """Test to_dict includes system section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 25.5
            mock_proc.return_value.memory_info.return_value.rss = 512 * 1024 * 1024
            mock_proc.return_value.num_threads.return_value = 8
            
            data = health.to_dict()
        
        assert "system" in data
        assert data["system"]["cpu_percent"] == 25.5
        assert data["system"]["memory_mb"] == 512.0
        assert data["system"]["threads"] == 8


# ==================== TestBotHealthDataIsHealthy ====================


class TestBotHealthDataIsHealthy:
    """Test BotHealthData is_healthy method."""

    def test_is_healthy_false_when_not_ready(self):
        """Test is_healthy returns false when not ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = False
        
        assert health.is_healthy() is False
    
    def test_is_healthy_false_when_heartbeat_stale(self):
        """Test is_healthy returns false when heartbeat is stale."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 50
        health.last_heartbeat = datetime.datetime.now() - timedelta(seconds=120)
        
        assert health.is_healthy() is False
    
    def test_is_healthy_false_when_high_latency(self):
        """Test is_healthy returns false when latency is too high."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 6000  # 6 seconds
        health.last_heartbeat = datetime.datetime.now()
        
        assert health.is_healthy() is False
    
    def test_is_healthy_true_when_all_good(self):
        """Test is_healthy returns true when all checks pass."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 50
        health.last_heartbeat = datetime.datetime.now()
        
        assert health.is_healthy() is True


# ==================== TestBotHealthDataGetAiPerformanceStats ====================


class TestBotHealthDataGetAiPerformanceStats:
    """Test BotHealthData AI performance stats."""

    def test_get_ai_performance_stats_no_bot(self):
        """Test getting AI stats with no bot."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        stats = health.get_ai_performance_stats()
        
        assert "error" in stats
    
    def test_get_ai_performance_stats_no_ai_cog(self):
        """Test getting AI stats with no AI cog."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.bot = MagicMock()
        health.bot.cogs = {}
        
        stats = health.get_ai_performance_stats()
        
        assert "error" in stats
    
    def test_get_ai_performance_stats_with_ai_cog(self):
        """Test getting AI stats with AI cog."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        mock_bot = MagicMock()
        mock_ai_cog = MagicMock()
        mock_ai_cog.chat_manager.get_performance_stats.return_value = {
            "total_requests": 100,
            "avg_response_time": 1.5
        }
        mock_bot.cogs = {"AI": mock_ai_cog}
        health.bot = mock_bot
        
        stats = health.get_ai_performance_stats()
        
        assert stats["total_requests"] == 100
        assert stats["avg_response_time"] == 1.5


# ==================== TestGlobalHealthData ====================


class TestGlobalHealthData:
    """Test global health_data instance."""

    def test_health_data_exists(self):
        """Test global health_data instance exists."""
        from utils.monitoring.health_api import health_data
        
        assert health_data is not None
    
    def test_health_data_is_bot_health_data(self):
        """Test global health_data is BotHealthData instance."""
        from utils.monitoring.health_api import health_data, BotHealthData
        
        assert isinstance(health_data, BotHealthData)


# ==================== TestHealthRequestHandler ====================


class TestHealthRequestHandler:
    """Test HealthRequestHandler class."""

    def test_handler_class_exists(self):
        """Test HealthRequestHandler class exists."""
        from utils.monitoring.health_api import HealthRequestHandler
        
        assert HealthRequestHandler is not None
    
    def test_handler_log_message_suppressed(self):
        """Test log_message is suppressed."""
        from utils.monitoring.health_api import HealthRequestHandler
        
        # log_message should do nothing (suppressed)
        handler = MagicMock(spec=HealthRequestHandler)
        HealthRequestHandler.log_message(handler, "test %s", "arg")
        # No assertion needed - just verify no exception


# ==================== TestModuleImports ====================


class TestModuleImports:
    """Test module imports."""

    def test_import_health_api(self):
        """Test importing health_api module."""
        import utils.monitoring.health_api
        
        assert utils.monitoring.health_api is not None
    
    def test_import_bot_health_data(self):
        """Test importing BotHealthData class."""
        from utils.monitoring.health_api import BotHealthData
        
        assert BotHealthData is not None
    
    def test_import_health_request_handler(self):
        """Test importing HealthRequestHandler class."""
        from utils.monitoring.health_api import HealthRequestHandler
        
        assert HealthRequestHandler is not None
    
    def test_import_health_data(self):
        """Test importing global health_data."""
        from utils.monitoring.health_api import health_data
        
        assert health_data is not None


# ==================== TestHealthyStatus ====================


class TestHealthyStatus:
    """Test healthy status variations."""

    def test_status_starting_when_not_ready(self):
        """Test status is 'starting' when not ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = False
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert data["status"] == "starting"
    
    def test_status_healthy_when_ready(self):
        """Test status is 'healthy' when ready."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.is_ready = True
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert data["status"] == "healthy"


# ==================== TestTimestamp ====================


class TestTimestamp:
    """Test timestamp functionality."""

    def test_to_dict_has_timestamp(self):
        """Test to_dict includes timestamp."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert "timestamp" in data
        # Should be ISO format
        assert "T" in data["timestamp"]
    
    def test_to_dict_has_uptime(self):
        """Test to_dict includes uptime."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert "uptime" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)


# ==================== TestHeartbeat ====================


class TestHeartbeat:
    """Test heartbeat functionality."""

    def test_to_dict_has_heartbeat(self):
        """Test to_dict includes heartbeat section."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        assert "heartbeat" in data
        assert "last" in data["heartbeat"]
        assert "age_seconds" in data["heartbeat"]
    
    def test_heartbeat_age_calculation(self):
        """Test heartbeat age is calculated correctly."""
        from utils.monitoring.health_api import BotHealthData
        
        health = BotHealthData()
        health.last_heartbeat = datetime.datetime.now() - timedelta(seconds=30)
        
        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1
            
            data = health.to_dict()
        
        # Age should be approximately 30 seconds
        assert 28 <= data["heartbeat"]["age_seconds"] <= 32
