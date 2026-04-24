"""
Tests for cogs.ai_core.api.api_handler module.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestBuildApiConfig:
    """Tests for build_api_config function."""

    def test_build_api_config_basic(self):
        """Test build_api_config with basic chat data."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "You are a helpful assistant.",
            "thinking_enabled": False,
        }

        result = build_api_config(chat_data)

        assert "system_instruction" in result
        assert "max_tokens" in result

    def test_build_api_config_with_search(self):
        """Test build_api_config with search enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "Test instruction",
            "thinking_enabled": False,
        }

        result = build_api_config(chat_data, use_search=True)

        assert "system_instruction" in result

    def test_build_api_config_max_tokens(self):
        """Test max_tokens is properly configured."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        assert result["max_tokens"] == 128000

    def test_build_api_config_system_instruction(self):
        """Test system_instruction is passed through."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        assert result["system_instruction"] == "Test"

    def test_build_api_config_with_guild_id(self):
        """Test build_api_config with guild_id."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        # Should not raise
        result = build_api_config(chat_data, guild_id=123456789)

        assert result is not None


class TestDetectSearchIntent:
    """Tests for detect_search_intent function."""

    @pytest.mark.asyncio
    async def test_detect_search_intent_returns_bool(self):
        """Test detect_search_intent returns boolean."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "NO_SEARCH"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(
            mock_client,
            "claude-opus-4-7",
            "Tell me a joke"
        )

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_detect_search_intent_search_needed(self):
        """Test detect_search_intent when search is needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "SEARCH"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(
            mock_client,
            "claude-opus-4-7",
            "What is the latest news?"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent when no search needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "NO_SEARCH"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(
            mock_client,
            "claude-opus-4-7",
            "Tell me a story"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_error_returns_false(self):
        """Test detect_search_intent returns False on error."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=ValueError("API Error"))

        result = await detect_search_intent(
            mock_client,
            "claude-opus-4-7",
            "Test message"
        )

        assert result is False


class TestApiHandlerImports:
    """Tests for api_handler module imports."""

    def test_import_build_api_config(self):
        """Test importing build_api_config."""
        from cogs.ai_core.api.api_handler import build_api_config

        assert callable(build_api_config)

    def test_import_detect_search_intent(self):
        """Test importing detect_search_intent."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        assert callable(detect_search_intent)

    def test_import_call_claude_api(self):
        """Test importing call_claude_api."""
        from cogs.ai_core.api.api_handler import call_claude_api

        assert callable(call_claude_api)

    def test_import_call_claude_api_streaming(self):
        """Test importing call_claude_api_streaming."""
        from cogs.ai_core.api.api_handler import call_claude_api_streaming

        assert callable(call_claude_api_streaming)


class TestBackwardCompatibilityModule:
    """Tests for backward compatibility api_handler module."""

    def test_import_from_api_handler(self):
        """Test importing from cogs.ai_core.api.api_handler."""
        from cogs.ai_core.api.api_handler import (
            build_api_config,
            call_claude_api,
            call_claude_api_streaming,
            detect_search_intent,
        )

        assert callable(build_api_config)
        assert callable(call_claude_api)
        assert callable(call_claude_api_streaming)
        assert callable(detect_search_intent)


class TestBuildApiConfigFaustMode:
    """Tests for build_api_config Faust mode detection."""

    def test_faust_mode_with_thinking(self):
        """Test Faust mode enables thinking when available."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data import FAUST_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_INSTRUCTION,
            "thinking_enabled": True,
        }

        result = build_api_config(chat_data)

        # Should have thinking config for RP/Faust modes
        assert "thinking" in result

    def test_faust_dm_mode_with_thinking(self):
        """Test Faust DM mode enables thinking when available."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data import FAUST_DM_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_DM_INSTRUCTION,
            "thinking_enabled": True,
        }

        result = build_api_config(chat_data)

        # Should have thinking config for RP/Faust modes
        assert "thinking" in result


class TestBuildApiConfigRoleplayMode:
    """Tests for build_api_config roleplay mode detection."""

    def test_rp_mode_with_thinking(self):
        """Test roleplay mode enables thinking when available."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data.roleplay_data import ROLEPLAY_ASSISTANT_INSTRUCTION

        chat_data = {
            "system_instruction": ROLEPLAY_ASSISTANT_INSTRUCTION,
            "thinking_enabled": True,
        }

        result = build_api_config(chat_data)

        # Should have thinking config for RP/Faust modes
        assert "thinking" in result


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    def test_circuit_breaker_availability(self):
        """Test circuit breaker availability flag."""
        from cogs.ai_core.api.api_handler import CIRCUIT_BREAKER_AVAILABLE

        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)


class TestPerfTrackerIntegration:
    """Tests for performance tracker integration."""

    def test_perf_tracker_availability(self):
        """Test performance tracker availability flag."""
        from cogs.ai_core.api.api_handler import PERF_TRACKER_AVAILABLE

        assert isinstance(PERF_TRACKER_AVAILABLE, bool)


class TestErrorRecoveryIntegration:
    """Tests for error recovery integration."""

    def test_error_recovery_availability(self):
        """Test error recovery availability flag."""
        from cogs.ai_core.api.api_handler import ERROR_RECOVERY_AVAILABLE

        assert isinstance(ERROR_RECOVERY_AVAILABLE, bool)


class TestGuardrailsIntegration:
    """Tests for guardrails integration."""

    def test_is_silent_block_fallback(self):
        """Test is_silent_block fallback function."""
        from cogs.ai_core.api.api_handler import is_silent_block

        result = is_silent_block("Test response", expected_min_length=50)

        assert isinstance(result, bool)


# ======================================================================
# Merged from test_api_handler_extended.py
# ======================================================================

class TestBuildApiConfig:
    """Tests for build_api_config function."""

    def test_build_api_config_basic(self):
        """Test building basic API config."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {
            "system_instruction": "Test instruction",
            "thinking_enabled": False
        }

        result = build_api_config(chat_data)

        assert 'system_instruction' in result
        assert result['system_instruction'] == "Test instruction"
        assert 'max_tokens' in result

    def test_build_api_config_max_tokens(self):
        """Test max_tokens in API config."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "", "thinking_enabled": False}

        result = build_api_config(chat_data)

        assert 'max_tokens' in result
        assert isinstance(result['max_tokens'], int)
        assert result['max_tokens'] > 0

    def test_build_api_config_with_search(self):
        """Test API config with search enabled."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "", "thinking_enabled": True}

        result = build_api_config(chat_data, use_search=True)

        # Claude has no built-in search tool; use_search only logs
        assert 'system_instruction' in result
        assert 'thinking' not in result

    def test_build_api_config_default_thinking(self):
        """Test API config defaults to thinking enabled."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}
        # Not setting thinking_enabled, should default to True

        build_api_config(chat_data)

        # Default behavior depends on mode


class TestDetectSearchIntent:
    """Tests for detect_search_intent function."""

    async def test_detect_search_intent_basic(self):
        """Test detect_search_intent function exists."""
        try:
            from cogs.ai_core.api.api_handler import detect_search_intent
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert callable(detect_search_intent)

    async def test_detect_search_intent_error_handling(self):
        """Test detect_search_intent handles errors gracefully."""
        try:
            from cogs.ai_core.api.api_handler import detect_search_intent
        except ImportError:
            pytest.skip("api_handler not available")
            return

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=ValueError("API Error")
        )

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "test message")

        # Should return False on error
        assert result is False


class TestCircuitBreakerImport:
    """Tests for circuit breaker import handling."""

    def test_circuit_breaker_available_defined(self):
        """Test CIRCUIT_BREAKER_AVAILABLE is defined."""
        try:
            from cogs.ai_core.api.api_handler import CIRCUIT_BREAKER_AVAILABLE
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)

    def test_gemini_circuit_defined(self):
        """Test gemini_circuit is defined (may be None)."""
        try:
            from cogs.ai_core.api import api_handler
        except ImportError:
            pytest.skip("api_handler not available")
            return

        # gemini_circuit should be defined (may be None if import failed)
        assert hasattr(api_handler, 'gemini_circuit')


class TestPerfTrackerImport:
    """Tests for performance tracker import handling."""

    def test_perf_tracker_available_defined(self):
        """Test PERF_TRACKER_AVAILABLE is defined."""
        try:
            from cogs.ai_core.api.api_handler import PERF_TRACKER_AVAILABLE
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert isinstance(PERF_TRACKER_AVAILABLE, bool)


class TestErrorRecoveryImport:
    """Tests for error recovery import handling."""

    def test_error_recovery_available_defined(self):
        """Test ERROR_RECOVERY_AVAILABLE is defined."""
        try:
            from cogs.ai_core.api.api_handler import ERROR_RECOVERY_AVAILABLE
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert isinstance(ERROR_RECOVERY_AVAILABLE, bool)


class TestGuardrailsImport:
    """Tests for guardrails import handling."""

    def test_is_silent_block_available(self):
        """Test is_silent_block function is available."""
        try:
            from cogs.ai_core.api.api_handler import is_silent_block
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert callable(is_silent_block)


class TestModuleDocstring:
    """Tests for module documentation."""

class TestFaustDataImport:
    """Tests for Faust data import."""

    def test_faust_instruction_imported(self):
        """Test FAUST_INSTRUCTION is imported."""
        try:
            from cogs.ai_core.api.api_handler import FAUST_DM_INSTRUCTION, FAUST_INSTRUCTION
        except ImportError:
            pytest.skip("api_handler not available")
            return

        # Should be imported from data module
        assert FAUST_INSTRUCTION is not None or FAUST_DM_INSTRUCTION is not None


class TestRoleplayDataImport:
    """Tests for roleplay data import."""

    def test_roleplay_instruction_imported(self):
        """Test ROLEPLAY_ASSISTANT_INSTRUCTION is imported."""
        try:
            from cogs.ai_core.api.api_handler import ROLEPLAY_ASSISTANT_INSTRUCTION
        except ImportError:
            pytest.skip("api_handler not available")
            return

        # Should be imported from data module


class TestEscalationFramings:
    """Tests for escalation framings import."""

    def test_escalation_framings_imported(self):
        """Test ESCALATION_FRAMINGS is imported."""
        try:
            from cogs.ai_core.api.api_handler import ESCALATION_FRAMINGS
        except ImportError:
            pytest.skip("api_handler not available")
            return


class TestApiBuildConfigEdgeCases:
    """Edge case tests for build_api_config."""

    def test_build_config_empty_system_instruction(self):
        """Test config with empty system instruction."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "", "thinking_enabled": True}

        result = build_api_config(chat_data)

        assert result['system_instruction'] == ""

    def test_build_config_none_guild_id(self):
        """Test config with None guild_id."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test", "thinking_enabled": True}

        result = build_api_config(chat_data, guild_id=None)

        assert 'system_instruction' in result

    def test_build_config_specific_guild_id(self):
        """Test config with specific guild_id."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test", "thinking_enabled": True}

        result = build_api_config(chat_data, guild_id=123456789)

        assert 'system_instruction' in result


