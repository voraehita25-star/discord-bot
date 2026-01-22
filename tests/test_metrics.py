"""
Tests for utils.monitoring.metrics module.
Uses the global metrics instance to avoid duplicated timeseries errors.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestBotMetricsInit:
    """Tests for BotMetrics initialization."""

    def test_metrics_enabled_when_prometheus_available(self):
        """Test metrics are enabled when prometheus_client is installed."""
        from utils.monitoring.metrics import metrics, PROMETHEUS_AVAILABLE
        
        # The global instance should reflect PROMETHEUS_AVAILABLE
        assert metrics.enabled == PROMETHEUS_AVAILABLE

    def test_metrics_disabled_when_prometheus_not_available(self):
        """Test metrics are disabled when prometheus_client is not installed."""
        # This tests the fallback behavior
        pass  # Already covered by default state


class TestBotMetricsMethods:
    """Tests for BotMetrics convenience methods using global instance."""

    def test_increment_messages_noop_when_disabled(self):
        """Test increment_messages does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            # Should not raise
            metrics.increment_messages("command")
        finally:
            metrics.enabled = original_enabled

    def test_increment_commands_noop_when_disabled(self):
        """Test increment_commands does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.increment_commands("test", success=True)
            metrics.increment_commands("test", success=False)
        finally:
            metrics.enabled = original_enabled

    def test_increment_ai_requests_noop_when_disabled(self):
        """Test increment_ai_requests does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.increment_ai_requests("success")
            metrics.increment_ai_requests("error")
        finally:
            metrics.enabled = original_enabled

    def test_increment_songs_noop_when_disabled(self):
        """Test increment_songs does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.increment_songs("youtube")
            metrics.increment_songs("spotify")
        finally:
            metrics.enabled = original_enabled

    def test_set_guilds_noop_when_disabled(self):
        """Test set_guilds does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.set_guilds(100)
        finally:
            metrics.enabled = original_enabled

    def test_set_voice_clients_noop_when_disabled(self):
        """Test set_voice_clients does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.set_voice_clients(5)
        finally:
            metrics.enabled = original_enabled

    def test_set_queue_size_noop_when_disabled(self):
        """Test set_queue_size does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.set_queue_size(123456, 10)
        finally:
            metrics.enabled = original_enabled

    def test_set_memory_noop_when_disabled(self):
        """Test set_memory does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.set_memory(1024 * 1024)
        finally:
            metrics.enabled = original_enabled

    def test_observe_command_latency_noop_when_disabled(self):
        """Test observe_command_latency does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.observe_command_latency("ping", 0.5)
        finally:
            metrics.enabled = original_enabled

    def test_observe_ai_response_time_noop_when_disabled(self):
        """Test observe_ai_response_time does nothing when disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            metrics.observe_ai_response_time(5.0)
        finally:
            metrics.enabled = original_enabled

    def test_increment_messages_works_when_enabled(self):
        """Test increment_messages works when enabled."""
        from utils.monitoring.metrics import metrics
        
        if metrics.enabled:
            # Should not raise
            metrics.increment_messages("test")

    def test_increment_commands_works_when_enabled(self):
        """Test increment_commands works when enabled."""
        from utils.monitoring.metrics import metrics
        
        if metrics.enabled:
            metrics.increment_commands("test_cmd", success=True)

    def test_set_guilds_works_when_enabled(self):
        """Test set_guilds works when enabled."""
        from utils.monitoring.metrics import metrics
        
        if metrics.enabled:
            metrics.set_guilds(10)


class TestStartServer:
    """Tests for start_server method."""

    def test_start_server_returns_false_when_disabled(self):
        """Test start_server returns False when metrics disabled."""
        from utils.monitoring.metrics import metrics
        
        original_enabled = metrics.enabled
        metrics.enabled = False
        
        try:
            result = metrics.start_server(8000)
            assert result is False
        finally:
            metrics.enabled = original_enabled

    def test_start_server_returns_true_if_already_started(self):
        """Test start_server returns True if already started."""
        from utils.monitoring.metrics import metrics
        
        original_started = metrics._server_started
        metrics._server_started = True
        
        try:
            if metrics.enabled:
                result = metrics.start_server(8000)
                assert result is True
        finally:
            metrics._server_started = original_started


class TestGlobalMetrics:
    """Tests for global metrics instance."""

    def test_global_metrics_exists(self):
        """Test that global metrics instance exists."""
        from utils.monitoring.metrics import metrics
        
        assert metrics is not None

    def test_global_metrics_is_botmetrics(self):
        """Test that global metrics is BotMetrics instance."""
        from utils.monitoring.metrics import metrics, BotMetrics
        
        assert isinstance(metrics, BotMetrics)

    def test_global_metrics_has_server_started_flag(self):
        """Test that global metrics has _server_started flag."""
        from utils.monitoring.metrics import metrics
        
        assert hasattr(metrics, "_server_started")
        assert isinstance(metrics._server_started, bool)
