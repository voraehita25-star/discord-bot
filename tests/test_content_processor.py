# pylint: disable=protected-access
"""
Unit Tests for Content Processor Module.
Tests image processing, caching, and avatar handling.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image


class TestLoadCachedImageBytes:
    """Tests for load_cached_image_bytes function."""

    def test_load_existing_file(self, tmp_path):
        """Test loading existing image file."""
        from cogs.ai_core.content_processor import load_cached_image_bytes

        # Clear cache for test
        load_cached_image_bytes.cache_clear()

        # Create test file
        test_file = tmp_path / "test_image.png"
        img = Image.new("RGB", (10, 10), color="red")
        img.save(test_file)

        result = load_cached_image_bytes(str(test_file))
        assert result is not None
        assert len(result) > 0

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading non-existent file returns None."""
        from cogs.ai_core.content_processor import load_cached_image_bytes

        load_cached_image_bytes.cache_clear()
        result = load_cached_image_bytes(str(tmp_path / "nonexistent.png"))
        assert result is None


class TestPilToInlineData:
    """Tests for pil_to_inline_data conversion."""

    def test_converts_image_to_base64(self):
        """Test PIL image is converted to base64 inline data."""
        from cogs.ai_core.content_processor import pil_to_inline_data

        img = Image.new("RGB", (10, 10), color="blue")
        result = pil_to_inline_data(img)

        assert "inline_data" in result
        assert result["inline_data"]["mime_type"] == "image/png"
        assert len(result["inline_data"]["data"]) > 0

        # Verify it's valid base64
        decoded = base64.b64decode(result["inline_data"]["data"])
        assert len(decoded) > 0

    def test_handles_rgba_image(self):
        """Test RGBA image with transparency."""
        from cogs.ai_core.content_processor import pil_to_inline_data

        img = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
        result = pil_to_inline_data(img)

        assert "inline_data" in result
        assert len(result["inline_data"]["data"]) > 0


class TestIsAnimatedGif:
    """Tests for animated GIF detection."""

    def test_detects_static_gif(self):
        """Test static GIF is not detected as animated."""
        from cogs.ai_core.content_processor import is_animated_gif

        # Create single-frame GIF
        img = Image.new("RGB", (10, 10), color="green")
        buffer = io.BytesIO()
        img.save(buffer, format="GIF")
        buffer.seek(0)

        result = is_animated_gif(buffer.getvalue())
        assert result is False

    def test_detects_animated_gif(self):
        """Test animated GIF with multiple frames is detected."""
        from cogs.ai_core.content_processor import is_animated_gif

        # Create multi-frame GIF
        frames = [
            Image.new("RGB", (10, 10), color="red"),
            Image.new("RGB", (10, 10), color="blue"),
        ]
        buffer = io.BytesIO()
        frames[0].save(
            buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100
        )
        buffer.seek(0)

        result = is_animated_gif(buffer.getvalue())
        assert result is True


class TestLoadCharacterImage:
    """Tests for character image loading."""

    def test_returns_none_for_no_guild(self):
        """Test returns None when guild_id is None."""
        from cogs.ai_core.content_processor import load_character_image

        result = load_character_image("some message", None)
        assert result is None

    def test_returns_none_for_unknown_guild(self):
        """Test returns None for guild not in SERVER_CHARACTERS."""
        from cogs.ai_core.content_processor import load_character_image

        result = load_character_image("some message", 999999)
        assert result is None
