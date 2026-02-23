"""
Tests for cogs.music.queue module.
"""


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
