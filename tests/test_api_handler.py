"""
Tests for cogs.ai_core.api.api_handler module.
"""

from unittest.mock import AsyncMock, MagicMock, patch

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
            "gemini-3-pro-preview",
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
            "gemini-3-pro-preview",
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
            "gemini-3-pro-preview",
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
            "gemini-3-pro-preview",
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
        """Test importing from cogs.ai_core.api_handler."""
        from cogs.ai_core.api_handler import (
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
