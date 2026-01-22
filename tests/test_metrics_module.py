"""
Tests for utils/monitoring/metrics.py module.
Tests the Prometheus metrics collection functionality.

Note: Prometheus metrics are globally registered and cannot be re-registered.
This test module uses the global singleton `metrics` instance to avoid
"Duplicated timeseries" errors when running tests.
"""

from unittest.mock import MagicMock, patch

import pytest


# ==================== TestPrometheusAvailable ====================


class TestPrometheusAvailable:
    """Test PROMETHEUS_AVAILABLE flag."""

    def test_prometheus_available_flag_exists(self):
        """Test PROMETHEUS_AVAILABLE flag exists."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE
        
        assert isinstance(PROMETHEUS_AVAILABLE, bool)


# ==================== TestBotMetricsInit ====================


class TestBotMetricsInit:
    """Test BotMetrics initialization using global singleton."""

    def test_init_creates_instance(self):
        """Test BotMetrics global instance exists."""
        from utils.monitoring.metrics import metrics
        
        assert metrics is not None
    
    def test_init_has_enabled_flag(self):
        """Test BotMetrics has enabled flag."""
        from utils.monitoring.metrics import metrics
        
        assert hasattr(metrics, 'enabled')
        assert isinstance(metrics.enabled, bool)
    
    def test_init_server_not_started_by_default(self):
        """Test server has _server_started attribute."""
        from utils.monitoring.metrics import metrics
        
        # Just verify attribute exists - it may or may not be started in other tests
        assert hasattr(metrics, '_server_started')


# ==================== TestBotMetricsStartServer ====================


class TestBotMetricsStartServer:
    """Test BotMetrics start_server method."""

    def test_start_server_disabled(self):
        """Test start_server when prometheus not available."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            result = metrics.start_server(18000)  # Use different port
            assert result is False
        finally:
            metrics.enabled = original_enabled
    
    def test_start_server_already_started(self):
        """Test start_server when already started returns True."""
        from utils.monitoring.metrics import metrics
        
        original_started = metrics._server_started
        try:
            metrics._server_started = True
            result = metrics.start_server(18001)
            assert result is True
        finally:
            metrics._server_started = original_started


# ==================== TestBotMetricsIncrementMessages ====================


class TestBotMetricsIncrementMessages:
    """Test increment_messages method."""

    def test_increment_messages_disabled(self):
        """Test increment_messages when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.increment_messages("command")
        finally:
            metrics.enabled = original_enabled
    
    def test_increment_messages_enabled(self):
        """Test increment_messages when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_messages("command")
        metrics.increment_messages("ai")
        metrics.increment_messages()  # default "other"


# ==================== TestBotMetricsIncrementCommands ====================


class TestBotMetricsIncrementCommands:
    """Test increment_commands method."""

    def test_increment_commands_disabled(self):
        """Test increment_commands when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.increment_commands("play", success=True)
        finally:
            metrics.enabled = original_enabled
    
    def test_increment_commands_success(self):
        """Test increment_commands with success."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_commands("play", success=True)
    
    def test_increment_commands_error(self):
        """Test increment_commands with error."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_commands("play", success=False)


# ==================== TestBotMetricsIncrementAiRequests ====================


class TestBotMetricsIncrementAiRequests:
    """Test increment_ai_requests method."""

    def test_increment_ai_requests_disabled(self):
        """Test increment_ai_requests when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.increment_ai_requests("success")
        finally:
            metrics.enabled = original_enabled
    
    def test_increment_ai_requests_success(self):
        """Test increment_ai_requests with success status."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_ai_requests("success")
    
    def test_increment_ai_requests_error(self):
        """Test increment_ai_requests with error status."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_ai_requests("error")


# ==================== TestBotMetricsIncrementSongs ====================


