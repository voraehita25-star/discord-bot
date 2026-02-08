"""
Tests for utils.monitoring.token_tracker module.
"""




class TestTokenUsageDataclass:
    """Tests for TokenUsage dataclass."""

    def test_create_token_usage(self):
        """Test creating TokenUsage instance."""
        from utils.monitoring.token_tracker import TokenUsage

        usage = TokenUsage()

        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.request_count == 0

    def test_token_usage_with_values(self):
        """Test TokenUsage with initial values."""
        from utils.monitoring.token_tracker import TokenUsage

        usage = TokenUsage(input_tokens=100, output_tokens=50, request_count=5)

        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.request_count == 5

    def test_total_tokens_property(self):
        """Test total_tokens property."""
        from utils.monitoring.token_tracker import TokenUsage

        usage = TokenUsage(input_tokens=100, output_tokens=50)

        assert usage.total_tokens == 150

    def test_add_method(self):
        """Test add method."""
        from utils.monitoring.token_tracker import TokenUsage

        usage = TokenUsage()
        usage.add(100, 50)

        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.request_count == 1

    def test_add_multiple_times(self):
        """Test add method accumulates."""
        from utils.monitoring.token_tracker import TokenUsage

        usage = TokenUsage()
        usage.add(100, 50)
        usage.add(200, 100)

        assert usage.input_tokens == 300
        assert usage.output_tokens == 150
        assert usage.request_count == 2


class TestUserTokenStats:
    """Tests for UserTokenStats dataclass."""

    def test_create_user_token_stats(self):
        """Test creating UserTokenStats instance."""
        from utils.monitoring.token_tracker import UserTokenStats

        stats = UserTokenStats(user_id=123)

        assert stats.user_id == 123
        assert stats.total_input == 0
        assert stats.total_output == 0
        assert stats.total_requests == 0

    def test_total_tokens_property(self):
        """Test total_tokens property."""
        from utils.monitoring.token_tracker import UserTokenStats

        stats = UserTokenStats(
            user_id=123,
            total_input=500,
            total_output=200
        )

        assert stats.total_tokens == 700

    def test_average_per_request_zero_requests(self):
        """Test average_per_request with zero requests."""
        from utils.monitoring.token_tracker import UserTokenStats

        stats = UserTokenStats(user_id=123)

        assert stats.average_per_request == 0

    def test_average_per_request_with_requests(self):
        """Test average_per_request with requests."""
        from utils.monitoring.token_tracker import UserTokenStats

        stats = UserTokenStats(
            user_id=123,
            total_input=500,
            total_output=200,
            total_requests=7
        )

        assert stats.average_per_request == 100


class TestTokenTrackerInit:
    """Tests for TokenTracker initialization."""

    def test_create_token_tracker(self):
        """Test creating TokenTracker instance."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        assert tracker is not None

    def test_token_tracker_with_max_history(self):
        """Test TokenTracker with custom max_history_days."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker(max_history_days=60)
        assert tracker._max_history_days == 60

    def test_empty_user_stats(self):
        """Test user_stats is empty initially."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        assert tracker._user_stats == {}


class TestTokenTrackerRecord:
    """Tests for TokenTracker.record method."""

    def test_record_first_usage(self):
        """Test recording first usage for user."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record(user_id=123, input_tokens=100, output_tokens=50)

        assert 123 in tracker._user_stats
        assert tracker._user_stats[123].total_input == 100
        assert tracker._user_stats[123].total_output == 50

    def test_record_multiple_usages(self):
        """Test recording multiple usages."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record(user_id=123, input_tokens=100, output_tokens=50)
        tracker.record(user_id=123, input_tokens=200, output_tokens=100)

        assert tracker._user_stats[123].total_input == 300
        assert tracker._user_stats[123].total_output == 150
        assert tracker._user_stats[123].total_requests == 2

    def test_record_with_channel(self):
        """Test recording with channel_id."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record(
            user_id=123,
            input_tokens=100,
            output_tokens=50,
            channel_id=456
        )

        assert 456 in tracker._channel_usage


class TestTokenTrackerGetUserStats:
    """Tests for TokenTracker.get_user_stats method."""

    def test_get_user_stats_existing(self):
        """Test getting stats for existing user."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record(user_id=123, input_tokens=100, output_tokens=50)

        stats = tracker.get_user_stats(123)

        assert stats is not None
        assert stats.user_id == 123

    def test_get_user_stats_nonexistent(self):
        """Test getting stats for nonexistent user."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        stats = tracker.get_user_stats(999)

        assert stats is None


class TestTokenTrackerGetTopUsers:
    """Tests for TokenTracker.get_top_users method."""

    def test_get_top_users_empty(self):
        """Test getting top users with no data."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        top_users = tracker.get_top_users()

        assert top_users == []

    def test_get_top_users_with_data(self):
        """Test getting top users with data."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record(user_id=1, input_tokens=100, output_tokens=50)
        tracker.record(user_id=2, input_tokens=500, output_tokens=250)
        tracker.record(user_id=3, input_tokens=200, output_tokens=100)

        top_users = tracker.get_top_users(limit=2)

        assert len(top_users) == 2
        # Returns list of tuples (user_id, UserTokenStats)
        assert top_users[0][0] == 2  # Highest usage user ID

    def test_get_top_users_limit(self):
        """Test get_top_users respects limit."""
        from utils.monitoring.token_tracker import TokenTracker

        tracker = TokenTracker()
        for i in range(10):
            tracker.record(user_id=i, input_tokens=100*i, output_tokens=50*i)

        top_users = tracker.get_top_users(limit=3)

        assert len(top_users) == 3


class TestTokenTrackerSingleton:
    """Tests for token_tracker singleton."""

    def test_singleton_exists(self):
        """Test token_tracker singleton exists."""
        from utils.monitoring.token_tracker import token_tracker

        assert token_tracker is not None

    def test_singleton_is_token_tracker(self):
        """Test singleton is TokenTracker instance."""
        from utils.monitoring.token_tracker import TokenTracker, token_tracker

        assert isinstance(token_tracker, TokenTracker)
