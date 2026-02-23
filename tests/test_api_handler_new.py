"""Tests for api_handler module."""

from unittest.mock import AsyncMock, MagicMock

import pytest


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

        result = await detect_search_intent(
            mock_client, "gemini-3.1-pro-preview", "what is the weather?"
        )

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
        detect_refusal("any response")
        # Should be tuple or single value depending on import

    def test_is_silent_block_fallback(self):
        """Test is_silent_block fallback when guardrails unavailable."""
        from cogs.ai_core.api.api_handler import is_silent_block

        # Test it works
        is_silent_block("any response", 50)
        # Should return False when guardrails unavailable
