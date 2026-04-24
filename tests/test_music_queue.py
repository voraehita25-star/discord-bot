"""Unit tests for Music Queue Manager."""


from cogs.music.queue import QueueManager


class TestQueueManager:
    """Tests for QueueManager class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = QueueManager()
        self.guild_id = 123456789

    def test_get_queue_creates_empty(self):
        """Test that get_queue creates an empty queue for new guild."""
        queue = self.manager.get_queue(self.guild_id)
        assert len(queue) == 0
        assert self.guild_id in self.manager.queues

    def test_add_to_queue(self):
        """Test adding tracks to queue."""
        track1 = {"title": "Song 1", "url": "http://example.com/1"}
        track2 = {"title": "Song 2", "url": "http://example.com/2"}

        pos1 = self.manager.add_to_queue(self.guild_id, track1)
        pos2 = self.manager.add_to_queue(self.guild_id, track2)

        assert pos1 == 1
        assert pos2 == 2
        assert len(self.manager.get_queue(self.guild_id)) == 2

    def test_get_next(self):
        """Test getting next track from queue."""
        track1 = {"title": "Song 1"}
        track2 = {"title": "Song 2"}
        self.manager.add_to_queue(self.guild_id, track1)
        self.manager.add_to_queue(self.guild_id, track2)

        next_track = self.manager.get_next(self.guild_id)
        assert next_track == track1
        assert len(self.manager.get_queue(self.guild_id)) == 1

    def test_get_next_empty_queue(self):
        """Test get_next returns None for empty queue."""
        assert self.manager.get_next(self.guild_id) is None

    def test_peek_next(self):
        """Test peeking at next track without removing."""
        track = {"title": "Song 1"}
        self.manager.add_to_queue(self.guild_id, track)

        peeked = self.manager.peek_next(self.guild_id)
        assert peeked == track
        assert len(self.manager.get_queue(self.guild_id)) == 1  # Still there

    def test_peek_next_empty(self):
        """Test peek_next returns None for empty queue."""
        assert self.manager.peek_next(self.guild_id) is None

    def test_clear_queue(self):
        """Test clearing the queue."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        self.manager.add_to_queue(self.guild_id, {"title": "Song 2"})

        count = self.manager.clear_queue(self.guild_id)
        assert count == 2
        assert len(self.manager.get_queue(self.guild_id)) == 0

    def test_shuffle_queue(self):
        """Test shuffling the queue."""
        for i in range(10):
            self.manager.add_to_queue(self.guild_id, {"title": f"Song {i}"})

        original = self.manager.get_queue(self.guild_id).copy()
        result = self.manager.shuffle_queue(self.guild_id)

        assert result is True
        assert len(self.manager.get_queue(self.guild_id)) == 10
        # Highly unlikely to be in same order
        assert self.manager.get_queue(self.guild_id) != original or len(original) < 2

    def test_shuffle_queue_too_small(self):
        """Test shuffle returns False for queue with < 2 items."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        assert self.manager.shuffle_queue(self.guild_id) is False

    def test_remove_track(self):
        """Test removing a track by position."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        self.manager.add_to_queue(self.guild_id, {"title": "Song 2"})
        self.manager.add_to_queue(self.guild_id, {"title": "Song 3"})

        removed = self.manager.remove_track(self.guild_id, 2)  # 1-indexed
        assert removed["title"] == "Song 2"
        assert len(self.manager.get_queue(self.guild_id)) == 2

    def test_remove_track_invalid_position(self):
        """Test remove_track with invalid position."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})

        assert self.manager.remove_track(self.guild_id, 0) is None
        assert self.manager.remove_track(self.guild_id, 5) is None

    def test_loop_toggle(self):
        """Test loop toggle functionality."""
        assert self.manager.is_looping(self.guild_id) is False

        result = self.manager.toggle_loop(self.guild_id)
        assert result is True
        assert self.manager.is_looping(self.guild_id) is True

        result = self.manager.toggle_loop(self.guild_id)
        assert result is False

    def test_volume_operations(self):
        """Test volume get/set operations."""
        assert self.manager.get_volume(self.guild_id) == 0.5  # Default

        self.manager.set_volume(self.guild_id, 1.0)
        assert self.manager.get_volume(self.guild_id) == 1.0

        # Test clamping
        self.manager.set_volume(self.guild_id, 5.0)
        assert self.manager.get_volume(self.guild_id) == 2.0

        self.manager.set_volume(self.guild_id, -1.0)
        assert self.manager.get_volume(self.guild_id) == 0.0

    def test_247_mode_toggle(self):
        """Test 24/7 mode toggle."""
        assert self.manager.is_247_mode(self.guild_id) is False

        result = self.manager.toggle_247_mode(self.guild_id)
        assert result is True
        assert self.manager.is_247_mode(self.guild_id) is True

    def test_cleanup_guild(self):
        """Test cleanup preserves 24/7 mode."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        self.manager.toggle_loop(self.guild_id)
        self.manager.toggle_247_mode(self.guild_id)
        self.manager.current_track[self.guild_id] = {"title": "Current"}

        self.manager.cleanup_guild(self.guild_id)

        assert self.guild_id not in self.manager.queues
        assert self.guild_id not in self.manager.loops
        assert self.guild_id not in self.manager.current_track
        # 24/7 mode should persist
        assert self.manager.is_247_mode(self.guild_id) is True


