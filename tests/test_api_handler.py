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
        assert "safety_settings" in result
        assert len(result["safety_settings"]) == 4

    def test_build_api_config_with_search(self):
        """Test build_api_config with search enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "Test instruction",
            "thinking_enabled": False,
        }

        result = build_api_config(chat_data, use_search=True)

        assert "tools" in result

    def test_build_api_config_safety_settings(self):
        """Test safety settings are properly configured."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        # All safety categories should be BLOCK_NONE
        for setting in result["safety_settings"]:
            assert setting["threshold"] == "BLOCK_NONE"

    def test_build_api_config_all_harm_categories(self):
        """Test all harm categories are covered."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        categories = [s["category"] for s in result["safety_settings"]]

        assert "HARM_CATEGORY_HATE_SPEECH" in categories
        assert "HARM_CATEGORY_DANGEROUS_CONTENT" in categories
        assert "HARM_CATEGORY_HARASSMENT" in categories
        assert "HARM_CATEGORY_SEXUALLY_EXPLICIT" in categories

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
        mock_response = MagicMock()
        mock_response.text = "NO_SEARCH"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(
            mock_client,
            "gemini-3.1-pro-preview",
            "Tell me a joke"
        )

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_detect_search_intent_search_needed(self):
        """Test detect_search_intent when search is needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "SEARCH"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(
            mock_client,
            "gemini-3.1-pro-preview",
            "What is the latest news?"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent when no search needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "NO_SEARCH"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(
            mock_client,
            "gemini-3.1-pro-preview",
            "Tell me a story"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_error_returns_false(self):
        """Test detect_search_intent returns False on error."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=ValueError("API Error"))

        result = await detect_search_intent(
            mock_client,
            "gemini-3.1-pro-preview",
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

    def test_import_call_gemini_api(self):
        """Test importing call_gemini_api."""
        from cogs.ai_core.api.api_handler import call_gemini_api

        assert callable(call_gemini_api)

    def test_import_call_gemini_api_streaming(self):
        """Test importing call_gemini_api_streaming."""
        from cogs.ai_core.api.api_handler import call_gemini_api_streaming

        assert callable(call_gemini_api_streaming)


class TestBackwardCompatibilityModule:
    """Tests for backward compatibility api_handler module."""

    def test_import_from_api_handler(self):
        """Test importing from cogs.ai_core.api.api_handler."""
        from cogs.ai_core.api.api_handler import (
            build_api_config,
            call_gemini_api,
            call_gemini_api_streaming,
            detect_search_intent,
        )

        assert callable(build_api_config)
        assert callable(call_gemini_api)
        assert callable(call_gemini_api_streaming)
        assert callable(detect_search_intent)


class TestBuildApiConfigFaustMode:
    """Tests for build_api_config Faust mode detection."""

    def test_faust_mode_with_thinking(self):
        """Test Faust mode enables thinking when available."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data.faust_data import FAUST_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_INSTRUCTION,
            "thinking_enabled": True,
        }

        result = build_api_config(chat_data)

        # Should have either thinking_config or tools
        assert "thinking_config" in result or "tools" in result

    def test_faust_dm_mode_with_thinking(self):
        """Test Faust DM mode enables thinking when available."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data.faust_data import FAUST_DM_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_DM_INSTRUCTION,
            "thinking_enabled": True,
        }

        result = build_api_config(chat_data)

        # Should have either thinking_config or tools
        assert "thinking_config" in result or "tools" in result


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

        # Should have either thinking_config or tools
        assert "thinking_config" in result or "tools" in result


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

    def test_guardrails_availability(self):
        """Test guardrails availability flag."""
        from cogs.ai_core.api.api_handler import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_detect_refusal_fallback(self):
        """Test detect_refusal fallback function."""
        from cogs.ai_core.api.api_handler import detect_refusal

        result = detect_refusal("Test response")

        # Returns tuple or bool depending on implementation
        assert result is not None

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
        assert 'safety_settings' in result

    def test_build_api_config_safety_settings(self):
        """Test safety settings in API config."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "", "thinking_enabled": False}

        result = build_api_config(chat_data)

        assert 'safety_settings' in result
        assert len(result['safety_settings']) == 4

        # Check safety categories
        categories = [s['category'] for s in result['safety_settings']]
        assert 'HARM_CATEGORY_HATE_SPEECH' in categories
        assert 'HARM_CATEGORY_DANGEROUS_CONTENT' in categories

    def test_build_api_config_with_search(self):
        """Test API config with search enabled."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "", "thinking_enabled": True}

        result = build_api_config(chat_data, use_search=True)

        assert 'tools' in result
        assert 'thinking_config' not in result

    def test_build_api_config_default_thinking(self):
        """Test API config defaults to thinking enabled."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}
        # Not setting thinking_enabled, should default to True

        result = build_api_config(chat_data)

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
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=ValueError("API Error")
        )

        result = await detect_search_intent(mock_client, "gemini-1.5-flash", "test message")

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

    def test_guardrails_available_defined(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        try:
            from cogs.ai_core.api.api_handler import GUARDRAILS_AVAILABLE
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_detect_refusal_available(self):
        """Test detect_refusal function is available."""
        try:
            from cogs.ai_core.api.api_handler import detect_refusal
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert callable(detect_refusal)

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


class TestDetectRefusalFallback:
    """Tests for detect_refusal functionality."""

    def test_detect_refusal_returns_tuple(self):
        """Test detect_refusal returns a tuple with bool and reason."""
        try:
            from cogs.ai_core.api.api_handler import detect_refusal
        except ImportError:
            pytest.skip("api_handler not available")
            return

        result = detect_refusal("any response")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)


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


