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
import threading
from typing import ClassVar

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
        # Per-instance (NOT class-shared) so multiple BotMetrics constructions
        # don't trample each other's queue snapshots — and a threading.Lock
        # so concurrent dict mutation/iteration doesn't trip
        # ``RuntimeError: dictionary changed size during iteration``.
        self._guild_queue_sizes = {}
        self._queue_lock = threading.Lock()

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

            # Aggregate queue-size metrics. The previous per-guild label
            # exploded series count for popular bots (one series per guild,
            # each at a default 8192 sample limit) and could push tens of MB
            # of cardinality into Prometheus. We instead track:
            #   - queue_size_total: sum of all guild queue depths
            #   - queue_size_max:   the largest single queue
            #   - queues_active:    how many guilds have non-empty queues
            # The set_queue_size / remove_queue_size helpers update these
            # aggregates from the per-guild numbers the cog already tracks.
            self.queue_size_total = Gauge(
                "discord_bot_queue_size_total",
                "Aggregate music queue depth across all guilds",
            )
            self.queue_size_max = Gauge(
                "discord_bot_queue_size_max",
                "Largest single music queue depth across guilds",
            )
            self.queues_active = Gauge(
                "discord_bot_queues_active",
                "Number of guilds with a non-empty music queue",
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
            # prometheus_client's start_http_server signature changed: newer
            # versions return (server, thread); older versions return None.
            # Handle both so we don't crash on `cannot unpack None`.
            # Older versions also lack ``addr=`` AND default to 0.0.0.0 —
            # binding metrics on a public interface is a real exposure
            # for a SaaS deployment. Refuse to start rather than silently
            # falling back to a public bind.
            try:
                result = start_http_server(port, addr="127.0.0.1")
            except TypeError:
                logger.error(
                    "prometheus_client too old (no ``addr=`` kwarg). "
                    "Refusing to start metrics server because the default "
                    "bind is 0.0.0.0 — please upgrade to >= 0.20."
                )
                return False

            if isinstance(result, tuple) and len(result) == 2:
                self._server, self._server_thread = result
            else:
                self._server, self._server_thread = None, None

            self._server_started = True
            logger.info("📊 Prometheus metrics server started on 127.0.0.1:%d", port)
            return True
        except OSError:
            logger.exception("Failed to start metrics server")
            return False

    def shutdown_server(self):
        """Gracefully shutdown the Prometheus metrics HTTP server."""
        if not self._server_started:
            return
        if self._server is None:
            # Started, but start_http_server() returned no handle (older
            # prometheus_client). The daemon HTTP thread is still running and
            # the port stays bound — make that visible instead of a silent
            # no-op so the leak isn't mistaken for a clean shutdown.
            logger.warning(
                "Metrics server is running but no server handle was captured; "
                "cannot stop it cleanly (upgrade prometheus_client >= 0.20)."
            )
            self._server_started = False
            return
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

    # Per-guild snapshot used to recompute aggregates without keeping a
    # per-guild Prometheus series (which would blow up cardinality).
    # Guarded by ``_queue_lock`` so concurrent set/remove from multiple
    # threads don't race on dict iteration during ``list(.values())``.
    # NOTE: stored as an instance attribute (init below) — the previous
    # ClassVar form silently shared state across every BotMetrics instance.
    _guild_queue_sizes: dict[int, int]
    _queue_lock: threading.Lock

    def _recompute_queue_aggregates(self) -> None:
        if not self.enabled:
            return
        # Compute AND publish under the lock so the last thread to take the
        # snapshot is also the last to publish — otherwise two concurrent
        # recompute calls can interleave (thread A snapshots, thread B
        # snapshots + publishes, thread A publishes its stale snapshot last),
        # leaving the exported gauges transiently inconsistent with
        # _guild_queue_sizes.
        with self._queue_lock:
            sizes = list(self._guild_queue_sizes.values())
            non_empty = [s for s in sizes if s > 0]
            self.queue_size_total.set(sum(non_empty))
            self.queue_size_max.set(max(non_empty) if non_empty else 0)
            self.queues_active.set(len(non_empty))

    def set_queue_size(self, guild_id: int, size: int):
        """Update per-guild queue size and refresh aggregates."""
        if not self.enabled:
            return
        with self._queue_lock:
            self._guild_queue_sizes[guild_id] = size
        self._recompute_queue_aggregates()

    def remove_queue_size(self, guild_id: int):
        """Forget a guild's queue size (call when the bot leaves the guild)."""
        if not self.enabled:
            return
        with self._queue_lock:
            self._guild_queue_sizes.pop(guild_id, None)
        self._recompute_queue_aggregates()

    def set_memory(self, bytes_used: int):
        """Set current memory usage."""
        if self.enabled:
            self.memory_bytes.set(bytes_used)

    # Allowlist of commands we're willing to label-explode metrics by.
    # Anything not in this set rolls up under "other" so an attacker
    # spamming variant command names can't blow up Prometheus cardinality.
    _COMMAND_LABEL_ALLOWLIST: ClassVar[set[str]] = {
        "chat",
        "ask",
        "gemini",
        "play",
        "skip",
        "stop",
        "queue",
        "leave",
        "join",
        "shuffle",
        "loop",
        "pause",
        "resume",
        "remove",
        "clear",
        "volume",
        "seek",
        "fix",
        "help",
        "ping",
        "stats",
        "memories",
        "remember",
        "forget",
        "view_memories",
        "memory_stats",
        "db_write_lock_wait",  # synthetic internal latency series (DB write-lock contention), not a user command
    }

    # Same defence for circuit-breaker and rate-limiter labels. An
    # untrusted caller (or a typo in a new feature) could otherwise
    # mint one Prometheus series per breaker name and exhaust the
    # /metrics endpoint.
    _CIRCUIT_NAME_ALLOWLIST: ClassVar[set[str]] = {
        "anthropic",
        "claude_cli",
        "gemini",
        "youtube",
        "spotify",
        "discord",
        "go_url_fetcher",
        "go_health_api",
    }
    _RATE_LIMIT_CONFIG_ALLOWLIST: ClassVar[set[str]] = {
        "ai_chat",
        "ai_image",
        "ai_global",
        "music",
        "command",
        "dashboard",
        "default",
    }

    def observe_command_latency(self, command: str, duration: float):
        """Record command execution duration."""
        if not self.enabled:
            return
        # Cap label cardinality — a misbehaving caller (or attacker) feeding
        # a unique command name per call would otherwise create one Prometheus
        # series per name and exhaust the metrics endpoint.
        safe_label = command if command in self._COMMAND_LABEL_ALLOWLIST else "other"
        self.command_latency.labels(command=safe_label).observe(duration)

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
            # Clamp to known values to bound Prometheus label cardinality, like
            # the sibling metric methods (a future dynamic caller can't explode
            # the series count).
            safe_method = method if method in ("prefilter", "ai", "game_keyword") else "other"
            safe_result = result if result in ("search", "no_search") else "other"
            self.search_intent_total.labels(method=safe_method, result=safe_result).inc()

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
            safe = name if name in self._CIRCUIT_NAME_ALLOWLIST else "other"
            self.circuit_breaker_state.labels(name=safe).set(state)

    def increment_circuit_breaker_failure(self, name: str):
        """Record a circuit breaker failure."""
        if self.enabled:
            safe = name if name in self._CIRCUIT_NAME_ALLOWLIST else "other"
            self.circuit_breaker_failures.labels(name=safe).inc()

    def increment_rate_limit_blocked(self, config: str):
        """Record a rate-limited request."""
        if self.enabled:
            safe = config if config in self._RATE_LIMIT_CONFIG_ALLOWLIST else "other"
            self.rate_limit_blocked.labels(config=safe).inc()


# Global metrics instance
metrics = BotMetrics()
