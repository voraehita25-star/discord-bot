"""
Tests for cogs.ai_core.fallback_responses module.
"""

from unittest.mock import patch


class TestFallbackReason:
    """Tests for FallbackReason enum."""

    def test_all_reasons_have_values(self):
        """Test that all fallback reasons have string values."""
        from cogs.ai_core.fallback_responses import FallbackReason

        assert FallbackReason.API_TIMEOUT.value == "api_timeout"
        assert FallbackReason.API_ERROR.value == "api_error"
        assert FallbackReason.CIRCUIT_OPEN.value == "circuit_open"
        assert FallbackReason.RATE_LIMITED.value == "rate_limited"
        assert FallbackReason.CONTEXT_TOO_LONG.value == "context_too_long"
        assert FallbackReason.UNKNOWN.value == "unknown"


class TestFallbackResponse:
    """Tests for FallbackResponse dataclass."""

    def test_create_with_defaults(self):
        """Test creating FallbackResponse with defaults."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackResponse

        response = FallbackResponse(
            message="Test message",
            reason=FallbackReason.UNKNOWN
        )

        assert response.message == "Test message"
        assert response.reason == FallbackReason.UNKNOWN
        assert response.should_retry is True
        assert response.retry_after_seconds is None

    def test_create_with_all_fields(self):
        """Test creating FallbackResponse with all fields."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackResponse

        response = FallbackResponse(
            message="Rate limited",
            reason=FallbackReason.RATE_LIMITED,
            should_retry=True,
            retry_after_seconds=30.0
        )

        assert response.message == "Rate limited"
        assert response.reason == FallbackReason.RATE_LIMITED
        assert response.should_retry is True
        assert response.retry_after_seconds == 30.0


