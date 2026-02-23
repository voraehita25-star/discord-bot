"""Tests for conversation_branch module."""

import time


class TestConversationCheckpointDataclass:
    """Tests for ConversationCheckpoint dataclass."""

    def test_checkpoint_creation(self):
        """Test creating a checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationCheckpoint

        checkpoint = ConversationCheckpoint(
            checkpoint_id="cp_123_1000",
            channel_id=123,
            timestamp=1000.0,
            history_snapshot=[{"role": "user", "content": "test"}],
        )

        assert checkpoint.checkpoint_id == "cp_123_1000"
        assert checkpoint.channel_id == 123
        assert checkpoint.timestamp == 1000.0
        assert len(checkpoint.history_snapshot) == 1

    def test_checkpoint_to_dict(self):
        """Test checkpoint to_dict method."""
        from cogs.ai_core.memory.conversation_branch import ConversationCheckpoint

        checkpoint = ConversationCheckpoint(
            checkpoint_id="cp_123_1000",
            channel_id=123,
            timestamp=1000.0,
            history_snapshot=[{"role": "user", "content": "test"}],
            label="test checkpoint",
        )

        d = checkpoint.to_dict()

        assert d["checkpoint_id"] == "cp_123_1000"
        assert d["channel_id"] == 123
        assert d["history_length"] == 1
        assert d["label"] == "test checkpoint"

    def test_checkpoint_default_values(self):
        """Test checkpoint default values."""
        from cogs.ai_core.memory.conversation_branch import ConversationCheckpoint

        checkpoint = ConversationCheckpoint(
            checkpoint_id="cp_123",
            channel_id=123,
            timestamp=1000.0,
            history_snapshot=[],
        )

        assert checkpoint.metadata == {}
        assert checkpoint.label is None


class TestConversationBranchDataclass:
    """Tests for ConversationBranch dataclass."""

    def test_branch_creation(self):
        """Test creating a branch."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranch

        branch = ConversationBranch(
            branch_id="branch_1",
            parent_checkpoint_id="cp_123",
            channel_id=123,
            created_at=1000.0,
        )

        assert branch.branch_id == "branch_1"
        assert branch.parent_checkpoint_id == "cp_123"
        assert branch.channel_id == 123
        assert branch.created_at == 1000.0

    def test_branch_default_values(self):
        """Test branch default values."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranch

        branch = ConversationBranch(
            branch_id="branch_1",
            parent_checkpoint_id="cp_123",
            channel_id=123,
            created_at=1000.0,
        )

        assert branch.history == []
        assert branch.label is None


class TestConversationBranchManager:
    """Tests for ConversationBranchManager class."""

    def test_manager_creation(self):
        """Test creating branch manager."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        assert manager._checkpoints is not None
        assert manager._branches is not None

    def test_create_checkpoint(self):
        """Test creating a checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        history = [{"role": "user", "content": "hello"}]

        checkpoint = manager.create_checkpoint(123, history, label="test")

        assert checkpoint is not None
        assert checkpoint.channel_id == 123
        assert checkpoint.label == "test"
        assert len(checkpoint.history_snapshot) == 1

    def test_create_checkpoint_with_metadata(self):
        """Test creating checkpoint with metadata."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        history = [{"role": "user", "content": "hello"}]
        metadata = {"custom": "data"}

        checkpoint = manager.create_checkpoint(123, history, metadata=metadata)

        assert checkpoint.metadata == {"custom": "data"}

    def test_get_checkpoints_empty(self):
        """Test getting checkpoints for channel with none."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        checkpoints = manager.get_checkpoints(999)

        assert checkpoints == []

    def test_get_checkpoints_with_data(self):
        """Test getting checkpoints with data."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        manager.create_checkpoint(123, [{"role": "user", "content": "1"}])
        manager.create_checkpoint(123, [{"role": "user", "content": "2"}])

        checkpoints = manager.get_checkpoints(123)

        assert len(checkpoints) == 2

    def test_get_checkpoint_most_recent(self):
        """Test getting most recent checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        manager.create_checkpoint(123, [{"role": "user", "content": "1"}], label="first")
        manager.create_checkpoint(123, [{"role": "user", "content": "2"}], label="second")

        checkpoint = manager.get_checkpoint(123)

        assert checkpoint.label == "second"

    def test_get_checkpoint_empty_channel(self):
        """Test getting checkpoint from empty channel."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        checkpoint = manager.get_checkpoint(999)

        assert checkpoint is None

    def test_maybe_auto_checkpoint_below_threshold(self):
        """Test auto checkpoint below threshold."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        # First few messages shouldn't create checkpoint
        result = manager.maybe_auto_checkpoint(123, [{"role": "user", "content": "1"}])

        assert result is None

    def test_maybe_auto_checkpoint_at_threshold(self):
        """Test auto checkpoint at threshold."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        # Simulate messages up to threshold
        for i in range(9):
            manager.maybe_auto_checkpoint(123, [{"role": "user", "content": str(i)}])

        # This one should trigger checkpoint
        result = manager.maybe_auto_checkpoint(123, [{"role": "user", "content": "10"}])

        assert result is not None
        assert "Auto-checkpoint" in result.label

    def test_max_checkpoints_enforced(self):
        """Test max checkpoints limit is enforced."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        # Create more than max
        for i in range(25):
            manager.create_checkpoint(123, [{"role": "user", "content": str(i)}])

        checkpoints = manager.get_checkpoints(123)

        assert len(checkpoints) <= ConversationBranchManager.MAX_CHECKPOINTS_PER_CHANNEL


class TestUndoToCheckpoint:
    """Tests for undo_to_checkpoint method."""

    def test_undo_to_most_recent(self):
        """Test undoing to most recent checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        history = [{"role": "user", "content": "original"}]
        manager.create_checkpoint(123, history)

        restored = manager.undo_to_checkpoint(123)

        assert restored is not None
        assert len(restored) == 1
        assert restored[0]["content"] == "original"

    def test_undo_to_specific_checkpoint(self):
        """Test undoing to a specific checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp1 = manager.create_checkpoint(123, [{"role": "user", "content": "first"}])
        manager.create_checkpoint(123, [{"role": "user", "content": "second"}])

        restored = manager.undo_to_checkpoint(123, cp1.checkpoint_id)

        assert restored[0]["content"] == "first"

    def test_undo_no_checkpoint(self):
        """Test undoing with no checkpoints."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        restored = manager.undo_to_checkpoint(999)

        assert restored is None


