"""
Extended tests for Media Processor module.
Tests image processing, avatar handling, and attachment processing.
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


import base64
from PIL import Image
from unittest.mock import patch

class TestLoadCachedImageBytes:
    """Tests for load_cached_image_bytes function."""

    def test_load_cached_image_bytes_file_exists(self):
        """Test loading image bytes when file exists."""
        try:
            from cogs.ai_core.media_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("media_processor not available")
            return

        # Clear cache before test
        load_cached_image_bytes.cache_clear()

        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.read_bytes', return_value=b'fake_image_data'):
                result = load_cached_image_bytes('/fake/path/image.png')

        assert result == b'fake_image_data'

    def test_load_cached_image_bytes_file_not_exists(self):
        """Test loading image bytes when file doesn't exist."""
        try:
            from cogs.ai_core.media_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("media_processor not available")
            return

        load_cached_image_bytes.cache_clear()

        with patch('pathlib.Path.exists', return_value=False):
            result = load_cached_image_bytes('/nonexistent/path/image.png')

        assert result is None

    def test_load_cached_image_bytes_read_error(self):
        """Test loading image bytes when read fails."""
        try:
            from cogs.ai_core.media_processor import load_cached_image_bytes
        except ImportError:
            pytest.skip("media_processor not available")
            return

        load_cached_image_bytes.cache_clear()

        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.read_bytes', side_effect=OSError("Read failed")):
                result = load_cached_image_bytes('/fake/path/image.png')

        assert result is None


class TestPilToInlineData:
    """Tests for pil_to_inline_data function."""

    def test_pil_to_inline_data_basic(self):
        """Test converting PIL image to inline data."""
        try:
            from PIL import Image

            from cogs.ai_core.media_processor import pil_to_inline_data
        except ImportError:
            pytest.skip("media_processor or PIL not available")
            return

        # Create a simple test image
        img = Image.new('RGB', (10, 10), color='red')

        result = pil_to_inline_data(img)

        assert 'inline_data' in result
        assert result['inline_data']['mime_type'] == 'image/png'
        assert 'data' in result['inline_data']
        # Check it's valid base64
        import base64
        decoded = base64.b64decode(result['inline_data']['data'])
        assert len(decoded) > 0


class TestIsAnimatedGif:
    """Tests for is_animated_gif function."""

    def test_is_animated_gif_static(self):
        """Test detecting static GIF."""
        try:
            from PIL import Image

            from cogs.ai_core.media_processor import is_animated_gif
        except ImportError:
            pytest.skip("media_processor or PIL not available")
            return

        # Create a static GIF
        img = Image.new('P', (10, 10), color=1)
        buffer = io.BytesIO()
        img.save(buffer, format='GIF')
        gif_data = buffer.getvalue()

        result = is_animated_gif(gif_data)

        assert result is False

    def test_is_animated_gif_invalid_data(self):
        """Test handling invalid GIF data."""
        try:
            from cogs.ai_core.media_processor import is_animated_gif
        except ImportError:
            pytest.skip("media_processor not available")
            return

        result = is_animated_gif(b'not a gif')

        assert result is False


class TestConvertGifToVideo:
    """Tests for convert_gif_to_video function."""

    def test_convert_gif_to_video_imageio_not_available(self):
        """Test conversion when imageio not available."""
        try:
            from cogs.ai_core import media_processor
        except ImportError:
            pytest.skip("media_processor not available")
            return

        # Temporarily disable imageio
        original = media_processor.IMAGEIO_AVAILABLE
        media_processor.IMAGEIO_AVAILABLE = False

        try:
            result = media_processor.convert_gif_to_video(b'fake_gif_data')
            assert result is None
        finally:
            media_processor.IMAGEIO_AVAILABLE = original


