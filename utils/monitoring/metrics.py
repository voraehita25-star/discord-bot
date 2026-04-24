"""
Prometheus Metrics Module for Discord Bot.
Provides observability metrics for monitoring bot performance.

This module is optional - install prometheus_client to enable:
    pip install prometheus-client

Usage:
    from utils.monitoring.metrics import metrics
    metrics.increment_messages()
    metrics.set_voice_clients(count)
"""

import logging
logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.debug("prometheus_client not installed - metrics disabled")


class BotMetrics:
    """Bot metrics collector for Prometheus."""

    def __init__(self):
        self.enabled = PROMETHEUS_AVAILABLE
        self._server_started = False
        self._server = None
        self._server_thread = None

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

            self.search_intent_total = Counter(
                "discord_bot_search_intent_total",
                "Search intent classification results",
                ["method", "result"],  # method: 'prefilter', 'ai'; result: 'search', 'no_search'
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

            # Database pool metrics
            self.db_pool_size = Gauge(
                "discord_bot_db_pool_connections", "Database connection pool size"
            )
            self.db_pool_available = Gauge(
                "discord_bot_db_pool_available", "Available connection pool slots"
            )
            self.db_pool_timeouts = Counter(
                "discord_bot_db_pool_timeouts_total", "Database pool acquire timeouts"
            )

            # Cache metrics
            self.cache_hits = Counter(
                "discord_bot_cache_hits_total",
                "Cache hits by tier",
                ["tier"],  # 'l1_memory', 'l2_sqlite'
            )
            self.cache_misses = Counter(
                "discord_bot_cache_misses_total",
                "Cache misses",
            )

            # Circuit breaker metrics
            self.circuit_breaker_state = Gauge(
                "discord_bot_circuit_breaker_state",
                "Circuit breaker state (0=closed, 1=half_open, 2=open)",
                ["name"],
            )
            self.circuit_breaker_failures = Counter(
                "discord_bot_circuit_breaker_failures_total",
                "Circuit breaker failure count",
                ["name"],
            )

            # Rate limiter metrics
            self.rate_limit_blocked = Counter(
                "discord_bot_rate_limit_blocked_total",
                "Rate limited requests",
                ["config"],
            )

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

            # Pre-initialize known label values to avoid missing metrics
            self.messages_total.labels(type="command")
            self.messages_total.labels(type="ai")
            self.messages_total.labels(type="music")
            self.messages_total.labels(type="other")
            self.ai_requests_total.labels(status="success")
            self.ai_requests_total.labels(status="error")
            self.ai_requests_total.labels(status="empty")
            self.songs_played_total.labels(source="youtube")
            self.songs_played_total.labels(source="spotify")
            self.songs_played_total.labels(source="search")
            self.search_intent_total.labels(method="prefilter", result="search")
            self.search_intent_total.labels(method="prefilter", result="no_search")
            self.search_intent_total.labels(method="ai", result="search")
            self.search_intent_total.labels(method="ai", result="no_search")
            self.search_intent_total.labels(method="game_keyword", result="search")
            self.search_intent_total.labels(method="game_keyword", result="no_search")

    def start_server(self, port: int = 8000) -> bool:
        """Start the Prometheus metrics HTTP server."""
        if not self.enabled:
            logger.warning("Prometheus metrics disabled (prometheus_client not installed)")
            return False

        if self._server_started:
            return True

        try:
            self._server, self._server_thread = start_http_server(port, addr="127.0.0.1")
            self._server_started = True
            logger.info("📊 Prometheus metrics server started on 127.0.0.1:%d", port)
            return True
        except OSError:
            logger.exception("Failed to start metrics server")
            return False

    def shutdown_server(self):
        """Gracefully shutdown the Prometheus metrics HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            if self._server_thread:
                self._server_thread.join(timeout=5)
            self._server = None
            self._server_thread = None
            self._server_started = False
            logger.info("📊 Prometheus metrics server stopped")

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

    def remove_queue_size(self, guild_id: int):
        """Remove queue size metric for a guild (call when bot leaves a guild)."""
        if self.enabled:
            self.queue_size.remove(str(guild_id))

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


    def increment_search_intent(self, method: str, result: str):
        """Record a search intent classification.

        Args:
            method: 'prefilter', 'ai', or 'game_keyword'
            result: 'search' or 'no_search'
        """
        if self.enabled:
            self.search_intent_total.labels(method=method, result=result).inc()

    def set_db_pool(self, total: int, available: int):
        """Set database pool metrics."""
        if self.enabled:
            self.db_pool_size.set(total)
            self.db_pool_available.set(available)

    def increment_db_pool_timeouts(self):
        """Increment database pool timeout counter."""
        if self.enabled:
            self.db_pool_timeouts.inc()

    def increment_cache_hit(self, tier: str = "l1_memory"):
        """Record a cache hit."""
        if self.enabled:
            self.cache_hits.labels(tier=tier).inc()

    def increment_cache_miss(self):
        """Record a cache miss."""
        if self.enabled:
            self.cache_misses.inc()

    def set_circuit_breaker_state(self, name: str, state: int):
        """Set circuit breaker state gauge (0=closed, 1=half_open, 2=open)."""
        if self.enabled:
            self.circuit_breaker_state.labels(name=name).set(state)

    def increment_circuit_breaker_failure(self, name: str):
        """Record a circuit breaker failure."""
        if self.enabled:
            self.circuit_breaker_failures.labels(name=name).inc()

    def increment_rate_limit_blocked(self, config: str):
        """Record a rate-limited request."""
        if self.enabled:
            self.rate_limit_blocked.labels(config=config).inc()


# Global metrics instance
metrics = BotMetrics()
