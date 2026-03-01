# pylint: disable=protected-access
"""
Unit Tests for Content Processor Module (deprecated, re-exports from media_processor).
Tests image processing, caching, and avatar handling.
"""

from __future__ import annotations

import base64
import io

# Suppress the expected DeprecationWarning from importing the deprecated module
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

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


# ======================================================================
# Merged from test_content_processor_module.py
# ======================================================================

class TestLoadCachedImageBytes:
    """Tests for load_cached_image_bytes function."""

    def test_load_cached_image_bytes_non_existent(self):
        """Test load_cached_image_bytes with non-existent file."""
        from cogs.ai_core.content_processor import load_cached_image_bytes

        result = load_cached_image_bytes("/non/existent/path/image.png")

        assert result is None

    def test_load_cached_image_bytes_function_exists(self):
        """Test load_cached_image_bytes function exists."""
        from cogs.ai_core.content_processor import load_cached_image_bytes
        assert callable(load_cached_image_bytes)


class TestPilToInlineData:
    """Tests for pil_to_inline_data function."""

    def test_pil_to_inline_data_basic(self):
        """Test pil_to_inline_data with basic image."""
        from cogs.ai_core.content_processor import pil_to_inline_data

        # Create a simple test image
        img = Image.new('RGB', (100, 100), color='red')

        result = pil_to_inline_data(img)

        assert "inline_data" in result
        assert "mime_type" in result["inline_data"]
        assert "data" in result["inline_data"]
        assert result["inline_data"]["mime_type"] == "image/png"

    def test_pil_to_inline_data_base64(self):
        """Test pil_to_inline_data returns valid base64."""
        import base64

        from cogs.ai_core.content_processor import pil_to_inline_data

        # Create a simple test image
        img = Image.new('RGB', (50, 50), color='blue')

        result = pil_to_inline_data(img)

        # Should be valid base64
        data = result["inline_data"]["data"]
        decoded = base64.b64decode(data)
        assert len(decoded) > 0

    def test_pil_to_inline_data_rgba(self):
        """Test pil_to_inline_data with RGBA image."""
        from cogs.ai_core.content_processor import pil_to_inline_data

        # Create RGBA image
        img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 128))

        result = pil_to_inline_data(img)

        assert "inline_data" in result


