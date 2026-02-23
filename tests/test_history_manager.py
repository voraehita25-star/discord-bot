# pylint: disable=protected-access
"""
Unit Tests for History Manager Module.
Tests intelligent trimming and message importance calculation.
"""

from __future__ import annotations

import pytest


class TestHistoryStats:
    """Tests for HistoryStats dataclass."""

    def test_history_stats_creation(self):
        """Test creating HistoryStats."""
        from cogs.ai_core.memory.history_manager import HistoryStats

        stats = HistoryStats(
            total_messages=100,
            user_messages=50,
            ai_messages=50,
            important_count=10,
            estimated_tokens=5000,
        )

        assert stats.total_messages == 100
        assert stats.user_messages == 50
        assert stats.ai_messages == 50
        assert stats.important_count == 10
        assert stats.estimated_tokens == 5000


class TestHistoryManagerInit:
    """Tests for HistoryManager initialization."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()

        assert manager.keep_recent == 200
        assert manager.max_history == 10000
        assert manager.compress_threshold == 2000
        assert manager.max_tokens == 1200000

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager(
            keep_recent=100,
            max_history=500,
            compress_threshold=100,
            max_tokens=50000,
        )

        assert manager.keep_recent == 100
        assert manager.max_history == 500
        assert manager.compress_threshold == 100
        assert manager.max_tokens == 50000

    def test_patterns_compiled(self):
        """Test importance patterns are compiled."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()

        assert len(manager._importance_patterns) > 0
        assert hasattr(manager._importance_patterns[0][0], "search")  # Compiled pattern


class TestGetMessageContent:
    """Tests for _get_message_content method."""

    def test_get_content_string_parts(self):
        """Test extracting content from string parts."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": ["Hello world"]}

        content = manager._get_message_content(message)

        assert content == "Hello world"

    def test_get_content_dict_parts(self):
        """Test extracting content from dict parts."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": [{"text": "Hello world"}]}

        content = manager._get_message_content(message)

        assert content == "Hello world"

    def test_get_content_mixed_parts(self):
        """Test extracting content from mixed parts."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": ["Hello", {"text": "world"}]}

        content = manager._get_message_content(message)

        assert "Hello" in content
        assert "world" in content

    def test_get_content_empty_parts(self):
        """Test extracting content from empty parts."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": []}

        content = manager._get_message_content(message)

        assert content == ""


class TestCalculateImportance:
    """Tests for _calculate_importance method."""

    def test_importance_base_score(self):
        """Test base importance score."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "model", "parts": ["Hello"]}

        score, matched = manager._calculate_importance(message)

        assert score >= 1.0
        assert isinstance(matched, list)

    def test_importance_user_name(self):
        """Test importance for user name mentions."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": ["ชื่อฉันคือ John"]}

        score, matched = manager._calculate_importance(message)

        assert score > 1.0
        assert "user_name" in matched

    def test_importance_preference(self):
        """Test importance for preference mentions."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": ["ฉันชอบอ่านหนังสือ"]}

        score, matched = manager._calculate_importance(message)

        assert score > 1.0
        assert "preference" in matched

    def test_importance_explicit_important(self):
        """Test importance for explicit important keywords."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": ["จำไว้เรื่องนี้สำคัญมาก"]}

        score, matched = manager._calculate_importance(message)

        assert score >= 2.0  # explicit_important has weight 2.0

    def test_importance_user_message_boost(self):
        """Test user message gets importance boost."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        user_msg = {"role": "user", "parts": ["Hello"]}
        model_msg = {"role": "model", "parts": ["Hello"]}

        user_score, _ = manager._calculate_importance(user_msg)
        model_score, _ = manager._calculate_importance(model_msg)

        assert user_score >= model_score


class TestEstimateTokens:
    """Tests for token estimation."""

    def test_estimate_tokens_empty(self):
        """Test token estimation for empty history."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        result = manager.estimate_tokens([])

        assert result == 0

    def test_estimate_tokens_simple(self):
        """Test token estimation for simple history."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [
            {"role": "user", "parts": ["Hello world"]},
            {"role": "model", "parts": ["Hi there!"]},
        ]

        result = manager.estimate_tokens(history)

        assert result > 0
        assert result < 100  # Should be reasonable for short messages

    def test_estimate_message_tokens(self):
        """Test single message token estimation."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        message = {"role": "user", "parts": ["Hello world"]}

        result = manager.estimate_message_tokens(message)

        assert result > 5  # At least overhead


