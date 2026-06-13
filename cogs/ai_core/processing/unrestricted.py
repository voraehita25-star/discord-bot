"""Unrestricted-channel registry for the Discord AI.

Tracks which channels are in "unrestricted mode" — a per-channel toggle (set via
the owner-only ``!unrestricted`` command) that injects the
``UNRESTRICTED_MODE_INSTRUCTION`` persona into the system prompt.

This logic used to live inside ``processing/guardrails.py``; that module was
removed, so the registry now stands on its own. It no longer bypasses any
content validation (there is none left) — it only controls persona injection.

State is persisted to ``data/unrestricted_channels.json`` so it survives bot
restarts. Access is thread-safe.

GLOBAL OVERRIDE (Discord AI only): when the ``AI_UNRESTRICTED_ALL`` env var is
truthy, EVERY channel is treated as unrestricted without needing the per-channel
toggle. This affects ONLY the Discord AI path (everything routed through
``is_unrestricted``); the dashboard chat has its own independent gate and is
deliberately NOT touched by this flag.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_UNRESTRICTED_ALL_ENV = "AI_UNRESTRICTED_ALL"


def unrestricted_all_enabled() -> bool:
    """True when the global 'all Discord channels unrestricted' override is set.

    Read from the environment on every call (not cached at import time) so the
    flag takes effect regardless of whether ``load_dotenv()`` ran before this
    module was first imported.
    """
    return os.getenv(_UNRESTRICTED_ALL_ENV, "").strip().lower() in ("1", "true", "yes", "on")


_UNRESTRICTED_FILE = Path(__file__).parent.parent / "data" / "unrestricted_channels.json"
_unrestricted_lock = threading.Lock()  # Thread-safe access to unrestricted_channels
unrestricted_channels: set[int] = set()

# Hard cap on persisted file size to prevent memory exhaustion via malicious/corrupt file
_UNRESTRICTED_MAX_BYTES = 1 * 1024 * 1024  # 1 MiB — plenty for thousands of channel IDs


def _load_unrestricted_channels() -> set[int]:
    """Load unrestricted channels from persistent storage."""
    try:
        if _UNRESTRICTED_FILE.exists():
            # Guard: refuse absurdly large files (memory exhaustion protection)
            try:
                size = _UNRESTRICTED_FILE.stat().st_size
            except OSError:
                size = 0
            if size > _UNRESTRICTED_MAX_BYTES:
                logger.error(
                    "unrestricted_channels.json too large (%d bytes > %d) — ignoring",
                    size,
                    _UNRESTRICTED_MAX_BYTES,
                )
                return set()
            data = json.loads(_UNRESTRICTED_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("channels"), list):
                logger.warning("Invalid unrestricted_channels.json format — using empty set")
                return set()
            channels = set()
            for ch in data["channels"]:
                if isinstance(ch, int):
                    channels.add(ch)
            logger.info("🔓 Loaded %d unrestricted channels from storage", len(channels))
            return channels
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("Failed to load unrestricted channels: %s", e)
    return set()


def _save_unrestricted_channels(channels_snapshot: list[int] | None = None) -> bool:
    """Save unrestricted channels to persistent storage using atomic write.

    Args:
        channels_snapshot: Pre-captured list of channel IDs to save. If None,
            acquires the lock to read the current set (for backward compatibility).
    """
    temp_file = _UNRESTRICTED_FILE.with_suffix(".tmp")  # Define early for cleanup
    try:
        _UNRESTRICTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Use provided snapshot or acquire lock to create one
        if channels_snapshot is None:
            with _unrestricted_lock:
                channels_snapshot = list(unrestricted_channels)
        data_to_save = {"channels": channels_snapshot}
        # Atomic write: write to temp file, fsync, then rename. fsync flushes OS
        # buffers before the rename so a crash mid-write cannot leave a
        # half-written temp that later gets promoted.
        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_file.replace(_UNRESTRICTED_FILE)  # Atomic on most filesystems
        return True
    except (OSError, TypeError, ValueError):
        logger.exception("Failed to save unrestricted channels")
        # Cleanup temp file on failure
        try:
            if temp_file.exists():
                temp_file.unlink()
        except OSError:
            pass
        return False


# Load on module import
unrestricted_channels = _load_unrestricted_channels()


def is_unrestricted(channel_id: int) -> bool:
    """Check if a channel is in unrestricted mode.

    Returns True if the global ``AI_UNRESTRICTED_ALL`` override is set, or if the
    channel has been explicitly set to unrestricted via the ``!unrestricted``
    command. Otherwise False.
    """
    if unrestricted_all_enabled():
        return True
    with _unrestricted_lock:
        return channel_id in unrestricted_channels


def set_unrestricted(channel_id: int, enabled: bool) -> bool:
    """Enable or disable unrestricted mode for a channel. Persists to disk (thread-safe).

    Returns the persistence outcome so callers can surface save failures.
    """
    with _unrestricted_lock:
        if enabled:
            unrestricted_channels.add(channel_id)
        else:
            unrestricted_channels.discard(channel_id)
        # Snapshot data while holding the lock
        channels_snapshot = list(unrestricted_channels)

    # Save to disk OUTSIDE the lock to avoid file I/O under threading.Lock
    saved = _save_unrestricted_channels(channels_snapshot)
    if not saved:
        logger.error("Failed to persist unrestricted channel state for %s", channel_id)

    logger.info(
        "🔓 Unrestricted mode %s for channel %s (persisted=%s)",
        "ENABLED" if enabled else "DISABLED",
        channel_id,
        saved,
    )
    # Return the actual persistence outcome so callers can surface failures.
    return saved
