"""
Content Processor Module for AI Core.

DEPRECATED: This module is kept for backward compatibility only.
All functionality has been moved to media_processor.py.

Please import from media_processor instead:
    from .media_processor import (
        load_cached_image_bytes,
        pil_to_inline_data,
        is_animated_gif,
        convert_gif_to_video,
        load_character_image,
        prepare_user_avatar,
        process_attachments,
        IMAGEIO_AVAILABLE,
        TEXT_EXTENSIONS,
        TEXT_MIMES,
    )
"""

from __future__ import annotations

import warnings

# Emit deprecation warning when this module is imported
warnings.warn(
    "content_processor module is deprecated. Use media_processor instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from media_processor for backward compatibility
from .media_processor import (
    IMAGEIO_AVAILABLE,
    TEXT_EXTENSIONS,
    TEXT_MIMES,
    convert_gif_to_video,
    is_animated_gif,
    load_cached_image_bytes,
    load_character_image,
    pil_to_inline_data,
    prepare_user_avatar,
    process_attachments,
)

__all__ = [
    "IMAGEIO_AVAILABLE",
    "TEXT_EXTENSIONS",
    "TEXT_MIMES",
    "convert_gif_to_video",
    "is_animated_gif",
    "load_cached_image_bytes",
    "load_character_image",
    "pil_to_inline_data",
    "prepare_user_avatar",
    "process_attachments",
]