class TestQueuePersistence:
    """Tests for queue persistence (JSON fallback)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = QueueManager()
        self.guild_id = 987654321

    def test_save_queue_json_fallback(self):
        """Test JSON save as fallback when database not available."""

        self.manager.add_to_queue(self.guild_id, {"title": "Test Song"})
        self.manager.set_volume(self.guild_id, 0.8)

        # This test just ensures no exceptions are raised
        # Actual file operations would require mocking
        self.manager._save_queue_json(self.guild_id)


# ======================================================================
# Merged from test_music_queue_extended.py
# ======================================================================

class TestQueueManagerInit:
    """Tests for QueueManager initialization."""

    def test_init_empty_queues(self):
        """Test initialization creates empty queues dict."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.queues == {}

    def test_init_empty_loops(self):
        """Test initialization creates empty loops dict."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.loops == {}

    def test_init_empty_volumes(self):
        """Test initialization creates empty volumes dict."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.volumes == {}


class TestGetQueue:
    """Tests for QueueManager.get_queue method."""

    def test_get_queue_creates_new(self):
        """Test get_queue creates new queue for guild."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        queue = manager.get_queue(123456)

        assert len(queue) == 0
        assert 123456 in manager.queues

    def test_get_queue_returns_existing(self):
        """Test get_queue returns existing queue."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.queues[123456] = [{"title": "Test"}]

        queue = manager.get_queue(123456)
        assert len(queue) == 1


class TestAddToQueue:
    """Tests for QueueManager.add_to_queue method."""

    def test_add_single_track(self):
        """Test adding single track."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        track = {"title": "Test Song", "url": "http://example.com"}

        position = manager.add_to_queue(123456, track)

        assert position == 1
        assert len(manager.get_queue(123456)) == 1

    def test_add_multiple_tracks(self):
        """Test adding multiple tracks returns correct positions."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()

        pos1 = manager.add_to_queue(123456, {"title": "Song 1"})
        pos2 = manager.add_to_queue(123456, {"title": "Song 2"})
        pos3 = manager.add_to_queue(123456, {"title": "Song 3"})

        assert pos1 == 1
        assert pos2 == 2
        assert pos3 == 3


class TestGetNext:
    """Tests for QueueManager.get_next method."""

    def test_get_next_empty_queue(self):
        """Test get_next returns None for empty queue."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        result = manager.get_next(123456)

        assert result is None

    def test_get_next_removes_track(self):
        """Test get_next removes and returns track."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})
        manager.add_to_queue(123456, {"title": "Song 2"})

        result = manager.get_next(123456)

        assert result["title"] == "Song 1"
        assert len(manager.get_queue(123456)) == 1


class TestPeekNext:
    """Tests for QueueManager.peek_next method."""

    def test_peek_next_empty_queue(self):
        """Test peek_next returns None for empty queue."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        result = manager.peek_next(123456)

        assert result is None

    def test_peek_next_does_not_remove(self):
        """Test peek_next doesn't remove track."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        result = manager.peek_next(123456)

        assert result["title"] == "Song 1"
        assert len(manager.get_queue(123456)) == 1


class TestClearQueue:
    """Tests for QueueManager.clear_queue method."""

    def test_clear_empty_queue(self):
        """Test clearing empty queue returns 0."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        count = manager.clear_queue(123456)

        assert count == 0

    def test_clear_queue_returns_count(self):
        """Test clearing queue returns count."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})
        manager.add_to_queue(123456, {"title": "Song 2"})
        manager.add_to_queue(123456, {"title": "Song 3"})

        count = manager.clear_queue(123456)

        assert count == 3
        assert len(manager.get_queue(123456)) == 0


class TestShuffleQueue:
    """Tests for QueueManager.shuffle_queue method."""

    def test_shuffle_empty_queue(self):
        """Test shuffling empty queue returns False."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        result = manager.shuffle_queue(123456)

        assert result is False

    def test_shuffle_single_track(self):
        """Test shuffling single track returns False."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        result = manager.shuffle_queue(123456)

        assert result is False

    def test_shuffle_multiple_tracks(self):
        """Test shuffling multiple tracks returns True."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        for i in range(10):
            manager.add_to_queue(123456, {"title": f"Song {i}"})

        result = manager.shuffle_queue(123456)

        assert result is True


class TestRemoveTrack:
    """Tests for QueueManager.remove_track method."""

    def test_remove_valid_position(self):
        """Test removing track at valid position."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})
        manager.add_to_queue(123456, {"title": "Song 2"})
        manager.add_to_queue(123456, {"title": "Song 3"})

        removed = manager.remove_track(123456, 2)  # 1-indexed

        assert removed["title"] == "Song 2"
        assert len(manager.get_queue(123456)) == 2

    def test_remove_invalid_position_zero(self):
        """Test removing at position 0 returns None."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        removed = manager.remove_track(123456, 0)

        assert removed is None

    def test_remove_invalid_position_too_high(self):
        """Test removing at too high position returns None."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        removed = manager.remove_track(123456, 99)

        assert removed is None


class TestLooping:
    """Tests for QueueManager looping methods."""

    def test_is_looping_default_false(self):
        """Test is_looping returns False by default."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.is_looping(123456) is False

    def test_toggle_loop(self):
        """Test toggle_loop switches state."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()

        result1 = manager.toggle_loop(123456)
        assert result1 is True
        assert manager.is_looping(123456) is True

        result2 = manager.toggle_loop(123456)
        assert result2 is False
        assert manager.is_looping(123456) is False
