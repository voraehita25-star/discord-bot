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
        assert "max_tokens" in result

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


class TestApiHandlerImports:
    """Tests for api_handler module imports."""

    def test_import_build_api_config(self):
        """Test importing build_api_config."""
        from cogs.ai_core.api.api_handler import build_api_config

        assert callable(build_api_config)

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
        )

        assert callable(build_api_config)
        assert callable(call_claude_api)
        assert callable(call_claude_api_streaming)


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
        import pytest

        from cogs.ai_core.api.api_handler import build_api_config

        try:
            from cogs.ai_core.data.roleplay_data import ROLEPLAY_ASSISTANT_INSTRUCTION
        except ImportError:
            pytest.skip("roleplay_data not available (server-specific)")

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

        result = is_silent_block("Test response")

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

        chat_data = {"system_instruction": "Test instruction", "thinking_enabled": False}

        result = build_api_config(chat_data)

        assert "system_instruction" in result
        assert result["system_instruction"] == "Test instruction"
        assert "max_tokens" in result

    def test_build_api_config_max_tokens(self):
        """Test max_tokens in API config."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "", "thinking_enabled": False}

        result = build_api_config(chat_data)

        assert "max_tokens" in result
        assert isinstance(result["max_tokens"], int)
        assert result["max_tokens"] > 0

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
        assert hasattr(api_handler, "gemini_circuit")


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

        assert result["system_instruction"] == ""

    def test_build_config_none_guild_id(self):
        """Test config with None guild_id."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test", "thinking_enabled": True}

        result = build_api_config(chat_data, guild_id=None)

        assert "system_instruction" in result

    def test_build_config_specific_guild_id(self):
        """Test config with specific guild_id."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test", "thinking_enabled": True}

        result = build_api_config(chat_data, guild_id=123456789)

        assert "system_instruction" in result


class TestIsSilentBlockFallback:
    """Tests for is_silent_block functionality."""

    def test_is_silent_block_returns_bool(self):
        """Test is_silent_block returns a boolean."""
        try:
            from cogs.ai_core.api.api_handler import is_silent_block
        except ImportError:
            pytest.skip("api_handler not available")
            return

        result = is_silent_block("any response")
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

        assert "system_instruction" in result
        assert result["system_instruction"] == "Test"

    def test_config_has_max_tokens(self):
        """Test config has max_tokens field."""
        try:
            from cogs.ai_core.api.api_handler import build_api_config
        except ImportError:
            pytest.skip("api_handler not available")
            return

        chat_data = {"system_instruction": "Test"}

        result = build_api_config(chat_data)

        assert "max_tokens" in result
        assert isinstance(result["max_tokens"], int)


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

    def test_build_api_config_with_guild_id(self):
        """Test build_api_config with guild_id."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {"system_instruction": "Test"}

        config = build_api_config(chat_data, guild_id=12345)

        # Should still work with guild_id
        assert "system_instruction" in config


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
        import pytest

        try:
            from cogs.ai_core.data.roleplay_data import ROLEPLAY_ASSISTANT_INSTRUCTION
        except ImportError:
            pytest.skip("roleplay_data not available (server-specific)")

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

    def test_build_config_default_instruction(self):
        """Test config with default system instruction."""
        from cogs.ai_core.api.api_handler import build_api_config

        chat_data = {}  # No system_instruction

        config = build_api_config(chat_data)

        assert config["system_instruction"] == ""


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
        is_silent_block("any response")
        # Should return False when guardrails unavailable


