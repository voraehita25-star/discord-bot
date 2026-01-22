"""Tests for media_processor module."""

import pytest
from unittest.mock import MagicMock, patch
import io
from PIL import Image


class TestLoadCachedImageBytes:
    """Tests for load_cached_image_bytes function."""

    def test_load_existing_file(self):
        """Test loading existing image file."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        
        # Create a temp image
        img = Image.new("RGB", (10, 10), color="red")
        with io.BytesIO() as buf:
            img.save(buf, format="PNG")
            expected_bytes = buf.getvalue()
        
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_bytes", return_value=expected_bytes):
                # Clear cache first
                load_cached_image_bytes.cache_clear()
                
                result = load_cached_image_bytes("/test/image.png")
                
                assert result == expected_bytes

    def test_load_nonexistent_file(self):
        """Test loading non-existent file returns None."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        
        # Clear cache
        load_cached_image_bytes.cache_clear()
        
        with patch("pathlib.Path.exists", return_value=False):
            result = load_cached_image_bytes("/nonexistent/image.png")
            
            assert result is None

    def test_load_file_oserror(self):
        """Test loading file with OSError returns None."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        
        load_cached_image_bytes.cache_clear()
        
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_bytes", side_effect=OSError("read error")):
                result = load_cached_image_bytes("/error/image.png")
                
                assert result is None


class TestPilToInlineData:
    """Tests for pil_to_inline_data function."""

    def test_convert_image_to_inline_data(self):
        """Test converting PIL image to inline data."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        img = Image.new("RGB", (10, 10), color="red")
        
        result = pil_to_inline_data(img)
        
        assert "inline_data" in result
        assert "mime_type" in result["inline_data"]
        assert result["inline_data"]["mime_type"] == "image/png"
        assert "data" in result["inline_data"]
        assert isinstance(result["inline_data"]["data"], str)

    def test_convert_rgba_image(self):
        """Test converting RGBA image."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        img = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
        
        result = pil_to_inline_data(img)
        
        assert "inline_data" in result


class TestIsAnimatedGif:
    """Tests for is_animated_gif function."""

    def test_static_image(self):
        """Test static image returns False."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        # Create a static PNG
        img = Image.new("RGB", (10, 10), color="red")
        with io.BytesIO() as buf:
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        
        result = is_animated_gif(img_bytes)
        
        assert result is False

    def test_static_gif(self):
        """Test static GIF returns False."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        # Create a static GIF
        img = Image.new("RGB", (10, 10), color="red")
        with io.BytesIO() as buf:
            img.save(buf, format="GIF")
            img_bytes = buf.getvalue()
        
        result = is_animated_gif(img_bytes)
        
        assert result is False

    def test_invalid_data(self):
        """Test invalid data returns False."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        result = is_animated_gif(b"not an image")
        
        assert result is False


class TestConvertGifToVideo:
    """Tests for convert_gif_to_video function."""

    def test_convert_without_imageio(self):
        """Test conversion returns None without imageio."""
        from cogs.ai_core import media_processor
        
        original = media_processor.IMAGEIO_AVAILABLE
        media_processor.IMAGEIO_AVAILABLE = False
        
        try:
            result = media_processor.convert_gif_to_video(b"gif data")
            assert result is None
        finally:
            media_processor.IMAGEIO_AVAILABLE = original

    def test_convert_static_gif(self):
        """Test converting static GIF returns None."""
        from cogs.ai_core import media_processor
        
        if not media_processor.IMAGEIO_AVAILABLE:
            pytest.skip("imageio not available")
        
        # Create a static GIF
        img = Image.new("RGB", (10, 10), color="red")
        with io.BytesIO() as buf:
            img.save(buf, format="GIF")
            gif_bytes = buf.getvalue()
        
        result = media_processor.convert_gif_to_video(gif_bytes)
        
        # Static GIF should return None
        assert result is None


class TestLoadCharacterImage:
    """Tests for load_character_image function."""

    def test_no_guild_id(self):
        """Test with no guild_id returns None."""
        from cogs.ai_core.media_processor import load_character_image
        
        result = load_character_image("test message", None)
        
        assert result is None

    def test_unknown_guild(self):
        """Test with unknown guild returns None."""
        from cogs.ai_core.media_processor import load_character_image
        
        result = load_character_image("test message", 99999999)
        
        assert result is None


class TestAvatarKeywords:
    """Tests for AVATAR_KEYWORDS constant."""

    def test_avatar_keywords_exists(self):
        """Test AVATAR_KEYWORDS list exists."""
        from cogs.ai_core.media_processor import AVATAR_KEYWORDS
        
        assert isinstance(AVATAR_KEYWORDS, list)
        assert len(AVATAR_KEYWORDS) > 0

    def test_avatar_keywords_contents(self):
        """Test AVATAR_KEYWORDS contains expected values."""
        from cogs.ai_core.media_processor import AVATAR_KEYWORDS
        
        assert "avatar" in AVATAR_KEYWORDS
        assert "face" in AVATAR_KEYWORDS


class TestModuleConstants:
    """Tests for module constants."""

    def test_imageio_available_exists(self):
        """Test IMAGEIO_AVAILABLE constant exists."""
        from cogs.ai_core.media_processor import IMAGEIO_AVAILABLE
        
        assert isinstance(IMAGEIO_AVAILABLE, bool)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_load_cached_image_bytes(self):
        """Test importing load_cached_image_bytes."""
        from cogs.ai_core.media_processor import load_cached_image_bytes
        
        assert callable(load_cached_image_bytes)

    def test_import_pil_to_inline_data(self):
        """Test importing pil_to_inline_data."""
        from cogs.ai_core.media_processor import pil_to_inline_data
        
        assert callable(pil_to_inline_data)

    def test_import_is_animated_gif(self):
        """Test importing is_animated_gif."""
        from cogs.ai_core.media_processor import is_animated_gif
        
        assert callable(is_animated_gif)

    def test_import_convert_gif_to_video(self):
        """Test importing convert_gif_to_video."""
        from cogs.ai_core.media_processor import convert_gif_to_video
        
        assert callable(convert_gif_to_video)

    def test_import_load_character_image(self):
        """Test importing load_character_image."""
        from cogs.ai_core.media_processor import load_character_image
        
        assert callable(load_character_image)