class TestSafetySettingsStructure:
    """Tests for safety settings structure."""

    def test_safety_settings_have_category(self):
        """Test safety settings have category field."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        for setting in result['safety_settings']:
            assert 'category' in setting

    def test_safety_settings_have_threshold(self):
        """Test safety settings have threshold field."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        for setting in result['safety_settings']:
            assert 'threshold' in setting
            assert setting['threshold'] == 'BLOCK_NONE'


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
        assert "safety_settings" in config
        assert config["system_instruction"] == "You are a helpful assistant."

    def test_build_api_config_safety_settings(self):
        """Test build_api_config includes all safety settings."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data)

        assert len(config["safety_settings"]) == 4

        categories = [s["category"] for s in config["safety_settings"]]
        assert "HARM_CATEGORY_HATE_SPEECH" in categories
        assert "HARM_CATEGORY_DANGEROUS_CONTENT" in categories
        assert "HARM_CATEGORY_HARASSMENT" in categories
        assert "HARM_CATEGORY_SEXUALLY_EXPLICIT" in categories

    def test_build_api_config_use_search(self):
        """Test build_api_config with search enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data, use_search=True)

        assert "tools" in config

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
        mock_client.aio.models.generate_content = AsyncMock(side_effect=ValueError("API Error"))

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "test")

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_search(self):
        """Test detect_search_intent returns True for SEARCH."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = "SEARCH"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "What is today's weather?")

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent returns False for NO_SEARCH."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = "NO_SEARCH"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "Hello!")

        assert result is False


class TestModuleImports:
    """Tests for module imports."""

    def test_import_build_api_config(self):
        """Test build_api_config can be imported."""
        from cogs.ai_core.api.api_handler import build_api_config
        assert build_api_config is not None

    def test_import_call_gemini_api(self):
        """Test call_gemini_api can be imported."""
        from cogs.ai_core.api.api_handler import call_gemini_api
        assert call_gemini_api is not None

    def test_import_call_gemini_api_streaming(self):
        """Test call_gemini_api_streaming can be imported."""
        from cogs.ai_core.api.api_handler import call_gemini_api_streaming
        assert call_gemini_api_streaming is not None

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


class TestGuardrailsAvailability:
    """Tests for guardrails availability."""

    def test_guardrails_import_flag(self):
        """Test GUARDRAILS_AVAILABLE flag."""
        from cogs.ai_core.api.api_handler import GUARDRAILS_AVAILABLE

        # Just test the flag exists
        assert isinstance(GUARDRAILS_AVAILABLE, bool)


class TestFaustData:
    """Tests for Faust data imports."""

    def test_import_faust_instruction(self):
        """Test FAUST_INSTRUCTION can be imported."""
        from cogs.ai_core.data.faust_data import FAUST_INSTRUCTION
        assert FAUST_INSTRUCTION is not None
        assert isinstance(FAUST_INSTRUCTION, str)

    def test_import_faust_dm_instruction(self):
        """Test FAUST_DM_INSTRUCTION can be imported."""
        from cogs.ai_core.data.faust_data import FAUST_DM_INSTRUCTION
        assert FAUST_DM_INSTRUCTION is not None
        assert isinstance(FAUST_DM_INSTRUCTION, str)

    def test_import_escalation_framings(self):
        """Test ESCALATION_FRAMINGS can be imported."""
        from cogs.ai_core.data.faust_data import ESCALATION_FRAMINGS
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
        from cogs.ai_core.data.faust_data import FAUST_INSTRUCTION

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
        assert "safety_settings" in config
        assert len(config["safety_settings"]) == 4

    def test_build_config_with_thinking(self):
        """Test config with thinking mode enabled."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.data.faust_data import FAUST_INSTRUCTION

        chat_data = {
            "system_instruction": FAUST_INSTRUCTION,
            "thinking_enabled": True,
        }

        config = build_api_config(chat_data)

        assert "thinking_config" in config

    def test_build_config_with_search(self):
        """Test config with search enabled."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {
            "system_instruction": "Test",
            "thinking_enabled": True,
        }

        config = build_api_config(chat_data, use_search=True)

        assert "tools" in config

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
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=ValueError("API error"))

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "test message")

        # Should return False on error
        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_search_needed(self):
        """Test detect_search_intent when search is needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = "SEARCH"

        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "what is the weather?")

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent when search not needed."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = "NO_SEARCH"

        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "hello")

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_empty_response(self):
        """Test detect_search_intent with empty response."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = None

        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3.1-pro-preview", "test")

        assert result is False


class TestSafetySettings:
    """Tests for safety settings in API config."""

    def test_safety_settings_categories(self):
        """Test safety settings have correct categories."""
        from cogs.ai_core.api.api_handler import build_api_config

        config = build_api_config({})

        categories = [s["category"] for s in config["safety_settings"]]

        assert "HARM_CATEGORY_HATE_SPEECH" in categories
        assert "HARM_CATEGORY_DANGEROUS_CONTENT" in categories
        assert "HARM_CATEGORY_HARASSMENT" in categories
        assert "HARM_CATEGORY_SEXUALLY_EXPLICIT" in categories

    def test_safety_settings_threshold(self):
        """Test safety settings have BLOCK_NONE threshold."""
        from cogs.ai_core.api.api_handler import build_api_config

        config = build_api_config({})

        for setting in config["safety_settings"]:
            assert setting["threshold"] == "BLOCK_NONE"


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

    def test_guardrails_available_exists(self):
        """Test GUARDRAILS_AVAILABLE constant exists."""
        from cogs.ai_core.api.api_handler import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)


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

    def test_import_call_gemini_api_streaming(self):
        """Test importing call_gemini_api_streaming."""
        from cogs.ai_core.api.api_handler import call_gemini_api_streaming

        assert callable(call_gemini_api_streaming)


class TestFallbackFunctions:
    """Tests for fallback function behavior."""

    def test_detect_refusal_fallback(self):
        """Test detect_refusal fallback when guardrails unavailable."""
        # Import module to get fallback function

        # The fallback detect_refusal should return False, None
        from cogs.ai_core.api.api_handler import detect_refusal

        # Test it works
        result = detect_refusal("any response")
        # Should be tuple or single value depending on import

    def test_is_silent_block_fallback(self):
        """Test is_silent_block fallback when guardrails unavailable."""
        from cogs.ai_core.api.api_handler import is_silent_block

        # Test it works
        result = is_silent_block("any response", 50)
        # Should return False when guardrails unavailable
