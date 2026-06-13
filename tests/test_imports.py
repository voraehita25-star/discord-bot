"""Tests for cogs.ai_core.imports — the centralized conditional-import shim.

This module consolidates every optional ai_core dependency behind a
``try/except ImportError`` block that sets a ``*_AVAILABLE`` boolean flag and
either re-exports the real symbol or installs a no-op/fallback stub. The tests
here verify two things:

1. As loaded in *this* environment, the module imports cleanly, every
   documented availability flag is a real ``bool``, and whenever a flag is
   ``True`` the symbol it guards is actually importable and non-None. These
   assertions are robust to whatever optional packages happen to be installed.
2. The graceful-degradation fallbacks themselves. Because the real
   dependencies are present in CI, we deterministically force each
   ``ImportError`` branch by reloading the module with the relevant submodule
   blocked from ``__import__``, then assert the fallback stub's exact behavior
   (fail-open guardrails, no-op token tracker, fallback GracefulDegradation
   async context manager, etc.).
"""

from __future__ import annotations

import asyncio
import builtins
import importlib
import sys
from typing import Any

import pytest

# All documented availability flags exposed by the shim.
AVAILABILITY_FLAGS = [
    "URL_FETCHER_AVAILABLE",
    "GUARDRAILS_AVAILABLE",
    "INTENT_DETECTOR_AVAILABLE",
    "ANALYTICS_AVAILABLE",
    "CACHE_AVAILABLE",
    "HISTORY_MANAGER_AVAILABLE",
    "CIRCUIT_BREAKER_AVAILABLE",
    "TOKEN_TRACKER_AVAILABLE",
    "FALLBACK_AVAILABLE",
    "STRUCTURED_LOGGER_AVAILABLE",
    "PERF_TRACKER_AVAILABLE",
    "ERROR_RECOVERY_AVAILABLE",
    "FEEDBACK_AVAILABLE",
    "LOCALIZATION_AVAILABLE",
]


def _reload_imports_blocking(blocked: set[str]) -> Any:
    """Reload ``cogs.ai_core.imports`` with ``blocked`` module names forced to
    raise ImportError, so the except-branch fallbacks are exercised.

    ``blocked`` entries are the names as ``__import__`` receives them inside the
    shim. For absolute imports that is the dotted path
    (e.g. ``"utils.web.url_fetcher"``); for the shim's *relative* imports it is
    the relative remainder (e.g. ``"processing.guardrails"``,
    ``"fallback_responses"``). To make a relative import actually re-run its
    ``__import__`` call (rather than resolve from ``sys.modules``), any cached
    target whose fully-qualified name ends with a blocked suffix is purged
    first.

    Returns a freshly-reloaded module object. Module caches are restored before
    returning so the normally imported shim (with real deps) stays cached for
    the rest of the session.
    """
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in blocked:
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    # Drop any cached copy of the shim so the reload re-runs every block, and
    # purge the cached target submodules so relative re-imports hit __import__.
    saved = sys.modules.pop("cogs.ai_core.imports", None)
    purged: dict[str, Any] = {}
    for mod_name in list(sys.modules):
        for suffix in blocked:
            if mod_name == suffix or mod_name.endswith("." + suffix):
                purged[mod_name] = sys.modules.pop(mod_name)
                break

    builtins.__import__ = fake_import
    try:
        module = importlib.import_module("cogs.ai_core.imports")
        module = importlib.reload(module)
        return module
    finally:
        builtins.__import__ = real_import
        # Restore the real module so other tests/imports see the healthy shim,
        # plus any submodules we purged.
        sys.modules.update(purged)
        sys.modules.pop("cogs.ai_core.imports", None)
        if saved is not None:
            sys.modules["cogs.ai_core.imports"] = saved
        else:
            importlib.import_module("cogs.ai_core.imports")


class TestModuleImports:
    """The shim imports cleanly and exposes the documented surface."""

    def test_module_imports(self):
        from cogs.ai_core import imports

        assert imports is not None

    def test_logger_exists(self):
        import logging

        from cogs.ai_core import imports

        assert isinstance(imports.logger, logging.Logger)

    def test_all_flags_exist(self):
        from cogs.ai_core import imports

        for flag in AVAILABILITY_FLAGS:
            assert hasattr(imports, flag), f"missing availability flag: {flag}"

    def test_all_flags_are_bool(self):
        from cogs.ai_core import imports

        for flag in AVAILABILITY_FLAGS:
            value = getattr(imports, flag)
            assert isinstance(value, bool), f"{flag} is not a bool: {value!r}"


