"""Tests for fast_json module."""



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
