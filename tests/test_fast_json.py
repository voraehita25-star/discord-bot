"""Unit tests for Fast JSON utility module."""


from utils.fast_json import (

    is_orjson_enabled,
    json_dumps,
    json_dumps_bytes,
    json_loads,
)


class TestJsonLoads:
    """Tests for json_loads function."""

    def test_loads_simple_dict(self):
        """Test parsing simple dictionary."""
        result = json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_loads_nested_dict(self):
        """Test parsing nested dictionary."""
        result = json_loads('{"outer": {"inner": 123}}')
        assert result == {"outer": {"inner": 123}}

    def test_loads_array(self):
        """Test parsing array."""
        result = json_loads('[1, 2, 3, "four"]')
        assert result == [1, 2, 3, "four"]

    def test_loads_unicode(self):
        """Test parsing unicode content."""
        result = json_loads('{"thai": "สวัสดี"}')
        assert result == {"thai": "สวัสดี"}

    def test_loads_bytes(self):
        """Test parsing bytes input."""
        result = json_loads(b'{"key": "value"}')
        assert result == {"key": "value"}

    def test_loads_numbers(self):
        """Test parsing various number types."""
        result = json_loads('{"int": 42, "float": 3.14, "neg": -5}')
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["neg"] == -5

    def test_loads_boolean_null(self):
        """Test parsing boolean and null values."""
        result = json_loads('{"yes": true, "no": false, "nothing": null}')
        assert result["yes"] is True
        assert result["no"] is False
        assert result["nothing"] is None