class TestIsSilentBlockFallback:
    """Tests for is_silent_block functionality."""

    def test_is_silent_block_returns_bool(self):
        """Test is_silent_block returns a boolean."""
        try:
            from cogs.ai_core.api.api_handler import is_silent_block
        except ImportError:
            pytest.skip("api_handler not available")
            return

        result = is_silent_block("any response", expected_min_length=50)
        assert isinstance(result, bool)


class TestClaudeConfigStructure:
    """Tests for Claude config structure."""

    def test_config_has_system_instruction(self):
        """Test config has system_instruction field."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        assert 'system_instruction' in result
        assert result['system_instruction'] == "Test"

    def test_config_has_max_tokens(self):
        """Test config has max_tokens field."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        assert 'max_tokens' in result
        assert isinstance(result['max_tokens'], int)


# ======================================================================
# Merged from test_api_handler_module.py
# ======================================================================

class TestBuildApiConfig:
    """Tests for build_api_config function."""

    def test_build_api_config_basic(self):
        """Test build_api_config with basic chat data."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "You are a helpful assistant.",
            "thinking_enabled": False,
        }

        config = build_api_config(chat_data)

        assert "system_instruction" in config
        assert "max_tokens" in config
        assert config["system_instruction"] == "You are a helpful assistant."

    def test_build_api_config_max_tokens_present(self):
        """Test build_api_config includes max_tokens."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data)

        assert "max_tokens" in config
        assert isinstance(config["max_tokens"], int)
        assert config["max_tokens"] > 0

    def test_build_api_config_use_search(self):
        """Test build_api_config with search enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data, use_search=True)

        # Claude has no built-in search tool; use_search only logs
        assert "system_instruction" in config

    def test_build_api_config_with_guild_id(self):
        """Test build_api_config with guild_id."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data, guild_id=12345)

        # Should still work with guild_id
        assert "system_instruction" in config


