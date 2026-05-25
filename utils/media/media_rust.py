"""
Python wrapper for Rust Media Processor.

Provides fallback to PIL if Rust extension is not available.
"""

from __future__ import annotations

import base64
import importlib
import io
import logging
import threading

logger = logging.getLogger(__name__)

# Serializes mutations of PIL's module-global ``Image.MAX_IMAGE_PIXELS``.
# Without this, two threads concurrently entering ``_pil_resize`` would
# race on the global: thread A sets the cap, thread B saves+sets, thread
# A restores B's saved value, thread B never restores — leaving the global
# permanently raised (or lowered) for the rest of the process.
_PIL_LOCK = threading.Lock()

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
    # Gate RUST_AVAILABLE on the FULL surface — including the standalone
    # functions — not just the class. If the binding ships the class but
    # one of the helpers is missing, callers using ``_use_rust`` would
    # otherwise hit ``TypeError: 'NoneType' object is not callable`` on
    # the hot path instead of falling back to PIL cleanly.
    if RustMediaProcessor and is_animated and get_dimensions and to_base64:
        RUST_AVAILABLE = True
        logger.info("✅ Rust Media Processor loaded successfully")
    elif RustMediaProcessor:
        logger.warning(
            "⚠️ Rust Media Processor partially loaded (missing helpers); "
            "using PIL fallback to avoid runtime TypeError"
        )
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
            self._processor = RustMediaProcessor(max_dimension, jpeg_quality)  # type: ignore[misc]

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

        # Decompression-bomb guard: 100 MP cap matches the Rust extension's
        # threshold and is well above any legitimate Discord attachment.
        # Without this, PIL's default warns at 89 MP but still decodes huge
        # crafted images, exhausting RAM.
        # The MAX_IMAGE_PIXELS save/set/restore is wrapped in _PIL_LOCK so
        # concurrent callers can't race on the module-global and leave it
        # in an inconsistent state — see _PIL_LOCK comment near the top of
        # this module.
        from PIL import Image as _PIL_Image

        with _PIL_LOCK:
            prev_max_pixels = _PIL_Image.MAX_IMAGE_PIXELS
            _PIL_Image.MAX_IMAGE_PIXELS = 100_000_000
            try:
                # Track every PIL Image object we allocate so the finally
                # block can close all of them — ``img`` is reassigned by
                # ``.resize()`` and ``.convert()`` and the previous code
                # only closed the LAST binding, leaking the buffers held
                # by Image.open() and any intermediate result.
                opened: list = []
                original = Image.open(io.BytesIO(data))
                opened.append(original)
                img = original
                try:
                    orig_w, orig_h = img.size

                    # Pathological PIL inputs can report zero dimensions
                    # (corrupt headers / 0-byte images). Bail before the
                    # division below would raise ZeroDivisionError.
                    if orig_w == 0 or orig_h == 0:
                        return data, orig_w, orig_h

                    # Calculate new dimensions
                    ratio = min(max_w / orig_w, max_h / orig_h)
                    if ratio >= 1.0:
                        return data, orig_w, orig_h

                    new_w = int(orig_w * ratio)
                    new_h = int(orig_h * ratio)

                    # Reject zero/negative dimensions before handing them
                    # to PIL — Image.resize raises an opaque ValueError on
                    # 0-size, and very small ratios can round to zero.
                    if new_w < 1 or new_h < 1:
                        return data, orig_w, orig_h

                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)  # type: ignore[assignment]
                    opened.append(img)

                    # Save to bytes
                    output = io.BytesIO()
                    if img.mode == "RGBA":
                        format_str = "PNG"
                        save_kwargs = {}
                    else:
                        format_str = "JPEG"
                        save_kwargs = {"quality": self.jpeg_quality}
                        if img.mode not in ("RGB", "L"):
                            img = img.convert("RGB")  # type: ignore[assignment]
                            opened.append(img)

                    img.save(output, format=format_str, **save_kwargs)
                    return output.getvalue(), new_w, new_h
                finally:
                    for handle in opened:
                        try:
                            handle.close()
                        except Exception:
                            # Best-effort: PIL.close() on already-closed
                            # images can raise OSError; we don't care.
                            pass
            finally:
                _PIL_Image.MAX_IMAGE_PIXELS = prev_max_pixels

    def thumbnail(self, data: bytes, size: int = 128) -> tuple[bytes, int, int]:
        """Create a thumbnail."""
        return self.resize(data, size, size)

    def is_animated(self, data: bytes) -> bool:
        """Check if image is an animated GIF."""
        if self._use_rust:
            return is_animated(data)  # type: ignore[misc, no-any-return]
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
            logger.debug("PIL animated GIF check failed: %s", e)
            return False

    def get_dimensions(self, data: bytes) -> tuple[int, int]:
        """Get image dimensions without fully decoding."""
        if self._use_rust:
            return get_dimensions(data)  # type: ignore[misc, no-any-return]
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
            return to_base64(data)  # type: ignore[misc, no-any-return]
        return base64.b64encode(data).decode("ascii")

    def from_base64(self, encoded: str) -> bytes:
        """Decode base64 string to bytes.

        Normalize the URL-safe variant (``-``/``_`` for ``+``/``/``) so
        the Python fallback decodes inputs the Rust path accepts —
        otherwise a URL-safe payload from a caller that exercised the
        Rust path crashes when falling back here.
        """
        if self._use_rust:
            return self._processor.decode_base64(encoded)  # type: ignore[no-any-return]
        normalized = encoded.replace("-", "+").replace("_", "/")
        return base64.b64decode(normalized)

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
