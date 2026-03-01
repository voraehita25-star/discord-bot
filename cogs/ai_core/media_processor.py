"""
Media Processor Module for AI Core.
Handles image, avatar, attachment, and character image processing.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import base64
import io
import logging
from collections import namedtuple
from pathlib import Path
from typing import Any

import discord
from PIL import Image

from .data.roleplay_data import SERVER_CHARACTER_NAMES

# Try to import imageio for GIF to video conversion
try:
    import imageio.v3 as iio

    IMAGEIO_AVAILABLE = True
except ImportError:
    IMAGEIO_AVAILABLE = False
    iio = None  # type: ignore


# ==================== Image Caching ====================

# Cache configuration - limit memory usage for image bytes
# 50 images * ~500KB average = ~25MB max memory for cache
IMAGE_CACHE_MAX_SIZE = 50

# Manual cache dict to avoid caching misses (lru_cache would permanently cache None)
_image_cache: dict[str, bytes] = {}


def load_cached_image_bytes(full_path: str) -> bytes | None:
    """Load and cache image bytes from disk.

    Args:
        full_path: Absolute path to the image file.

    Returns:
        Image bytes if file exists and readable, None otherwise.

    Note:
        Cache is limited to IMAGE_CACHE_MAX_SIZE entries to prevent
        memory issues. Only successful reads are cached; missing files
        are NOT cached so they can be found after deployment.
    """
    if full_path in _image_cache:
        return _image_cache[full_path]
    path = Path(full_path)
    if path.exists():
        try:
            data = path.read_bytes()
            if len(_image_cache) < IMAGE_CACHE_MAX_SIZE:
                _image_cache[full_path] = data
            return data
        except OSError:
            return None
    return None  # Don't cache misses


def clear_image_cache() -> None:
    """Clear the image bytes cache to free memory."""
    _image_cache.clear()
    logging.debug("Image cache cleared")


# Backward-compatible attribute so callers using load_cached_image_bytes.cache_clear() still work
load_cached_image_bytes.cache_clear = clear_image_cache  # type: ignore[attr-defined]

# Backward-compatible cache_info for callers expecting lru_cache-style info
_CacheInfo = namedtuple("CacheInfo", ["hits", "misses", "maxsize", "currsize"])

def _cache_info():
    return _CacheInfo(hits=0, misses=0, maxsize=IMAGE_CACHE_MAX_SIZE, currsize=len(_image_cache))

load_cached_image_bytes.cache_info = _cache_info  # type: ignore[attr-defined]


def get_image_cache_info() -> dict:
    """Get image cache statistics.

    Returns:
        Dict with maxsize and currsize (hits/misses not tracked with manual cache).
    """
    return {
        "hits": 0,
        "misses": 0,
        "maxsize": IMAGE_CACHE_MAX_SIZE,
        "currsize": len(_image_cache),
    }


# ==================== PIL Conversion ====================


def pil_to_inline_data(img: Image.Image) -> dict[str, Any]:
    """Convert PIL Image to base64 inline_data dict for Gemini API.

    Args:
        img: PIL Image to convert.

    Returns:
        Dict with inline_data containing base64-encoded PNG.

    Note:
        Uses context manager for BytesIO to ensure proper cleanup.
    """
    with io.BytesIO() as buffer:
        img.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()
    b64_data = base64.b64encode(img_bytes).decode("utf-8")
    return {"inline_data": {"mime_type": "image/png", "data": b64_data}}


# ==================== GIF Detection and Conversion ====================


def is_animated_gif(image_data: bytes) -> bool:
    """Check if GIF data contains animation (multiple frames).

    Args:
        image_data: Raw GIF bytes.

    Returns:
        True if GIF has multiple frames, False otherwise.
    """
    img = None
    try:
        img = Image.open(io.BytesIO(image_data))
        try:
            img.seek(1)  # Try to go to second frame
            return True
        except EOFError:
            return False  # Only one frame = static GIF
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        logging.debug("Failed to check if GIF is animated: %s", e)
        return False
    finally:
        if img is not None:
            img.close()


def convert_gif_to_video(gif_data: bytes) -> bytes | None:
    """Convert animated GIF to MP4 video bytes.

    Args:
        gif_data: Raw GIF bytes.

    Returns:
        MP4 video bytes or None if conversion failed.
    """
    if not IMAGEIO_AVAILABLE or iio is None:
        return None

    try:
        # Read GIF frames using imageio
        frames = iio.imread(gif_data, index=None, extension=".gif")

        if len(frames) < 2:
            return None  # Not animated

        # Get frame duration from PIL (imageio doesn't expose this well)
        pil_img = None
        try:
            pil_img = Image.open(io.BytesIO(gif_data))
            duration = pil_img.info.get("duration", 100) or 100  # Default 100ms, fallback if 0
        finally:
            if pil_img is not None:
                pil_img.close()
        fps = min(30, max(5, 1000 / duration))  # Clamp FPS between 5-30

        # Write to MP4 video bytes
        video_buffer = io.BytesIO()
        try:
            iio.imwrite(
                video_buffer,
                frames,
                extension=".mp4",
                fps=fps,
                codec="libx264",
                pixelformat="yuv420p",
            )
            video_buffer.seek(0)

            logging.info("Converted GIF (%d frames) to MP4 at %d fps", len(frames), int(fps))
            return video_buffer.read()
        finally:
            video_buffer.close()

    except (OSError, ValueError, Image.DecompressionBombError, RuntimeError) as e:
        logging.warning("Failed to convert GIF to video: %s", e)
        return None


# ==================== Character Image Loading ====================


def load_character_image(message: str, guild_id: int | None) -> tuple[str, Image.Image] | None:
    """Load character reference image if character name is mentioned.

    Args:
        message: User message to check for character names.
        guild_id: Guild ID to look up character map.

    Returns:
        Tuple of (character_name, PIL Image) or None if no match.
    """
    if not guild_id or guild_id not in SERVER_CHARACTER_NAMES:
        return None

    character_map = SERVER_CHARACTER_NAMES[guild_id]
    message_lower = message.lower()

    for char_name, img_path in character_map.items():
        if char_name.lower() in message_lower:
            try:
                full_path = str(Path.cwd() / img_path)

                # Use cached image bytes
                img_bytes = load_cached_image_bytes(full_path)
                if img_bytes:
                    # Use context manager and copy to prevent resource leak
                    with Image.open(io.BytesIO(img_bytes)) as char_image:
                        char_copy = char_image.copy()
                    logging.info("🎭 Loaded character image for %s (cached)", char_name)
                    return (char_name, char_copy)
            except OSError as e:
                logging.warning("Failed to load character image for %s: %s", char_name, e)
    return None


# ==================== Avatar Processing ====================


# Keywords that trigger avatar sending
AVATAR_KEYWORDS = [
    "หน้าตา",
    "รูปโปรไฟล์",
    "หน้าของ",
    "หน้าผม",
    "หน้าหนู",
    "หน้าฉัน",
    "look like",
    "appearance",
    "face",
    "avatar",
    "who am i",
    "ฉันคือใคร",
]


async def prepare_user_avatar(
    user: discord.User,
    message: str,
    chat_data: dict[str, Any],
    context_channel_id: int,
    seen_users: dict[int, set[str]],
) -> Image.Image | None:
    """Prepare user avatar image if needed.

    Args:
        user: Discord user to get avatar for.
        message: User's message text for keyword detection.
        chat_data: Chat session data to check history.
        context_channel_id: Channel ID for tracking seen users.
        seen_users: Dict tracking which users have been seen per channel.

    Returns:
        PIL Image copy of avatar, or None if avatar not needed.

    Note:
        The returned Image is a copy that should be passed to the API.
        This function modifies seen_users in place to track which users
        have had their avatars sent.
    """
    user_name = user.display_name
    user_key = f"{user.id}_{user_name}"

    # Initialize seen_users for this channel if not exists
    if context_channel_id not in seen_users:
        seen_users[context_channel_id] = set()

    # Determine if we should send avatar
    should_send_avatar = False

    # Check if history is empty (Start of conversation)
    if not chat_data.get("history"):
        should_send_avatar = True

    # Check if user has been seen in this session
    if user_key not in seen_users[context_channel_id]:
        should_send_avatar = True

    # Check keywords for appearance-related questions
    if any(k in message.lower() for k in AVATAR_KEYWORDS):
        should_send_avatar = True

    if not should_send_avatar:
        return None

    try:
        # Get avatar as PNG, small size
        avatar_bytes = await user.display_avatar.with_format("png").with_size(256).read()
        with Image.open(io.BytesIO(avatar_bytes)) as avatar_image:
            avatar_copy = avatar_image.copy()

        # Mark user as seen
        seen_users[context_channel_id].add(user_key)
        logging.info("Sent avatar for %s", user_name)
        return avatar_copy
    except (discord.HTTPException, OSError) as e:
        logging.warning("Failed to load avatar for %s: %s", user_name, e)
        return None


# ==================== Attachment Processing ====================

# Supported text file extensions
TEXT_EXTENSIONS = (
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".xml",
    ".ini",
    ".cfg",
    ".sh",
    ".bat",
    ".sql",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".rs",
    ".go",
    ".rb",
    ".php",
    ".lua",
    ".r",
    ".vue",
    ".jsx",
    ".tsx",
)

# Supported text MIME types
TEXT_MIMES = (
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
    "text/html",
    "text/css",
    "text/xml",
    "application/xml",
    "text/x-python",
    "application/x-python-code",
)


async def process_attachments(
    attachments: list[discord.Attachment] | None, user_name: str
) -> tuple[list[Image.Image], list[dict], list[str]]:
    """Process image and text attachments.

    Args:
        attachments: List of Discord attachments to process.
        user_name: Name of user who sent attachments (for logging).

    Returns:
        Tuple of (image_parts, video_parts, text_parts) where:
        - image_parts: list of PIL Images
        - video_parts: dicts with 'data' and 'mime_type' keys for animated GIFs
        - text_parts: list of formatted text file contents
    """
    image_parts = []
    video_parts = []
    text_parts = []

    if not attachments:
        return image_parts, video_parts, text_parts

    # Maximum attachment size to download (10 MB)
    MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

    for attachment in attachments:
        # Skip attachments that are too large to prevent memory issues
        if attachment.size is not None and attachment.size > MAX_ATTACHMENT_SIZE:
            logging.warning(
                "Skipping attachment '%s' (%d bytes) — exceeds %d byte limit",
                attachment.filename,
                attachment.size,
                MAX_ATTACHMENT_SIZE,
            )
            continue

        # Check for text files first
        is_text = (
            attachment.content_type and any(m in attachment.content_type for m in TEXT_MIMES)
        ) or attachment.filename.lower().endswith(TEXT_EXTENSIONS)

        if is_text:
            try:
                text_data = await attachment.read()

                # Decode with fallback encodings
                content = None
                for encoding in ["utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1"]:
                    try:
                        content = text_data.decode(encoding)
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue

                if content is None:
                    content = text_data.decode("utf-8", errors="replace")

                # Split into smaller chunks to avoid API issues with large content
                chunk_size = 15000
                if len(content) > chunk_size:
                    # Split into multiple chunks
                    total_chunks = (len(content) + chunk_size - 1) // chunk_size
                    for i in range(total_chunks):
                        start = i * chunk_size
                        end = min((i + 1) * chunk_size, len(content))
                        chunk = content[start:end]
                        text_parts.append(
                            f"[Document: {attachment.filename} - Section {i + 1}/{total_chunks}]\n"
                            f"---BEGIN TEXT---\n{chunk}\n---END TEXT---"
                        )
                    logging.info(
                        "📄 Processed text file '%s' from %s (%d chars, %d chunks)",
                        attachment.filename,
                        user_name,
                        len(content),
                        total_chunks,
                    )
                else:
                    # Single file
                    text_parts.append(
                        f"[Document: {attachment.filename}]\n"
                        f"---BEGIN TEXT---\n{content}\n---END TEXT---"
                    )
                    logging.info(
                        "📄 Processed text file '%s' from %s (%d chars)",
                        attachment.filename,
                        user_name,
                        len(content),
                    )
            except (OSError, UnicodeDecodeError) as e:
                logging.warning(
                    "Failed to process text attachment '%s': %s", attachment.filename, e
                )
            continue

        # Handle images
        if attachment.content_type and attachment.content_type.startswith("image/"):
            try:
                image_data = await attachment.read()

                # Check if it's an animated GIF
                if attachment.content_type == "image/gif" and IMAGEIO_AVAILABLE:
                    if is_animated_gif(image_data):
                        # Convert animated GIF to video
                        video_bytes = convert_gif_to_video(image_data)
                        if video_bytes:
                            video_parts.append({"data": video_bytes, "mime_type": "video/mp4"})
                            logging.info("Converted animated GIF to video from %s", user_name)
                            continue

                # Regular static image
                with Image.open(io.BytesIO(image_data)) as image:
                    # Copy the image so we can close the original
                    image_copy = image.copy()
                image_parts.append(image_copy)
                logging.info("Processed image from %s", user_name)
            except (OSError, discord.HTTPException) as e:
                logging.warning("Failed to process attachment: %s", e)

    return image_parts, video_parts, text_parts
