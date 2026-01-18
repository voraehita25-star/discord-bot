"""
Prometheus Metrics Module for Discord Bot.
Provides observability metrics for monitoring bot performance.

This module is optional - install prometheus_client to enable:
    pip install prometheus-client

Usage:
    from utils.metrics import metrics
    metrics.increment_messages()
    metrics.set_voice_clients(count)
"""

import logging

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logging.debug("prometheus_client not installed - metrics disabled")


class BotMetrics:
    """Bot metrics collector for Prometheus."""

    def __init__(self):
        self.enabled = PROMETHEUS_AVAILABLE
        self._server_started = False

        if self.enabled:
            # Counters (always increasing)
            self.messages_total = Counter(
                "discord_bot_messages_total",
                "Total messages processed",
                ["type"],  # 'command', 'ai', 'music'
            )

            self.commands_total = Counter(
                "discord_bot_commands_total",
                "Total commands executed",
                ["command", "status"],  # status: 'success', 'error'
            )

            self.ai_requests_total = Counter(
                "discord_bot_ai_requests_total",
                "Total AI API requests",
                ["status"],  # 'success', 'error', 'empty'
            )

            self.songs_played_total = Counter(
                "discord_bot_songs_played_total",
                "Total songs played",
                ["source"],  # 'youtube', 'spotify', 'search'
            )

            # Gauges (can go up and down)
            self.guilds_count = Gauge("discord_bot_guilds", "Number of guilds bot is in")

            self.voice_clients_count = Gauge(
                "discord_bot_voice_clients", "Number of active voice connections"
            )

            self.queue_size = Gauge(
                "discord_bot_queue_size", "Music queue size per guild", ["guild_id"]
            )

            self.memory_bytes = Gauge("discord_bot_memory_bytes", "Memory usage in bytes")

            # Histograms (for latency/duration)
            self.command_latency = Histogram(
                "discord_bot_command_latency_seconds",
                "Command execution latency",
                ["command"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
            )

            self.ai_response_time = Histogram(
                "discord_bot_ai_response_seconds",
                "AI response generation time",
                buckets=[1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
            )

    def start_server(self, port: int = 8000) -> bool:
        """Start the Prometheus metrics HTTP server."""
        if not self.enabled:
            logging.warning("Prometheus metrics disabled (prometheus_client not installed)")
            return False

        if self._server_started:
            return True

        try:
            start_http_server(port)
            self._server_started = True
            logging.info("📊 Prometheus metrics server started on port %d", port)
            return True
        except OSError as e:
            logging.error("Failed to start metrics server: %s", e)
            return False

    # Convenience methods
    def increment_messages(self, message_type: str = "other"):
        """Increment message counter."""
        if self.enabled:
            self.messages_total.labels(type=message_type).inc()

    def increment_commands(self, command: str, success: bool = True):
        """Increment command counter."""
        if self.enabled:
            status = "success" if success else "error"
            self.commands_total.labels(command=command, status=status).inc()

    def increment_ai_requests(self, status: str = "success"):
        """Increment AI request counter."""
        if self.enabled:
            self.ai_requests_total.labels(status=status).inc()

    def increment_songs(self, source: str = "youtube"):
        """Increment songs played counter."""
        if self.enabled:
            self.songs_played_total.labels(source=source).inc()

    def set_guilds(self, count: int):
        """Set current guild count."""
        if self.enabled:
            self.guilds_count.set(count)

    def set_voice_clients(self, count: int):
        """Set current voice client count."""
        if self.enabled:
            self.voice_clients_count.set(count)

    def set_queue_size(self, guild_id: int, size: int):
        """Set queue size for a guild."""
        if self.enabled:
            self.queue_size.labels(guild_id=str(guild_id)).set(size)

    def set_memory(self, bytes_used: int):
        """Set current memory usage."""
        if self.enabled:
            self.memory_bytes.set(bytes_used)

    def observe_command_latency(self, command: str, duration: float):
        """Record command execution duration."""
        if self.enabled:
            self.command_latency.labels(command=command).observe(duration)

    def observe_ai_response_time(self, duration: float):
        """Record AI response generation time."""
        if self.enabled:
            self.ai_response_time.observe(duration)


# Global metrics instance
metrics = BotMetrics()
