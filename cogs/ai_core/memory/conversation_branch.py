"""
Conversation Branching Module
Provides undo and branch-and-continue functionality for AI chat sessions.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationCheckpoint:
    """A snapshot of conversation state at a point in time."""

    checkpoint_id: str
    channel_id: int
    timestamp: float
    history_snapshot: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "channel_id": self.channel_id,
            "timestamp": self.timestamp,
            "history_length": len(self.history_snapshot),
            "label": self.label,
            "metadata": self.metadata,
        }


@dataclass
class ConversationBranch:
    """A branch from a checkpoint with its own history."""

    branch_id: str
    parent_checkpoint_id: str
    channel_id: int
    created_at: float
    history: list[dict[str, Any]] = field(default_factory=list)
    label: str | None = None


class ConversationBranchManager:
    """
    Manages conversation checkpoints and branches.

    Features:
    - Create checkpoints at any point in conversation
    - Undo to previous checkpoints
    - Create branches from checkpoints
    - Switch between branches
    - Automatic checkpoint creation before significant changes
    """

    MAX_CHECKPOINTS_PER_CHANNEL = 20
    AUTO_CHECKPOINT_INTERVAL = 10  # messages

    def __init__(self):
        self._checkpoints: dict[int, list[ConversationCheckpoint]] = defaultdict(list)
        self._branches: dict[str, ConversationBranch] = {}
        self._active_branch: dict[int, str | None] = {}  # channel_id -> branch_id
        self._message_counts: dict[int, int] = defaultdict(int)
        self.logger = logging.getLogger("ConversationBranch")

    def create_checkpoint(
        self,
        channel_id: int,
        history: list[dict[str, Any]],
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationCheckpoint:
        """
        Create a checkpoint of the current conversation state.

        Args:
            channel_id: Discord channel ID
            history: Current conversation history
            label: Optional human-readable label
            metadata: Optional additional metadata

        Returns:
            Created checkpoint
        """
        checkpoint_id = f"cp_{channel_id}_{int(time.time() * 1000)}"

        checkpoint = ConversationCheckpoint(
            checkpoint_id=checkpoint_id,
            channel_id=channel_id,
            timestamp=time.time(),
            history_snapshot=[msg.copy() for msg in history],
            metadata=metadata or {},
            label=label,
        )

        # Add to channel's checkpoints
        self._checkpoints[channel_id].append(checkpoint)

        # Enforce max checkpoints
        while len(self._checkpoints[channel_id]) > self.MAX_CHECKPOINTS_PER_CHANNEL:
            removed = self._checkpoints[channel_id].pop(0)
            self.logger.debug("Removed old checkpoint: %s", removed.checkpoint_id)

        self.logger.info(
            "📌 Checkpoint created: %s (history: %d messages)", checkpoint_id, len(history)
        )

        return checkpoint

    def maybe_auto_checkpoint(
        self, channel_id: int, history: list[dict[str, Any]]
    ) -> ConversationCheckpoint | None:
        """
        Create an automatic checkpoint if enough messages have passed.

        Args:
            channel_id: Discord channel ID
            history: Current conversation history

        Returns:
            Created checkpoint if one was made, None otherwise
        """
        self._message_counts[channel_id] += 1

        if self._message_counts[channel_id] >= self.AUTO_CHECKPOINT_INTERVAL:
            self._message_counts[channel_id] = 0
            return self.create_checkpoint(
                channel_id, history, label=f"Auto-checkpoint at {len(history)} messages"
            )

        return None

    def get_checkpoints(self, channel_id: int) -> list[ConversationCheckpoint]:
        """Get all checkpoints for a channel."""
        return list(self._checkpoints.get(channel_id, []))

    def get_checkpoint(
        self, channel_id: int, checkpoint_id: str | None = None
    ) -> ConversationCheckpoint | None:
        """
        Get a specific checkpoint or the most recent one.

        Args:
            channel_id: Discord channel ID
            checkpoint_id: Specific checkpoint ID (None for most recent)

        Returns:
            Checkpoint if found, None otherwise
        """
        checkpoints = self._checkpoints.get(channel_id, [])

        if not checkpoints:
            return None

        if checkpoint_id is None:
            return checkpoints[-1]  # Most recent

        for cp in checkpoints:
            if cp.checkpoint_id == checkpoint_id:
                return cp

        return None

    def undo_to_checkpoint(
        self, channel_id: int, checkpoint_id: str | None = None
    ) -> list[dict[str, Any]] | None:
        """
        Restore conversation to a checkpoint state.

        Args:
            channel_id: Discord channel ID
            checkpoint_id: Specific checkpoint (None for most recent)

        Returns:
            Restored history if successful, None otherwise
        """
        checkpoint = self.get_checkpoint(channel_id, checkpoint_id)

        if checkpoint is None:
            self.logger.warning("No checkpoint found for channel %d", channel_id)
            return None

        restored = [msg.copy() for msg in checkpoint.history_snapshot]

        self.logger.info(
            "⏪ Restored to checkpoint: %s (%d messages)", checkpoint.checkpoint_id, len(restored)
        )

        return restored

    def create_branch(
        self, channel_id: int, checkpoint_id: str, label: str | None = None
    ) -> ConversationBranch | None:
        """
        Create a new branch from a checkpoint.

        Args:
            channel_id: Discord channel ID
            checkpoint_id: Checkpoint to branch from
            label: Optional label for the branch

        Returns:
            Created branch if successful, None otherwise
        """
        checkpoint = self.get_checkpoint(channel_id, checkpoint_id)

        if checkpoint is None:
            return None

        branch_id = f"br_{channel_id}_{int(time.time() * 1000)}"

        branch = ConversationBranch(
            branch_id=branch_id,
            parent_checkpoint_id=checkpoint_id,
            channel_id=channel_id,
            created_at=time.time(),
            history=[msg.copy() for msg in checkpoint.history_snapshot],
            label=label,
        )

        self._branches[branch_id] = branch

        self.logger.info("🌿 Branch created: %s from checkpoint %s", branch_id, checkpoint_id)

        return branch

    def switch_branch(
        self, channel_id: int, branch_id: str | None = None
    ) -> list[dict[str, Any]] | None:
        """
        Switch to a different branch (or main timeline).

        Args:
            channel_id: Discord channel ID
            branch_id: Branch to switch to (None for main timeline)

        Returns:
            History of the branch if successful, None otherwise
        """
        if branch_id is None:
            # Switch back to main
            self._active_branch[channel_id] = None
            self.logger.info("🌿 Switched to main timeline for channel %d", channel_id)
            return None  # Caller should use main history

        branch = self._branches.get(branch_id)

        if branch is None or branch.channel_id != channel_id:
            self.logger.warning("Branch not found: %s", branch_id)
            return None

        self._active_branch[channel_id] = branch_id

        self.logger.info("🌿 Switched to branch: %s (%d messages)", branch_id, len(branch.history))

        return [msg.copy() for msg in branch.history]

    def get_active_branch(self, channel_id: int) -> str | None:
        """Get the active branch ID for a channel (None = main timeline)."""
        return self._active_branch.get(channel_id)

    def list_branches(self, channel_id: int) -> list[ConversationBranch]:
        """List all branches for a channel."""
        return [branch for branch in self._branches.values() if branch.channel_id == channel_id]

    def update_branch_history(self, channel_id: int, history: list[dict[str, Any]]) -> None:
        """
        Update the history of the active branch.

        Args:
            channel_id: Discord channel ID
            history: Updated history
        """
        branch_id = self._active_branch.get(channel_id)

        if branch_id and branch_id in self._branches:
            self._branches[branch_id].history = [msg.copy() for msg in history]

    def delete_branch(self, branch_id: str) -> bool:
        """Delete a branch."""
        if branch_id in self._branches:
            branch = self._branches.pop(branch_id)

            # Clear active branch if it was this one
            if self._active_branch.get(branch.channel_id) == branch_id:
                self._active_branch[branch.channel_id] = None

            self.logger.info("🗑️ Deleted branch: %s", branch_id)
            return True

        return False

    def clear_channel(self, channel_id: int) -> None:
        """Clear all checkpoints and branches for a channel."""
        self._checkpoints[channel_id].clear()
        self._active_branch.pop(channel_id, None)
        self._message_counts.pop(channel_id, None)

        # Remove branches for this channel
        to_remove = [
            branch_id
            for branch_id, branch in self._branches.items()
            if branch.channel_id == channel_id
        ]
        for branch_id in to_remove:
            del self._branches[branch_id]

        self.logger.info("🧹 Cleared branching data for channel %d", channel_id)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about branching system."""
        total_checkpoints = sum(len(cps) for cps in self._checkpoints.values())
        total_branches = len(self._branches)
        channels_with_checkpoints = len(self._checkpoints)

        return {
            "total_checkpoints": total_checkpoints,
            "total_branches": total_branches,
            "channels_tracked": channels_with_checkpoints,
            "active_branches": sum(1 for b in self._active_branch.values() if b),
        }


# Global instance
branch_manager = ConversationBranchManager()