class TestLoadCharacterImage:
    """Tests for load_character_image function."""

    def test_load_character_image_no_guild_id(self):
        """Test loading character image with no guild ID."""
        try:
            from cogs.ai_core.media_processor import load_character_image
        except ImportError:
            pytest.skip("media_processor not available")
            return

        result = load_character_image("test message", None)

        assert result is None

    def test_load_character_image_guild_not_in_characters(self):
        """Test loading character image for guild without characters."""
        try:
            from cogs.ai_core.media_processor import load_character_image
        except ImportError:
            pytest.skip("media_processor not available")
            return

        result = load_character_image("test message", 999999)

        assert result is None


class TestAvatarKeywords:
    """Tests for AVATAR_KEYWORDS."""

    def test_avatar_keywords_defined(self):
        """Test AVATAR_KEYWORDS is defined."""
        try:
            from cogs.ai_core.media_processor import AVATAR_KEYWORDS
        except ImportError:
            pytest.skip("media_processor not available")
            return

        assert isinstance(AVATAR_KEYWORDS, (list, tuple))
        assert len(AVATAR_KEYWORDS) > 0

    def test_avatar_keywords_contains_thai(self):
        """Test AVATAR_KEYWORDS contains Thai keywords."""
        try:
            from cogs.ai_core.media_processor import AVATAR_KEYWORDS
        except ImportError:
            pytest.skip("media_processor not available")
            return

        thai_keywords = [k for k in AVATAR_KEYWORDS if not k.isascii()]
        assert len(thai_keywords) > 0

    def test_avatar_keywords_contains_english(self):
        """Test AVATAR_KEYWORDS contains English keywords."""
        try:
            from cogs.ai_core.media_processor import AVATAR_KEYWORDS
        except ImportError:
            pytest.skip("media_processor not available")
            return

        english_keywords = [k for k in AVATAR_KEYWORDS if k.isascii()]
        assert len(english_keywords) > 0


class TestPrepareUserAvatar:
    """Tests for prepare_user_avatar function."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock Discord user."""
        user = MagicMock()
        user.id = 123456
        user.display_name = "TestUser"
        user.display_avatar = MagicMock()
        return user

    async def test_prepare_avatar_empty_history(self, mock_user):
        """Test avatar is sent when history is empty."""
        try:
            from PIL import Image

            from cogs.ai_core.media_processor import prepare_user_avatar
        except ImportError:
            pytest.skip("media_processor or PIL not available")
            return

        # Create a fake avatar image
        avatar_img = Image.new('RGB', (256, 256), color='blue')
        buffer = io.BytesIO()
        avatar_img.save(buffer, format='PNG')
        avatar_bytes = buffer.getvalue()

        mock_user.display_avatar.with_format.return_value.with_size.return_value.read = AsyncMock(
            return_value=avatar_bytes
        )

        chat_data = {"history": []}  # Empty history
        seen_users = {}

        result = await prepare_user_avatar(
            mock_user, "hello", chat_data, 123, seen_users
        )

        assert result is not None

    async def test_prepare_avatar_new_user(self, mock_user):
        """Test avatar is sent for new user in session."""
        try:
            from PIL import Image

            from cogs.ai_core.media_processor import prepare_user_avatar
        except ImportError:
            pytest.skip("media_processor or PIL not available")
            return

        avatar_img = Image.new('RGB', (256, 256), color='blue')
        buffer = io.BytesIO()
        avatar_img.save(buffer, format='PNG')
        avatar_bytes = buffer.getvalue()

        mock_user.display_avatar.with_format.return_value.with_size.return_value.read = AsyncMock(
            return_value=avatar_bytes
        )

        chat_data = {"history": [{"role": "user", "content": "test"}]}
        seen_users = {123: set()}  # User not seen yet

        result = await prepare_user_avatar(
            mock_user, "hello", chat_data, 123, seen_users
        )

        assert result is not None

    async def test_prepare_avatar_keyword_match(self, mock_user):
        """Test avatar is sent when keyword matches."""
        try:
            from PIL import Image

            from cogs.ai_core.media_processor import prepare_user_avatar
        except ImportError:
            pytest.skip("media_processor or PIL not available")
            return

        avatar_img = Image.new('RGB', (256, 256), color='blue')
        buffer = io.BytesIO()
        avatar_img.save(buffer, format='PNG')
        avatar_bytes = buffer.getvalue()

        mock_user.display_avatar.with_format.return_value.with_size.return_value.read = AsyncMock(
            return_value=avatar_bytes
        )

        user_key = f"{mock_user.id}_{mock_user.display_name}"
        chat_data = {"history": [{"role": "user", "content": "test"}]}
        seen_users = {123: {user_key}}  # Already seen, but keyword should trigger

        result = await prepare_user_avatar(
            mock_user, "what does my avatar look like?", chat_data, 123, seen_users
        )

        assert result is not None

    async def test_prepare_avatar_already_seen_no_keyword(self, mock_user):
        """Test no avatar sent when user already seen and no keyword."""
        try:
            from cogs.ai_core.media_processor import prepare_user_avatar
        except ImportError:
            pytest.skip("media_processor not available")
            return

        user_key = f"{mock_user.id}_{mock_user.display_name}"
        chat_data = {"history": [{"role": "user", "content": "test"}]}
        seen_users = {123: {user_key}}  # Already seen

        result = await prepare_user_avatar(
            mock_user, "hello", chat_data, 123, seen_users
        )

        assert result is None

    async def test_prepare_avatar_fetch_error(self, mock_user):
        """Test handling avatar fetch error."""
        try:
            import discord

            from cogs.ai_core.media_processor import prepare_user_avatar
        except ImportError:
            pytest.skip("media_processor or discord not available")
            return

        mock_user.display_avatar.with_format.return_value.with_size.return_value.read = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "Failed")
        )

        chat_data = {"history": []}
        seen_users = {}

        result = await prepare_user_avatar(
            mock_user, "hello", chat_data, 123, seen_users
        )

        assert result is None


