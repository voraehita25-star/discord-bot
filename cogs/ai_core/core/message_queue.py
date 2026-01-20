"""
Message Queue Module
Handles message queue management for handling multiple concurrent messages.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..data.constants import LOCK_TIMEOUT

if TYPE_CHECKING:
    pass


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

    def get_lock(self, channel_id: int) -> asyncio.Lock:
        """Get or create a lock for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            asyncio.Lock for the channel
        """
        return self.processing_locks.setdefault(channel_id, asyncio.Lock())

    def is_locked(self, channel_id: int) -> bool:
        """Check if a channel is currently locked.

        Args:
            channel_id: Channel ID

        Returns:
            True if channel is locked
        """
        lock = self.processing_locks.get(channel_id)
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
        if channel_id not in self.pending_messages:
            self.pending_messages[channel_id] = []

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
        self.cancel_flags[channel_id] = True
        logging.info("📝 Signaling cancel for channel %s", channel_id)

    def reset_cancel(self, channel_id: int) -> None:
        """Reset the cancel flag for a channel.

        Args:
            channel_id: Channel ID
        """
        self.cancel_flags[channel_id] = False

    def is_cancelled(self, channel_id: int) -> bool:
        """Check if processing is cancelled for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            True if cancelled
        """
        return self.cancel_flags.get(channel_id, False)

    def has_pending(self, channel_id: int) -> bool:
        """Check if a channel has pending messages.

        Args:
            channel_id: Channel ID

        Returns:
            True if there are pending messages
        """
        return bool(self.pending_messages.get(channel_id))

    def get_pending_count(self, channel_id: int) -> int:
        """Get the number of pending messages for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            Number of pending messages
        """
        return len(self.pending_messages.get(channel_id, []))

    def pop_pending_messages(self, channel_id: int) -> list[PendingMessage]:
        """Get and clear pending messages for a channel.

        Args:
            channel_id: Channel ID

        Returns:
            List of pending messages
        """
        pending = self.pending_messages.get(channel_id, [])
        self.pending_messages[channel_id] = []
        self.cancel_flags[channel_id] = False
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
            all_messages = [
                f"[{msg.user.display_name}]: {msg.message}" for msg in pending
            ]
            combined_message = "\n".join(all_messages)
            logging.info(
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
        lock = self.get_lock(channel_id)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            self._lock_times[channel_id] = time.time()
            return True
        except asyncio.TimeoutError:
            logging.error(
                "⚠️ Lock acquisition timeout for channel %s (>%ss)",
                channel_id,
                timeout,
            )
            return False

    def release_lock(self, channel_id: int) -> None:
        """Release the lock for a channel.

        Args:
            channel_id: Channel ID
        """
        lock = self.processing_locks.get(channel_id)
        if lock and lock.locked():
            lock.release()
        self._lock_times.pop(channel_id, None)

    def get_lock_time(self, channel_id: int) -> float | None:
        """Get the time a lock was acquired.

        Args:
            channel_id: Channel ID

        Returns:
            Lock acquisition time, or None if not locked
        """
        return self._lock_times.get(channel_id)

    def cleanup_stale_locks(self, max_age: float = 300.0) -> int:
        """Clean up locks that have been held too long.

        Args:
            max_age: Maximum age in seconds

        Returns:
            Number of locks cleaned up
        """
        now = time.time()
        stale = [
            cid
            for cid, lock_time in self._lock_times.items()
            if now - lock_time > max_age
        ]
        for channel_id in stale:
            logging.warning("🔓 Force-releasing stale lock for channel %s", channel_id)
            self.release_lock(channel_id)
        return len(stale)


# Module-level instance for easy access
message_queue = MessageQueue()
