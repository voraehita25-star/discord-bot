"""
Tests for utils/media/media_rust.py

Comprehensive tests for MediaProcessorWrapper and PIL fallback.
"""

import base64
import io
from unittest.mock import MagicMock, patch

import pytest


class TestMediaProcessorWrapperInit:
    """Tests for MediaProcessorWrapper initialization."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_init_python_fallback(self):
        """Test init with Python fallback."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper(max_dimension=512)

        assert processor.max_dimension == 512
        assert processor.jpeg_quality == 85
        assert processor._use_rust is False

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_init_custom_quality(self):
        """Test init with custom JPEG quality."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper(max_dimension=1024, jpeg_quality=95)

        assert processor.jpeg_quality == 95


class TestMediaProcessorWrapperResize:
    """Tests for resize method."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_resize_small_image(self):
        """Test resize returns original for small images."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper(max_dimension=1024)

        # Create a small test image
        from PIL import Image
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()

        result_bytes, width, height = processor.resize(img_bytes, 512, 512)

        # Image should be returned as-is (smaller than max)
        assert width <= 512
        assert height <= 512

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_resize_large_image(self):
        """Test resize shrinks large images."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper(max_dimension=1024)

        # Create a large test image
        from PIL import Image
        img = Image.new("RGB", (2000, 1000), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        img_bytes = buffer.getvalue()

        result_bytes, width, height = processor.resize(img_bytes, 500, 500)

        assert width <= 500
        assert height <= 500


class TestMediaProcessorWrapperThumbnail:
    """Tests for thumbnail method."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_thumbnail(self):
        """Test thumbnail creates small image."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()

        # Create a test image
        from PIL import Image
        img = Image.new("RGB", (500, 500), color="green")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        img_bytes = buffer.getvalue()

        result_bytes, width, height = processor.thumbnail(img_bytes, size=128)

        assert width <= 128
        assert height <= 128


class TestMediaProcessorWrapperIsAnimated:
    """Tests for is_animated method."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_is_animated_static(self):
        """Test is_animated returns False for static image."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()

        # Create a static image
        from PIL import Image
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()

        assert processor.is_animated(img_bytes) is False

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", False)
    def test_is_animated_no_pil(self):
        """Test is_animated returns False when PIL not available."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()
        result = processor.is_animated(b"fake data")

        assert result is False


class TestMediaProcessorWrapperGetDimensions:
    """Tests for get_dimensions method."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_get_dimensions(self):
        """Test getting image dimensions."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()

        # Create a test image
        from PIL import Image
        img = Image.new("RGB", (300, 200), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        img_bytes = buffer.getvalue()

        width, height = processor.get_dimensions(img_bytes)

        assert width == 300
        assert height == 200

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", False)
    def test_get_dimensions_no_pil(self):
        """Test get_dimensions raises when PIL not available."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()

        with pytest.raises(RuntimeError):
            processor.get_dimensions(b"fake data")


class TestMediaProcessorWrapperBase64:
    """Tests for base64 methods."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_to_base64(self):
        """Test encoding to base64."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()
        data = b"Hello, World!"

        result = processor.to_base64(data)

        assert result == base64.b64encode(data).decode("ascii")

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_from_base64(self):
        """Test decoding from base64."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()
        data = b"Hello, World!"
        encoded = base64.b64encode(data).decode("ascii")

        result = processor.from_base64(encoded)

        assert result == data

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_to_data_uri(self):
        """Test creating data URI."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()
        data = b"test"

        result = processor.to_data_uri(data, "image/png")

        assert result.startswith("data:image/png;base64,")
        assert base64.b64encode(data).decode("ascii") in result


class TestMediaProcessorWrapperIsRust:
    """Tests for is_rust property."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_is_rust_false(self):
        """Test is_rust returns False when using PIL."""
        from utils.media.media_rust import MediaProcessorWrapper

        processor = MediaProcessorWrapper()
        assert processor.is_rust is False


class TestStandaloneFunctions:
    """Tests for standalone functions."""

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_resize_image(self):
        """Test resize_image function."""
        # Create a test image
        from PIL import Image

        from utils.media.media_rust import resize_image
        img = Image.new("RGB", (200, 200), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        img_bytes = buffer.getvalue()

        result_bytes, width, height = resize_image(img_bytes, 100, 100)

        assert width <= 100
        assert height <= 100

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    @patch("utils.media.media_rust.PIL_AVAILABLE", True)
    def test_is_animated_gif(self):
        """Test is_animated_gif function."""
        # Create a static image
        from PIL import Image

        from utils.media.media_rust import is_animated_gif
        img = Image.new("RGB", (100, 100), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()

        result = is_animated_gif(img_bytes)

        assert result is False

    @patch("utils.media.media_rust.RUST_AVAILABLE", False)
    def test_image_to_base64(self):
        """Test image_to_base64 function."""
        from utils.media.media_rust import image_to_base64

        data = b"test image data"
        result = image_to_base64(data)

        assert result == base64.b64encode(data).decode("ascii")


class TestModuleImports:
    """Tests for module imports."""

    def test_import_media_processor_wrapper(self):
        """Test MediaProcessorWrapper can be imported."""
        from utils.media.media_rust import MediaProcessorWrapper

        assert MediaProcessorWrapper is not None

    def test_import_media_processor_alias(self):
        """Test MediaProcessor alias can be imported."""
        from utils.media.media_rust import MediaProcessor

        assert MediaProcessor is not None

    def test_rust_available_flag_exists(self):
        """Test RUST_AVAILABLE flag exists."""
        from utils.media.media_rust import RUST_AVAILABLE

        assert isinstance(RUST_AVAILABLE, bool)

    def test_pil_available_flag_exists(self):
        """Test PIL_AVAILABLE flag exists."""
        from utils.media.media_rust import PIL_AVAILABLE

        assert isinstance(PIL_AVAILABLE, bool)