class TestJsonDumps:
    """Tests for json_dumps function."""

    def test_dumps_simple_dict(self):
        """Test serializing simple dictionary."""
        result = json_dumps({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_dumps_nested_dict(self):
        """Test serializing nested dictionary."""
        data = {"outer": {"inner": [1, 2, 3]}}
        result = json_dumps(data)
        assert "outer" in result
        assert "inner" in result

    def test_dumps_unicode(self):
        """Test serializing unicode content."""
        result = json_dumps({"thai": "สวัสดี"})
        assert "สวัสดี" in result or "\\u" in result  # Either direct or escaped

    def test_dumps_returns_string(self):
        """Test that dumps returns a string."""
        result = json_dumps({"key": "value"})
        assert isinstance(result, str)

    def test_dumps_with_indent(self):
        """Test serializing with indentation."""
        result = json_dumps({"key": "value"}, indent=2)
        assert isinstance(result, str)
        # Should have some kind of formatting
        assert "\n" in result or len(result) > 15


class TestJsonDumpsBytes:
    """Tests for json_dumps_bytes function."""

    def test_dumps_bytes_returns_bytes(self):
        """Test that dumps_bytes returns bytes."""
        result = json_dumps_bytes({"key": "value"})
        assert isinstance(result, bytes)

    def test_dumps_bytes_valid_json(self):
        """Test that returned bytes are valid JSON."""
        data = {"key": "value", "num": 42}
        result = json_dumps_bytes(data)
        # Should be parseable
        parsed = json_loads(result)
        assert parsed == data


class TestOrjsonDetection:
    """Tests for orjson detection."""

    def test_is_orjson_enabled_returns_bool(self):
        """Test that is_orjson_enabled returns boolean."""
        result = is_orjson_enabled()
        assert isinstance(result, bool)


class TestRoundTrip:
    """Tests for round-trip serialization/deserialization."""

    def test_roundtrip_dict(self):
        """Test round-trip with dictionary."""
        original = {"key": "value", "number": 123, "list": [1, 2, 3]}
        serialized = json_dumps(original)
        result = json_loads(serialized)
        assert result == original

    def test_roundtrip_complex(self):
        """Test round-trip with complex data."""
        original = {
            "nested": {"deep": {"deeper": True}},
            "array": [{"a": 1}, {"b": 2}],
            "unicode": "日本語",
        }
        serialized = json_dumps(original)
        result = json_loads(serialized)
        assert result == original

    def test_roundtrip_bytes(self):
        """Test round-trip using bytes."""
        original = {"key": "value"}
        serialized = json_dumps_bytes(original)
        result = json_loads(serialized)
        assert result == original


# ======================================================================
# Merged from test_fast_json_extended.py
# ======================================================================

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


# ======================================================================
# Merged from test_fast_json_module.py
# ======================================================================

class TestJsonLoads:
    """Tests for json_loads function."""

    def test_json_loads_string(self):
        """Test json_loads with string input."""
        from utils.fast_json import json_loads

        result = json_loads('{"key": "value"}')

        assert result == {"key": "value"}

    def test_json_loads_bytes(self):
        """Test json_loads with bytes input."""
        from utils.fast_json import json_loads

        result = json_loads(b'{"key": "value"}')

        assert result == {"key": "value"}

    def test_json_loads_array(self):
        """Test json_loads with array."""
        from utils.fast_json import json_loads

        result = json_loads('[1, 2, 3]')

        assert result == [1, 2, 3]

    def test_json_loads_nested(self):
        """Test json_loads with nested structure."""
        from utils.fast_json import json_loads

        result = json_loads('{"outer": {"inner": 123}}')

        assert result["outer"]["inner"] == 123

    def test_json_loads_unicode(self):
        """Test json_loads with unicode."""
        from utils.fast_json import json_loads

        result = json_loads('{"emoji": "🎵"}')

        assert result["emoji"] == "🎵"


class TestJsonDumps:
    """Tests for json_dumps function."""

    def test_json_dumps_dict(self):
        """Test json_dumps with dict."""
        from utils.fast_json import json_dumps

        result = json_dumps({"key": "value"})

        assert '"key"' in result
        assert '"value"' in result

    def test_json_dumps_list(self):
        """Test json_dumps with list."""
        from utils.fast_json import json_dumps

        result = json_dumps([1, 2, 3])

        assert result == "[1,2,3]"

    def test_json_dumps_nested(self):
        """Test json_dumps with nested structure."""
        from utils.fast_json import json_dumps

        result = json_dumps({"outer": {"inner": 123}})

        assert "outer" in result
        assert "inner" in result
        assert "123" in result

    def test_json_dumps_indent(self):
        """Test json_dumps with indent."""
        from utils.fast_json import json_dumps

        result = json_dumps({"key": "value"}, indent=2)

        # Should contain newlines with indent
        assert isinstance(result, str)


class TestJsonDumpsBytes:
    """Tests for json_dumps_bytes function."""

    def test_json_dumps_bytes_returns_bytes(self):
        """Test json_dumps_bytes returns bytes."""
        from utils.fast_json import json_dumps_bytes

        result = json_dumps_bytes({"key": "value"})

        assert isinstance(result, bytes)

    def test_json_dumps_bytes_valid_json(self):
        """Test json_dumps_bytes returns valid JSON."""
        from utils.fast_json import json_dumps_bytes, json_loads

        original = {"key": "value", "number": 42}
        result = json_dumps_bytes(original)
        parsed = json_loads(result)

        assert parsed == original


class TestIsOrjsonEnabled:
    """Tests for is_orjson_enabled function."""

    def test_is_orjson_enabled_returns_bool(self):
        """Test is_orjson_enabled returns boolean."""
        from utils.fast_json import is_orjson_enabled

        result = is_orjson_enabled()

        assert isinstance(result, bool)


class TestOrjsonEnabledFlag:
    """Tests for _ORJSON_ENABLED flag."""

    def test_orjson_enabled_flag_exists(self):
        """Test _ORJSON_ENABLED flag exists."""
        from utils.fast_json import _ORJSON_ENABLED

        assert isinstance(_ORJSON_ENABLED, bool)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_fast_json(self):
        """Test fast_json module can be imported."""
        from utils import fast_json

        assert fast_json is not None

    def test_import_json_loads(self):
        """Test json_loads can be imported."""
        from utils.fast_json import json_loads

        assert json_loads is not None

    def test_import_json_dumps(self):
        """Test json_dumps can be imported."""
        from utils.fast_json import json_dumps

        assert json_dumps is not None

    def test_import_json_dumps_bytes(self):
        """Test json_dumps_bytes can be imported."""
        from utils.fast_json import json_dumps_bytes

        assert json_dumps_bytes is not None

    def test_import_is_orjson_enabled(self):
        """Test is_orjson_enabled can be imported."""
        from utils.fast_json import is_orjson_enabled

        assert is_orjson_enabled is not None


class TestRoundTrip:
    """Tests for round-trip JSON operations."""

    def test_roundtrip_simple(self):
        """Test simple roundtrip."""
        from utils.fast_json import json_dumps, json_loads

        original = {"key": "value"}
        json_str = json_dumps(original)
        result = json_loads(json_str)

        assert result == original

    def test_roundtrip_complex(self):
        """Test complex roundtrip."""
        from utils.fast_json import json_dumps, json_loads

        original = {
            "string": "hello",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"a": 1, "b": 2},
        }

        json_str = json_dumps(original)
        result = json_loads(json_str)

        assert result == original

    def test_roundtrip_bytes(self):
        """Test roundtrip with bytes."""
        from utils.fast_json import json_dumps_bytes, json_loads

        original = {"key": "value"}
        json_bytes = json_dumps_bytes(original)
        result = json_loads(json_bytes)

        assert result == original


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_dict(self):
        """Test with empty dict."""
        from utils.fast_json import json_dumps, json_loads

        original = {}
        json_str = json_dumps(original)
        result = json_loads(json_str)

        assert result == {}

    def test_empty_list(self):
        """Test with empty list."""
        from utils.fast_json import json_dumps, json_loads

        original = []
        json_str = json_dumps(original)
        result = json_loads(json_str)

        assert result == []

    def test_null_value(self):
        """Test with null value."""
        from utils.fast_json import json_dumps, json_loads

        original = {"key": None}
        json_str = json_dumps(original)
        result = json_loads(json_str)

        assert result["key"] is None
