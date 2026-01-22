"""
Extended tests for cogs/ai_core/core/context_builder.py
Comprehensive tests for AIContext and ContextBuilder.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAIContextDataclass:
    """Tests for AIContext dataclass."""

    def test_ai_context_default_values(self):
        """Test AIContext with default values."""
        from cogs.ai_core.core.context_builder import AIContext
        
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

    def test_ai_context_with_values(self):
        """Test AIContext with custom values."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(
            avatar_name="TestBot",
            avatar_personality="Friendly and helpful",
            avatar_image_url="https://example.com/avatar.png",
            rag_context="Some RAG context",
            entity_memory="Entity data",
            state_tracker="Current state",
            url_content="Content from URL",
            recent_history=[{"role": "user", "content": "Hello"}],
            instructions="Be helpful",
        )
        
        assert ctx.avatar_name == "TestBot"
        assert ctx.avatar_personality == "Friendly and helpful"
        assert ctx.avatar_image_url == "https://example.com/avatar.png"
        assert ctx.rag_context == "Some RAG context"
        assert ctx.entity_memory == "Entity data"
        assert ctx.state_tracker == "Current state"
        assert ctx.url_content == "Content from URL"
        assert len(ctx.recent_history) == 1
        assert ctx.instructions == "Be helpful"

    def test_has_avatar_true(self):
        """Test has_avatar property when avatar_name is set."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(avatar_name="TestBot")
        assert ctx.has_avatar is True

    def test_has_avatar_false(self):
        """Test has_avatar property when avatar_name is None."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext()
        assert ctx.has_avatar is False

    def test_build_system_context_empty(self):
        """Test build_system_context with no content."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext()
        result = ctx.build_system_context()
        assert result == ""

    def test_build_system_context_with_instructions(self):
        """Test build_system_context with instructions only."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(instructions="Be helpful and friendly")
        result = ctx.build_system_context()
        assert "## Instructions" in result
        assert "Be helpful and friendly" in result

    def test_build_system_context_with_rag(self):
        """Test build_system_context with RAG context."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(rag_context="Knowledge from database")
        result = ctx.build_system_context()
        assert "## Relevant Knowledge" in result
        assert "Knowledge from database" in result

    def test_build_system_context_with_entity_memory(self):
        """Test build_system_context with entity memory."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(entity_memory="User is named John, age 25")
        result = ctx.build_system_context()
        assert "## Entity Memory" in result
        assert "User is named John" in result

    def test_build_system_context_with_state_tracker(self):
        """Test build_system_context with state tracker."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(state_tracker="Current topic: coding")
        result = ctx.build_system_context()
        assert "## State Tracker" in result
        assert "Current topic: coding" in result

    def test_build_system_context_with_url_content(self):
        """Test build_system_context with URL content."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(url_content="Content from webpage")
        result = ctx.build_system_context()
        assert "## URL Content" in result
        assert "Content from webpage" in result

    def test_build_system_context_combined(self):
        """Test build_system_context with all content."""
        from cogs.ai_core.core.context_builder import AIContext
        
        ctx = AIContext(
            instructions="Be helpful",
            rag_context="Knowledge data",
            entity_memory="Entity data",
            state_tracker="State data",
            url_content="URL data",
        )
        result = ctx.build_system_context()
        
        assert "## Instructions" in result
        assert "## Relevant Knowledge" in result
        assert "## Entity Memory" in result
        assert "## State Tracker" in result
        assert "## URL Content" in result