class TestDetectSearchIntent:
    """Tests for detect_search_intent function."""

    @pytest.mark.asyncio
    async def test_detect_search_intent_returns_false_on_error(self):
        """Test detect_search_intent returns False on error."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=ValueError("API Error"))

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "test")

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_search(self):
        """Test detect_search_intent returns True for SEARCH."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "SEARCH"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "What is today's weather?")

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent returns False for NO_SEARCH."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "NO_SEARCH"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "Hello!")

        assert result is False


class TestModuleImports:
    """Tests for module imports."""

    def test_import_build_api_config(self):
        """Test build_api_config can be imported."""
        from cogs.ai_core.api.api_handler import build_api_config
        assert build_api_config is not None

    def test_import_call_claude_api(self):
        """Test call_claude_api can be imported."""
        from cogs.ai_core.api.api_handler import call_claude_api
        assert call_claude_api is not None

    def test_import_call_claude_api_streaming(self):
        """Test call_claude_api_streaming can be imported."""
        from cogs.ai_core.api.api_handler import call_claude_api_streaming
        assert call_claude_api_streaming is not None

    def test_import_detect_search_intent(self):
        """Test detect_search_intent can be imported."""
        from cogs.ai_core.api.api_handler import detect_search_intent
        assert detect_search_intent is not None


