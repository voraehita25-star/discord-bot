"""
YTDL Source Utility Module
Handles YouTube audio extraction and streaming for the music system.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import discord
import yt_dlp

# --- MUSIC SYSTEM ---
# Suppress bug reports
yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ""

# 🎵 PREMIUM AUDIO QUALITY CONFIG (Optimized for Performance)
# Format priority: Opus > Vorbis > AAC > MP3 (Opus is best for Discord)
ytdl_opts_hq = {
    "format": (
        "bestaudio[acodec=opus]/bestaudio[acodec=vorbis]/bestaudio[acodec=aac]/bestaudio/best"
    ),
    "outtmpl": "temp/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": False,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "http_chunk_size": 10485760,
    # Updated Chrome user-agent (2024)
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    # Performance optimizations
    "retries": 5,  # Reduced from 10 (faster fail)
    "fragment_retries": 5,  # Reduced from 10
    "concurrent_fragment_downloads": 5,  # Increased from 3 (more parallel)
    "socket_timeout": 10,  # Faster timeout
    "buffersize": 1024 * 1024,  # 1MB buffer
    "geo_bypass": True,
    "geo_bypass_country": "US",
    # Use Android client to bypass 403 errors
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    },
    # Audio quality settings
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "320",
        }
    ],
    "prefer_ffmpeg": True,
    "keepvideo": False,
    # Additional optimizations
    "extract_flat": False,  # Full extraction for single videos
    "lazy_playlist": True,  # Lazy load playlists
}


def get_cookie_opts() -> dict[str, str]:
    """
    Get cookie options for yt-dlp.
    Only uses cookies.txt if it exists in the bot's root directory.

    To create cookies.txt:
    1. Install "Get cookies.txt LOCALLY" extension in Chrome
    2. Go to youtube.com and make sure you're logged in
    3. Click the extension icon and export cookies for youtube.com
    4. Save as 'cookies.txt' in the bot's root folder (same folder as bot.py)
    """
    cookie_opts = {}
    cookies_file = Path("cookies.txt")
    if cookies_file.exists():
        cookie_opts["cookiefile"] = "cookies.txt"
        logging.info("🍪 Using cookies.txt for YouTube authentication")
    return cookie_opts


def get_ytdl_with_cookies() -> dict[str, Any]:
    """Get ytdl options with cookies if available (checked at runtime)"""
    opts = ytdl_opts_hq.copy()
    # Remove postprocessors for download mode (we handle audio with ffmpeg)
    opts.pop("postprocessors", None)
    # Add cookies if available
    opts.update(get_cookie_opts())
    return opts


# 2. Fallback Config (Safe Mode) - Also with cookies support
def get_ytdl_fallback_opts() -> dict[str, Any]:
    """Get fallback ytdl options with cookies support"""
    opts = ytdl_opts_hq.copy()
    opts.pop("postprocessors", None)
    opts["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
    # Add cookies if available
    opts.update(get_cookie_opts())
    return opts


def get_ytdl_hq() -> yt_dlp.YoutubeDL:
    """Get YoutubeDL instance with runtime cookie check"""
    return yt_dlp.YoutubeDL(get_ytdl_with_cookies())


def get_ytdl_fallback() -> yt_dlp.YoutubeDL:
    """Get fallback YoutubeDL instance"""
    return yt_dlp.YoutubeDL(get_ytdl_fallback_opts())


def get_ffmpeg_options(stream: bool = False, start_time: int = 0) -> dict[str, str]:
    """
    🎵 Premium FFmpeg Audio Settings
    - 48kHz sample rate (Discord native)
    - Stereo audio
    - Audio normalization for consistent volume
    - Bass boost option
    """
    options = ["-vn"]  # No video
    before_options = []

    # === RAW AUDIO (NO ENHANCEMENT) ===
    # Output: 48kHz Stereo 16-bit PCM (Discord native format)
    # No audio filters applied - pure unprocessed audio
    options.extend(["-ar", "48000", "-ac", "2", "-f", "s16le"])

    # === STREAMING SETTINGS ===
    if stream:
        before_options.extend(
            [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
                "-probesize",
                "20M",  # Increased for better analysis
                "-analyzeduration",
                "20M",  # Analyze more of the file
            ]
        )
    else:
        # Download mode - larger buffer for stability
        options.extend(["-bufsize", "1024k"])

    # === SEEK POSITION (for fix/resume) ===
    if start_time > 0:
        before_options.extend(["-ss", str(int(start_time))])

    return {"options": " ".join(options), "before_options": " ".join(before_options)}


class YTDLSource(discord.PCMVolumeTransformer):
    """
    YTDLSource class wrapper for playing music via Discord voice.
    Handles downloading or streaming from YouTube via yt-dlp.
    """

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        data: dict[str, Any],
        volume: float = 0.5,
        filename: str | None = None,
    ) -> None:
        super().__init__(source, volume)
        self.data: dict[str, Any] = data
        self.title: str | None = data.get("title")
        self.url: str | None = data.get("url")
        self.filename: str | None = filename

    @classmethod
    async def from_url(
        cls, url: str, *, loop: asyncio.AbstractEventLoop | None = None, stream: bool = False
    ) -> YTDLSource:
        """Create a player from a URL"""
        loop = loop or asyncio.get_running_loop()

        # Attempt 1: High Quality / Default (with runtime cookie check)
        try:
            logging.info("⬇️ Downloading: %s (Mode: HQ)", url)
            ytdl_hq = get_ytdl_hq()
            data = await loop.run_in_executor(
                None, lambda: ytdl_hq.extract_info(url, download=not stream)
            )
            ytdl_obj = ytdl_hq
        except yt_dlp.DownloadError as e:
            logging.warning("⚠️ HQ Download failed: %s. Switching to Fallback Mode...", e)

            # Attempt 2: Fallback (No cookies, safer format)
            try:
                logging.info("⬇️ Downloading: %s (Mode: Fallback)", url)
                ytdl_fallback = get_ytdl_fallback()
                data = await loop.run_in_executor(
                    None, lambda: ytdl_fallback.extract_info(url, download=not stream)
                )
                ytdl_obj = ytdl_fallback
            except yt_dlp.DownloadError as e2:
                logging.error("❌ All download attempts failed: %s", e2)
                raise e2  # Give up

        if "entries" in data:
            # take first item from a playlist
            entries = data["entries"]
            if entries and len(entries) > 0:
                data = entries[0]
                # yt-dlp can return None for unavailable entries
                if data is None:
                    raise ValueError("First entry is None - video may be unavailable")
            else:
                raise ValueError("Playlist or search result is empty")

        # Validate data has required fields
        if not data:
            raise ValueError("No data extracted from URL")

        if stream:
            if "url" not in data:
                raise ValueError("Streaming URL not found in data")
            filename = data["url"]
        else:
            filename = ytdl_obj.prepare_filename(data)

        current_options = get_ffmpeg_options(stream=stream)

        return cls(
            discord.FFmpegPCMAudio(filename, **current_options, executable="ffmpeg"),
            data=data,
            filename=filename,
        )

    @classmethod
    async def search_source(
        cls, query: str, loop: asyncio.AbstractEventLoop | None = None
    ) -> dict[str, Any] | None:
        """Search specifically for a song on YouTube"""
        loop = loop or asyncio.get_running_loop()

        # Handle search query if not a URL
        if not query.startswith(("http://", "https://")):
            query = f"ytsearch:{query}"

        try:
            ytdl_hq = get_ytdl_hq()
            data = await loop.run_in_executor(
                None, lambda: ytdl_hq.extract_info(query, download=False)
            )
        except yt_dlp.DownloadError:
            ytdl_fallback = get_ytdl_fallback()
            data = await loop.run_in_executor(
                None, lambda: ytdl_fallback.extract_info(query, download=False)
            )

        if "entries" in data:
            # If it's a search result or playlist, take the first item
            entries = data["entries"]
            if entries and len(entries) > 0:
                data = entries[0]
            else:
                logging.warning("Search result has no entries")
                return None

        if not data:
            logging.warning("No data extracted from search query")
            return None

        return data
