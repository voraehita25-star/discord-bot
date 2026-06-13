"""Module-level weakref registry exposing the live ChatManager to dashboard code.

The dashboard WebSocket server is started argument-less from ``bot.py`` and
holds no bot/cog reference, but it runs in the same process and on the same
asyncio event loop as the AI cog. The cog registers its ``ChatManager`` here on
load so dashboard handlers can patch the live in-memory chat history after an
external DB edit (without the patch, the next diff/force save would clobber the
DB row with the stale in-memory copy).

Why ``weakref``: the registry must never keep an unloaded cog's ChatManager
alive — if ``cog_unload`` forgets (or fails before) the explicit unregister,
the dead reference simply resolves to None instead of leaking the whole
session graph.

Single event loop, no locking needed (same reasoning as the rest of the
dashboard modules).
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..logic import ChatManager

_chat_manager_ref: weakref.ref[ChatManager] | None = None


def register_chat_manager(chat_manager: ChatManager) -> None:
    """Register the live ChatManager (called from ``AICog.cog_load``)."""
    global _chat_manager_ref
    _chat_manager_ref = weakref.ref(chat_manager)


def unregister_chat_manager(chat_manager: ChatManager | None = None) -> None:
    """Drop the registration (called from ``AICog.cog_unload``).

    When an instance is passed, only clears the slot if that exact instance is
    the one registered — an overlapping reload (new cog's ``cog_load`` runs
    before the old cog's ``cog_unload`` finishes) must not wipe the fresh
    registration. Passing None clears unconditionally.
    """
    global _chat_manager_ref
    if chat_manager is not None and _chat_manager_ref is not None:
        current = _chat_manager_ref()
        if current is not None and current is not chat_manager:
            return
    _chat_manager_ref = None


def get_chat_manager() -> ChatManager | None:
    """Return the registered ChatManager, or None when absent / already GC'd."""
    if _chat_manager_ref is None:
        return None
    return _chat_manager_ref()
