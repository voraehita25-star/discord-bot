"""
Tests for utils.fast_json module.
"""

from unittest.mock import patch

import pytest


class TestFastJSONLoads:
    """Tests for fast_json.json_loads function."""

    def test_loads_simple_dict(self):
        """Test loading simple dictionary."""
        from utils.fast_json import json_loads

        result = json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_loads_simple_list(self):
        """Test loading simple list."""
        from utils.fast_json import json_loads

        result = json_loads('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_loads_nested_structure(self):
        """Test loading nested structure."""
        from utils.fast_json import json_loads

        json_str = '{"outer": {"inner": "value"}, "list": [1, 2]}'
        result = json_loads(json_str)

        assert result["outer"]["inner"] == "value"
        assert result["list"] == [1, 2]

    def test_loads_unicode(self):
        """Test loading unicode characters."""
        from utils.fast_json import json_loads

        result = json_loads('{"text": "สวัสดี"}')
        assert result["text"] == "สวัสดี"

    def test_loads_numbers(self):
        """Test loading numbers."""
        from utils.fast_json import json_loads

        result = json_loads('{"int": 42, "float": 3.14}')
        assert result["int"] == 42
        assert result["float"] == 3.14

    def test_loads_null(self):
        """Test loading null value."""
        from utils.fast_json import json_loads

        result = json_loads('{"value": null}')
        assert result["value"] is None

    def test_loads_boolean(self):
        """Test loading boolean values."""
        from utils.fast_json import json_loads

        result = json_loads('{"true": true, "false": false}')
        assert result["true"] is True
        assert result["false"] is False


class TestFastJSONDumps:
    """Tests for fast_json.json_dumps function."""

    def test_dumps_simple_dict(self):
        """Test dumping simple dictionary."""
        from utils.fast_json import json_dumps

        result = json_dumps({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_dumps_simple_list(self):
        """Test dumping simple list."""
        from utils.fast_json import json_dumps

        result = json_dumps([1, 2, 3])
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_dumps_unicode(self):
        """Test dumping unicode characters."""
        from utils.fast_json import json_dumps

        result = json_dumps({"text": "สวัสดี"})
        # Result should contain unicode or escaped unicode
        assert "text" in result

    def test_dumps_returns_string(self):
        """Test dumps returns string."""
        from utils.fast_json import json_dumps

        result = json_dumps({"test": 123})
        assert isinstance(result, str)

    def test_dumps_null(self):
        """Test dumping None value."""
        from utils.fast_json import json_dumps

        result = json_dumps({"value": None})
        assert "null" in result

    def test_dumps_boolean(self):
        """Test dumping boolean values."""
        from utils.fast_json import json_dumps

        result = json_dumps({"t": True, "f": False})
        assert "true" in result
        assert "false" in result


class TestFastJSONRoundTrip:
    """Tests for JSON round-trip (json_dumps -> json_loads)."""

    def test_roundtrip_dict(self):
        """Test dictionary round-trip."""
        from utils.fast_json import json_dumps, json_loads

        original = {"key": "value", "num": 42}
        result = json_loads(json_dumps(original))

        assert result == original

    def test_roundtrip_list(self):
        """Test list round-trip."""
        from utils.fast_json import json_dumps, json_loads

        original = [1, "two", 3.0, None, True]
        result = json_loads(json_dumps(original))

        assert result == original

    def test_roundtrip_nested(self):
        """Test nested structure round-trip."""
        from utils.fast_json import json_dumps, json_loads

        original = {
            "users": [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25}
            ],
            "meta": {"version": 1}
        }
        result = json_loads(json_dumps(original))

        assert result == original


class TestOrjsonFallback:
    """Tests for orjson/json fallback behavior."""

    def test_orjson_available_flag(self):
        """Test _ORJSON_ENABLED flag exists."""
        from utils.fast_json import _ORJSON_ENABLED

        assert isinstance(_ORJSON_ENABLED, bool)

    def test_loads_works_regardless_of_orjson(self):
        """Test json_loads works whether orjson is available or not."""
        from utils.fast_json import json_loads

        # Should work in both cases
        result = json_loads('{"test": true}')
        assert result["test"] is True

    def test_dumps_works_regardless_of_orjson(self):
        """Test json_dumps works whether orjson is available or not."""
        from utils.fast_json import json_dumps

        # Should work in both cases
        result = json_dumps({"test": True})
        assert "test" in result

    def test_is_orjson_enabled_function(self):
        """Test is_orjson_enabled function exists."""
        from utils.fast_json import is_orjson_enabled

        result = is_orjson_enabled()
        assert isinstance(result, bool)

    def test_json_dumps_bytes(self):
        """Test json_dumps_bytes returns bytes."""
        from utils.fast_json import json_dumps_bytes

        result = json_dumps_bytes({"key": "value"})
        assert isinstance(result, bytes)