class TestTypeAliases:
    """The module declares three Callable type aliases used by callers."""

    def test_type_aliases_present(self):
        from cogs.ai_core import imports

        assert imports.RecordTokenUsageFn is not None
        assert imports.LogAIRequestFn is not None
        assert imports.AddFeedbackReactionsFn is not None


class TestAvailabilityInvariants:
    """For every guarded symbol: if its flag is True the symbol must be a real,
    non-None object. These hold regardless of which optional deps are installed.
    """

    def test_url_fetcher_symbols(self):
        from cogs.ai_core import imports

        # extract_urls / fetch_all_urls / format_url_content_for_context always
        # exist (real or stub) and are always callable.
        assert callable(imports.extract_urls)
        assert callable(imports.fetch_all_urls)
        assert callable(imports.format_url_content_for_context)

    def test_guardrails_symbols_callable(self):
        from cogs.ai_core import imports

        for name in (
            "validate_response",
            "is_unrestricted",
            "set_unrestricted",
            "validate_response_for_channel",
            "validate_input_for_channel",
            "is_silent_block",
        ):
            assert callable(getattr(imports, name)), name
        assert isinstance(imports.unrestricted_channels, set) or hasattr(
            imports.unrestricted_channels, "__contains__"
        )

    def test_token_tracker_invariant(self):
        from cogs.ai_core import imports

        assert callable(imports.record_token_usage)
        if imports.TOKEN_TRACKER_AVAILABLE:
            assert imports.token_tracker is not None

    def test_structured_logger_invariant(self):
        from cogs.ai_core import imports

        assert callable(imports.log_ai_request)
        if imports.STRUCTURED_LOGGER_AVAILABLE:
            assert imports.structured_logger is not None

    def test_feedback_invariant(self):
        from cogs.ai_core import imports

        assert callable(imports.add_feedback_reactions)
        if imports.FEEDBACK_AVAILABLE:
            assert imports.feedback_collector is not None

    def test_circuit_breaker_invariant(self):
        from cogs.ai_core import imports

        if imports.CIRCUIT_BREAKER_AVAILABLE:
            assert imports.gemini_circuit is not None

    def test_history_manager_invariant(self):
        from cogs.ai_core import imports

        if imports.HISTORY_MANAGER_AVAILABLE:
            assert imports.history_manager is not None

    def test_fallback_system_invariant(self):
        from cogs.ai_core import imports

        if imports.FALLBACK_AVAILABLE:
            assert imports.fallback_system is not None

    def test_perf_tracker_invariant(self):
        from cogs.ai_core import imports

        if imports.PERF_TRACKER_AVAILABLE:
            assert imports.perf_tracker is not None

    def test_error_recovery_invariant(self):
        from cogs.ai_core import imports

        # GracefulDegradation is always a type (real class or fallback stub).
        assert isinstance(imports.GracefulDegradation, type)
        if imports.ERROR_RECOVERY_AVAILABLE:
            assert imports.service_monitor is not None

    def test_localization_symbols(self):
        from cogs.ai_core import imports

        assert callable(imports.msg)
        assert callable(imports.msg_en)

    def test_intent_detector_invariant(self):
        from cogs.ai_core import imports

        # When available, Intent + detect_intent are re-exported; there is no
        # fallback stub for this one, so they only exist when the flag is True.
        if imports.INTENT_DETECTOR_AVAILABLE:
            assert imports.detect_intent is not None
            assert imports.Intent is not None

    def test_analytics_invariant(self):
        from cogs.ai_core import imports

        if imports.ANALYTICS_AVAILABLE:
            assert callable(imports.get_ai_stats)
            assert callable(imports.log_ai_interaction)

    def test_cache_invariant(self):
        from cogs.ai_core import imports

        if imports.CACHE_AVAILABLE:
            assert imports.ai_cache is not None