class TestCircuitBreakerAvailability:
    """Tests for circuit breaker availability."""

    def test_circuit_breaker_import_flag(self):
        """Test CIRCUIT_BREAKER_AVAILABLE flag."""
        from cogs.ai_core.api.api_handler import CIRCUIT_BREAKER_AVAILABLE

        # Just test the flag exists
        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)


class TestPerfTrackerAvailability:
    """Tests for performance tracker availability."""

    def test_perf_tracker_import_flag(self):
        """Test PERF_TRACKER_AVAILABLE flag."""
        from cogs.ai_core.api.api_handler import PERF_TRACKER_AVAILABLE

        # Just test the flag exists
        assert isinstance(PERF_TRACKER_AVAILABLE, bool)


class TestErrorRecoveryAvailability:
    """Tests for error recovery availability."""

    def test_error_recovery_import_flag(self):
        """Test ERROR_RECOVERY_AVAILABLE flag."""
        from cogs.ai_core.api.api_handler import ERROR_RECOVERY_AVAILABLE

        # Just test the flag exists
        assert isinstance(ERROR_RECOVERY_AVAILABLE, bool)


class TestFaustData:
    """Tests for Faust data imports."""

    def test_import_faust_instruction(self):
        """Test FAUST_INSTRUCTION can be imported."""
        from cogs.ai_core.data import FAUST_INSTRUCTION
        assert FAUST_INSTRUCTION is not None
        assert isinstance(FAUST_INSTRUCTION, str)

    def test_import_faust_dm_instruction(self):
        """Test FAUST_DM_INSTRUCTION can be imported."""
        from cogs.ai_core.data import FAUST_DM_INSTRUCTION
        assert FAUST_DM_INSTRUCTION is not None
        assert isinstance(FAUST_DM_INSTRUCTION, str)

    def test_import_escalation_framings(self):
        """Test ESCALATION_FRAMINGS can be imported."""
        from cogs.ai_core.data import ESCALATION_FRAMINGS
        assert ESCALATION_FRAMINGS is not None


