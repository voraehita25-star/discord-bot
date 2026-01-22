"""
Extended tests for AI Cog module.
Tests imports, constants, and configuration.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestAiCogImports:
    """Tests for ai_cog module imports."""

    def test_guardrails_available_defined(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_feedback_available_defined(self):
        """Test FEEDBACK_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import FEEDBACK_AVAILABLE

        assert isinstance(FEEDBACK_AVAILABLE, bool)


class TestStorageImports:
    """Tests for storage imports in ai_cog."""

    def test_cleanup_storage_cache_import(self):
        """Test cleanup_storage_cache is imported."""
        from cogs.ai_core.ai_cog import cleanup_storage_cache

        assert callable(cleanup_storage_cache)

    def test_copy_history_import(self):
        """Test copy_history is imported."""
        from cogs.ai_core.ai_cog import copy_history

        assert callable(copy_history)

    def test_delete_history_import(self):
        """Test delete_history is imported."""
        from cogs.ai_core.ai_cog import delete_history

        assert callable(delete_history)

    def test_get_all_channel_ids_import(self):
        """Test get_all_channel_ids is imported."""
        from cogs.ai_core.ai_cog import get_all_channel_ids

        assert callable(get_all_channel_ids)

    def test_get_last_model_message_import(self):
        """Test get_last_model_message is imported."""
        from cogs.ai_core.ai_cog import get_last_model_message

        assert callable(get_last_model_message)

    def test_get_message_by_local_id_import(self):
        """Test get_message_by_local_id is imported."""
        from cogs.ai_core.ai_cog import get_message_by_local_id

        assert callable(get_message_by_local_id)

    def test_move_history_import(self):
        """Test move_history is imported."""
        from cogs.ai_core.ai_cog import move_history

        assert callable(move_history)


class TestToolsImports:
    """Tests for tools imports in ai_cog."""

    def test_invalidate_webhook_cache_import(self):
        """Test invalidate_webhook_cache_on_channel_delete is imported."""
        from cogs.ai_core.ai_cog import invalidate_webhook_cache_on_channel_delete

        assert callable(invalidate_webhook_cache_on_channel_delete)

    def test_send_as_webhook_import(self):
        """Test send_as_webhook is imported."""
        from cogs.ai_core.ai_cog import send_as_webhook

        assert callable(send_as_webhook)

    def test_start_webhook_cache_cleanup_import(self):
        """Test start_webhook_cache_cleanup is imported."""
        from cogs.ai_core.ai_cog import start_webhook_cache_cleanup

        assert callable(start_webhook_cache_cleanup)

    def test_stop_webhook_cache_cleanup_import(self):
        """Test stop_webhook_cache_cleanup is imported."""
        from cogs.ai_core.ai_cog import stop_webhook_cache_cleanup

        assert callable(stop_webhook_cache_cleanup)


class TestLogicImport:
    """Tests for logic import in ai_cog."""

    def test_chat_manager_import(self):
        """Test ChatManager is imported."""
        from cogs.ai_core.ai_cog import ChatManager

        assert ChatManager is not None


class TestRagImport:
    """Tests for RAG import in ai_cog."""

    def test_rag_system_import(self):
        """Test rag_system is imported."""
        from cogs.ai_core.ai_cog import rag_system

        assert rag_system is not None


class TestRateLimiterImports:
    """Tests for rate limiter imports."""

    def test_check_rate_limit_import(self):
        """Test check_rate_limit is imported."""
        from cogs.ai_core.ai_cog import check_rate_limit

        assert callable(check_rate_limit)

    def test_rate_limiter_import(self):
        """Test rate_limiter is imported."""
        from cogs.ai_core.ai_cog import rate_limiter

        assert rate_limiter is not None


class TestColorsImport:
    """Tests for Colors import."""

    def test_colors_import(self):
        """Test Colors is imported."""
        from cogs.ai_core.ai_cog import Colors

        assert Colors is not None


class TestConstantsImports:
    """Tests for constants imports."""

    def test_channel_id_allowed_import(self):
        """Test CHANNEL_ID_ALLOWED is imported."""
        from cogs.ai_core.ai_cog import CHANNEL_ID_ALLOWED

        assert CHANNEL_ID_ALLOWED is not None

    def test_channel_id_rp_command_import(self):
        """Test CHANNEL_ID_RP_COMMAND is imported."""
        from cogs.ai_core.ai_cog import CHANNEL_ID_RP_COMMAND

        assert CHANNEL_ID_RP_COMMAND is not None

    def test_channel_id_rp_output_import(self):
        """Test CHANNEL_ID_RP_OUTPUT is imported."""
        from cogs.ai_core.ai_cog import CHANNEL_ID_RP_OUTPUT

        assert CHANNEL_ID_RP_OUTPUT is not None

    def test_creator_id_import(self):
        """Test CREATOR_ID is imported."""
        from cogs.ai_core.ai_cog import CREATOR_ID

        assert CREATOR_ID is not None

    def test_guild_id_main_import(self):
        """Test GUILD_ID_MAIN is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_MAIN

        assert GUILD_ID_MAIN is not None

    def test_guild_id_rp_import(self):
        """Test GUILD_ID_RP is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_RP

        assert GUILD_ID_RP is not None

    def test_guild_id_restricted_import(self):
        """Test GUILD_ID_RESTRICTED is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_RESTRICTED

        assert GUILD_ID_RESTRICTED is not None

    def test_guild_id_command_only_import(self):
        """Test GUILD_ID_COMMAND_ONLY is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_COMMAND_ONLY

        assert GUILD_ID_COMMAND_ONLY is not None


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test ai_cog module has docstring."""
        from cogs.ai_core import ai_cog

        assert ai_cog.__doc__ is not None

    def test_module_docstring_mentions_discord(self):
        """Test ai_cog module docstring mentions Discord."""
        from cogs.ai_core import ai_cog

        assert "Discord" in ai_cog.__doc__


class TestUnrestrictedFunctions:
    """Tests for unrestricted fallback functions."""

    def test_is_unrestricted_callable(self):
        """Test is_unrestricted is callable."""
        from cogs.ai_core.ai_cog import is_unrestricted

        assert callable(is_unrestricted)

    def test_set_unrestricted_callable(self):
        """Test set_unrestricted is callable."""
        from cogs.ai_core.ai_cog import set_unrestricted

        assert callable(set_unrestricted)


class TestUnrestrictedChannels:
    """Tests for unrestricted_channels."""

    def test_unrestricted_channels_exists(self):
        """Test unrestricted_channels exists."""
        from cogs.ai_core.ai_cog import unrestricted_channels

        assert unrestricted_channels is not None


class TestFeedbackCollector:
    """Tests for feedback collector."""

    def test_add_feedback_reactions_callable(self):
        """Test add_feedback_reactions is callable."""
        from cogs.ai_core.ai_cog import add_feedback_reactions

        assert callable(add_feedback_reactions)
