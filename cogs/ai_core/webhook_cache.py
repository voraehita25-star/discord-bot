"""
Backward compatibility re-export for webhook_cache module.
This file re-exports from response/ subdirectory.
"""

from .response.webhook_cache import (
    WEBHOOK_CACHE_TTL,
    _webhook_cache,
    _webhook_cache_time,
    get_cached_webhook,
    invalidate_webhook_cache,
    invalidate_webhook_cache_on_channel_delete,
    set_cached_webhook,
    start_webhook_cache_cleanup,
    stop_webhook_cache_cleanup,
)

__all__ = [
    "WEBHOOK_CACHE_TTL",
    "_webhook_cache",
    "_webhook_cache_time",
    "get_cached_webhook",
    "invalidate_webhook_cache",
    "invalidate_webhook_cache_on_channel_delete",
    "set_cached_webhook",
    "start_webhook_cache_cleanup",
    "stop_webhook_cache_cleanup",
]
