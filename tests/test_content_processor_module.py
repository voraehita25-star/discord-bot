"""Tests for content processor module."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image


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
