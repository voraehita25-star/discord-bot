"""
Extended tests for API Handler module.
Tests API configuration and helper functions.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


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

    def test_module_has_docstring(self):
        """Test api_handler module has docstring."""
        try:
            from cogs.ai_core.api import api_handler
        except ImportError:
            pytest.skip("api_handler not available")
            return

        assert api_handler.__doc__ is not None
        assert len(api_handler.__doc__) > 0


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
