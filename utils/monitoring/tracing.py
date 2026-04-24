"""
Distributed tracing: lightweight trace ID propagation between Python, Go, and Rust services.

Generates a unique trace ID per request and propagates it via HTTP headers (X-Trace-ID).
Uses contextvars for async-safe trace context within Python.
"""

from __future__ import annotations

import contextvars
import logging
import uuid

logger = logging.getLogger(__name__)

# Async-safe trace context
_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)

TRACE_HEADER = "X-Trace-ID"


def new_trace_id() -> str:
    """Generate a new trace ID and set it in the current context."""
    trace_id = uuid.uuid4().hex[:16]
    _trace_id_var.set(trace_id)
    return trace_id


def get_trace_id() -> str | None:
    """Get the current trace ID from context."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """Set the trace ID in the current context (e.g. from incoming header)."""
    _trace_id_var.set(trace_id)


def clear_trace_id() -> None:
    """Clear the trace ID from the current context."""
    _trace_id_var.set(None)


def trace_headers() -> dict[str, str]:
    """Return headers dict with trace ID for outgoing HTTP requests."""
    trace_id = _trace_id_var.get()
    if trace_id:
        return {TRACE_HEADER: trace_id}
    return {}