class TestBranchOperations:
    """Tests for branch operations."""

    def test_create_branch(self):
        """Test creating a branch from checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])

        branch = manager.create_branch(123, cp.checkpoint_id, label="test branch")

        assert branch is not None
        assert branch.label == "test branch"
        assert len(branch.history) == 1

    def test_create_branch_invalid_checkpoint(self):
        """Test creating branch from invalid checkpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        branch = manager.create_branch(123, "invalid_checkpoint")

        assert branch is None

    def test_switch_branch(self):
        """Test switching to a branch."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        branch = manager.create_branch(123, cp.checkpoint_id)

        history = manager.switch_branch(123, branch.branch_id)

        assert history is not None
        assert manager.get_active_branch(123) == branch.branch_id

    def test_switch_branch_to_main(self):
        """Test switching back to main timeline."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        branch = manager.create_branch(123, cp.checkpoint_id)
        manager.switch_branch(123, branch.branch_id)

        result = manager.switch_branch(123, None)

        assert result is None
        assert manager.get_active_branch(123) is None

    def test_switch_branch_invalid(self):
        """Test switching to invalid branch."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        result = manager.switch_branch(123, "invalid_branch")

        assert result is None

    def test_list_branches_empty(self):
        """Test listing branches with none."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        branches = manager.list_branches(123)

        assert branches == []

    def test_list_branches_with_data(self):
        """Test listing branches."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        manager.create_branch(123, cp.checkpoint_id, label="branch1")
        time.sleep(0.01)  # Ensure different timestamp
        manager.create_branch(123, cp.checkpoint_id, label="branch2")

        branches = manager.list_branches(123)

        assert len(branches) == 2

    def test_update_branch_history(self):
        """Test updating branch history."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        branch = manager.create_branch(123, cp.checkpoint_id)
        manager.switch_branch(123, branch.branch_id)

        new_history = [{"role": "user", "content": "updated"}]
        manager.update_branch_history(123, new_history)

        updated_branch = manager._branches[branch.branch_id]
        assert updated_branch.history[0]["content"] == "updated"

    def test_delete_branch(self):
        """Test deleting a branch."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        branch = manager.create_branch(123, cp.checkpoint_id)

        result = manager.delete_branch(branch.branch_id)

        assert result is True
        assert branch.branch_id not in manager._branches

    def test_delete_branch_clears_active(self):
        """Test deleting active branch clears it."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        branch = manager.create_branch(123, cp.checkpoint_id)
        manager.switch_branch(123, branch.branch_id)

        manager.delete_branch(branch.branch_id)

        assert manager.get_active_branch(123) is None

    def test_delete_branch_invalid(self):
        """Test deleting invalid branch."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        result = manager.delete_branch("invalid")

        assert result is False


class TestClearAndStats:
    """Tests for clear_channel and get_stats."""

    def test_clear_channel(self):
        """Test clearing channel data."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        manager.create_branch(123, cp.checkpoint_id)

        manager.clear_channel(123)

        assert manager.get_checkpoints(123) == []
        assert manager.list_branches(123) == []

    def test_get_stats_empty(self):
        """Test getting stats with no data."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()

        stats = manager.get_stats()

        assert stats["total_checkpoints"] == 0
        assert stats["total_branches"] == 0
        assert stats["active_branches"] == 0

    def test_get_stats_with_data(self):
        """Test getting stats with data."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        manager = ConversationBranchManager()
        cp = manager.create_checkpoint(123, [{"role": "user", "content": "test"}])
        branch = manager.create_branch(123, cp.checkpoint_id)
        manager.switch_branch(123, branch.branch_id)

        stats = manager.get_stats()

        assert stats["total_checkpoints"] >= 1
        assert stats["total_branches"] >= 1
        assert stats["active_branches"] >= 1


class TestModuleImports:
    """Tests for module imports."""

    def test_import_conversation_checkpoint(self):
        """Test importing ConversationCheckpoint."""
        from cogs.ai_core.memory.conversation_branch import ConversationCheckpoint

        assert ConversationCheckpoint is not None

    def test_import_conversation_branch(self):
        """Test importing ConversationBranch."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranch

        assert ConversationBranch is not None

    def test_import_conversation_branch_manager(self):
        """Test importing ConversationBranchManager."""
        from cogs.ai_core.memory.conversation_branch import ConversationBranchManager

        assert ConversationBranchManager is not None

    def test_global_branch_manager(self):
        """Test global branch_manager instance."""
        from cogs.ai_core.memory.conversation_branch import branch_manager

        assert branch_manager is not None
