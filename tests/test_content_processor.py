# pylint: disable=protected-access
"""
Unit Tests for Content Processor Module (deprecated, re-exports from media_processor).
Tests image processing, caching, and avatar handling.
"""

from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

# Suppress the expected DeprecationWarning from importing the deprecated module
pytestmark = pytest.mark.filterwarnings(
    "ignore:content_processor module is deprecated:DeprecationWarning"
)


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


class TestTextExtensions:
    """Tests for TEXT_EXTENSIONS constant."""

    def test_text_extensions_exists(self):
        """Test TEXT_EXTENSIONS constant exists."""
        from cogs.ai_core.content_processor import TEXT_EXTENSIONS

        assert isinstance(TEXT_EXTENSIONS, tuple)

    def test_text_extensions_common_types(self):
        """Test common text extensions are included."""
        from cogs.ai_core.content_processor import TEXT_EXTENSIONS

        assert ".txt" in TEXT_EXTENSIONS
        assert ".md" in TEXT_EXTENSIONS
        assert ".json" in TEXT_EXTENSIONS
        assert ".py" in TEXT_EXTENSIONS
        assert ".js" in TEXT_EXTENSIONS
        assert ".html" in TEXT_EXTENSIONS


class TestTextMimes:
    """Tests for TEXT_MIMES constant."""

    def test_text_mimes_exists(self):
        """Test TEXT_MIMES constant exists."""
        from cogs.ai_core.content_processor import TEXT_MIMES

        assert isinstance(TEXT_MIMES, tuple)

    def test_text_mimes_common_types(self):
        """Test common MIME types are included."""
        from cogs.ai_core.content_processor import TEXT_MIMES

        assert "text/plain" in TEXT_MIMES
        assert "application/json" in TEXT_MIMES
        assert "text/html" in TEXT_MIMES


class TestProcessAttachments:
    """Tests for process_attachments function."""

    @pytest.mark.asyncio
    async def test_process_attachments_none(self):
        """Test processing None attachments."""
        from cogs.ai_core.content_processor import process_attachments

        image_parts, video_parts, text_parts = await process_attachments(
            None, "TestUser"
        )

        assert image_parts == []
        assert video_parts == []
        assert text_parts == []

    @pytest.mark.asyncio
    async def test_process_attachments_empty_list(self):
        """Test processing empty attachment list."""
        from cogs.ai_core.content_processor import process_attachments

        image_parts, video_parts, text_parts = await process_attachments(
            [], "TestUser"
        )

        assert image_parts == []
        assert video_parts == []
        assert text_parts == []

    @pytest.mark.asyncio
    async def test_process_attachments_text_file(self):
        """Test processing text file attachment."""
        from cogs.ai_core.content_processor import process_attachments

        # Create mock attachment
        mock_attachment = MagicMock()
        mock_attachment.content_type = "text/plain"
        mock_attachment.filename = "test.txt"
        mock_attachment.size = 11
        mock_attachment.read = AsyncMock(return_value=b"Hello World")

        image_parts, video_parts, text_parts = await process_attachments(
            [mock_attachment], "TestUser"
        )

        assert len(text_parts) == 1
        assert "Hello World" in text_parts[0]

    @pytest.mark.asyncio
    async def test_process_attachments_utf8_text(self):
        """Test processing UTF-8 encoded text file."""
        from cogs.ai_core.content_processor import process_attachments

        # Create mock attachment with UTF-8 text
        mock_attachment = MagicMock()
        mock_attachment.content_type = "text/plain"
        mock_attachment.filename = "test.txt"
        mock_attachment.size = 100
        mock_attachment.read = AsyncMock(return_value="สวัสดี".encode())

        image_parts, video_parts, text_parts = await process_attachments(
            [mock_attachment], "TestUser"
        )

        assert len(text_parts) == 1
        assert "สวัสดี" in text_parts[0]

    @pytest.mark.asyncio
    async def test_process_attachments_large_file_chunking(self):
        """Test processing large text file with chunking."""
        from cogs.ai_core.content_processor import process_attachments

        # Create large content
        large_content = "A" * 20000  # Over chunk_size

        mock_attachment = MagicMock()
        mock_attachment.content_type = "text/plain"
        mock_attachment.filename = "large.txt"
        mock_attachment.size = 20000
        mock_attachment.read = AsyncMock(return_value=large_content.encode('utf-8'))

        image_parts, video_parts, text_parts = await process_attachments(
            [mock_attachment], "TestUser"
        )

        # Should be chunked into multiple parts
        assert len(text_parts) >= 2

    @pytest.mark.asyncio
    async def test_process_python_file_by_extension(self):
        """Test processing .py file by extension."""
        from cogs.ai_core.content_processor import process_attachments

        mock_attachment = MagicMock()
        mock_attachment.content_type = None  # No MIME type
        mock_attachment.filename = "script.py"
        mock_attachment.size = 14
        mock_attachment.read = AsyncMock(return_value=b"print('hello')")

        image_parts, video_parts, text_parts = await process_attachments(
            [mock_attachment], "TestUser"
        )

        assert len(text_parts) == 1
        assert "print('hello')" in text_parts[0]

    @pytest.mark.asyncio
    async def test_process_json_file(self):
        """Test processing .json file."""
        from cogs.ai_core.content_processor import process_attachments

        mock_attachment = MagicMock()
        mock_attachment.content_type = "application/json"
        mock_attachment.filename = "data.json"
        mock_attachment.size = 16
        mock_attachment.read = AsyncMock(return_value=b'{"key": "value"}')

        image_parts, video_parts, text_parts = await process_attachments(
            [mock_attachment], "TestUser"
        )

        assert len(text_parts) == 1
        assert '{"key": "value"}' in text_parts[0]


