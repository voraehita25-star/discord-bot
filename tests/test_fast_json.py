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
