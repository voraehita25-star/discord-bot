"""Tests for API handler module."""

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

        result = await detect_search_intent(mock_client, "gemini-3-pro-preview", "test")

        assert result is False

    @pytest.mark.asyncio
    async def test_detect_search_intent_search(self):
        """Test detect_search_intent returns True for SEARCH."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = "SEARCH"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3-pro-preview", "What is today's weather?")

        assert result is True

    @pytest.mark.asyncio
    async def test_detect_search_intent_no_search(self):
        """Test detect_search_intent returns False for NO_SEARCH."""
        from cogs.ai_core.api.api_handler import detect_search_intent

        mock_response = MagicMock()
        mock_response.text = "NO_SEARCH"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await detect_search_intent(mock_client, "gemini-3-pro-preview", "Hello!")

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