class TestPrepareUserAvatar:
    """Tests for prepare_user_avatar function."""

    @pytest.mark.asyncio
    async def test_prepare_user_avatar_empty_history(self):
        """Test prepare_user_avatar with empty history."""
        from cogs.ai_core.content_processor import prepare_user_avatar

        mock_user = MagicMock()
        mock_user.display_name = "TestUser"
        mock_user.id = 12345

        # Create mock avatar
        mock_avatar = MagicMock()
        mock_avatar.with_format.return_value = mock_avatar
        mock_avatar.with_size.return_value = mock_avatar

        # Create valid PNG bytes
        img = Image.new('RGB', (256, 256), color='red')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        mock_avatar.read = AsyncMock(return_value=buffer.getvalue())

        mock_user.display_avatar = mock_avatar

        chat_data = {"history": []}  # Empty history
        seen_users = {}

        result = await prepare_user_avatar(
            mock_user, "Hello", chat_data, 123, seen_users
        )

        assert result is not None
        assert isinstance(result, Image.Image)

    @pytest.mark.asyncio
    async def test_prepare_user_avatar_keyword_trigger(self):
        """Test prepare_user_avatar with avatar keyword."""
        from cogs.ai_core.content_processor import prepare_user_avatar

        mock_user = MagicMock()
        mock_user.display_name = "TestUser"
        mock_user.id = 12345

        # Create mock avatar
        mock_avatar = MagicMock()
        mock_avatar.with_format.return_value = mock_avatar
        mock_avatar.with_size.return_value = mock_avatar

        # Create valid PNG bytes
        img = Image.new('RGB', (256, 256), color='green')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        mock_avatar.read = AsyncMock(return_value=buffer.getvalue())

        mock_user.display_avatar = mock_avatar

        chat_data = {"history": ["previous message"]}
        seen_users = {123: {"12345_TestUser"}}  # Already seen

        # Message contains avatar keyword
        result = await prepare_user_avatar(
            mock_user, "What does my avatar look like?", chat_data, 123, seen_users
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_prepare_user_avatar_already_seen(self):
        """Test prepare_user_avatar when user already seen."""
        from cogs.ai_core.content_processor import prepare_user_avatar

        mock_user = MagicMock()
        mock_user.display_name = "TestUser"
        mock_user.id = 12345

        chat_data = {"history": ["previous"]}
        seen_users = {123: {"12345_TestUser"}}  # Already seen

        # No keyword trigger
        result = await prepare_user_avatar(
            mock_user, "Hello there!", chat_data, 123, seen_users
        )

        assert result is None


class TestTextExtensions:
    """Tests for TEXT_EXTENSIONS constant."""

    def test_text_extensions_includes_common(self):
        """Test TEXT_EXTENSIONS includes common extensions."""
        from cogs.ai_core.content_processor import TEXT_EXTENSIONS

        assert ".txt" in TEXT_EXTENSIONS
        assert ".md" in TEXT_EXTENSIONS
        assert ".json" in TEXT_EXTENSIONS
        assert ".py" in TEXT_EXTENSIONS
        assert ".js" in TEXT_EXTENSIONS

    def test_text_extensions_is_tuple(self):
        """Test TEXT_EXTENSIONS is a tuple."""
        from cogs.ai_core.content_processor import TEXT_EXTENSIONS

        assert isinstance(TEXT_EXTENSIONS, tuple)


class TestTextMimes:
    """Tests for TEXT_MIMES constant."""

    def test_text_mimes_includes_common(self):
        """Test TEXT_MIMES includes common types."""
        from cogs.ai_core.content_processor import TEXT_MIMES

        assert "text/plain" in TEXT_MIMES
        assert "text/markdown" in TEXT_MIMES
        assert "application/json" in TEXT_MIMES

    def test_text_mimes_is_tuple(self):
        """Test TEXT_MIMES is a tuple."""
        from cogs.ai_core.content_processor import TEXT_MIMES

        assert isinstance(TEXT_MIMES, tuple)


class TestProcessAttachments:
    """Tests for process_attachments function."""

    @pytest.mark.asyncio
    async def test_process_attachments_none(self):
        """Test process_attachments with None."""
        from cogs.ai_core.content_processor import process_attachments

        result = await process_attachments(None, "TestUser")

        images, videos, texts = result
        assert images == []
        assert videos == []
        assert texts == []

    @pytest.mark.asyncio
    async def test_process_attachments_empty(self):
        """Test process_attachments with empty list."""
        from cogs.ai_core.content_processor import process_attachments

        result = await process_attachments([], "TestUser")

        images, videos, texts = result
        assert images == []
        assert videos == []
        assert texts == []


class TestModuleImports:
    """Tests for module imports."""

    def test_import_content_processor(self):
        """Test content_processor module can be imported."""
        from cogs.ai_core import content_processor
        assert content_processor is not None

    def test_import_load_cached_image_bytes(self):
        """Test load_cached_image_bytes can be imported."""
        from cogs.ai_core.content_processor import load_cached_image_bytes
        assert load_cached_image_bytes is not None

    def test_import_pil_to_inline_data(self):
        """Test pil_to_inline_data can be imported."""
        from cogs.ai_core.content_processor import pil_to_inline_data
        assert pil_to_inline_data is not None

    def test_import_prepare_user_avatar(self):
        """Test prepare_user_avatar can be imported."""
        from cogs.ai_core.content_processor import prepare_user_avatar
        assert prepare_user_avatar is not None

    def test_import_process_attachments(self):
        """Test process_attachments can be imported."""
        from cogs.ai_core.content_processor import process_attachments
        assert process_attachments is not None


class TestImageioAvailability:
    """Tests for imageio availability."""

    def test_imageio_available_flag(self):
        """Test IMAGEIO_AVAILABLE flag exists."""
        from cogs.ai_core.content_processor import IMAGEIO_AVAILABLE

        assert isinstance(IMAGEIO_AVAILABLE, bool)


class TestServerCharacters:
    """Tests for SERVER_CHARACTERS import."""

    def test_import_server_characters(self):
        """Test SERVER_CHARACTERS can be imported."""
        from cogs.ai_core.data.roleplay_data import SERVER_CHARACTERS
        assert SERVER_CHARACTERS is not None
        assert isinstance(SERVER_CHARACTERS, list)


# ======================================================================
# Merged from test_content_processor_more.py
# ======================================================================

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

        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.read_bytes', return_value=b'test_image_data'):
                result = load_cached_image_bytes('/test/image.png')

        assert result == b'test_image_data'

    def test_load_cached_image_bytes_not_exists(self):
        """Test loading image bytes when file does not exist."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        load_cached_image_bytes.cache_clear()

        with patch('pathlib.Path.exists', return_value=False):
            result = load_cached_image_bytes('/nonexistent/image.png')

        assert result is None

    def test_load_cached_image_bytes_oserror(self):
        """Test loading image bytes with OSError."""
        try:
            from cogs.ai_core.content_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("content_processor not available")
            return

        load_cached_image_bytes.cache_clear()

        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.read_bytes', side_effect=OSError("Read error")):
                result = load_cached_image_bytes('/error/image.png')

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

        img = Image.new('RGB', (10, 10), color='blue')
        result = pil_to_inline_data(img)

        assert 'inline_data' in result
        assert 'mime_type' in result['inline_data']
        assert 'data' in result['inline_data']

    def test_pil_to_inline_data_mime_type(self):
        """Test pil_to_inline_data returns PNG mime type."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new('RGB', (10, 10), color='green')
        result = pil_to_inline_data(img)

        assert result['inline_data']['mime_type'] == 'image/png'

    def test_pil_to_inline_data_valid_base64(self):
        """Test pil_to_inline_data returns valid base64."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new('RGB', (5, 5), color='red')
        result = pil_to_inline_data(img)

        # Try to decode base64
        decoded = base64.b64decode(result['inline_data']['data'])
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
        assert hasattr(load_cached_image_bytes, 'cache_info')
        assert hasattr(load_cached_image_bytes, 'cache_clear')

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

        img = Image.new('RGBA', (10, 10), color=(255, 0, 0, 128))
        result = pil_to_inline_data(img)

        assert 'inline_data' in result

    def test_convert_grayscale_image(self):
        """Test converting grayscale image."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new('L', (10, 10), color=128)
        result = pil_to_inline_data(img)

        assert 'inline_data' in result


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

        img = Image.new('RGB', (5, 5), color='yellow')
        result = pil_to_inline_data(img)

        assert isinstance(result['inline_data']['data'], str)

    def test_mime_type_is_string(self):
        """Test mime_type field is a string."""
        try:
            from PIL import Image

            from cogs.ai_core.content_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("content_processor or PIL not available")
            return

        img = Image.new('RGB', (5, 5), color='cyan')
        result = pil_to_inline_data(img)

        assert isinstance(result['inline_data']['mime_type'], str)