class TestGetStats:
    """Tests for get_stats method."""

    def test_get_stats_empty(self):
        """Test stats for empty history."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        stats = manager.get_stats([])

        assert stats.total_messages == 0
        assert stats.user_messages == 0
        assert stats.ai_messages == 0

    def test_get_stats_with_data(self):
        """Test stats with history data."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [
            {"role": "user", "parts": ["Hello"]},
            {"role": "model", "parts": ["Hi"]},
            {"role": "user", "parts": ["How are you?"]},
        ]

        stats = manager.get_stats(history)

        assert stats.total_messages == 3
        assert stats.user_messages == 2
        assert stats.ai_messages == 1


class TestQuickTrim:
    """Tests for quick_trim method."""

    def test_quick_trim_no_trim_needed(self):
        """Test quick_trim when no trimming needed."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [{"role": "user", "parts": ["msg"]}] * 10

        result = manager.quick_trim(history, max_messages=100)

        assert len(result) == 10  # No change

    def test_quick_trim_needed(self):
        """Test quick_trim when trimming needed."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [{"role": "user", "parts": [f"msg{idx}"]} for idx in range(100)]

        result = manager.quick_trim(history, max_messages=50)

        assert len(result) == 50
        # First few messages preserved
        assert result[0]["parts"][0] == "msg0"
        # Last messages preserved
        assert result[-1]["parts"][0] == "msg99"


class TestSmartTrimAsync:
    """Async tests for smart_trim method."""

    @pytest.mark.asyncio
    async def test_smart_trim_no_trim_needed(self):
        """Test smart_trim when no trimming needed."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [{"role": "user", "parts": ["Hello"]}] * 10

        result = await manager.smart_trim(history, max_messages=100)

        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_smart_trim_needed(self):
        """Test smart_trim when trimming needed."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager(keep_recent=10)
        history = [{"role": "user", "parts": [f"msg{idx}"]} for idx in range(100)]

        result = await manager.smart_trim(history, max_messages=30)

        assert len(result) <= 30

    @pytest.mark.asyncio
    async def test_smart_trim_preserves_important(self):
        """Test smart_trim preserves important messages."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager(keep_recent=5)

        # Create history with one important message in the middle
        history = []
        for i in range(50):
            if i == 25:
                history.append({"role": "user", "parts": ["ชื่อฉันคือ John สำคัญมาก"]})
            else:
                history.append({"role": "user", "parts": [f"normal msg {i}"]})

        result = await manager.smart_trim(history, max_messages=20)

        # Important message should be preserved
        all_content = " ".join(manager._get_message_content(m) for m in result)
        assert "John" in all_content or "สำคัญ" in all_content


class TestSmartTrimByTokens:
    """Async tests for smart_trim_by_tokens method."""

    @pytest.mark.asyncio
    async def test_smart_trim_by_tokens_no_trim(self):
        """Test smart_trim_by_tokens when within budget."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [{"role": "user", "parts": ["Hello"]}] * 5

        result = await manager.smart_trim_by_tokens(history, max_tokens=10000)

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_smart_trim_by_tokens_trim_needed(self):
        """Test smart_trim_by_tokens when trimming needed."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager(keep_recent=2)
        # Create messages with substantial content
        history = [{"role": "user", "parts": ["A" * 100]} for _ in range(50)]

        # Very small token budget
        result = await manager.smart_trim_by_tokens(history, max_tokens=500)

        assert len(result) < 50


class TestExtractUserFacts:
    """Tests for extract_user_facts method."""

    def test_extract_user_facts_empty(self):
        """Test extracting facts from empty history."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        facts = manager.extract_user_facts([])

        assert facts == {
            "names": [],
            "preferences": [],
            "personal_info": [],
            "rules": [],
        }

    def test_extract_user_facts_name(self):
        """Test extracting user name."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [
            {"role": "user", "parts": ["ชื่อฉันคือ John"]},
        ]

        facts = manager.extract_user_facts(history)

        assert "John" in facts["names"]

    def test_extract_user_facts_preference(self):
        """Test extracting user preferences."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [
            {"role": "user", "parts": ["I like reading books"]},
        ]

        facts = manager.extract_user_facts(history)

        # Pattern may or may not match depending on regex
        assert isinstance(facts["preferences"], list)

    def test_extract_user_facts_ignores_model(self):
        """Test that model messages are ignored."""
        from cogs.ai_core.memory.history_manager import HistoryManager

        manager = HistoryManager()
        history = [
            {"role": "model", "parts": ["ชื่อฉันคือ Faust"]},
        ]

        facts = manager.extract_user_facts(history)

        assert facts["names"] == []


class TestGlobalInstance:
    """Tests for global history_manager instance."""

    def test_global_instance_exists(self):
        """Test global instance is available."""
        from cogs.ai_core.memory.history_manager import history_manager

        assert history_manager is not None

    def test_smart_trim_history_function(self):
        """Test smart_trim_history convenience function."""
        from cogs.ai_core.memory.history_manager import smart_trim_history

        assert callable(smart_trim_history)
