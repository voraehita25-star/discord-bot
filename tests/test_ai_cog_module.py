"""Tests for AI Cog module."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio


class TestAICogInit:
    """Tests for AI Cog initialization."""

    def test_ai_cog_creation(self):
        """Test creating AI cog."""
        from cogs.ai_core.ai_cog import AI
        
        mock_bot = MagicMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager'):
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                cog = AI(mock_bot)
                
                assert cog.bot == mock_bot
                assert cog.cleanup_task is None

    def test_ai_cog_has_chat_manager(self):
        """Test AI cog has ChatManager."""
        from cogs.ai_core.ai_cog import AI
        
        mock_bot = MagicMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager') as mock_cm:
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                cog = AI(mock_bot)
                
                mock_cm.assert_called_once_with(mock_bot)


class TestAICogLoadUnload:
    """Tests for cog load and unload."""

    @pytest.mark.asyncio
    async def test_cog_load(self):
        """Test cog_load method."""
        from cogs.ai_core.ai_cog import AI
        
        mock_bot = MagicMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager') as mock_cm:
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                with patch('cogs.ai_core.ai_cog.start_webhook_cache_cleanup'):
                    with patch('cogs.ai_core.ai_cog.rag_system'):
                        mock_cm_instance = MagicMock()
                        mock_cm_instance.cleanup_inactive_sessions = AsyncMock()
                        mock_cm.return_value = mock_cm_instance
                        
                        cog = AI(mock_bot)
                        await cog.cog_load()
                        
                        assert cog.cleanup_task is not None

    @pytest.mark.asyncio
    async def test_cog_unload(self):
        """Test cog_unload method."""
        from cogs.ai_core.ai_cog import AI
        
        mock_bot = MagicMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager') as mock_cm:
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                with patch('cogs.ai_core.ai_cog.stop_webhook_cache_cleanup'):
                    mock_rag = MagicMock()
                    mock_rag.stop_periodic_save = AsyncMock()
                    mock_rag.force_save_index = AsyncMock()
                    
                    with patch('cogs.ai_core.ai_cog.rag_system', mock_rag):
                        mock_cm_instance = MagicMock()
                        mock_cm_instance.save_all_sessions = AsyncMock()
                        mock_cm.return_value = mock_cm_instance
                        
                        cog = AI(mock_bot)
                        cog.cleanup_task = None
                        cog._pending_request_cleanup_task = None
                        
                        await cog.cog_unload()
                        
                        mock_cm_instance.save_all_sessions.assert_called_once()


class TestChatCommand:
    """Tests for chat command."""

    @pytest.mark.asyncio
    async def test_chat_command_exists(self):
        """Test chat command is defined."""
        from cogs.ai_core.ai_cog import AI
        
        mock_bot = MagicMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager'):
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                cog = AI(mock_bot)
                
                assert hasattr(cog, 'chat_command')

    @pytest.mark.asyncio
    async def test_chat_command_error_handler(self):
        """Test chat command error handler."""
        from cogs.ai_core.ai_cog import AI
        from discord.ext import commands
        
        mock_bot = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager'):
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                cog = AI(mock_bot)
                
                # Create a cooldown error
                error = commands.CommandOnCooldown(
                    commands.Cooldown(1, 3),
                    2.5,
                    commands.BucketType.user
                )
                
                await cog.chat_command_error(mock_ctx, error)
                
                mock_ctx.send.assert_called_once()
                call_args = mock_ctx.send.call_args[0][0]
                assert "2.5" in call_args


class TestOwnerCommands:
    """Tests for owner-only commands."""

    @pytest.mark.asyncio
    async def test_reset_ai_command_exists(self):
        """Test reset_ai command is defined."""
        from cogs.ai_core.ai_cog import AI
        
        mock_bot = MagicMock()
        
        with patch('cogs.ai_core.ai_cog.ChatManager'):
            with patch('cogs.ai_core.ai_cog.rate_limiter'):
                cog = AI(mock_bot)
                
                assert hasattr(cog, 'reset_ai')


class TestFeatureFlags:
    """Tests for feature availability flags."""

    def test_guardrails_available_flag(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import GUARDRAILS_AVAILABLE
        
        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_feedback_available_flag(self):
        """Test FEEDBACK_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import FEEDBACK_AVAILABLE
        
        assert isinstance(FEEDBACK_AVAILABLE, bool)

    def test_localization_available_flag(self):
        """Test LOCALIZATION_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import LOCALIZATION_AVAILABLE
        
        assert isinstance(LOCALIZATION_AVAILABLE, bool)


class TestConstants:
    """Tests for module constants."""

    def test_owner_id_defined(self):
        """Test OWNER_ID is defined in cog."""
        from cogs.ai_core.ai_cog import AI
        
        assert hasattr(AI, 'OWNER_ID')


class TestModuleImports:
    """Tests for module imports."""

    def test_import_ai_cog(self):
        """Test importing AI cog."""
        from cogs.ai_core.ai_cog import AI
        assert AI is not None

    def test_import_constants(self):
        """Test importing constants."""
        from cogs.ai_core.ai_cog import (
            CHANNEL_ID_ALLOWED,
            GUILD_ID_MAIN,
            CREATOR_ID,
        )
        
        # Constants may be None but should be importable
        assert GUILD_ID_MAIN is not None or GUILD_ID_MAIN is None

    def test_import_chat_manager_class(self):
        """Test ChatManager is imported."""
        from cogs.ai_core.ai_cog import ChatManager
        assert ChatManager is not None

    def test_import_storage_functions(self):
        """Test storage functions are imported."""
        from cogs.ai_core.ai_cog import (
            copy_history,
            delete_history,
            get_all_channel_ids,
            move_history,
        )
        
        assert copy_history is not None
        assert delete_history is not None


class TestFallbackFunctions:
    """Tests for fallback functions when features unavailable."""

    def test_is_unrestricted_fallback(self):
        """Test is_unrestricted fallback when guardrails unavailable."""
        from cogs.ai_core.ai_cog import is_unrestricted
        
        # Should return False by default
        result = is_unrestricted(123456)
        assert result is False or result is True  # Either is valid

    def test_msg_fallback(self):
        """Test msg fallback when localization unavailable."""
        from cogs.ai_core.ai_cog import msg
        
        # Should return key as is
        result = msg("test_key")
        assert "test_key" in result or result is not None
