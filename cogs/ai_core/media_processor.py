"""
Media Processor Module for AI Core.
Handles image, avatar, attachment, and character image processing.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import io
import logging
import re
import warnings
from collections import OrderedDict, namedtuple
from pathlib import Path
from typing import Any, TypedDict

import discord
from PIL import Image

# Decompression-bomb hardening: cap pixel count and convert PIL's
# DecompressionBombWarning into a hard error so existing except clauses trip
# instead of silently letting a 100MP image through.
#
# Use ``filterwarnings("error", category=...)`` rather than
# ``simplefilter("error", ...)``. ``simplefilter`` REPLACES the entire warning
# filter list with this single rule, wiping out any operator-configured
# filters (PYTHONWARNINGS env, ``-W`` flags, or pyproject.toml ``filterwarnings``).
# ``filterwarnings`` PREPENDS to the existing list so other modules' filter
# decisions survive this import.
Image.MAX_IMAGE_PIXELS = 30_000_000  # ~30MP cap (Pillow default is ~89MP)
warnings.filterwarnings("error", category=Image.DecompressionBombWarning)

from .data import SERVER_CHARACTER_NAMES

# Try to import imageio for GIF to video conversion
try:
    import imageio.v3 as iio

    IMAGEIO_AVAILABLE = True
except ImportError:
    IMAGEIO_AVAILABLE = False
    iio = None


logger = logging.getLogger(__name__)

# Module-level executor for GIF→MP4 encoding. Previously every call
# constructed a fresh ``ThreadPoolExecutor(max_workers=1)`` and (on
# timeout) abandoned it via ``shutdown(wait=False)``, leaking a thread
# per slow GIF. A shared pool caps the concurrency regardless of caller
# burstiness; the timeout path no longer needs to kill the executor —
# the worker thread is released back to the pool when ffmpeg eventually
# finishes.
#
# The pool is deliberately WIDER than ``_GIF_CONVERT_SEMAPHORE`` (4 vs 2).
# ``future.result(timeout=60.0)`` abandons — but cannot cancel — a worker
# still running an uninterruptible ffmpeg encode, so a slow/adversarial GIF
# keeps its slot occupied past the timeout. If the pool width equalled the
# semaphore (the old 2/2), two such hung encodes would occupy BOTH workers
# while the semaphore still admitted two NEW conversions, which would then
# queue forever behind the stuck workers — starving GIF conversion
# process-wide. With 2 admitted conversions but 4 worker slots, up to two
# abandoned encodes still leave free workers for new conversions to start on
# instead of queueing unboundedly. Frames are bounded (<=300, <=1.5MP) so a
# true infinite hang is unlikely; this headroom absorbs the transient, and the
# in-flight cap below (_GIF_ENCODE_MAX_INFLIGHT) hard-bounds the pathological
# case where abandoned encodes would otherwise fill every slot.
import concurrent.futures as _futures

_GIF_ENCODE_EXECUTOR: _futures.ThreadPoolExecutor = _futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="gif-encode",
)

# Tear the pool down on interpreter exit. It's a module-level, non-daemon
# executor that was never shut down — its worker threads can delay interpreter
# exit (CPython's atexit joins executor threads) — unlike bot.py's
# _default_executor which is explicitly torn down on graceful shutdown. Mirror
# that teardown (wait=False, cancel_futures=True) so shutdown isn't stalled by
# an in-flight slow GIF encode.
atexit.register(lambda: _GIF_ENCODE_EXECUTOR.shutdown(wait=False, cancel_futures=True))

# Throttle concurrent GIF→MP4 conversions to 2 (BELOW the encode-pool width of
# 4 — see _GIF_ENCODE_EXECUTOR for why the pool keeps the extra headroom). Each
# in-flight conversion otherwise parks a default-executor thread for up to 60s
# (``future.result(timeout=60.0)``) WHILE waiting on an encode-pool slot —
# under a burst that starves the shared default pool with conversions that
# can't even start encoding. The semaphore caps in-flight conversions so excess
# callers wait on the (cheap) semaphore instead of holding a default-pool
# thread hostage. Bound to the running loop lazily on first acquire
# (Python 3.10+), so construction at import time is safe.
_GIF_CONVERT_SEMAPHORE = asyncio.Semaphore(2)

# Hard cap on encodes occupying the pool. The semaphore above bounds CONCURRENT
# conversions, but a timed-out encode keeps running its uninterruptible ffmpeg
# in its worker thread after we abandon it (see convert_gif_to_video), so
# abandoned encodes accumulate INDEPENDENTLY of the semaphore. Without a cap,
# once enough stuck encodes fill all the pool workers, each new submit would
# queue behind them and only fail after its own 60s timeout — i.e. GIF
# conversion stalls process-wide (widening the pool 2->4 only raised the trigger
# count, it did not bound this). Track in-flight encodes (incremented at submit,
# decremented when the encode ACTUALLY finishes via add_done_callback — even if
# we abandoned it after the timeout) and, when every worker slot is taken, skip
# the encode and fall back to a static image immediately instead of queueing.
# This bounds the worst case to "instant static fallback" rather than "60s hang
# per request behind a starved queue".
import threading as _threading

_GIF_ENCODE_MAX_INFLIGHT = 4  # == _GIF_ENCODE_EXECUTOR max_workers
_GIF_ENCODE_INFLIGHT = 0
_GIF_ENCODE_INFLIGHT_LOCK = _threading.Lock()


def _try_reserve_gif_encode_slot() -> bool:
    """Reserve a pool slot for a GIF encode; False if all workers are occupied."""
    global _GIF_ENCODE_INFLIGHT
    with _GIF_ENCODE_INFLIGHT_LOCK:
        if _GIF_ENCODE_INFLIGHT >= _GIF_ENCODE_MAX_INFLIGHT:
            return False
        _GIF_ENCODE_INFLIGHT += 1
        return True


def _release_gif_encode_slot(_future: object = None) -> None:
    """Release a reserved slot (registered as the encode Future's done-callback)."""
    global _GIF_ENCODE_INFLIGHT
    with _GIF_ENCODE_INFLIGHT_LOCK:
        _GIF_ENCODE_INFLIGHT = max(0, _GIF_ENCODE_INFLIGHT - 1)


# ==================== Image Caching ====================

# Cache configuration - limit memory usage for image bytes
# 50 images * ~500KB average = ~25MB max memory for cache
IMAGE_CACHE_MAX_SIZE = 50

# Manual cache dict to avoid caching misses (lru_cache would permanently cache None).
# Each entry is ``(mtime_ns, bytes)`` so we can detect on-disk changes — without
# this, an updated character image stays stale until process restart even though
# the new file is sitting on disk.
# Uses OrderedDict so we can evict the oldest entry on cap (true LRU behaviour)
# instead of relying on insertion-only dict ordering plus accidental eviction.
_image_cache: OrderedDict[str, tuple[int, bytes]] = OrderedDict()


# Fixed base directory for path validation (resolved once at import time)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Maximum number of GIF frames to process (prevent decompression bombs)
_MAX_GIF_FRAMES = 300


def load_cached_image_bytes(full_path: str) -> bytes | None:
    """Load and cache image bytes from disk.

    Args:
        full_path: Absolute path to the image file.

    Returns:
        Image bytes if file exists and readable, None otherwise.

    Note:
        Cache is limited to IMAGE_CACHE_MAX_SIZE entries to prevent
        memory issues. Only successful reads are cached; missing files
        are NOT cached so they can be found after deployment. Cache hits
        are validated against the file's ``mtime_ns`` so an on-disk update
        invalidates the entry on the next access — no manual clear needed
        when swapping a character image.
        Path must be within the project base directory for security.
    """
    path = Path(full_path).resolve()
    # Security: Validate path is within the project directory
    if not path.is_relative_to(_BASE_DIR):
        logger.warning("Blocked path traversal attempt in image cache: %s", full_path)
        return None

    # Stat once and reuse — we need mtime for the cache check AND to know
    # whether the file exists to read.
    try:
        current_mtime = path.stat().st_mtime_ns
    except (FileNotFoundError, OSError):
        # File missing or unreadable — drop any stale cache entry so we don't
        # keep returning bytes for a deleted file forever.
        _image_cache.pop(full_path, None)
        return None

    cached = _image_cache.get(full_path)
    if cached is not None and cached[0] == current_mtime:
        # Mark as most-recently-used so it won't be the next eviction target.
        _image_cache.move_to_end(full_path)
        return cached[1]

    try:
        data = path.read_bytes()
    except OSError:
        # Read failed (race with delete, perms changed) — clear stale and bail.
        _image_cache.pop(full_path, None)
        return None

    # Insert / refresh the entry, then evict the oldest if we're over capacity.
    # Always move_to_end so a refresh promotes the entry to MRU.
    _image_cache[full_path] = (current_mtime, data)
    _image_cache.move_to_end(full_path)
    while len(_image_cache) > IMAGE_CACHE_MAX_SIZE:
        _image_cache.popitem(last=False)
    return data


def clear_image_cache() -> None:
    """Clear the image bytes cache to free memory."""
    _image_cache.clear()
    logger.debug("Image cache cleared")


# Backward-compatible attribute so callers using load_cached_image_bytes.cache_clear() still work
load_cached_image_bytes.cache_clear = clear_image_cache  # type: ignore[attr-defined]

# Backward-compatible cache_info for callers expecting lru_cache-style info
_CacheInfo = namedtuple("_CacheInfo", ["hits", "misses", "maxsize", "currsize"])


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


class InlineDataPayload(TypedDict):
    """Internal multimodal payload used before provider conversion."""

    mime_type: str
    data: str


class InlineDataPart(TypedDict):
    """Internal multimodal part carrying inline base64 data."""

    inline_data: InlineDataPayload


class ProcessedVideoPart(TypedDict):
    """Processed animated media represented as bytes + MIME type."""

    data: bytes
    mime_type: str


def pil_to_inline_data(img: Image.Image) -> InlineDataPart:
    """Convert PIL Image to base64 inline_data dict for API.

    Args:
        img: PIL Image to convert.

    Returns:
        Dict with inline_data containing base64-encoded PNG.
        Compatible with both Gemini and Claude format converters.

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
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        # ``DecompressionBombWarning`` is a sibling of ``DecompressionBombError``
        # (both subclass Exception directly), so the module-level
        # ``filterwarnings("error", ...)`` raises it as its own type for a
        # 30–60MP image — catch it here too or it escapes process_attachments.
        logger.debug("Failed to check if GIF is animated: %s", e)
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

    # Declared up front so the outer except can safely close it whether or not
    # execution reached the ``video_buffer = io.BytesIO()`` assignment below.
    video_buffer = None

    try:
        # Pre-check frame count using PIL to prevent decompression bomb
        # PIL uses lazy loading so this doesn't load all pixels into memory
        pil_check = None
        try:
            pil_check = Image.open(io.BytesIO(gif_data))
            # Reject oversized GIFs early: a 4000x4000 GIF with 300 frames
            # would balloon to ~14GB of decoded RGB pixels in frames_list
            # below. ~1.5MP is enough for any reasonable Discord avatar /
            # reaction GIF and bounds total memory at ~1.3GB worst case.
            first_w = pil_check.width
            first_h = pil_check.height
            # Animated GIFs can composite later frames onto a larger logical
            # canvas, so a tiny frame0 with a big canvas would otherwise slip
            # past this gate. Guard against the canvas (pil_check.size) too.
            canvas_w, canvas_h = pil_check.size
            if first_w * first_h > 1_500_000 or canvas_w * canvas_h > 1_500_000:
                logger.warning(
                    "GIF too large to process: %sx%s (canvas %sx%s)",
                    first_w,
                    first_h,
                    canvas_w,
                    canvas_h,
                )
                return None
            frame_count = 0
            try:
                while True:
                    frame_count += 1
                    if frame_count > _MAX_GIF_FRAMES:
                        logger.warning(
                            "GIF exceeds %d frames (checked via PIL), truncating", _MAX_GIF_FRAMES
                        )
                        break
                    pil_check.seek(pil_check.tell() + 1)
            except EOFError:
                pass  # Reached end of frames
        finally:
            if pil_check is not None:
                pil_check.close()

        if frame_count < 2:
            return None  # Not animated

        # Decode frames lazily via PIL so we never load more than
        # _MAX_GIF_FRAMES into memory at once. iio.imread(index=None)
        # would decode every frame first then slice — which a crafted
        # GIF with thousands of frames could turn into a memory bomb.
        import numpy as np

        frames_list: list[np.ndarray] = []
        pil_iter = None
        try:
            pil_iter = Image.open(io.BytesIO(gif_data))
            try:
                while len(frames_list) < _MAX_GIF_FRAMES:
                    frame_rgb = pil_iter.convert("RGB")
                    frames_list.append(np.asarray(frame_rgb, dtype=np.uint8))
                    pil_iter.seek(pil_iter.tell() + 1)
            except EOFError:
                pass  # End of frames
        finally:
            if pil_iter is not None:
                pil_iter.close()

        if not frames_list:
            return None
        frames = np.stack(frames_list, axis=0)

        # Get frame duration from PIL (imageio doesn't expose this well)
        pil_img = None
        try:
            pil_img = Image.open(io.BytesIO(gif_data))
            duration = pil_img.info.get("duration", 100) or 100  # Default 100ms, fallback if 0
        finally:
            if pil_img is not None:
                pil_img.close()
        fps = min(30, max(5, 1000 / duration))  # Clamp FPS between 5-30

        # Write to MP4 video bytes. Bound the ffmpeg encode at 60s — without
        # this a pathological input could hang the worker thread indefinitely.
        # We run imwrite in a thread-pool executor so we can enforce the
        # timeout without blocking the calling event loop (callers are async)
        # and without depending on Unix-only signal.alarm.
        #
        # Caveat: ``imwrite`` shells out to ffmpeg, and Python can't
        # interrupt a busy native thread. On timeout we abandon the
        # executor with ``wait=False`` so the caller returns promptly,
        # but the underlying ffmpeg keeps running until it finishes on
        # its own. That's acceptable (the spawned process exits without
        # consumers) and is strictly better than the previous behaviour
        # where ``with executor:`` blocked the caller for the full
        # encode regardless of the supposed 60s cap.
        import concurrent.futures

        video_buffer = io.BytesIO()

        def _encode():
            iio.imwrite(
                video_buffer,
                frames,
                extension=".mp4",
                fps=fps,
                codec="libx264",
                pixelformat="yuv420p",
            )

        # Refuse to submit when every pool worker is already occupied by an
        # in-flight/abandoned encode — otherwise this submit queues behind the
        # stuck workers and only fails after its own 60s timeout. Fall back to a
        # static image immediately (same as the timeout path: caller treats None
        # as "send the still frame"). See _GIF_ENCODE_MAX_INFLIGHT.
        if not _try_reserve_gif_encode_slot():
            logger.warning(
                "GIF -> MP4 encode pool saturated (all %d workers occupied by "
                "in-flight/abandoned encodes); falling back to static image",
                _GIF_ENCODE_MAX_INFLIGHT,
            )
            return None
        try:
            future = _GIF_ENCODE_EXECUTOR.submit(_encode)
        except RuntimeError:
            # Pool shut down (atexit) between reserve and submit — release the
            # slot and let the outer handler fall back to a static image.
            _release_gif_encode_slot()
            raise
        # Release the slot when the encode truly completes (even one we abandon
        # after the timeout below finishes eventually and fires this callback).
        future.add_done_callback(_release_gif_encode_slot)
        try:
            future.result(timeout=60.0)
        except concurrent.futures.TimeoutError:
            logger.warning("GIF -> MP4 encode timed out after 60s; thread continues in background")
            # Do NOT close ``video_buffer`` here — the worker thread is STILL
            # writing into it. Closing it now would make imageio's deferred
            # write-back raise ValueError("I/O operation on closed file") inside
            # the abandoned thread AND skip its os.remove, leaking the ffmpeg
            # temp file on every timeout. Leaving the buffer open lets the worker
            # finish into a live buffer and clean up its own temp file; the
            # buffer is then reclaimed by GC. The caller gets None and falls back
            # to a static image. (A non-timeout encode failure re-raises from
            # result() to the outer handler below — the worker has already
            # finished in that case, so the buffer needs no explicit close.)
            return None

        video_buffer.seek(0)
        logger.info("Converted GIF (%d frames) to MP4 at %d fps", len(frames), int(fps))
        result_bytes = video_buffer.read()
        # Worker finished, so the buffer is safe to close on this success path.
        video_buffer.close()
        return result_bytes

    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        RuntimeError,
    ) as e:
        # ``DecompressionBombWarning`` is included for consistency with the other
        # decode paths; the 1.5MP first-frame guard above already prevents the
        # promoted warning from firing on realistic inputs.
        if video_buffer is not None:
            # Non-timeout failure: future.result() re-raised after the worker
            # already finished, so the buffer is safe to close here (the timeout
            # path returns earlier and intentionally leaves the buffer open).
            video_buffer.close()
        logger.warning("Failed to convert GIF to video: %s", e)
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
        # Word-boundary match (not a naive substring) so a short character
        # name ("rin", "al", "mai") doesn't match inside unrelated words
        # ("drinking", "always", "email") and load the wrong reference image.
        # Lookarounds anchor on \w boundaries, which also tolerates multi-word
        # and Thai names (their edges are non-\w spaces/punctuation). Mirrors
        # the anchoring rationale in character_tags.replace_character_names.
        name_lower = char_name.lower()
        if name_lower and re.search(rf"(?<!\w){re.escape(name_lower)}(?!\w)", message_lower):
            try:
                # Resolve path and validate it's within the project directory
                resolved = (_BASE_DIR / img_path).resolve()
                if not resolved.is_relative_to(_BASE_DIR):
                    logger.warning("Blocked path traversal attempt: %s", img_path)
                    continue
                full_path = str(resolved)

                # Use cached image bytes
                img_bytes = load_cached_image_bytes(full_path)
                if img_bytes:
                    # Use context manager and copy to prevent resource leak
                    with Image.open(io.BytesIO(img_bytes)) as char_image:
                        char_copy = char_image.copy()
                    logger.info("🎭 Loaded character image for %s (cached)", char_name)
                    return (char_name, char_copy)
            # Also catch Pillow decompression-bomb error/warning (warning is
            # promoted to an exception at module level) so an oversized character
            # reference image is skipped instead of aborting the whole AI turn.
            # Mirrors prepare_user_avatar / process_attachments / convert_gif_to_video.
            except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                logger.warning("Failed to load character image for %s: %s", char_name, e)
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
    user: discord.User | discord.Member,
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
        logger.info("Sent avatar for %s", user_name)
        return avatar_copy
    except (
        discord.HTTPException,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as e:
        logger.warning("Failed to load avatar for %s: %s", user_name, e)
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
) -> tuple[list[Image.Image], list[ProcessedVideoPart], list[str]]:
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
    image_parts: list[Image.Image] = []
    video_parts: list[ProcessedVideoPart] = []
    text_parts: list[str] = []

    if not attachments:
        return image_parts, video_parts, text_parts

    # Maximum attachment size to download (10 MB)
    MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

    for attachment in attachments:
        # Skip attachments that are too large to prevent memory issues
        if attachment.size is not None and attachment.size > MAX_ATTACHMENT_SIZE:
            logger.warning(
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

                # Validate actual downloaded size. The pre-check above is
                # skipped when ``attachment.size`` is None, so guard here too
                # (mirrors the image path below) to avoid decoding/chunking an
                # oversized file into memory.
                if len(text_data) > MAX_ATTACHMENT_SIZE:
                    logger.warning(
                        "Skipping text attachment '%s' — actual size %d exceeds limit",
                        attachment.filename,
                        len(text_data),
                    )
                    continue

                # Decode with fallback encodings. 'latin-1' is intentionally NOT
                # in this list: it maps all 256 byte values and so never raises,
                # which would make the errors="replace" last resort below dead
                # code. Failing the loop through to that explicit replacement is
                # the intended "decode with replacement as last resort" path.
                content = None
                for encoding in ["utf-8", "utf-8-sig", "utf-16", "cp1252"]:
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
                    logger.info(
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
                    logger.info(
                        "📄 Processed text file '%s' from %s (%d chars)",
                        attachment.filename,
                        user_name,
                        len(content),
                    )
            except (OSError, UnicodeDecodeError, discord.HTTPException) as e:
                # discord.HTTPException covers a deleted/unfetchable
                # attachment — the image branch already catches it; without
                # it here a failed text download aborted the whole AI turn.
                logger.warning("Failed to process text attachment '%s': %s", attachment.filename, e)
            continue

        # Handle images
        if attachment.content_type and attachment.content_type.startswith("image/"):
            try:
                image_data = await attachment.read()

                # Validate actual downloaded size
                if len(image_data) > MAX_ATTACHMENT_SIZE:
                    logger.warning(
                        "Skipping attachment '%s' — actual size %d exceeds limit",
                        attachment.filename,
                        len(image_data),
                    )
                    continue

                # Check if it's an animated GIF. Inspect the actual bytes
                # rather than trusting ``attachment.content_type`` — Discord
                # sets the mime from the upload extension/header, which
                # may lie (e.g. ``screenshot.png`` that's actually an
                # animated GIF). ``is_animated_gif`` reads the GIF magic
                # bytes + frame count, so it correctly returns False for
                # non-GIF inputs and we don't waste a video-encode pass.
                if IMAGEIO_AVAILABLE and is_animated_gif(image_data):
                    # Convert animated GIF to video. ``convert_gif_to_video``
                    # uses a ThreadPoolExecutor internally but calls
                    # ``future.result()`` synchronously — that BLOCKS the
                    # calling thread for up to 60s. Inside an ``async def``
                    # the calling thread is the event loop, so we run the
                    # whole helper in a worker thread to keep the loop
                    # responsive across all channels while encode runs.
                    loop = asyncio.get_running_loop()
                    # Hold the encode-width semaphore for the duration so the
                    # default-pool thread we're about to park isn't waiting on a
                    # busy encode slot — excess concurrent GIFs queue on the
                    # semaphore instead of starving the shared default executor.
                    async with _GIF_CONVERT_SEMAPHORE:
                        video_bytes = await loop.run_in_executor(
                            None, convert_gif_to_video, image_data
                        )
                    if video_bytes:
                        video_parts.append({"data": video_bytes, "mime_type": "video/mp4"})
                        logger.info("Converted animated GIF to video from %s", user_name)
                        continue

                # Regular static image. ``image.copy()`` forces PIL to fully
                # decode all pixels synchronously; inside this ``async def`` the
                # calling thread is the event loop, so offload the decode to a
                # worker thread to keep the loop responsive (mirrors the GIF
                # branch above). The DecompressionBomb/OSError handling around
                # the awaited call is preserved by the surrounding ``except``.
                loop = asyncio.get_running_loop()

                def _decode(data):
                    with Image.open(io.BytesIO(data)) as image:
                        # Copy the image so we can close the original
                        return image.copy()

                image_copy = await loop.run_in_executor(None, _decode, image_data)
                image_parts.append(image_copy)
                logger.info("Processed image from %s", user_name)
            except (
                OSError,
                discord.HTTPException,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ) as e:
                # The module-level ``warnings.filterwarnings("error", ...)`` makes
                # Pillow's decompression-bomb check raise. For >2*MAX (>60MP) it
                # raises ``DecompressionBombError``; for MAX<pixels<=2*MAX
                # (30–60MP) it raises the ``DecompressionBombWarning`` CLASS
                # (a sibling of the Error — both subclass Exception directly,
                # neither subclasses the other), so BOTH must be listed here.
                # They inherit from ``Exception`` rather than ``OSError`` so
                # without explicit catch they would propagate up to logic.py's
                # catch-all and surface as a generic "AI error" message — the
                # user would never see that their image was the actual problem.
                logger.warning("Failed to process attachment: %s", e)

    return image_parts, video_parts, text_parts