class TestImageioAvailable:
    """Tests for IMAGEIO_AVAILABLE flag."""

    def test_imageio_available_is_bool(self):
        """Test IMAGEIO_AVAILABLE is boolean."""
        from cogs.ai_core.content_processor import IMAGEIO_AVAILABLE

        assert isinstance(IMAGEIO_AVAILABLE, bool)


class TestPrepareUserAvatar:
    """Tests for prepare_user_avatar function."""

    @pytest.mark.asyncio
    async def test_prepare_user_avatar_initializes_seen_users(self):
        """Test prepare_user_avatar initializes seen_users for channel."""
        from cogs.ai_core.content_processor import prepare_user_avatar

        # Create mock user
        mock_user = MagicMock()
        mock_user.display_name = "TestUser"
        mock_user.id = 123456789

        # Create mock avatar
        img = Image.new('RGB', (256, 256), color='red')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')

        mock_avatar = MagicMock()
        mock_avatar.with_format = MagicMock(return_value=mock_avatar)
        mock_avatar.with_size = MagicMock(return_value=mock_avatar)
        mock_avatar.read = AsyncMock(return_value=buffer.getvalue())
        mock_user.display_avatar = mock_avatar

        chat_data = {}  # No history key
        seen_users = {}

        await prepare_user_avatar(
            mock_user,
            "Hello",
            chat_data,
            12345,
            seen_users
        )

        # Channel should be initialized in seen_users
        assert 12345 in seen_users

    @pytest.mark.asyncio
    async def test_prepare_user_avatar_keyword_trigger(self):
        """Test prepare_user_avatar with appearance keyword."""
        from cogs.ai_core.content_processor import prepare_user_avatar

        # Create mock user
        mock_user = MagicMock()
        mock_user.display_name = "TestUser"
        mock_user.id = 123456789

        # Create mock avatar
        img = Image.new('RGB', (256, 256), color='red')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')

        mock_avatar = MagicMock()
        mock_avatar.with_format = MagicMock(return_value=mock_avatar)
        mock_avatar.with_size = MagicMock(return_value=mock_avatar)
        mock_avatar.read = AsyncMock(return_value=buffer.getvalue())
        mock_user.display_avatar = mock_avatar

        chat_data = {"history": [{"text": "hi"}]}
        seen_users = {12345: {"123456789_TestUser"}}

        # Use keyword "appearance" to trigger avatar
        result = await prepare_user_avatar(
            mock_user,
            "What does my face look like?",
            chat_data,
            12345,
            seen_users
        )

        # Should return an image due to keyword "face"
        assert result is not None