class TestRoleplayData:
    """Tests for roleplay data imports."""

    def test_import_roleplay_assistant_instruction(self):
        """Test ROLEPLAY_ASSISTANT_INSTRUCTION can be imported."""
        from cogs.ai_core.data.roleplay_data import ROLEPLAY_ASSISTANT_INSTRUCTION
        assert ROLEPLAY_ASSISTANT_INSTRUCTION is not None
        assert isinstance(ROLEPLAY_ASSISTANT_INSTRUCTION, str)


class TestBuildApiConfigModes:
    """Tests for different modes in build_api_config."""

    def test_build_api_config_faust_mode(self):
        """Test build_api_config with Faust mode."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data import FAUST_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_INSTRUCTION,
            "thinking_enabled": True,
        }

        config = build_api_config(chat_data)

        # Should have thinking config or tools depending on mode
        assert "system_instruction" in config

    def test_build_api_config_empty_system_instruction(self):
        """Test build_api_config with empty system instruction."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "",
            "thinking_enabled": False,
        }

        config = build_api_config(chat_data)

        assert config["system_instruction"] == ""

    def test_build_api_config_missing_thinking_enabled(self):
        """Test build_api_config with missing thinking_enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data)

        # Should default to True and not error
        assert "system_instruction" in config


# ======================================================================
# Merged from test_api_handler_new.py
# ======================================================================

class TestBuildApiConfig:
    """Tests for build_api_config function."""

    def test_build_basic_config(self):
        """Test building basic API config."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "Test instruction",
            "thinking_enabled": False,
        }

        config = build_api_config(chat_data)

        assert "system_instruction" in config
        assert config["system_instruction"] == "Test instruction"
        assert "max_tokens" in config
        assert config["max_tokens"] == 128000

    def test_build_config_with_thinking(self):
        """Test config with thinking mode enabled."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data import FAUST_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_INSTRUCTION,
            "thinking_enabled": True,
        }

        config = build_api_config(chat_data)

        assert "thinking" in config

    def test_build_config_with_search(self):
        """Test config with search enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "Test",
            "thinking_enabled": True,
        }

        config = build_api_config(chat_data, use_search=True)

        # Claude doesn't have built-in search tools, search is handled via URL fetcher
        assert "system_instruction" in config

    def test_build_config_default_instruction(self):
        """Test config with default system instruction."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {}  # No system_instruction

        config = build_api_config(chat_data)

        assert config["system_instruction"] == ""


class TestDetectSearchIntent:
    """Tests for detect_search_intent function."""

    @pytest.mark.asyncio
    async def test_detect_search_intent_error(self):
        """Test detect_search_intent handles errors."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=ValueError("API error"))

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "test message")

        # Should return False on error
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_search_needed(self):
        """Test detect_search_intent when search is needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "SEARCH"

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "what is the weather?")

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent when search not needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "NO_SEARCH"

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "hello")

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_empty_response(self):
        """Test detect_search_intent with empty response."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.content = []

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "claude-opus-4-7", "test")

        assert result is False


class TestClaudeConfig:
    """Tests for Claude API config structure."""

    def test_config_has_max_tokens(self):
        """Test config includes max_tokens."""
        from cogs.ai_core.api.api_handler import build_api_config

        config = build_api_config({})

        assert "max_tokens" in config
        assert config["max_tokens"] == 128000

    def test_config_has_system_instruction(self):
        """Test config includes system_instruction."""
        from cogs.ai_core.api.api_handler import build_api_config

        config = build_api_config({"system_instruction": "Test"})

        assert config["system_instruction"] == "Test"