class TestTextExtensions:
    """Tests for TEXT_EXTENSIONS constant."""

    def test_text_extensions_defined(self):
        """Test TEXT_EXTENSIONS is defined."""
        try:
            from cogs.ai_core.media_processor import TEXT_EXTENSIONS
        except ImportError:
            pytest.skip("media_processor not available")
            return

        assert isinstance(TEXT_EXTENSIONS, tuple)
        assert len(TEXT_EXTENSIONS) > 0

    def test_text_extensions_contains_common(self):
        """Test TEXT_EXTENSIONS contains common extensions."""
        try:
            from cogs.ai_core.media_processor import TEXT_EXTENSIONS
        except ImportError:
            pytest.skip("media_processor not available")
            return

        assert '.txt' in TEXT_EXTENSIONS
        assert '.py' in TEXT_EXTENSIONS
        assert '.json' in TEXT_EXTENSIONS
        assert '.md' in TEXT_EXTENSIONS


class TestTextMimes:
    """Tests for TEXT_MIMES constant."""

    def test_text_mimes_defined(self):
        """Test TEXT_MIMES is defined."""
        try:
            from cogs.ai_core.media_processor import TEXT_MIMES
        except ImportError:
            pytest.skip("media_processor not available")
            return

        assert isinstance(TEXT_MIMES, tuple)
        assert len(TEXT_MIMES) > 0

    def test_text_mimes_contains_common(self):
        """Test TEXT_MIMES contains common MIME types."""
        try:
            from cogs.ai_core.media_processor import TEXT_MIMES
        except ImportError:
            pytest.skip("media_processor not available")
            return

        assert 'text/plain' in TEXT_MIMES
        assert 'application/json' in TEXT_MIMES


