"""Reliability utilities - Circuit breakers, rate limiting, self-healing, memory & shutdown."""

from .circuit_breaker import CircuitBreaker, CircuitState, gemini_circuit, spotify_circuit

# Error Recovery with Smart Backoff
from .error_recovery import (
    BackoffState,
    GracefulDegradation,
    JitterStrategy,
    RetryConfig,
    ServiceHealthMonitor,
    calculate_delay_sync,
    retry_async,
    with_retry,
)

# Memory Management (Memory Leak Prevention)
from .memory_manager import (
    CacheStats,
    MemoryMonitor,
    TTLCache,
    WeakRefCache,
    cached_with_ttl,
    memory_monitor,
)
from .rate_limiter import RateLimiter, ai_ratelimit, rate_limiter, ratelimit
from .self_healer import SelfHealer, ensure_single_bot, quick_heal

# Graceful Shutdown
from .shutdown_manager import (
    CleanupHandler,
    Priority,
    ShutdownManager,
    ShutdownPhase,
    on_shutdown,
    shutdown_manager,
)
