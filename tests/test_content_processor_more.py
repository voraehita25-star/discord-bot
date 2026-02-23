"""
Extended tests for Content Processor module.
Tests image caching and PIL conversion functions.
"""

import base64
from unittest.mock import patch

import pytest


class TestLoadCachedImageBytesFunction:
    """Tests for load_cached_image_bytes function."""

    def test_load_cached_image_bytes_exists(self):
        """Test loading image bytes when file exists."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        # Clear the cache
        load_cached_image_bytes.cache_clear()

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_bytes", return_value=b"test_image_data"):
                result = load_cached_image_bytes("/test/image.png")

        assert result == b"test_image_data"

    def test_load_cached_image_bytes_not_exists(self):
        """Test loading image bytes when file does not exist."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        load_cached_image_bytes.cache_clear()

        with patch("pathlib.Path.exists", return_value=False):
            result = load_cached_image_bytes("/nonexistent/image.png")

        assert result is None

    def test_load_cached_image_bytes_oserror(self):
        """Test loading image bytes with OSError."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        load_cached_image_bytes.cache_clear()

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_bytes", side_effect=OSError("Read error")):
                result = load_cached_image_bytes("/error/image.png")

        assert result is None


class TestPilToInlineData:
    """Tests for pil_to_inline_data function."""

    def test_pil_to_inline_data_structure(self):
        """Test pil_to_inline_data returns correct structure."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("RGB", (10, 10), color="blue")
        result = pil_to_inline_data(img)

        assert "inline_data" in result
        assert "mime_type" in result["inline_data"]
        assert "data" in result["inline_data"]

    def test_pil_to_inline_data_mime_type(self):
        """Test pil_to_inline_data returns PNG mime type."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("RGB", (10, 10), color="green")
        result = pil_to_inline_data(img)

        assert result["inline_data"]["mime_type"] == "image/png"

    def test_pil_to_inline_data_valid_base64(self):
        """Test pil_to_inline_data returns valid base64."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("RGB", (5, 5), color="red")
        result = pil_to_inline_data(img)

        # Try to decode base64
        decoded = base64.b64decode(result["inline_data"]["data"])
        assert len(decoded) > 0


class TestImageioAvailable:
    """Tests for IMAGEIO_AVAILABLE constant."""

    def test_imageio_available_is_bool(self):
        """Test IMAGEIO_AVAILABLE is boolean."""
        try:
            from cogs.ai_core.content_processor import IMAGEIO_AVAILABLE
        except ImportError:
            pytest.skip("content_processor not available")
            return

        assert isinstance(IMAGEIO_AVAILABLE, bool)


class TestServerCharactersImport:
    """Tests for SERVER_CHARACTER_NAMES import."""

    def test_server_characters_imported(self):
        """Test SERVER_CHARACTER_NAMES is imported from roleplay_data."""
        try:
            from cogs.ai_core.data.roleplay_data import SERVER_CHARACTER_NAMES
        except ImportError:
            pytest.skip("roleplay_data not available")
            return

        # SERVER_CHARACTER_NAMES should be a dict
        assert isinstance(SERVER_CHARACTER_NAMES, dict)


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test content_processor module has docstring."""
        try:
            from cogs.ai_core import content_processor
        except ImportError:
            pytest.skip("content_processor not available")
            return

        assert content_processor.__doc__ is not None


class TestCacheFunction:
    """Tests for cache functionality."""

    def test_cache_is_lru_cache(self):
        """Test load_cached_image_bytes uses lru_cache."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        # Check for cache_info method (added by lru_cache)
        assert hasattr(load_cached_image_bytes, "cache_info")
        assert hasattr(load_cached_image_bytes, "cache_clear")

    def test_cache_clear_works(self):
        """Test cache_clear works."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        # Should not raise an error
        load_cached_image_bytes.cache_clear()


class TestPilImageConversion:
    """Tests for PIL image conversion."""

    def test_convert_rgba_image(self):
        """Test converting RGBA image."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
        result = pil_to_inline_data(img)

        assert "inline_data" in result

    def test_convert_grayscale_image(self):
        """Test converting grayscale image."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("L", (10, 10), color=128)
        result = pil_to_inline_data(img)

        assert "inline_data" in result


class TestInlineDataFormat:
    """Tests for inline_data format."""

    def test_data_is_string(self):
        """Test data field is a string."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("RGB", (5, 5), color="yellow")
        result = pil_to_inline_data(img)

        assert isinstance(result["inline_data"]["data"], str)

    def test_mime_type_is_string(self):
        """Test mime_type field is a string."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new("RGB", (5, 5), color="cyan")
        result = pil_to_inline_data(img)

        assert isinstance(result["inline_data"]["mime_type"], str)