class TestUrlFetcherFallback:
    """Forced-ImportError path for utils.web.url_fetcher."""

    def test_flag_false_and_stubs_installed(self):
        m = _reload_imports_blocking({"utils.web.url_fetcher"})
        assert m.URL_FETCHER_AVAILABLE is False

    def test_extract_urls_returns_empty_list(self):
        m = _reload_imports_blocking({"utils.web.url_fetcher"})
        assert m.extract_urls("see http://example.com here") == []

    def test_fetch_all_urls_returns_empty_list(self):
        m = _reload_imports_blocking({"utils.web.url_fetcher"})
        result = asyncio.run(m.fetch_all_urls(["http://example.com"], max_urls=5))
        assert result == []

    def test_format_url_content_returns_empty_string(self):
        m = _reload_imports_blocking({"utils.web.url_fetcher"})
        assert m.format_url_content_for_context([("u", "title", "body")]) == ""


class TestGuardrailsFallback:
    """Guardrails module removed — imports exposes permanent no-op shims.

    ``processing.guardrails`` no longer exists; these assert the pass-through
    behaviour of the validation shims that replaced it (``GUARDRAILS_AVAILABLE``
    is always False, validation never blocks). Unrestricted mode moved to its own
    module — see ``tests/test_unrestricted.py``.
    """

    BLOCK = {"processing.guardrails"}

    def test_flag_false(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.GUARDRAILS_AVAILABLE is False

    def test_validate_response_fails_open(self):
        m = _reload_imports_blocking(self.BLOCK)
        ok, text, flags = m.validate_response("anything at all")
        # Fail-open: allowed through unchanged, flagged as unvalidated.
        assert ok is True
        assert text == "anything at all"
        assert "guardrails_unavailable" in flags

    def test_validate_response_for_channel_fails_open(self):
        m = _reload_imports_blocking(self.BLOCK)
        ok, text, flags = m.validate_response_for_channel("hi", 123)
        assert ok is True
        assert text == "hi"
        assert "guardrails_unavailable" in flags

    def test_validate_input_for_channel_fails_open(self):
        m = _reload_imports_blocking(self.BLOCK)
        ok, text, score, flags = m.validate_input_for_channel("hi", 123)
        assert ok is True
        assert text == "hi"
        assert score == 0.0
        assert flags == []

    def test_is_silent_block_only_flags_empty(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.is_silent_block("") is True
        assert m.is_silent_block("   ") is True
        assert m.is_silent_block("real text") is False


class TestTokenTrackerFallback:
    """Forced-ImportError path for utils.monitoring.token_tracker."""

    BLOCK = {"utils.monitoring.token_tracker"}

    def test_flag_false_and_tracker_none(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.TOKEN_TRACKER_AVAILABLE is False
        assert m.token_tracker is None

    def test_record_token_usage_is_noop(self):
        m = _reload_imports_blocking(self.BLOCK)
        # Must not raise; returns None.
        assert m.record_token_usage(1, 10, 20, channel_id=5) is None

    def test_record_token_usage_warns_once(self, caplog):
        import logging

        m = _reload_imports_blocking(self.BLOCK)
        with caplog.at_level(logging.WARNING, logger="cogs.ai_core.imports"):
            m.record_token_usage(1, 10, 20)
            m.record_token_usage(2, 30, 40)
        warnings = [r for r in caplog.records if "token_tracker unavailable" in r.message]
        # The no-op warns only the first time it runs.
        assert len(warnings) == 1


class TestStructuredLoggerFallback:
    """Forced-ImportError path for utils.monitoring.structured_logger."""

    BLOCK = {"utils.monitoring.structured_logger"}

    def test_flag_false_and_logger_none(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.STRUCTURED_LOGGER_AVAILABLE is False
        assert m.structured_logger is None

    def test_log_ai_request_is_noop(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.log_ai_request(user_id=1, message="hi", extra_field="x") is None

    def test_log_ai_request_warns_once(self, caplog):
        import logging

        m = _reload_imports_blocking(self.BLOCK)
        with caplog.at_level(logging.WARNING, logger="cogs.ai_core.imports"):
            m.log_ai_request(user_id=1)
            m.log_ai_request(user_id=2)
        warnings = [r for r in caplog.records if "structured_logger unavailable" in r.message]
        assert len(warnings) == 1


class TestErrorRecoveryFallback:
    """Forced-ImportError path for utils.reliability.error_recovery."""

    BLOCK = {"utils.reliability.error_recovery"}

    def test_flag_false_and_monitor_none(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.ERROR_RECOVERY_AVAILABLE is False
        assert m.service_monitor is None

    def test_graceful_degradation_is_class(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert isinstance(m.GracefulDegradation, type)

    def test_graceful_degradation_constructs_with_any_args(self):
        m = _reload_imports_blocking(self.BLOCK)
        # Fallback accepts arbitrary positional/keyword args.
        instance = m.GracefulDegradation("svc", retries=3, foo="bar")
        assert instance is not None

    def test_graceful_degradation_async_context_manager(self):
        m = _reload_imports_blocking(self.BLOCK)

        async def run():
            async with m.GracefulDegradation("svc") as cm:
                return cm

        cm = asyncio.run(run())
        # __aenter__ returns the instance itself.
        assert isinstance(cm, m.GracefulDegradation)

    def test_graceful_degradation_does_not_suppress_exceptions(self):
        m = _reload_imports_blocking(self.BLOCK)

        async def run():
            async with m.GracefulDegradation("svc"):
                raise ValueError("boom")

        # __aexit__ returns False => exception must propagate.
        with pytest.raises(ValueError, match="boom"):
            asyncio.run(run())


class TestFeedbackFallback:
    """Forced-ImportError path for utils.monitoring.feedback."""

    BLOCK = {"utils.monitoring.feedback"}

    def test_flag_false_and_collector_none(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.FEEDBACK_AVAILABLE is False
        assert m.feedback_collector is None

    def test_add_feedback_reactions_is_noop(self):
        m = _reload_imports_blocking(self.BLOCK)
        from unittest.mock import MagicMock

        message = MagicMock()
        # Must be an awaitable that resolves to None without touching message.
        assert asyncio.run(m.add_feedback_reactions(message)) is None
        message.add_reaction.assert_not_called()


class TestLocalizationFallback:
    """Forced-ImportError path for utils.localization."""

    BLOCK = {"utils.localization"}

    def test_flag_false(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.LOCALIZATION_AVAILABLE is False

    def test_msg_echoes_key(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.msg("ai_busy", who="x") == "ai_busy"

    def test_msg_en_echoes_key(self):
        m = _reload_imports_blocking(self.BLOCK)
        assert m.msg_en("ai_error") == "ai_error"


class TestSimpleFlagFallbacks:
    """Forced-ImportError paths for the flag-only modules (no fallback stubs
    beyond setting the symbol to None where applicable)."""

    def test_intent_detector_flag_false(self):
        m = _reload_imports_blocking({"processing.intent_detector"})
        assert m.INTENT_DETECTOR_AVAILABLE is False

    def test_analytics_flag_false(self):
        m = _reload_imports_blocking({"cache.analytics"})
        assert m.ANALYTICS_AVAILABLE is False

    def test_cache_flag_false(self):
        m = _reload_imports_blocking({"cache.ai_cache"})
        assert m.CACHE_AVAILABLE is False

    def test_history_manager_flag_false_and_none(self):
        m = _reload_imports_blocking({"memory.history_manager"})
        assert m.HISTORY_MANAGER_AVAILABLE is False
        assert m.history_manager is None

    def test_circuit_breaker_flag_false_and_none(self):
        m = _reload_imports_blocking({"utils.reliability.circuit_breaker"})
        assert m.CIRCUIT_BREAKER_AVAILABLE is False
        assert m.gemini_circuit is None

    def test_fallback_flag_false_and_none(self):
        m = _reload_imports_blocking({"fallback_responses"})
        assert m.FALLBACK_AVAILABLE is False
        assert m.fallback_system is None

    def test_perf_tracker_flag_false_and_none(self):
        m = _reload_imports_blocking({"utils.monitoring.performance_tracker"})
        assert m.PERF_TRACKER_AVAILABLE is False
        assert m.perf_tracker is None


class TestReloadRestoresHealthyModule:
    """After exercising fallback paths, the cached shim is the healthy one
    again, so we don't pollute the rest of the test session."""

    def test_module_healthy_after_blocking_reloads(self):
        # Run a couple of blocking reloads then confirm the live module is fine.
        _reload_imports_blocking({"utils.localization"})
        _reload_imports_blocking({"utils.web.url_fetcher"})

        from cogs.ai_core import imports

        for flag in AVAILABILITY_FLAGS:
            assert isinstance(getattr(imports, flag), bool)
        # GracefulDegradation remains a type after the restore.
        assert isinstance(imports.GracefulDegradation, type)