class TestProcessAttachments:
    """Tests for process_attachments function."""

    async def test_process_attachments_none(self):
        """Test processing None attachments."""
        try:
            from cogs.ai_core.media_processor import process_attachments
        except ImportError:
            pytest.skip("media_processor not available")
            return

        images, videos, texts = await process_attachments(None, "TestUser")

        assert images == []
        assert videos == []
        assert texts == []

    async def test_process_attachments_empty(self):
        """Test processing empty attachments."""
        try:
            from cogs.ai_core.media_processor import process_attachments
        except ImportError:
            pytest.skip("media_processor not available")
            return

        images, videos, texts = await process_attachments([], "TestUser")

        assert images == []
        assert videos == []
        assert texts == []

    async def test_process_attachments_text_file(self):
        """Test processing text file attachment."""
        try:
            from cogs.ai_core.media_processor import process_attachments
        except ImportError:
            pytest.skip("media_processor not available")
            return

        mock_attachment = MagicMock()
        mock_attachment.content_type = "text/plain"
        mock_attachment.filename = "test.txt"
        mock_attachment.size = 11
        mock_attachment.read = AsyncMock(return_value=b"Hello World")

        images, videos, texts = await process_attachments([mock_attachment], "TestUser")

        assert len(texts) == 1
        assert "Hello World" in texts[0]
        assert "test.txt" in texts[0]

    async def test_process_attachments_image(self):
        """Test processing image attachment."""
        try:
            from PIL import Image

            from cogs.ai_core.media_processor import process_attachments
        except ImportError:
            pytest.skip("media_processor or PIL not available")
            return

        # Create a fake image
        img = Image.new('RGB', (10, 10), color='red')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_bytes = buffer.getvalue()

        mock_attachment = MagicMock()
        mock_attachment.content_type = "image/png"
        mock_attachment.filename = "test.png"
        mock_attachment.size = len(img_bytes)
        mock_attachment.read = AsyncMock(return_value=img_bytes)

        images, videos, texts = await process_attachments([mock_attachment], "TestUser")

        assert len(images) == 1

    async def test_process_attachments_large_text(self):
        """Test processing large text file gets chunked."""
        try:
            from cogs.ai_core.media_processor import process_attachments
        except ImportError:
            pytest.skip("media_processor not available")
            return

        # Create text larger than chunk size (15000)
        large_text = "x" * 30000

        mock_attachment = MagicMock()
        mock_attachment.content_type = "text/plain"
        mock_attachment.filename = "large.txt"
        mock_attachment.size = 30000
        mock_attachment.read = AsyncMock(return_value=large_text.encode('utf-8'))

        images, videos, texts = await process_attachments([mock_attachment], "TestUser")

        # Should be split into chunks
        assert len(texts) >= 2

    async def test_process_attachments_unicode_fallback(self):
        """Test processing text with unicode issues."""
        try:
            from cogs.ai_core.media_processor import process_attachments
        except ImportError:
            pytest.skip("media_processor not available")
            return

        # Latin-1 encoded text
        latin1_text = "café résumé".encode('latin-1')

        mock_attachment = MagicMock()
        mock_attachment.content_type = "text/plain"
        mock_attachment.filename = "latin.txt"
        mock_attachment.size = len(latin1_text)
        mock_attachment.read = AsyncMock(return_value=latin1_text)

        images, videos, texts = await process_attachments([mock_attachment], "TestUser")

        assert len(texts) == 1


class TestImageioAvailable:
    """Tests for IMAGEIO_AVAILABLE flag."""

    def test_imageio_available_defined(self):
        """Test IMAGEIO_AVAILABLE flag is defined."""
        try:
            from cogs.ai_core.media_processor import IMAGEIO_AVAILABLE
        except ImportError:
            pytest.skip("media_processor not available")
            return

        assert isinstance(IMAGEIO_AVAILABLE, bool)


class TestModuleConstants:
    """Tests for module-level constants."""


# ======================================================================
# Merged from test_media_processor_module.py
# ======================================================================

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


# ======================================================================
# Merged from test_media_processor_new.py
# ======================================================================

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