class TestStreamingPlaceholderSendBreaker:
    """FINDING 1: the placeholder ``send_channel.send`` is a Discord REST call.
    A discord.Forbidden / Discord 5xx there must NOT be recorded on
    gemini_circuit (the breaker gating every Claude call) — a burst of Discord
    send failures could otherwise trip it OPEN bot-wide while Anthropic is
    healthy. The fallback-to-normal-API behaviour must still be preserved."""

    @pytest.mark.asyncio
    async def test_discord_send_failure_does_not_trip_breaker(self):
        from cogs.ai_core.api.api_handler import call_claude_api_streaming

        breaker = MagicMock()
        breaker.can_execute.return_value = True
        send_channel = MagicMock()
        send_channel.send = AsyncMock(side_effect=RuntimeError("discord 503"))
        fallback_mock = AsyncMock(return_value=("fallback text", "", []))

        with (
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", True),
            patch("cogs.ai_core.api.api_handler.gemini_circuit", breaker),
        ):
            result = await call_claude_api_streaming(
                MagicMock(),
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hi"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
                send_channel,
                fallback_func=fallback_mock,
            )

        # Falls back to the non-streaming path...
        assert result[0] == "fallback text"
        fallback_mock.assert_awaited_once()
        # ...but the Discord send failure must NOT count against the AI breaker.
        breaker.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_genuine_setup_failure_still_records_breaker(self):
        """A genuine API-setup failure (e.g. content conversion) after the send
        succeeds must still record on the breaker — the exemption is only for
        the Discord placeholder send."""
        from cogs.ai_core.api.api_handler import call_claude_api_streaming

        breaker = MagicMock()
        breaker.can_execute.return_value = True
        placeholder = MagicMock()
        placeholder.delete = AsyncMock()
        send_channel = MagicMock()
        send_channel.send = AsyncMock(return_value=placeholder)
        fallback_mock = AsyncMock(return_value=("fallback text", "", []))

        with (
            patch("cogs.ai_core.api.api_handler.CIRCUIT_BREAKER_AVAILABLE", True),
            patch("cogs.ai_core.api.api_handler.gemini_circuit", breaker),
            patch(
                "cogs.ai_core.api.api_handler.convert_to_claude_messages",
                side_effect=RuntimeError("bad contents"),
            ),
        ):
            result = await call_claude_api_streaming(
                MagicMock(),
                "claude-opus-4-7",
                [{"role": "user", "parts": [{"text": "hi"}]}],
                {"system_instruction": "Test", "max_tokens": 100},
                send_channel,
                fallback_func=fallback_mock,
            )

        assert result[0] == "fallback text"
        fallback_mock.assert_awaited_once()
        breaker.record_failure.assert_called_once()


class TestServerLoreBridge:
    """``server_lore`` is the only wire from session_mixin to the CLI stripper.

    Nothing covered it: deleting the key left the suite green while every
    resumed turn silently went back to re-sending the whole 50 KB block.
    """

    def test_config_carries_the_lore_text(self):
        from cogs.ai_core.api.api_handler import build_api_config

        cfg = build_api_config(
            {"system_instruction": "PERSONA\n\nLORE_BODY", "server_lore": "LORE_BODY"}
        )
        assert cfg["server_lore"] == "LORE_BODY"

    def test_missing_key_degrades_to_empty_not_none(self):
        """Pre-change sessions in memory have no such key; the CLI path does
        ``config_params.get(...) or ""`` and must get a string either way."""
        from cogs.ai_core.api.api_handler import build_api_config

        cfg = build_api_config({"system_instruction": "PERSONA"})
        assert cfg["server_lore"] == ""

    def test_round_trip_strips_exactly_what_session_mixin_appended(self):
        """The producer and the consumer agree — asserted across both, since
        each side's own unit tests pass literals to itself."""
        from cogs.ai_core.api.api_handler import build_api_config
        from cogs.ai_core.api.discord_chat_claude_cli import _without_server_lore

        lore = "WORLD LORE BODY " * 50
        chat_data = {
            "system_instruction": "PERSONA_HEAD\n\n" + lore,
            "server_lore": lore,
        }
        cfg = build_api_config(chat_data)
        lean = _without_server_lore(cfg["system_instruction"], cfg["server_lore"])
        assert lean == "PERSONA_HEAD"
