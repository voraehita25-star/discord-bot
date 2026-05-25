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
        ensure_ascii: bool = False,  # NOTE: orjson always outputs UTF-8
        indent: int | None = None,
        default: Any = None,
        sort_keys: bool = False,
        **kwargs,
    ) -> str:
        """
        Serialize Python object to JSON string (orjson-accelerated).

        Honors stdlib-compatible kwargs that orjson does support natively:
        - ``default`` → orjson ``default=`` (called for unknown types)
        - ``sort_keys`` → ``orjson.OPT_SORT_KEYS``
        - ``indent`` → ``orjson.OPT_INDENT_2`` (orjson only supports 2-space)

        ``ensure_ascii=True`` is rejected because orjson always emits UTF-8;
        callers needing BMP-escaping must use stdlib ``json`` directly.
        Other unknown kwargs raise ``TypeError`` so silent semantic drift
        between orjson and stdlib paths becomes a loud failure.
        """
        if ensure_ascii:
            raise NotImplementedError(
                "fast_json.json_dumps: ensure_ascii=True is not supported under orjson. "
                "Use stdlib json directly if BMP-escaping is required."
            )
        if kwargs:
            raise TypeError(
                f"fast_json.json_dumps: unsupported kwargs {sorted(kwargs)} under orjson"
            )

        option = orjson.OPT_NON_STR_KEYS
        # `if indent:` is falsy for `indent=0` (a valid "no newlines"
        # JSON option), which would silently drop indentation when the
        # caller explicitly passed 0. Only skip when indent is None.
        if indent is not None and indent > 0:
            option |= orjson.OPT_INDENT_2
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS

        # orjson returns bytes, decode to str for compatibility
        return orjson.dumps(obj, default=default, option=option).decode("utf-8")

    def json_dumps_bytes(obj: Any, *, default: Any = None) -> bytes:
        """Serialize Python object to JSON bytes (zero-copy, fastest)."""
        return orjson.dumps(obj, default=default)

except ImportError:
    import json as _json

    _ORJSON_ENABLED = False

    def json_loads(data: str | bytes) -> Any:
        """Parse JSON string/bytes to Python object (standard json)."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return _json.loads(data)

    def json_dumps(
        obj: Any,
        *,
        ensure_ascii: bool = False,
        indent: int | None = None,
        default: Any = None,
        sort_keys: bool = False,
        **kwargs: Any,
    ) -> str:
        """Serialize Python object to JSON string (standard json).

        Mirrors the orjson-backed signature so callers don't get silent
        semantic drift between paths. The previous ``**kwargs`` passthrough
        accepted arbitrary stdlib kwargs that the orjson branch would
        reject — meaning calls would succeed in production (orjson
        installed) but raise TypeError in tests (no orjson), or vice
        versa. Listing every arg explicitly keeps the two branches in
        lockstep; ``**kwargs`` is accepted but rejected loudly to match
        the orjson branch's behavior.
        """
        if kwargs:
            raise TypeError(
                f"fast_json.json_dumps: unsupported kwargs {sorted(kwargs)} under stdlib json"
            )
        # Force ``allow_nan=False`` to match the orjson branch, which
        # raises ``TypeError`` on NaN/Infinity. The default
        # ``allow_nan=True`` emits ``NaN`` / ``Infinity`` tokens (non-
        # standard JSON) — fine for stdlib readers but unparseable by any
        # strict JSON parser, including orjson loading the same file.
        # Loud failure is better than producing files only some paths can
        # read.
        return _json.dumps(
            obj,
            ensure_ascii=ensure_ascii,
            indent=indent,
            default=default,
            sort_keys=sort_keys,
            allow_nan=False,
        )

    def json_dumps_bytes(obj: Any, *, default: Any = None) -> bytes:
        """Serialize Python object to JSON bytes (standard json)."""
        return _json.dumps(obj, default=default).encode("utf-8")


def is_orjson_enabled() -> bool:
    """Check if orjson acceleration is active."""
    return _ORJSON_ENABLED


# Convenience exports. Drop the private ``_ORJSON_ENABLED`` from
# ``__all__`` — callers should use the public ``is_orjson_enabled()``
# helper instead so the underlying flag stays an implementation detail.
__all__ = ["is_orjson_enabled", "json_dumps", "json_dumps_bytes", "json_loads"]
