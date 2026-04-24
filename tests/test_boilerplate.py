"""
Parametrized boilerplate tests.

Consolidates ~86 repetitive tests (module_has_docstring, singleton_exists,
global_instance_exists, module_imports) into parametrized test functions.
"""
from __future__ import annotations

import importlib

import pytest

# ============================================================================
# Module docstring tests (was: 15x test_module_has_docstring)
# ============================================================================

_MODULES_WITH_DOCSTRINGS = [
    "cogs.ai_core.storage",
    "cogs.ai_core.logic",
    "cogs.ai_core.ai_cog",
    "cogs.ai_core.cache.ai_cache",
    "cogs.ai_core.memory.consolidator",
    "cogs.ai_core.memory.rag",
    "cogs.ai_core.memory.long_term_memory",
    "cogs.ai_core.memory.entity_memory",
    "cogs.ai_core.memory.summarizer",
    "cogs.ai_core.core.context_builder",
    "cogs.ai_core.response.response_sender",
    "cogs.ai_core.voice",
    "utils.database.database",
    "utils.reliability.error_recovery",
    "utils.reliability.circuit_breaker",
]


@pytest.mark.parametrize("module_path", _MODULES_WITH_DOCSTRINGS)
def test_module_has_docstring(module_path: str):
    """Test that module has a docstring."""
    mod = importlib.import_module(module_path)
    assert mod.__doc__ is not None, f"{module_path} missing docstring"


# ============================================================================
# Module import tests (was: 7x test_module_imports)
# ============================================================================

_IMPORTABLE_MODULES = [
    "cogs.ai_core.storage",
    "cogs.ai_core.voice",
    "cogs.ai_core.emoji",
    "cogs.ai_core.media_processor",
    "utils.monitoring.health_api",
    "utils.reliability.error_recovery",
    "utils.reliability.circuit_breaker",
]


@pytest.mark.parametrize("module_path", _IMPORTABLE_MODULES)
def test_module_imports(module_path: str):
    """Test that module can be imported."""
    mod = importlib.import_module(module_path)
    assert mod is not None


# ============================================================================
# Singleton/global instance tests (was: 9x + 8x = 17x)
# ============================================================================

_SINGLETONS = [
    # (module_path, attribute_name)
    ("cogs.ai_core.cache.ai_cache", "ai_cache"),
    ("cogs.ai_core.cache.token_tracker", "token_tracker"),
    ("cogs.ai_core.memory.consolidator", "memory_consolidator"),
    ("cogs.ai_core.memory.rag", "rag_system"),
    ("cogs.ai_core.memory.summarizer", "summarizer"),
    ("cogs.ai_core.memory.entity_memory", "entity_memory"),
    ("cogs.ai_core.memory.state_tracker", "state_tracker"),
    ("cogs.ai_core.memory.history_manager", "history_manager"),
    ("cogs.ai_core.core.context_builder", "context_builder"),
    ("cogs.ai_core.core.message_queue", "message_queue"),
    ("cogs.ai_core.fallback_responses", "fallback_system"),
    ("utils.reliability.error_recovery", "service_monitor"),
    ("utils.reliability.rate_limiter", "rate_limiter"),
    ("utils.monitoring.feedback", "feedback_collector"),
    ("utils.monitoring.performance_tracker", "perf_tracker"),
    ("utils.monitoring.token_tracker", "token_tracker"),
]


@pytest.mark.parametrize("module_path,attr", _SINGLETONS, ids=[f"{m}.{a}" for m, a in _SINGLETONS])
def test_singleton_exists(module_path: str, attr: str):
    """Test that singleton/global instance exists and is not None."""
    mod = importlib.import_module(module_path)
    obj = getattr(mod, attr, None)
    assert obj is not None, f"{module_path}.{attr} is None"