class TestFallbackSystem:
    """Tests for FallbackSystem class."""

    def test_init(self):
        """Test FallbackSystem initialization."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()

        assert system._fallback_count == 0

    def test_get_by_intent_greeting(self):
        """Test getting fallback by greeting intent."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("greeting")

        assert response.message is not None
        assert response.reason == FallbackReason.UNKNOWN
        assert response.should_retry is True

    def test_get_by_intent_question(self):
        """Test getting fallback by question intent."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("question")

        assert response.message is not None

    def test_get_by_intent_command(self):
        """Test getting fallback by command intent."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("command")

        assert "⚠️" in response.message

    def test_get_by_intent_roleplay(self):
        """Test getting fallback by roleplay intent."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("roleplay")

        assert "*" in response.message  # Roleplay uses asterisks

    def test_get_by_intent_emotional(self):
        """Test getting fallback by emotional intent."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("emotional")

        assert response.message is not None

    def test_get_by_intent_casual(self):
        """Test getting fallback by casual intent."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("casual")

        assert response.message is not None

    def test_get_by_intent_unknown_falls_back_to_casual(self):
        """Test that unknown intent falls back to casual."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        response = system.get_by_intent("nonexistent_intent")

        # Should still return a valid response
        assert response.message is not None

    def test_get_by_intent_increments_counter(self):
        """Test that get_by_intent increments fallback counter."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        assert system._fallback_count == 0

        system.get_by_intent("greeting")
        assert system._fallback_count == 1

        system.get_by_intent("question")
        assert system._fallback_count == 2

    def test_get_by_reason_api_timeout(self):
        """Test getting fallback by API timeout reason."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_reason(FallbackReason.API_TIMEOUT)

        assert "⏳" in response.message
        assert response.retry_after_seconds == 5.0

    def test_get_by_reason_api_error(self):
        """Test getting fallback by API error reason."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_reason(FallbackReason.API_ERROR)

        assert "❌" in response.message
        assert response.retry_after_seconds == 10.0

    def test_get_by_reason_circuit_open(self):
        """Test getting fallback by circuit open reason."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_reason(FallbackReason.CIRCUIT_OPEN)

        assert response.retry_after_seconds == 60.0

    def test_get_by_reason_rate_limited_with_seconds(self):
        """Test getting fallback by rate limited reason with custom seconds."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_reason(FallbackReason.RATE_LIMITED, seconds=45.0)

        assert response.retry_after_seconds == 45.0

    def test_get_by_reason_context_too_long_no_retry(self):
        """Test that context too long reason sets should_retry to False."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_reason(FallbackReason.CONTEXT_TOO_LONG)

        assert response.should_retry is False

    def test_get_by_reason_unknown(self):
        """Test getting fallback by unknown reason."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        response = system.get_by_reason(FallbackReason.UNKNOWN)

        assert response.message is not None
        assert response.should_retry is True

    def test_get_by_reason_increments_counter(self):
        """Test that get_by_reason increments fallback counter."""
        from cogs.ai_core.fallback_responses import FallbackReason, FallbackSystem

        system = FallbackSystem()
        assert system._fallback_count == 0

        system.get_by_reason(FallbackReason.API_ERROR)
        assert system._fallback_count == 1

    def test_get_stats(self):
        """Test getting fallback statistics."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        system.get_by_intent("greeting")
        system.get_by_intent("question")

        stats = system.get_stats()

        assert stats["total_fallbacks"] == 2
        assert "circuit_state" in stats

    def test_reset_stats(self):
        """Test resetting fallback statistics."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()
        system.get_by_intent("greeting")
        assert system._fallback_count == 1

        system.reset_stats()
        assert system._fallback_count == 0

    def test_should_use_fallback_without_circuit_breaker(self):
        """Test should_use_fallback when circuit breaker is unavailable."""
        from cogs.ai_core.fallback_responses import FallbackSystem

        system = FallbackSystem()

        with patch("cogs.ai_core.fallback_responses.CIRCUIT_BREAKER_AVAILABLE", False):
            result = system.should_use_fallback()
            assert result is False


class TestGlobalFallbackSystem:
    """Tests for global fallback_system instance."""

    def test_global_instance_is_fallback_system(self):
        """Test that global instance is FallbackSystem."""
        from cogs.ai_core.fallback_responses import FallbackSystem, fallback_system

        assert isinstance(fallback_system, FallbackSystem)


class TestGetFallbackResponse:
    """Tests for get_fallback_response convenience function."""

    def test_with_intent(self):
        """Test get_fallback_response with intent."""
        from cogs.ai_core.fallback_responses import get_fallback_response

        result = get_fallback_response(intent="greeting")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_reason(self):
        """Test get_fallback_response with reason."""
        from cogs.ai_core.fallback_responses import FallbackReason, get_fallback_response

        result = get_fallback_response(reason=FallbackReason.API_ERROR)

        assert isinstance(result, str)
        assert "❌" in result

    def test_with_kwargs(self):
        """Test get_fallback_response with kwargs."""
        from cogs.ai_core.fallback_responses import FallbackReason, get_fallback_response

        result = get_fallback_response(reason=FallbackReason.RATE_LIMITED, seconds=30)

        assert isinstance(result, str)

    def test_default_returns_unknown_reason(self):
        """Test that default call uses unknown reason."""
        from cogs.ai_core.fallback_responses import get_fallback_response

        result = get_fallback_response()

        assert isinstance(result, str)


class TestIntentFallbacks:
    """Tests for INTENT_FALLBACKS dictionary."""

    def test_all_intents_have_responses(self):
        """Test that all expected intents have fallback responses."""
        from cogs.ai_core.fallback_responses import INTENT_FALLBACKS

        expected_intents = ["greeting", "question", "command", "roleplay", "emotional", "casual"]

        for intent in expected_intents:
            assert intent in INTENT_FALLBACKS
            assert len(INTENT_FALLBACKS[intent]) > 0

    def test_responses_are_strings(self):
        """Test that all responses are strings."""
        from cogs.ai_core.fallback_responses import INTENT_FALLBACKS

        for _intent, responses in INTENT_FALLBACKS.items():
            for response in responses:
                assert isinstance(response, str)


class TestReasonFallbacks:
    """Tests for REASON_FALLBACKS dictionary."""

    def test_all_reasons_have_responses(self):
        """Test that all FallbackReasons have fallback responses."""
        from cogs.ai_core.fallback_responses import REASON_FALLBACKS, FallbackReason

        for reason in FallbackReason:
            assert reason in REASON_FALLBACKS
            assert len(REASON_FALLBACKS[reason]) > 0

    def test_responses_are_strings(self):
        """Test that all responses are strings."""
        from cogs.ai_core.fallback_responses import REASON_FALLBACKS

        for _reason, responses in REASON_FALLBACKS.items():
            for response in responses:
                assert isinstance(response, str)
