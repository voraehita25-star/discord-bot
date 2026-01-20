"""
Backward compatibility re-export for performance module.
This file re-exports from core/ subdirectory.
"""

from .core.performance import (
    PerformanceTracker,
    RequestDeduplicator,
    performance_tracker,
    request_deduplicator,
    PERFORMANCE_SAMPLES_MAX,
)

__all__ = [
    "PerformanceTracker",
    "RequestDeduplicator",
    "performance_tracker",
    "request_deduplicator",
    "PERFORMANCE_SAMPLES_MAX",
]