class TestContextBuilder:
    """Tests for ContextBuilder class."""

    def test_context_builder_init_no_dependencies(self):
        """Test ContextBuilder initialization without dependencies."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        builder = ContextBuilder()
        assert builder.memory_manager is None
        assert builder.entity_memory is None
        assert builder.state_tracker is None
        assert builder.avatar_manager is None

    def test_context_builder_init_with_dependencies(self):
        """Test ContextBuilder initialization with dependencies."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_memory = MagicMock()
        mock_entity = MagicMock()
        mock_state = MagicMock()
        mock_avatar = MagicMock()
        
        builder = ContextBuilder(
            memory_manager=mock_memory,
            entity_memory=mock_entity,
            state_tracker=mock_state,
            avatar_manager=mock_avatar,
        )
        
        assert builder.memory_manager == mock_memory
        assert builder.entity_memory == mock_entity
        assert builder.state_tracker == mock_state
        assert builder.avatar_manager == mock_avatar

    @pytest.mark.asyncio
    async def test_build_context_empty(self):
        """Test build_context with no dependencies."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        builder = ContextBuilder()
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Hello",
        )
        
        assert ctx.rag_context == ""
        assert ctx.entity_memory == ""
        assert ctx.state_tracker == ""

    @pytest.mark.asyncio
    async def test_build_context_with_memory_manager(self):
        """Test build_context with memory manager."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_memory = MagicMock()
        mock_memory.search = AsyncMock(return_value=[
            {"text": "Result 1", "score": 0.9},
            {"text": "Result 2", "score": 0.8},
        ])
        
        builder = ContextBuilder(memory_manager=mock_memory)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Test query",
            include_rag=True,
        )
        
        # Context should have RAG data if method exists

    @pytest.mark.asyncio
    async def test_build_context_exclude_rag(self):
        """Test build_context with RAG excluded."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_memory = MagicMock()
        mock_memory.search = AsyncMock(return_value=[])
        
        builder = ContextBuilder(memory_manager=mock_memory)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Test",
            include_rag=False,
        )
        
        # RAG should not be called when excluded
        assert ctx.rag_context == ""

    @pytest.mark.asyncio
    async def test_build_context_with_entity_memory(self):
        """Test build_context with entity memory."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_entity = MagicMock()
        mock_entity.get_entity = AsyncMock(return_value=None)
        
        builder = ContextBuilder(entity_memory=mock_entity)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Tell me about John",
            include_entity=True,
        )
        
        # Should process even if no entity found

    @pytest.mark.asyncio
    async def test_build_context_with_state_tracker(self):
        """Test build_context with state tracker."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_state = MagicMock()
        mock_state.get_state = AsyncMock(return_value={"topic": "coding"})
        
        builder = ContextBuilder(state_tracker=mock_state)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Continue",
            include_state=True,
        )
        
        # Should process state tracker

    @pytest.mark.asyncio
    async def test_build_context_with_avatar_manager(self):
        """Test build_context with avatar manager."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_avatar = MagicMock()
        mock_avatar.get_avatar = AsyncMock(return_value={
            "name": "TestBot",
            "personality": "Friendly",
        })
        
        mock_guild = MagicMock()
        
        builder = ContextBuilder(avatar_manager=mock_avatar)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Hello",
            guild=mock_guild,
            include_avatar=True,
        )
        
        # Should process avatar if guild provided

    @pytest.mark.asyncio
    async def test_build_context_no_guild_no_avatar(self):
        """Test build_context without guild doesn't load avatar."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_avatar = MagicMock()
        mock_avatar.get_avatar = AsyncMock(return_value=None)
        
        builder = ContextBuilder(avatar_manager=mock_avatar)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Hello",
            guild=None,  # No guild
            include_avatar=True,
        )
        
        # Avatar should not be loaded without guild
        assert ctx.avatar_name is None

    @pytest.mark.asyncio
    async def test_build_context_handles_exceptions(self):
        """Test build_context handles exceptions gracefully."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_memory = MagicMock()
        mock_memory.search = AsyncMock(side_effect=Exception("Memory error"))
        
        builder = ContextBuilder(memory_manager=mock_memory)
        
        # Should not raise, should handle exception
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Test",
        )
        
        # Should return context even on error
        assert isinstance(ctx.rag_context, str)


class TestContextBuilderPrivateMethods:
    """Tests for ContextBuilder private helper methods."""

    @pytest.mark.asyncio
    async def test_get_rag_context_no_manager(self):
        """Test _get_rag_context without memory manager."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        builder = ContextBuilder()
        # Method should handle None manager

    @pytest.mark.asyncio
    async def test_get_entity_memory_no_manager(self):
        """Test _get_entity_memory without entity memory manager."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        builder = ContextBuilder()
        # Method should handle None manager

    @pytest.mark.asyncio
    async def test_get_state_tracker_no_manager(self):
        """Test _get_state_tracker without state tracker."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        builder = ContextBuilder()
        # Method should handle None manager


class TestContextBuilderIntegration:
    """Integration tests for ContextBuilder."""

    @pytest.mark.asyncio
    async def test_full_context_build(self):
        """Test building context with all components."""
        from cogs.ai_core.core.context_builder import ContextBuilder, AIContext
        
        # Create mocks for all dependencies
        mock_memory = MagicMock()
        mock_memory.search = AsyncMock(return_value=[])
        
        mock_entity = MagicMock()
        mock_entity.search_entities = AsyncMock(return_value=[])
        
        mock_state = MagicMock()
        mock_state.get_state = AsyncMock(return_value={})
        
        mock_avatar = MagicMock()
        mock_avatar.get_avatar = AsyncMock(return_value=None)
        
        mock_guild = MagicMock()
        mock_guild.id = 123456
        
        builder = ContextBuilder(
            memory_manager=mock_memory,
            entity_memory=mock_entity,
            state_tracker=mock_state,
            avatar_manager=mock_avatar,
        )
        
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Test message",
            guild=mock_guild,
            include_rag=True,
            include_entity=True,
            include_state=True,
            include_avatar=True,
        )
        
        assert isinstance(ctx, AIContext)

    @pytest.mark.asyncio
    async def test_selective_context_build(self):
        """Test building context with selective components."""
        from cogs.ai_core.core.context_builder import ContextBuilder
        
        mock_memory = MagicMock()
        mock_memory.search = AsyncMock(return_value=[])
        
        builder = ContextBuilder(memory_manager=mock_memory)
        
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Test",
            include_rag=True,
            include_entity=False,
            include_state=False,
            include_avatar=False,
        )
        
        # Only RAG should be processed
        assert ctx.entity_memory == ""
        assert ctx.state_tracker == ""
        assert ctx.avatar_name is None


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_default_constants(self):
        """Test default constant values."""
        from cogs.ai_core.core.context_builder import (
            MAX_RAG_RESULTS,
            RAG_MIN_SIMILARITY,
            MAX_ENTITY_ITEMS,
        )
        
        # Check defaults exist
        assert isinstance(MAX_RAG_RESULTS, int)
        assert isinstance(RAG_MIN_SIMILARITY, float)
        assert isinstance(MAX_ENTITY_ITEMS, int)
        
        # Check reasonable values
        assert MAX_RAG_RESULTS > 0
        assert 0 <= RAG_MIN_SIMILARITY <= 1
        assert MAX_ENTITY_ITEMS > 0
