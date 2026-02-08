"""
Python wrapper for Rust Media Processor.

Provides fallback to PIL if Rust extension is not available.
"""

from __future__ import annotations

import base64
import importlib
import io
import logging

logger = logging.getLogger(__name__)

# Try to import Rust extension dynamically to avoid Pylance warnings
RUST_AVAILABLE = False
RustMediaProcessor = None
is_animated = None
get_dimensions = None
to_base64 = None

try:
    _media_module = importlib.import_module("media_processor")
    RustMediaProcessor = getattr(_media_module, "MediaProcessor", None)
    is_animated = getattr(_media_module, "is_animated", None)
    get_dimensions = getattr(_media_module, "get_dimensions", None)
    to_base64 = getattr(_media_module, "to_base64", None)
    if RustMediaProcessor:
        RUST_AVAILABLE = True
        logger.info("✅ Rust Media Processor loaded successfully")
except ImportError:
    logger.warning("⚠️ Rust Media Processor not available, using PIL fallback")

# PIL fallback
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class MediaProcessorWrapper:
    """
    Wrapper for Media Processor with automatic fallback to PIL.

    Usage:
        processor = MediaProcessorWrapper(max_dimension=1024)
        resized = processor.resize(image_bytes, max_width=512)
        is_gif = processor.is_animated(image_bytes)
    """

    def __init__(self, max_dimension: int = 1024, jpeg_quality: int = 85):
        self.max_dimension = max_dimension
        self.jpeg_quality = jpeg_quality
        self._use_rust = RUST_AVAILABLE

        if self._use_rust:
            self._processor = RustMediaProcessor(max_dimension, jpeg_quality)

    def resize(
        self,
        data: bytes,
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> tuple[bytes, int, int]:
        """
        Resize image to fit within max dimensions.

        Returns:
            Tuple of (resized_bytes, width, height)
        """
        max_w = max_width or self.max_dimension
        max_h = max_height or self.max_dimension

        if self._use_rust:
            result = self._processor.resize(data, max_w, max_h)
            return result.get_data(), result.width, result.height
        else:
            return self._pil_resize(data, max_w, max_h)

    def _pil_resize(self, data: bytes, max_w: int, max_h: int) -> tuple[bytes, int, int]:
        """PIL fallback for resize."""
        if not PIL_AVAILABLE:
            raise RuntimeError("Neither Rust extension nor PIL is available")

        img = Image.open(io.BytesIO(data))
        try:
            orig_w, orig_h = img.size

            # Calculate new dimensions
            ratio = min(max_w / orig_w, max_h / orig_h)
            if ratio >= 1.0:
                return data, orig_w, orig_h

            new_w = int(orig_w * ratio)
            new_h = int(orig_h * ratio)

            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Save to bytes
            output = io.BytesIO()
            format_str = "JPEG" if img.mode != "RGBA" else "PNG"
            save_kwargs = {"quality": self.jpeg_quality} if format_str == "JPEG" else {}

            if img.mode == "RGBA" and format_str == "JPEG":
                img = img.convert("RGB")

            img.save(output, format=format_str, **save_kwargs)
            return output.getvalue(), new_w, new_h
        finally:
            img.close()

    def thumbnail(self, data: bytes, size: int = 128) -> tuple[bytes, int, int]:
        """Create a thumbnail."""
        return self.resize(data, size, size)

    def is_animated(self, data: bytes) -> bool:
        """Check if image is an animated GIF."""
        if self._use_rust:
            return is_animated(data)
        else:
            return self._pil_is_animated(data)

    def _pil_is_animated(self, data: bytes) -> bool:
        """PIL fallback for animated GIF detection."""
        if not PIL_AVAILABLE:
            return False

        try:
            img = Image.open(io.BytesIO(data))
            try:
                img.seek(1)
                return True
            except EOFError:
                return False
            finally:
                img.close()
        except (OSError, ValueError) as e:
            logging.debug("PIL animated GIF check failed: %s", e)
            return False

    def get_dimensions(self, data: bytes) -> tuple[int, int]:
        """Get image dimensions without fully decoding."""
        if self._use_rust:
            return get_dimensions(data)
        else:
            if not PIL_AVAILABLE:
                raise RuntimeError("Neither Rust extension nor PIL is available")
            img = Image.open(io.BytesIO(data))
            try:
                return img.size
            finally:
                img.close()

    def to_base64(self, data: bytes) -> str:
        """Encode bytes to base64 string."""
        if self._use_rust:
            return to_base64(data)
        return base64.b64encode(data).decode("ascii")

    def from_base64(self, encoded: str) -> bytes:
        """Decode base64 string to bytes."""
        if self._use_rust:
            return self._processor.decode_base64(encoded)
        return base64.b64decode(encoded)

    def to_data_uri(self, data: bytes, mime_type: str = "image/jpeg") -> str:
        """Convert bytes to data URI."""
        b64 = self.to_base64(data)
        return f"data:{mime_type};base64,{b64}"

    @property
    def is_rust(self) -> bool:
        """Check if using Rust backend."""
        return self._use_rust


# Convenience alias
MediaProcessor = MediaProcessorWrapper


# Standalone functions
def resize_image(data: bytes, max_width: int, max_height: int) -> tuple[bytes, int, int]:
    """Resize an image."""
    processor = MediaProcessorWrapper()
    return processor.resize(data, max_width, max_height)


def is_animated_gif(data: bytes) -> bool:
    """Check if data is an animated GIF."""
    processor = MediaProcessorWrapper()
    return processor.is_animated(data)


def image_to_base64(data: bytes) -> str:
    """Encode image to base64."""
    processor = MediaProcessorWrapper()
    return processor.to_base64(data)
