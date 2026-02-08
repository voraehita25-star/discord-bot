"""Tests for context builder module."""

from unittest.mock import MagicMock

import pytest


class TestAIContextDataclass:
    """Tests for AIContext dataclass."""

    def test_ai_context_defaults(self):
        """Test AIContext default values."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext()

        assert ctx.avatar_name is None
        assert ctx.avatar_personality is None
        assert ctx.avatar_image_url is None
        assert ctx.rag_context == ""
        assert ctx.entity_memory == ""
        assert ctx.state_tracker == ""
        assert ctx.url_content == ""
        assert ctx.recent_history is None
        assert ctx.instructions == ""

    def test_ai_context_has_avatar_false(self):
        """Test has_avatar property when no avatar."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext()

        assert ctx.has_avatar is False

    def test_ai_context_has_avatar_true(self):
        """Test has_avatar property when avatar exists."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(avatar_name="TestAvatar")

        assert ctx.has_avatar is True

    def test_ai_context_build_system_context_empty(self):
        """Test build_system_context with no data."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext()

        result = ctx.build_system_context()

        assert result == ""

    def test_ai_context_build_system_context_with_instructions(self):
        """Test build_system_context with instructions."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(instructions="Be helpful")

        result = ctx.build_system_context()

        assert "## Instructions" in result
        assert "Be helpful" in result

    def test_ai_context_build_system_context_with_rag(self):
        """Test build_system_context with RAG context."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(rag_context="Relevant info")

        result = ctx.build_system_context()

        assert "## Relevant Knowledge" in result
        assert "Relevant info" in result

    def test_ai_context_build_system_context_with_entity(self):
        """Test build_system_context with entity memory."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(entity_memory="User likes cats")

        result = ctx.build_system_context()

        assert "## Entity Memory" in result
        assert "User likes cats" in result

    def test_ai_context_build_system_context_with_url(self):
        """Test build_system_context with URL content."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(url_content="Page content here")

        result = ctx.build_system_context()

        assert "## URL Content" in result
        assert "Page content here" in result

    def test_ai_context_build_system_context_multiple(self):
        """Test build_system_context with multiple parts."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(
            instructions="Be helpful",
            rag_context="Relevant info",
            entity_memory="User likes cats",
        )

        result = ctx.build_system_context()

        assert "## Instructions" in result
        assert "## Relevant Knowledge" in result
        assert "## Entity Memory" in result


class TestContextBuilder:
    """Tests for ContextBuilder class."""

    def test_context_builder_init_defaults(self):
        """Test ContextBuilder initialization with defaults."""
        from cogs.ai_core.context_builder import ContextBuilder

        builder = ContextBuilder()

        assert builder.memory_manager is None
        assert builder.entity_memory is None
        assert builder.state_tracker is None
        assert builder.avatar_manager is None

    def test_context_builder_init_with_params(self):
        """Test ContextBuilder initialization with params."""
        from cogs.ai_core.context_builder import ContextBuilder

        mock_memory = MagicMock()
        mock_entity = MagicMock()

        builder = ContextBuilder(
            memory_manager=mock_memory,
            entity_memory=mock_entity,
        )

        assert builder.memory_manager is mock_memory
        assert builder.entity_memory is mock_entity


class TestModuleImports:
    """Tests for module imports."""

    def test_import_ai_context(self):
        """Test AIContext can be imported."""
        from cogs.ai_core.context_builder import AIContext
        assert AIContext is not None

    def test_import_context_builder(self):
        """Test ContextBuilder can be imported."""
        from cogs.ai_core.context_builder import ContextBuilder
        assert ContextBuilder is not None

    def test_import_context_builder_singleton(self):
        """Test context_builder singleton can be imported."""
        from cogs.ai_core.context_builder import context_builder
        assert context_builder is not None


class TestConstants:
    """Tests for context builder constants."""

    def test_max_rag_results_exists(self):
        """Test MAX_RAG_RESULTS constant."""
        from cogs.ai_core.core.context_builder import MAX_RAG_RESULTS

        assert isinstance(MAX_RAG_RESULTS, int)
        assert MAX_RAG_RESULTS > 0

    def test_rag_min_similarity_exists(self):
        """Test RAG_MIN_SIMILARITY constant."""
        from cogs.ai_core.core.context_builder import RAG_MIN_SIMILARITY

        assert isinstance(RAG_MIN_SIMILARITY, float)
        assert 0 <= RAG_MIN_SIMILARITY <= 1


class TestAIContextCustomValues:
    """Tests for AIContext with custom values."""

    def test_ai_context_avatar_fields(self):
        """Test AIContext with avatar fields."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(
            avatar_name="TestBot",
            avatar_personality="Friendly and helpful",
            avatar_image_url="https://example.com/avatar.png",
        )

        assert ctx.avatar_name == "TestBot"
        assert ctx.avatar_personality == "Friendly and helpful"
        assert ctx.avatar_image_url == "https://example.com/avatar.png"
        assert ctx.has_avatar is True

    def test_ai_context_recent_history(self):
        """Test AIContext with recent history."""
        from cogs.ai_core.context_builder import AIContext

        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        ctx = AIContext(recent_history=history)

        assert ctx.recent_history is not None
        assert len(ctx.recent_history) == 2
        assert ctx.recent_history[0]["role"] == "user"


class TestContextBuilderWithMocks:
    """Tests for ContextBuilder with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_build_context_has_method(self):
        """Test ContextBuilder has build_context method."""
        from cogs.ai_core.context_builder import ContextBuilder

        builder = ContextBuilder()

        assert hasattr(builder, 'build_context')
        assert callable(builder.build_context)
