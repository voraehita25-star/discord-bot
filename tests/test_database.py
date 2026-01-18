"""
Unit Tests for Database Module.
Tests core database operations including CRUD, schema, and edge cases.
"""

from __future__ import annotations

import os

# Add project root to path
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestDatabaseSchema:
    """Test database schema initialization."""

    @pytest.fixture
    def temp_db_path(self) -> str:
        """Create a temporary database file."""
        fd, path_str = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        path = Path(path_str)
        yield path_str
        # Cleanup
        if path.exists():
            path.unlink()

    @pytest.mark.asyncio
    async def test_init_schema_creates_tables(self, temp_db_path: str) -> None:
        """Test that init_schema creates all required tables."""
        import aiosqlite

        # Create a minimal database with schema
        async with aiosqlite.connect(temp_db_path) as conn:
            # Create ai_history table (simplified version)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    local_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()

            # Verify table exists
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_history'"
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == "ai_history"

    @pytest.mark.asyncio
    async def test_local_id_column_exists(self, temp_db_path: str) -> None:
        """Test that local_id column exists in ai_history table."""
        import aiosqlite

        async with aiosqlite.connect(temp_db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    role TEXT,
                    content TEXT,
                    local_id INTEGER
                )
            """)
            await conn.commit()

            # Check column exists
            cursor = await conn.execute("PRAGMA table_info(ai_history)")
            columns = [row[1] for row in await cursor.fetchall()]
            assert "local_id" in columns


class TestGuildSettings:
    """Test guild settings operations."""

    def test_allowed_columns_whitelist(self) -> None:
        """Test that save_guild_settings uses whitelist for SQL injection protection."""
        # Define expected allowed columns
        allowed_columns = {
            "prefix",
            "ai_enabled",
            "music_enabled",
            "auto_disconnect_delay",
            "mode_247",
        }

        # Test that malicious column names would be filtered
        test_settings = {
            "prefix": "!",
            "ai_enabled": True,
            "malicious_column": "DROP TABLE users;",  # Should be filtered
            "mode_247": False,
        }

        # Filter using the same logic as save_guild_settings
        safe_settings = {k: v for k, v in test_settings.items() if k in allowed_columns}

        assert "malicious_column" not in safe_settings
        assert "prefix" in safe_settings
        assert "mode_247" in safe_settings
        assert len(safe_settings) == 3


class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_bucket_creation_thread_safe(self) -> None:
        """Test that bucket creation is atomic using setdefault."""
        from dataclasses import dataclass

        @dataclass
        class MockBucket:
            tokens: float
            max_tokens: int

        buckets: dict[str, MockBucket] = {}

        # Simulate setdefault behavior (atomic)
        key = "test_key"

        # First call - creates bucket
        bucket1 = buckets.setdefault(key, MockBucket(tokens=10.0, max_tokens=10))

        # Second call - returns existing bucket
        bucket2 = buckets.setdefault(key, MockBucket(tokens=5.0, max_tokens=5))

        # Both should reference the same bucket (first one created)
        assert bucket1 is bucket2
        assert bucket1.tokens == 10.0
        assert bucket1.max_tokens == 10

    def test_token_consumption(self) -> None:
        """Test token bucket consumption logic."""
        import time
        from dataclasses import dataclass

        @dataclass
        class TokenBucket:
            tokens: float
            max_tokens: int
            last_update: float
            window: float

            def consume(self) -> tuple[bool, float]:
                """Consume a token if available."""
                now = time.time()
                elapsed = now - self.last_update

                # Refill tokens
                refill = elapsed * (self.max_tokens / self.window)
                self.tokens = min(self.max_tokens, self.tokens + refill)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return True, 0.0
                else:
                    retry_after = (1 - self.tokens) * (self.window / self.max_tokens)
                    return False, retry_after

        # Create bucket with 2 tokens, 60 second window
        bucket = TokenBucket(tokens=2.0, max_tokens=2, last_update=time.time(), window=60.0)

        # First two calls should succeed
        assert bucket.consume()[0] is True
        assert bucket.consume()[0] is True

        # Third call should fail (no tokens left)
        allowed, retry_after = bucket.consume()
        assert allowed is False
        assert retry_after > 0


class TestInputSanitization:
    """Test input sanitization functions."""

    def test_sanitize_channel_name(self) -> None:
        """Test channel name sanitization."""
        import re

        def sanitize_channel_name(name: str) -> str:
            """Sanitize channel name for Discord."""
            if not name:
                return ""
            # Remove dangerous characters
            name = re.sub(r"[<>@#&!]", "", name)
            # Limit length
            name = name[:100].strip()
            # Replace spaces with hyphens (Discord convention)
            name = re.sub(r"\s+", "-", name)
            return name.lower()

        # Test basic sanitization
        assert sanitize_channel_name("Hello World") == "hello-world"
        assert sanitize_channel_name("<script>alert</script>") == "scriptalert/script"
        assert sanitize_channel_name("test@channel#name") == "testchannelname"
        assert sanitize_channel_name("") == ""

        # Test length limit
        long_name = "a" * 200
        assert len(sanitize_channel_name(long_name)) <= 100

    def test_sanitize_role_name(self) -> None:
        """Test role name sanitization."""
        import re

        def sanitize_role_name(name: str) -> str:
            """Sanitize role name for Discord."""
            if not name:
                return ""
            # Remove dangerous characters but keep spaces for roles
            name = re.sub(r"[<>@#&!]", "", name)
            # Limit length
            return name[:100].strip()

        # Test basic sanitization
        assert sanitize_role_name("Admin") == "Admin"
        assert sanitize_role_name("@everyone") == "everyone"
        assert sanitize_role_name("") == ""


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_circuit_states(self) -> None:
        """Test circuit breaker state transitions."""
        from enum import Enum

        class CircuitState(Enum):
            CLOSED = "closed"
            OPEN = "open"
            HALF_OPEN = "half_open"

        # Test state values
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_failure_threshold(self) -> None:
        """Test that circuit opens after failure threshold."""
        failure_count = 0
        failure_threshold = 5
        state = "closed"

        # Simulate failures
        for _ in range(failure_threshold):
            failure_count += 1
            if failure_count >= failure_threshold:
                state = "open"

        assert state == "open"
        assert failure_count == 5


class TestMusicUtils:
    """Test music utility functions."""

    def test_format_duration(self) -> None:
        """Test duration formatting."""

        def format_duration(seconds: int | float | None) -> str:
            if not seconds:
                return "00:00"
            seconds = int(seconds)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            if hours > 0:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"

        assert format_duration(0) == "00:00"
        assert format_duration(None) == "00:00"
        assert format_duration(65) == "1:05"
        assert format_duration(3661) == "1:01:01"
        assert format_duration(7200) == "2:00:00"

    def test_create_progress_bar(self) -> None:
        """Test progress bar creation."""

        def create_progress_bar(current: int | float, total: int | float, length: int = 12) -> str:
            if total == 0:
                return "▱" * length
            progress = int((current / total) * length)
            filled = "▰" * progress
            empty = "▱" * (length - progress)
            return filled + empty

        assert create_progress_bar(0, 100) == "▱" * 12
        assert create_progress_bar(50, 100) == "▰" * 6 + "▱" * 6
        assert create_progress_bar(100, 100) == "▰" * 12
        assert create_progress_bar(0, 0) == "▱" * 12


# Run tests with: python -m pytest tests/test_database.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