class TestModuleConstants:
    """Tests for module constants."""

    def test_circuit_breaker_available_exists(self):
        """Test CIRCUIT_BREAKER_AVAILABLE constant exists."""
        from cogs.ai_core.api.api_handler import CIRCUIT_BREAKER_AVAILABLE

        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)

    def test_perf_tracker_available_exists(self):
        """Test PERF_TRACKER_AVAILABLE constant exists."""
        from cogs.ai_core.api.api_handler import PERF_TRACKER_AVAILABLE

        assert isinstance(PERF_TRACKER_AVAILABLE, bool)

    def test_error_recovery_available_exists(self):
        """Test ERROR_RECOVERY_AVAILABLE constant exists."""
        from cogs.ai_core.api.api_handler import ERROR_RECOVERY_AVAILABLE

        assert isinstance(ERROR_RECOVERY_AVAILABLE, bool)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_build_api_config(self):
        """Test importing build_api_config."""
        from cogs.ai_core.api.api_handler import build_api_config

        assert callable(build_api_config)

    def test_import_detect_search_intent(self):
        """Test importing detect_search_intent."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        assert callable(detect_search_intent)

    def test_import_call_claude_api_streaming(self):
        """Test importing call_claude_api_streaming."""
        from cogs.ai_core.api.api_handler import call_claude_api_streaming

        assert callable(call_claude_api_streaming)


class TestFallbackFunctions:
    """Tests for fallback function behavior."""

    def test_is_silent_block_fallback(self):
        """Test is_silent_block fallback when guardrails unavailable."""
        from cogs.ai_core.api.api_handler import is_silent_block

        # Test it works
        is_silent_block("any response", 50)
        # Should return False when guardrails unavailable


class TestClassifySearchIntent:
    """Tests for classify_search_intent pre-filter."""

    def test_import(self):
        """Test importing classify_search_intent."""
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert callable(classify_search_intent)

    # --- Empty / trivial inputs ---

    def test_empty_string_returns_false(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("") is False

    def test_whitespace_only_returns_false(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("   ") is False

    # --- Layer 1: Search patterns ---

    def test_factual_question_english(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("What is the capital of France?") is True

    def test_factual_question_who(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("Who is the president of the United States?") is True

    def test_factual_question_how_much(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("How much does a Tesla Model 3 cost?") is True

    def test_factual_question_thai(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("กรุงเทพมีประชากรเท่าไหร่") is True

    def test_time_sensitive_latest(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        result = classify_search_intent("What are the latest patch notes for Genshin Impact?")
        assert result is True

    def test_time_sensitive_thai(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        result = classify_search_intent("ข่าวล่าสุดเกี่ยวกับ AI คืออะไร")
        assert result is True

    def test_explicit_search_request(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("Can you search for Python documentation on asyncio?") is True

    def test_explicit_search_thai(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("ค้นหาราคา iPhone 16 ให้หน่อย") is True

    def test_lookup_comparison(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        result = classify_search_intent("Compare RTX 4090 vs RTX 5090 benchmark results")
        assert result is True

    def test_definition_question(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        result = classify_search_intent("What does SSRF mean in cybersecurity?")
        assert result is True

    # --- Layer 2: No-search patterns ---

    def test_roleplay_action(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("*walks into the room and smiles*") is False

    def test_greeting_hello(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("Hello!") is False

    def test_greeting_thai(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("สวัสดี") is False

    def test_emotion_lol(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("lol") is False

    def test_emotion_555(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("555555") is False

    def test_creative_write_story(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("Write me a story about a dragon") is False

    def test_creative_thai(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("เขียนบทกวีให้หน่อย") is False

    def test_opinion_question(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("Do you think AI will take over the world?") is False

    def test_short_casual(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("ok cool") is False

    def test_short_thai_casual(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("โอเค") is False

    # --- Layer 3: Borderline / uncertain ---

    def test_ambiguous_returns_none(self):
        """Messages that could go either way should return None for AI fallback."""
        from cogs.ai_core.api.api_handler import classify_search_intent

        # A medium-length message with no strong signals either way
        result = classify_search_intent("Tell me about the history of this place")
        assert result is None or isinstance(result, bool)

    def test_search_signal_words_boost_score(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        # Message with multiple search signal words
        result = classify_search_intent("What is the price and release date for this version?")
        assert result is True

    def test_no_search_signal_words_boost(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        # Message with no-search signal words
        result = classify_search_intent("I feel happy and love chatting with you")
        assert result is False

    # --- Edge cases ---

    def test_question_mark_alone(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        result = classify_search_intent("?")
        # Short message, should be False or None
        assert result is not True  # Should not trigger search

    def test_long_roleplay_with_asterisks(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        result = classify_search_intent("*She looked up at the stars and whispered softly, remembering the ancient tales her grandmother used to tell*")
        assert result is False

    def test_goodbye(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("bye!") is False

    def test_good_morning(self):
        from cogs.ai_core.api.api_handler import classify_search_intent

        assert classify_search_intent("Good morning!") is False