class TestBotMetricsIncrementSongs:
    """Test increment_songs method."""

    def test_increment_songs_disabled(self):
        """Test increment_songs when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.increment_songs("youtube")
        finally:
            metrics.enabled = original_enabled
    
    def test_increment_songs_youtube(self):
        """Test increment_songs with youtube source."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_songs("youtube")
    
    def test_increment_songs_spotify(self):
        """Test increment_songs with spotify source."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.increment_songs("spotify")


# ==================== TestBotMetricsSetGuilds ====================


class TestBotMetricsSetGuilds:
    """Test set_guilds method."""

    def test_set_guilds_disabled(self):
        """Test set_guilds when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.set_guilds(10)
        finally:
            metrics.enabled = original_enabled
    
    def test_set_guilds_enabled(self):
        """Test set_guilds when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.set_guilds(50)


# ==================== TestBotMetricsSetVoiceClients ====================


class TestBotMetricsSetVoiceClients:
    """Test set_voice_clients method."""

    def test_set_voice_clients_disabled(self):
        """Test set_voice_clients when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.set_voice_clients(5)
        finally:
            metrics.enabled = original_enabled
    
    def test_set_voice_clients_enabled(self):
        """Test set_voice_clients when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.set_voice_clients(3)


# ==================== TestBotMetricsSetQueueSize ====================


class TestBotMetricsSetQueueSize:
    """Test set_queue_size method."""

    def test_set_queue_size_disabled(self):
        """Test set_queue_size when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.set_queue_size(123456789, 10)
        finally:
            metrics.enabled = original_enabled
    
    def test_set_queue_size_enabled(self):
        """Test set_queue_size when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.set_queue_size(123456789, 25)


# ==================== TestBotMetricsSetMemory ====================


class TestBotMetricsSetMemory:
    """Test set_memory method."""

    def test_set_memory_disabled(self):
        """Test set_memory when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.set_memory(1024 * 1024 * 100)  # 100MB
        finally:
            metrics.enabled = original_enabled
    
    def test_set_memory_enabled(self):
        """Test set_memory when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.set_memory(1024 * 1024 * 256)  # 256MB


# ==================== TestBotMetricsObserveCommandLatency ====================


class TestBotMetricsObserveCommandLatency:
    """Test observe_command_latency method."""

    def test_observe_command_latency_disabled(self):
        """Test observe_command_latency when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.observe_command_latency("play", 0.5)
        finally:
            metrics.enabled = original_enabled
    
    def test_observe_command_latency_enabled(self):
        """Test observe_command_latency when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.observe_command_latency("play", 1.5)
        metrics.observe_command_latency("skip", 0.1)


# ==================== TestBotMetricsObserveAiResponseTime ====================


class TestBotMetricsObserveAiResponseTime:
    """Test observe_ai_response_time method."""

    def test_observe_ai_response_time_disabled(self):
        """Test observe_ai_response_time when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            # Should not raise
            metrics.observe_ai_response_time(2.5)
        finally:
            metrics.enabled = original_enabled
    
    def test_observe_ai_response_time_enabled(self):
        """Test observe_ai_response_time when enabled."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Should not raise
        metrics.observe_ai_response_time(5.0)


# ==================== TestGlobalMetrics ====================


class TestGlobalMetrics:
    """Test global metrics instance."""

    def test_global_metrics_exists(self):
        """Test global metrics instance exists."""
        from utils.monitoring.metrics import metrics
        
        assert metrics is not None
    
    def test_global_metrics_is_bot_metrics(self):
        """Test global metrics is BotMetrics instance."""
        from utils.monitoring.metrics import metrics, BotMetrics
        
        assert isinstance(metrics, BotMetrics)


# ==================== TestModuleImports ====================


class TestModuleImports:
    """Test module imports."""

    def test_import_metrics_module(self):
        """Test importing metrics module."""
        import utils.monitoring.metrics
        
        assert utils.monitoring.metrics is not None
    
    def test_import_bot_metrics(self):
        """Test importing BotMetrics class."""
        from utils.monitoring.metrics import BotMetrics
        
        assert BotMetrics is not None
    
    def test_import_metrics_instance(self):
        """Test importing global metrics instance."""
        from utils.monitoring.metrics import metrics
        
        assert metrics is not None
    
    def test_import_prometheus_available(self):
        """Test importing PROMETHEUS_AVAILABLE flag."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE
        
        assert isinstance(PROMETHEUS_AVAILABLE, bool)


# ==================== TestMetricsDisabledBehavior ====================


class TestMetricsDisabledBehavior:
    """Test metrics behavior when prometheus is disabled."""

    def test_all_methods_work_when_disabled(self):
        """Test all methods work without raising when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        try:
            metrics.enabled = False
            
            # None of these should raise
            metrics.increment_messages("command")
            metrics.increment_commands("play", success=True)
            metrics.increment_ai_requests("success")
            metrics.increment_songs("youtube")
            metrics.set_guilds(10)
            metrics.set_voice_clients(5)
            metrics.set_queue_size(123, 10)
            metrics.set_memory(1024)
            metrics.observe_command_latency("play", 0.5)
            metrics.observe_ai_response_time(2.0)
        finally:
            metrics.enabled = original_enabled


# ==================== TestMetricsCounterTypes ====================


class TestMetricsCounterTypes:
    """Test metrics counter label values."""

    def test_message_types(self):
        """Test message type labels."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Different message types
        for msg_type in ["command", "ai", "music", "other"]:
            metrics.increment_messages(msg_type)
    
    def test_command_status_labels(self):
        """Test command status labels."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Success and error
        metrics.increment_commands("test", success=True)
        metrics.increment_commands("test", success=False)
    
    def test_ai_status_labels(self):
        """Test AI status labels."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Different statuses
        for status in ["success", "error", "empty"]:
            metrics.increment_ai_requests(status)
    
    def test_song_source_labels(self):
        """Test song source labels."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        
        # Different sources
        for source in ["youtube", "spotify", "search"]:
            metrics.increment_songs(source)
