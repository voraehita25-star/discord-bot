"""Tests for media processor module."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import io
from PIL import Image
import base64


class TestLoadCachedImageBytes:
    """Tests for load_cached_image_bytes function."""

    def test_load_cached_image_bytes_non_existent(self):
        """Test load_cached_image_bytes with non-existent file."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        
        result = load_cached_image_bytes("/non/existent/path/image.png")
        
        assert result is None

    def test_load_cached_image_bytes_function_exists(self):
        """Test load_cached_image_bytes function exists."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        assert callable(load_cached_image_bytes)


class TestPilToInlineData:
    """Tests for pil_to_inline_data function."""

    def test_pil_to_inline_data_basic(self):
        """Test pil_to_inline_data with basic image."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        # Create a simple test image
        img = Image.new('RGB', (100, 100), color='red')
        
        result = pil_to_inline_data(img)
        
        assert "inline_data" in result
        assert "mime_type" in result["inline_data"]
        assert "data" in result["inline_data"]
        assert result["inline_data"]["mime_type"] == "image/png"

    def test_pil_to_inline_data_base64_valid(self):
        """Test pil_to_inline_data returns valid base64."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        # Create a simple test image
        img = Image.new('RGB', (50, 50), color='blue')
        
        result = pil_to_inline_data(img)
        
        # Should be valid base64
        data = result["inline_data"]["data"]
        decoded = base64.b64decode(data)
        assert len(decoded) > 0

    def test_pil_to_inline_data_rgba(self):
        """Test pil_to_inline_data with RGBA image."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        # Create RGBA image
        img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 128))
        
        result = pil_to_inline_data(img)
        
        assert "inline_data" in result


class TestIsAnimatedGif:
    """Tests for is_animated_gif function."""

    def test_is_animated_gif_static(self):
        """Test is_animated_gif with static image."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        # Create static GIF
        img = Image.new('P', (10, 10), color=0)
        buffer = io.BytesIO()
        img.save(buffer, format='GIF')
        
        result = is_animated_gif(buffer.getvalue())
        
        assert result is False

    def test_is_animated_gif_invalid_data(self):
        """Test is_animated_gif with invalid data."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        result = is_animated_gif(b"not a gif")
        
        assert result is False


class TestModuleImports:
    """Tests for module imports."""

    def test_import_media_processor(self):
        """Test media_processor module can be imported."""
        from cogs.ai_core import media_processor
        assert media_processor is not None

    def test_import_load_cached_image_bytes(self):
        """Test load_cached_image_bytes can be imported."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        assert load_cached_image_bytes is not None

    def test_import_pil_to_inline_data(self):
        """Test pil_to_inline_data can be imported."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        assert pil_to_inline_data is not None

    def test_import_is_animated_gif(self):
        """Test is_animated_gif can be imported."""
        from cogs.ai_core.media_processor import is_animated_gif
        assert is_animated_gif is not None


class TestImageioAvailability:
    """Tests for imageio availability."""

    def test_imageio_available_flag(self):
        """Test IMAGEIO_AVAILABLE flag exists."""
        from cogs.ai_core.media_processor import IMAGEIO_AVAILABLE
        
        assert isinstance(IMAGEIO_AVAILABLE, bool)


class TestServerCharacters:
    """Tests for SERVER_CHARACTER_NAMES import."""

    def test_server_characters_imported(self):
        """Test SERVER_CHARACTER_NAMES is imported in media_processor."""
        from cogs.ai_core.media_processor import SERVER_CHARACTER_NAMES
        assert SERVER_CHARACTER_NAMES is not None


class TestImageConversion:
    """Tests for image conversion functions."""

    def test_convert_small_image(self):
        """Test converting small image."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        # Very small image
        img = Image.new('RGB', (1, 1), color='white')
        
        result = pil_to_inline_data(img)
        
        assert result is not None
        assert "inline_data" in result

    def test_convert_large_image(self):
        """Test converting larger image."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        # Larger image
        img = Image.new('RGB', (500, 500), color='green')
        
        result = pil_to_inline_data(img)
        
        assert result is not None
        assert len(result["inline_data"]["data"]) > 100


class TestStaticGifDetection:
    """Tests for static GIF detection."""

    def test_static_png_as_gif(self):
        """Test PNG image is not detected as animated."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        # Create PNG and convert to bytes
        img = Image.new('RGB', (10, 10), color='red')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        
        # Should return False (not animated)
        result = is_animated_gif(buffer.getvalue())
        
        assert result is False

    def test_empty_bytes(self):
        """Test empty bytes returns False."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        result = is_animated_gif(b"")
        
        assert result is False
