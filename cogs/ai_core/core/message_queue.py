"""
Message Queue Module
Handles message queue management for handling multiple concurrent messages.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..data.constants import LOCK_TIMEOUT, MAX_CHANNELS, MAX_PENDING_PER_CHANNEL

logger = logging.getLogger(__name__)

# Upper bound on how many attachments survive a multi-message merge. A rapid
# burst can queue up to MAX_PENDING_PER_CHANNEL messages, each with several
# images; without a cap the merged turn could ship dozens of images into one
# vision request. 10 matches Discord's per-message attachment limit and is
# already generous for a single model call.
_MAX_MERGED_ATTACHMENTS = 10


def _lock_in_use(lock: asyncio.Lock | None) -> bool:
    """True if the lock is held OR has coroutines queued waiting on it.

    ``locked()`` alone is insufficient for safe eviction: right after a holder
    calls ``release()`` the lock reports ``locked() == False`` while a queued
    waiter is still pending resume. Evicting in that window pops the lock and
    lets the next caller create a brand-new one for the same channel, so two
    ``process_chat`` turns run concurrently — the exact thing the per-channel
    lock exists to prevent. ``_waiters`` is a private CPython detail; guard
    with getattr so a future asyncio change degrades to the old behaviour
    rather than crashing.
    """
    if lock is None:
        return False
    return lock.locked() or bool(getattr(lock, "_waiters", None))


@dataclass
class PendingMessage:
    """Represents a pending message in the queue."""

    channel: Any  # discord.TextChannel
    user: Any  # discord.User
    message: str
    attachments: list[Any] | None = None
    output_channel: Any | None = None
    generate_response: bool = True
    user_message_id: int | None = None
    timestamp: float = field(default_factory=time.time)


class MessageQueue:
    """Manages message queues for channels."""

    def __init__(self) -> None:
        """Initialize the message queue manager."""
        self.pending_messages: dict[int, list[PendingMessage]] = {}
        self.cancel_flags: dict[int, bool] = {}
        self.processing_locks: dict[int, asyncio.Lock] = {}
        self._lock_times: dict[int, float] = {}
        self._queue_lock = threading.Lock()  # Unified lock for all dict access (sync + async)

    async def get_lock(self, channel_id: int) -> asyncio.Lock:
        """Get or create a lock for a channel (thread-safe).

        Args:
            channel_id: Channel ID

        Returns:
            asyncio.Lock for the channel
        """
        with self._queue_lock:
            if channel_id not in self.processing_locks:
                self.processing_locks[channel_id] = asyncio.Lock()
            return self.processing_locks[channel_id]

    def get_lock_sync(self, channel_id: int) -> asyncio.Lock:
        """Get or create a lock for a channel (sync entry returning an asyncio.Lock).

        Despite the ``_sync`` suffix, the returned lock is an
        ``asyncio.Lock`` and is only useful from coroutines — it must be
        ``await``-acquired on the same running loop. Calling this from a
        thread with no running loop creates a lock bound to no loop and
        the eventual ``await lock.acquire()`` will raise a confusing
        ``RuntimeError`` deep in the stack. Fail fast here instead.

        Args:
            channel_id: Channel ID

        Returns:
            asyncio.Lock for the channel
        """
        # Use the public API; `asyncio._get_running_loop` is a private
        # CPython internal that has no contract on alternative interpreters.
        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "get_lock_sync requires a running asyncio loop — the returned "
                "asyncio.Lock cannot be acquired from a thread without one."
            ) from exc
        with self._queue_lock:
            if channel_id not in self.processing_locks:
                self.processing_locks[channel_id] = asyncio.Lock()
            return self.processing_locks[channel_id]

    def is_locked(self, channel_id: int) -> bool:
        """Check if a channel is currently locked.

        Args:
            channel_id: Channel ID

        Returns:
            True if channel is locked
        """
        with self._queue_lock:
            lock = self.processing_locks.get(channel_id)
            # Read ``locked()`` inside the queue_lock so another thread can't
            # delete the lock between the dict lookup and the locked() probe.
            return lock.locked() if lock else False

    def queue_message(
        self,
        channel_id: int,
        channel: Any,
        user: Any,
        message: str,
        attachments: list[Any] | None = None,
        output_channel: Any | None = None,
        generate_response: bool = True,
        user_message_id: int | None = None,
    ) -> None:
        """Add a message to the pending queue.

        Args:
            channel_id: Channel ID
            channel: Discord channel
            user: Discord user
            message: Message content
            attachments: List of attachments
            output_channel: Output channel (if different)
            generate_response: Whether to generate a response
            user_message_id: User message ID
        """
        with self._queue_lock:
            # Enforce max channels limit
            if channel_id not in self.pending_messages:
                if len(self.pending_messages) >= MAX_CHANNELS:
                    # Build candidate list excluding channels whose
                    # processing_lock is currently held — evicting a locked
                    # channel would orphan the lock held by the in-flight
                    # processor (a fresh lock would be created later for the
                    # same channel id, breaking mutual exclusion). If
                    # nothing is evictable, refuse the new channel rather
                    # than corrupt state.
                    candidates = [
                        cid
                        for cid in self.pending_messages
                        if not _lock_in_use(self.processing_locks.get(cid))
                    ]
                    if not candidates:
                        logger.warning(
                            "🧹 Message queue at limit (%d) but every channel "
                            "is currently locked — refusing new channel %s",
                            MAX_CHANNELS,
                            channel_id,
                        )
                        return

                    def _evict_key(cid: int) -> tuple[int, float, float]:
                        msgs = self.pending_messages[cid]
                        return (
                            0 if not msgs else 1,  # empty first
                            msgs[0].timestamp if msgs else 0.0,
                            # tie-breaker: among empty-pending channels (which
                            # all share timestamp 0.0) evict the genuinely
                            # least-recently-active one by last lock time.
                            self._lock_times.get(cid, 0.0),
                        )

                    oldest_channel = min(candidates, key=_evict_key)
                    del self.pending_messages[oldest_channel]
                    self.cancel_flags.pop(oldest_channel, None)
                    # Safe to drop the lock since it wasn't held (we filtered
                    # locked channels out of the candidate set above).
                    self.processing_locks.pop(oldest_channel, None)
                    # Keep all four per-channel maps consistent (mirrors
                    # clear_channel) so no orphan _lock_times entry survives to
                    # trip cleanup_stale_locks' perpetual warning.
                    self._lock_times.pop(oldest_channel, None)
                    logger.warning(
                        "🧹 Message queue limit reached, evicted channel %s", oldest_channel
                    )
                self.pending_messages[channel_id] = []

            # Enforce max pending messages per channel
            if len(self.pending_messages[channel_id]) >= MAX_PENDING_PER_CHANNEL:
                # Remove oldest messages to make room
                self.pending_messages[channel_id] = self.pending_messages[channel_id][
                    -(MAX_PENDING_PER_CHANNEL - 1) :
                ]
                logger.warning(
                    "🧹 Pending messages limit reached for channel %s, trimmed queue",
                    channel_id,
                )

            pending_msg = PendingMessage(
                channel=channel,
                user=user,
                message=message,
                attachments=attachments,
                output_channel=output_channel,
                generate_response=generate_response,
                user_message_id=user_message_id,
            )
            self.pending_messages[channel_id].append(pending_msg)

    def signal_cancel(self, channel_id: int) -> None:
        """Signal to cancel current processing for a channel.

        Args:
            channel_id: Channel ID
        """
        with self._queue_lock:
            self.cancel_flags[channel_id] = True
        logger.info("📝 Signaling cancel for channel %s", channel_id)

    def reset_cancel(self, channel_id: int) -> None:
        """Reset the cancel flag for a channel.

        Args:
            channel_id: Channel ID
        """
        with self._queue_lock:
            self.cancel_flags[channel_id] = False

    def is_cancelled(self, channel_id: int) -> bool:
        """Check if processing is cancelled for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            True if cancelled
        """
        with self._queue_lock:
            return self.cancel_flags.get(channel_id, False)

    def has_pending(self, channel_id: int) -> bool:
        """Check if a channel has pending messages.

        Args:
            channel_id: Channel ID

        Returns:
            True if there are pending messages
        """
        with self._queue_lock:
            return bool(self.pending_messages.get(channel_id))

    def get_pending_count(self, channel_id: int) -> int:
        """Get the number of pending messages for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            Number of pending messages
        """
        with self._queue_lock:
            return len(self.pending_messages.get(channel_id, []))

    def pop_pending_messages(self, channel_id: int) -> list[PendingMessage]:
        """Get and clear pending messages for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            List of pending messages
        """
        with self._queue_lock:
            pending = self.pending_messages.get(channel_id, [])
            self.pending_messages[channel_id] = []
            # Only clear an existing cancel flag — pre-populating `False` for
            # channels that have never had one bloats the dict and changes
            # `is_cancelled()` semantics from "never seen" to "explicitly
            # not cancelled".
            self.cancel_flags.pop(channel_id, None)
            return pending

    def merge_pending_messages(self, channel_id: int) -> tuple[PendingMessage | None, str]:
        """Merge pending messages into a single message.

        Args:
            channel_id: Channel ID

        Returns:
            Tuple of (latest message data, combined message text)
        """
        pending = self.pop_pending_messages(channel_id)
        if not pending:
            return None, ""

        # Get the latest message
        latest_msg = pending[-1]

        # Merge all messages
        if len(pending) > 1:
            # Strip CR/LF from the display name so a crafted name can't forge a
            # line-based prompt-structure boundary in the merged body — mirrors
            # the single-message header path in logic.py process_chat
            # (user.display_name.replace("\n", " ").replace("\r", " ")).
            all_messages = [
                f"[{(getattr(msg.user, 'display_name', None) or getattr(msg.user, 'name', 'Unknown')).replace(chr(10), ' ').replace(chr(13), ' ')}]: {msg.message}"
                for msg in pending
            ]
            combined_message = "\n".join(all_messages)
            # Merge attachments from ALL pending messages onto the latest one.
            # The caller reads ``latest_msg.attachments``; without this union a
            # user who sent several images across rapid messages (while the
            # channel was locked) would silently lose every image except the
            # last message's. Cap the merged list so a 50-deep queue of
            # image-laden messages can't push an unbounded payload into the
            # vision request.
            merged_attachments: list[Any] = []
            for msg in pending:
                if msg.attachments:
                    merged_attachments.extend(msg.attachments)
            if merged_attachments:
                if len(merged_attachments) > _MAX_MERGED_ATTACHMENTS:
                    logger.info(
                        "📎 Capping merged attachments for channel %s: %d -> %d",
                        channel_id,
                        len(merged_attachments),
                        _MAX_MERGED_ATTACHMENTS,
                    )
                    merged_attachments = merged_attachments[:_MAX_MERGED_ATTACHMENTS]
                latest_msg.attachments = merged_attachments
            logger.info(
                "📝 Merged %d pending messages for channel %s",
                len(pending),
                channel_id,
            )
        else:
            combined_message = latest_msg.message

        return latest_msg, combined_message

    async def acquire_lock_with_timeout(
        self, channel_id: int, timeout: float = LOCK_TIMEOUT
    ) -> bool:
        """Acquire a lock with timeout.

        Args:
            channel_id: Channel ID
            timeout: Timeout in seconds

        Returns:
            True if lock was acquired
        """
        # Periodic cleanup of stale locks (every time we try to acquire)
        self.cleanup_stale_locks()

        lock = await self.get_lock(channel_id)

        # Direct lock acquisition with timeout.
        # CPython #42130 was fixed in Python 3.12+; no shield workaround needed.
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            with self._queue_lock:
                self._lock_times[channel_id] = time.time()
            return True
        except TimeoutError:
            logger.error(
                "⚠️ Lock acquisition timeout for channel %s (>%ss)",
                channel_id,
                timeout,
            )
            return False

    def release_lock(self, channel_id: int) -> None:
        """Release the lock for a channel.

        NOTE: asyncio.Lock has NO ownership concept — release() succeeds from
        any task, and the unlocked case is already guarded below. The except
        is pure defence against a concurrent release between our locked()
        check and the release() call; it does not (and cannot) enforce
        owner-only semantics.

        Args:
            channel_id: Channel ID
        """
        with self._queue_lock:
            lock = self.processing_locks.get(channel_id)
            self._lock_times.pop(channel_id, None)
        if lock is None or not lock.locked():
            return
        try:
            lock.release()
        except RuntimeError as exc:
            # Lock was already released concurrently (asyncio.Lock raises
            # RuntimeError only on releasing an UNLOCKED lock).
            logger.warning(
                "release_lock raced for channel %s (already released): %s",
                channel_id,
                exc,
            )

    def get_lock_time(self, channel_id: int) -> float | None:
        """Get the time a lock was acquired.

        Args:
            channel_id: Channel ID

        Returns:
            Lock acquisition time, or None if not locked
        """
        return self._lock_times.get(channel_id)

    def cleanup_stale_locks(self, max_age: float = 300.0) -> int:
        """Warn about locks that have been held too long. Does NOT release them.

        Despite the legacy ``cleanup_`` prefix, this method only emits a
        warning log line per stale lock and returns the count of stale
        locks observed. It does NOT mutate ``processing_locks`` or release
        anything, because the coroutine still holding the lock may simply
        be running slowly and force-releasing would let a second handler
        run concurrently with the first.

        Args:
            max_age: Maximum age in seconds before emitting a warning.

        Returns:
            Number of stale locks detected (not released).
        """
        now = time.time()
        with self._queue_lock:
            stale = [
                cid for cid, lock_time in self._lock_times.items() if now - lock_time > max_age
            ]
        for channel_id in stale:
            # Only log warning - do not force-release as the task may still be running
            logger.warning(
                "🔒 Lock for channel %s has been held for >%ss (may be slow processing)",
                channel_id,
                max_age,
            )
        return len(stale)

    def cleanup_unused_locks(self, inactive_threshold: float = 3600.0) -> int:
        """Clean up locks for channels that haven't been used recently.

        Removes lock objects for channels that:
        1. Are not currently locked
        2. Haven't had any pending messages for a while
        3. Don't have any lock time recorded

        Args:
            inactive_threshold: Time in seconds after which an unused lock can be cleaned

        Returns:
            Number of locks cleaned up
        """
        now = time.time()
        cleaned = 0

        with self._queue_lock:
            # Find channels with locks that are not in use
            for channel_id in list(self.processing_locks.keys()):
                lock = self.processing_locks.get(channel_id)
                if lock is None:
                    continue

                # Skip if lock is currently held OR has queued waiters. A lock
                # whose holder just called release() reads locked()==False
                # while a waiter is still pending resume — popping it then
                # hands the next caller a fresh Lock and two process_chat
                # turns run concurrently on one channel.
                if _lock_in_use(lock):
                    continue

                # Skip if channel has pending messages
                if self.pending_messages.get(channel_id):
                    continue

                # Skip if lock was recently used (has lock_time within threshold)
                lock_time = self._lock_times.get(channel_id)
                if lock_time and (now - lock_time) < inactive_threshold:
                    continue

                # Safe to remove this lock
                self.processing_locks.pop(channel_id, None)
                self._lock_times.pop(channel_id, None)
                self.cancel_flags.pop(channel_id, None)
                # Also drop the residual empty pending_messages entry. The
                # ``self.pending_messages.get(channel_id)`` skip above means only
                # empty/absent lists reach here, so nothing queued is lost — this
                # just stops the empty-list entry from lingering forever.
                self.pending_messages.pop(channel_id, None)
                cleaned += 1

        if cleaned > 0:
            logger.debug("🧹 Cleaned up %d unused channel locks", cleaned)
        return cleaned

    def clear_channel(self, channel_id: int) -> None:
        """Drop all per-channel state (pending messages, cancel flag,
        lock metadata, lock object) for ``channel_id`` atomically.

        Public surface for callers like the ``reset_ai`` command and
        the ``on_guild_channel_delete`` listener — previously those
        sites reached into ``self.pending_messages`` /
        ``self.cancel_flags`` / ``self._lock_times`` directly, which
        broke encapsulation and silently regressed if any of those
        attributes were ever renamed. Holds ``_queue_lock`` so the
        clear is atomic across all four maps.
        """
        with self._queue_lock:
            self.pending_messages.pop(channel_id, None)
            self.cancel_flags.pop(channel_id, None)
            self.processing_locks.pop(channel_id, None)
            self._lock_times.pop(channel_id, None)


# Module-level instance for easy access
message_queue = MessageQueue()
