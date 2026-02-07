"""
Fast JSON Utility Module

Provides orjson-accelerated JSON functions with fallback to standard json.
orjson is ~10x faster than standard json for parsing and dumping.

Usage:
    from utils.fast_json import json_loads, json_dumps

    data = json_loads(json_string)
    json_string = json_dumps(data)
"""

from __future__ import annotations

from typing import Any

# ==================== Performance: Faster JSON ====================
# orjson is ~10x faster than standard json for parsing and dumping
try:
    import orjson

    _ORJSON_ENABLED = True

    def json_loads(data: str | bytes) -> Any:
        """Parse JSON string/bytes to Python object (orjson-accelerated)."""
        return orjson.loads(data)

    def json_dumps(
        obj: Any,
        *,
        ensure_ascii: bool = True,  # NOTE: Ignored by orjson (always outputs UTF-8)
        indent: int | None = None,
        **kwargs,
    ) -> str:
        """
        Serialize Python object to JSON string (orjson-accelerated).

        Note: orjson always outputs UTF-8 and does not support ensure_ascii.
        If ensure_ascii=True is critical, use stdlib json directly.
        orjson doesn't support indent parameter directly.
        For pretty printing, use json_dumps_pretty().
        """
        # orjson options
        option = orjson.OPT_NON_STR_KEYS
        if indent:
            option |= orjson.OPT_INDENT_2

        # orjson returns bytes, decode to str for compatibility
        return orjson.dumps(obj, option=option).decode("utf-8")

    def json_dumps_bytes(obj: Any) -> bytes:
        """Serialize Python object to JSON bytes (zero-copy, fastest)."""
        return orjson.dumps(obj)

except ImportError:
    import json as _json

    _ORJSON_ENABLED = False

    def json_loads(data: str | bytes) -> Any:
        """Parse JSON string/bytes to Python object (standard json)."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return _json.loads(data)

    def json_dumps(
        obj: Any, *, ensure_ascii: bool = True, indent: int | None = None, **kwargs
    ) -> str:
        """Serialize Python object to JSON string (standard json)."""
        return _json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent, **kwargs)

    def json_dumps_bytes(obj: Any) -> bytes:
        """Serialize Python object to JSON bytes (standard json)."""
        return _json.dumps(obj).encode("utf-8")


def is_orjson_enabled() -> bool:
    """Check if orjson acceleration is active."""
    return _ORJSON_ENABLED


# Convenience exports
__all__ = ["_ORJSON_ENABLED", "is_orjson_enabled", "json_dumps", "json_dumps_bytes", "json_loads"]
