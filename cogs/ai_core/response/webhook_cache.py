"""
Webhook Cache Module.
Provides caching for Discord webhooks to reduce API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord

# ==================== Webhook Cache ====================
# Cache webhooks to reduce API calls
_webhook_cache: dict[int, dict[str, discord.Webhook]] = {}  # channel_id -> {name: webhook}
_webhook_cache_time: dict[int, float] = {}  # channel_id -> last_update_time
WEBHOOK_CACHE_TTL = 600  # 10 minutes
_webhook_cache_cleanup_task: asyncio.Task | None = None  # Background cleanup task


def get_cached_webhook(channel_id: int, webhook_name: str) -> discord.Webhook | None:
    """Get webhook from cache if valid.

    Args:
        channel_id: The channel ID
        webhook_name: Name of the webhook

    Returns:
        Cached webhook if valid, None otherwise
    """
    now = time.time()
    if channel_id in _webhook_cache:
        if now - _webhook_cache_time.get(channel_id, 0) < WEBHOOK_CACHE_TTL:
            return _webhook_cache[channel_id].get(webhook_name)
    return None


async def _cleanup_expired_webhook_cache() -> None:
    """Background task to clean up expired webhook cache entries."""
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            now = time.time()
            expired_channels = [
                channel_id
                for channel_id, last_time in _webhook_cache_time.items()
                if now - last_time >= WEBHOOK_CACHE_TTL
            ]
            for channel_id in expired_channels:
                _webhook_cache.pop(channel_id, None)
                _webhook_cache_time.pop(channel_id, None)
            if expired_channels:
                logging.debug(
                    "🧹 Cleaned up %d expired webhook cache entries", len(expired_channels)
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            # Catch all exceptions to prevent task death, log and continue
            logging.error("Error in webhook cache cleanup: %s", e)
            await asyncio.sleep(60)  # Backoff on error before retrying


def start_webhook_cache_cleanup(bot) -> None:
    """Start the background webhook cache cleanup task.

    Args:
        bot: The Discord bot instance
    """
    global _webhook_cache_cleanup_task  # pylint: disable=global-statement
    if _webhook_cache_cleanup_task is None or _webhook_cache_cleanup_task.done():
        _webhook_cache_cleanup_task = bot.loop.create_task(_cleanup_expired_webhook_cache())
        logging.info("🧹 Started webhook cache cleanup task")


def stop_webhook_cache_cleanup() -> None:
    """Stop the background webhook cache cleanup task."""
    global _webhook_cache_cleanup_task  # pylint: disable=global-statement

    if _webhook_cache_cleanup_task and not _webhook_cache_cleanup_task.done():
        _webhook_cache_cleanup_task.cancel()
        _webhook_cache_cleanup_task = None
        logging.info("🧹 Stopped webhook cache cleanup task")

    # Clear cache on stop to free memory
    _webhook_cache.clear()
    _webhook_cache_time.clear()


def set_cached_webhook(channel_id: int, webhook_name: str, webhook: discord.Webhook) -> None:
    """Store webhook in cache.

    Args:
        channel_id: The channel ID
        webhook_name: Name of the webhook
        webhook: The webhook object to cache
    """
    if channel_id not in _webhook_cache:
        _webhook_cache[channel_id] = {}
    _webhook_cache[channel_id][webhook_name] = webhook
    _webhook_cache_time[channel_id] = time.time()


def invalidate_webhook_cache(channel_id: int, webhook_name: str | None = None) -> None:
    """Invalidate webhook cache for a channel.

    Call this when:
    - A channel is deleted
    - A webhook operation fails with 404
    - Cache needs to be refreshed

    Args:
        channel_id: The channel ID to invalidate
        webhook_name: Optional specific webhook name, or None to clear all for channel
    """
    if webhook_name:
        if channel_id in _webhook_cache:
            _webhook_cache[channel_id].pop(webhook_name, None)
    else:
        _webhook_cache.pop(channel_id, None)
        _webhook_cache_time.pop(channel_id, None)


def invalidate_webhook_cache_on_channel_delete(channel_id: int) -> None:
    """Public function to invalidate webhook cache when a channel is deleted.

    This should be called from an on_guild_channel_delete event listener.

    Args:
        channel_id: The ID of the deleted channel
    """
    invalidate_webhook_cache(channel_id)
    logging.debug("🧹 Invalidated webhook cache for deleted channel %s", channel_id)


__all__ = [
    "WEBHOOK_CACHE_TTL",
    "get_cached_webhook",
    "invalidate_webhook_cache",
    "invalidate_webhook_cache_on_channel_delete",
    "set_cached_webhook",
    "start_webhook_cache_cleanup",
    "stop_webhook_cache_cleanup",
]
