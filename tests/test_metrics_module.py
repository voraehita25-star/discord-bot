"""
Tests for utils/monitoring/metrics.py module.
Tests the Prometheus metrics collection functionality.

Note: Prometheus metrics are globally registered and cannot be re-registered.
This test module uses the global singleton `metrics` instance to avoid
"Duplicated timeseries" errors when running tests.

When prometheus_client is not installed, enabled-path tests use MagicMock
to simulate Counter/Gauge/Histogram objects instead of skipping.
"""

from unittest.mock import MagicMock

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

        assert hasattr(metrics, "enabled")
        assert isinstance(metrics.enabled, bool)

    def test_init_server_not_started_by_default(self):
        """Test server has _server_started attribute."""
        from utils.monitoring.metrics import metrics

        # Just verify attribute exists - it may or may not be started in other tests
        assert hasattr(metrics, "_server_started")


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
        original_enabled = metrics.enabled
        try:
            # Must also set enabled = True for the early return check to work
            metrics.enabled = True
            metrics._server_started = True
            result = metrics.start_server(18001)
            assert result is True
        finally:
            metrics._server_started = original_started
            metrics.enabled = original_enabled


# ==================== Helper to ensure metrics enabled with mocks ====================


def _enable_metrics_with_mocks(metrics):
    """Temporarily enable metrics by mocking prometheus objects if not available.

    Always creates fresh MagicMock objects to avoid call count leaking between tests.
    """
    from utils.monitoring.metrics import PROMETHEUS_AVAILABLE

    if PROMETHEUS_AVAILABLE:
        # Real prometheus objects exist, just ensure enabled
        metrics.enabled = True
        return

    # Always create fresh mocks to reset call counts between tests
    metrics.enabled = True
    metrics.messages_total = MagicMock()
    metrics.commands_total = MagicMock()
    metrics.ai_requests_total = MagicMock()
    metrics.songs_played_total = MagicMock()
    metrics.guilds_count = MagicMock()
    metrics.voice_clients_count = MagicMock()
    metrics.queue_size = MagicMock()
    metrics.memory_bytes = MagicMock()
    metrics.command_latency = MagicMock()
    metrics.ai_response_time = MagicMock()


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_messages = getattr(metrics, "messages_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            # Should not raise
            metrics.increment_messages("command")
            metrics.increment_messages("ai")
            metrics.increment_messages()  # default "other"

            if not PROMETHEUS_AVAILABLE:
                # Verify mock was called with labels
                assert metrics.messages_total.labels.call_count == 3
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_messages is None and hasattr(metrics, "messages_total"):
                    del metrics.messages_total
                else:
                    metrics.messages_total = original_messages


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_commands = getattr(metrics, "commands_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.increment_commands("play", success=True)

            if not PROMETHEUS_AVAILABLE:
                metrics.commands_total.labels.assert_called_with(command="play", status="success")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_commands is None and hasattr(metrics, "commands_total"):
                    del metrics.commands_total
                else:
                    metrics.commands_total = original_commands

    def test_increment_commands_error(self):
        """Test increment_commands with error."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_commands = getattr(metrics, "commands_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.increment_commands("play", success=False)

            if not PROMETHEUS_AVAILABLE:
                metrics.commands_total.labels.assert_called_with(command="play", status="error")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_commands is None and hasattr(metrics, "commands_total"):
                    del metrics.commands_total
                else:
                    metrics.commands_total = original_commands


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_ai = getattr(metrics, "ai_requests_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.increment_ai_requests("success")

            if not PROMETHEUS_AVAILABLE:
                metrics.ai_requests_total.labels.assert_called_with(status="success")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_ai is None and hasattr(metrics, "ai_requests_total"):
                    del metrics.ai_requests_total
                else:
                    metrics.ai_requests_total = original_ai

    def test_increment_ai_requests_error(self):
        """Test increment_ai_requests with error status."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_ai = getattr(metrics, "ai_requests_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.increment_ai_requests("error")

            if not PROMETHEUS_AVAILABLE:
                metrics.ai_requests_total.labels.assert_called_with(status="error")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_ai is None and hasattr(metrics, "ai_requests_total"):
                    del metrics.ai_requests_total
                else:
                    metrics.ai_requests_total = original_ai


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_songs = getattr(metrics, "songs_played_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.increment_songs("youtube")

            if not PROMETHEUS_AVAILABLE:
                metrics.songs_played_total.labels.assert_called_with(source="youtube")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_songs is None and hasattr(metrics, "songs_played_total"):
                    del metrics.songs_played_total
                else:
                    metrics.songs_played_total = original_songs

    def test_increment_songs_spotify(self):
        """Test increment_songs with spotify source."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_songs = getattr(metrics, "songs_played_total", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.increment_songs("spotify")

            if not PROMETHEUS_AVAILABLE:
                metrics.songs_played_total.labels.assert_called_with(source="spotify")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_songs is None and hasattr(metrics, "songs_played_total"):
                    del metrics.songs_played_total
                else:
                    metrics.songs_played_total = original_songs


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_guilds = getattr(metrics, "guilds_count", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.set_guilds(50)

            if not PROMETHEUS_AVAILABLE:
                metrics.guilds_count.set.assert_called_with(50)
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_guilds is None and hasattr(metrics, "guilds_count"):
                    del metrics.guilds_count
                else:
                    metrics.guilds_count = original_guilds


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_vc = getattr(metrics, "voice_clients_count", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.set_voice_clients(3)

            if not PROMETHEUS_AVAILABLE:
                metrics.voice_clients_count.set.assert_called_with(3)
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_vc is None and hasattr(metrics, "voice_clients_count"):
                    del metrics.voice_clients_count
                else:
                    metrics.voice_clients_count = original_vc


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_qs = getattr(metrics, "queue_size", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.set_queue_size(123456789, 25)

            if not PROMETHEUS_AVAILABLE:
                metrics.queue_size.labels.assert_called_with(guild_id="123456789")
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_qs is None and hasattr(metrics, "queue_size"):
                    del metrics.queue_size
                else:
                    metrics.queue_size = original_qs


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_mem = getattr(metrics, "memory_bytes", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.set_memory(1024 * 1024 * 256)  # 256MB

            if not PROMETHEUS_AVAILABLE:
                metrics.memory_bytes.set.assert_called_with(1024 * 1024 * 256)
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_mem is None and hasattr(metrics, "memory_bytes"):
                    del metrics.memory_bytes
                else:
                    metrics.memory_bytes = original_mem


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_lat = getattr(metrics, "command_latency", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.observe_command_latency("play", 1.5)
            metrics.observe_command_latency("skip", 0.1)

            if not PROMETHEUS_AVAILABLE:
                assert metrics.command_latency.labels.call_count == 2
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_lat is None and hasattr(metrics, "command_latency"):
                    del metrics.command_latency
                else:
                    metrics.command_latency = original_lat


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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_rt = getattr(metrics, "ai_response_time", None)
        try:
            _enable_metrics_with_mocks(metrics)
            metrics.observe_ai_response_time(5.0)

            if not PROMETHEUS_AVAILABLE:
                metrics.ai_response_time.observe.assert_called_with(5.0)
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_rt is None and hasattr(metrics, "ai_response_time"):
                    del metrics.ai_response_time
                else:
                    metrics.ai_response_time = original_rt


# ==================== TestGlobalMetrics ====================


class TestGlobalMetrics:
    """Test global metrics instance."""

    def test_global_metrics_exists(self):
        """Test global metrics instance exists."""
        from utils.monitoring.metrics import metrics

        assert metrics is not None

    def test_global_metrics_is_bot_metrics(self):
        """Test global metrics is BotMetrics instance."""
        from utils.monitoring.metrics import BotMetrics, metrics

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
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_msg = getattr(metrics, "messages_total", None)
        try:
            _enable_metrics_with_mocks(metrics)

            for msg_type in ["command", "ai", "music", "other"]:
                metrics.increment_messages(msg_type)

            if not PROMETHEUS_AVAILABLE:
                assert metrics.messages_total.labels.call_count == 4
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_msg is None and hasattr(metrics, "messages_total"):
                    del metrics.messages_total
                else:
                    metrics.messages_total = original_msg

    def test_command_status_labels(self):
        """Test command status labels."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_cmd = getattr(metrics, "commands_total", None)
        try:
            _enable_metrics_with_mocks(metrics)

            metrics.increment_commands("test", success=True)
            metrics.increment_commands("test", success=False)

            if not PROMETHEUS_AVAILABLE:
                assert metrics.commands_total.labels.call_count == 2
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_cmd is None and hasattr(metrics, "commands_total"):
                    del metrics.commands_total
                else:
                    metrics.commands_total = original_cmd

    def test_ai_status_labels(self):
        """Test AI status labels."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_ai = getattr(metrics, "ai_requests_total", None)
        try:
            _enable_metrics_with_mocks(metrics)

            for status in ["success", "error", "empty"]:
                metrics.increment_ai_requests(status)

            if not PROMETHEUS_AVAILABLE:
                assert metrics.ai_requests_total.labels.call_count == 3
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_ai is None and hasattr(metrics, "ai_requests_total"):
                    del metrics.ai_requests_total
                else:
                    metrics.ai_requests_total = original_ai

    def test_song_source_labels(self):
        """Test song source labels."""
        from utils.monitoring.metrics import PROMETHEUS_AVAILABLE, metrics

        original_enabled = metrics.enabled
        original_songs = getattr(metrics, "songs_played_total", None)
        try:
            _enable_metrics_with_mocks(metrics)

            for source in ["youtube", "spotify", "search"]:
                metrics.increment_songs(source)

            if not PROMETHEUS_AVAILABLE:
                assert metrics.songs_played_total.labels.call_count == 3
        finally:
            metrics.enabled = original_enabled
            if not PROMETHEUS_AVAILABLE:
                if original_songs is None and hasattr(metrics, "songs_played_total"):
                    del metrics.songs_played_total
                else:
                    metrics.songs_played_total = original_songs
