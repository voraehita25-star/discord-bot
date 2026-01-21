"""
Backward compatibility re-export for performance module.
This file re-exports from core/ subdirectory.
"""

from .core.performance import (
    PERFORMANCE_SAMPLES_MAX,
    PerformanceTracker,
    RequestDeduplicator,
    performance_tracker,
    request_deduplicator,
)

__all__ = [
    "PERFORMANCE_SAMPLES_MAX",
    "PerformanceTracker",
    "RequestDeduplicator",
    "performance_tracker",
    "request_deduplicator",
]
