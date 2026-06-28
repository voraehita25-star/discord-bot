"""
YTDL Source Utility Module
Handles YouTube audio extraction and streaming for the music system.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TypedDict, cast

import discord
import yt_dlp

from .ffmpeg_path import get_ffmpeg_executable

logger = logging.getLogger(__name__)


class FFmpegOptions(TypedDict):
    """Kwargs accepted by `discord.FFmpegPCMAudio` we set here.

    Constraining the dict keys lets `**opts` unpack cleanly into the
    constructor without the type checker objecting that arbitrary keys
    might collide with `pipe`/`stderr`.
    """

    options: str
    before_options: str


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
    "source_address": "0.0.0.0",  # nosec B104  # yt-dlp outbound bind, not a server
    "http_chunk_size": 10485760,
    # Hard cap on downloaded audio to prevent disk-fill DoS from malicious
    # or oversized URLs. 300 MiB is far larger than any reasonable track
    # (~30 min of 320 kbps audio is ~75 MiB), so legitimate use is unaffected.
    # NOTE: max_filesize is a yt-dlp *download-side* option only — it is NOT
    # enforced in stream mode (download=False), where the upstream media URL is
    # handed straight to ffmpeg. The stream path enforces an equivalent bound
    # itself via the extracted filesize/duration metadata check in from_url().
    "max_filesize": 300 * 1024 * 1024,
    # Updated Chrome user-agent (2024)
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    # Performance optimizations
    "retries": 5,  # Reduced from 10 (faster fail)
    "fragment_retries": 5,  # Reduced from 10
    "concurrent_fragment_downloads": 8,  # 8 threads for R7 9800X3D
    "socket_timeout": 10,  # Faster timeout
    "buffersize": 4 * 1024 * 1024,  # 4MB buffer (DDR5 can handle it)
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
        logger.info("🍪 Using cookies.txt for YouTube authentication")
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


def get_ffmpeg_options(stream: bool = False, start_time: int = 0) -> FFmpegOptions:
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

    return FFmpegOptions(options=" ".join(options), before_options=" ".join(before_options))


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

    # Maximum time for yt-dlp operations before giving up (seconds)
    YTDL_TIMEOUT = 60

    @classmethod
    async def from_url(
        cls, url: str, *, loop: asyncio.AbstractEventLoop | None = None, stream: bool = False
    ) -> YTDLSource:
        """Create a player from a URL"""
        loop = loop or asyncio.get_running_loop()

        # Restrict to safe URL schemes — yt-dlp accepts file://, ftp://,
        # custom protocols, etc. that an attacker could use to read local
        # files or hit internal services. Only http(s) is allowed here.
        from urllib.parse import urlparse as _urlparse

        try:
            parsed = _urlparse(url)
            scheme = parsed.scheme.lower()
        except (ValueError, TypeError):
            parsed = None
            scheme = ""
        if scheme not in ("http", "https"):
            raise yt_dlp.DownloadError(
                f"URL scheme '{scheme or '(unknown)'}' is not allowed; only http(s) accepted"
            )

        # SSRF guard: delegate to the shared helper in utils.web.url_fetcher.
        # That helper covers more cases than our previous single-A-record
        # ``gethostbyname`` lookup did: it walks all addrinfo entries (so
        # AAAA + A pairs are both checked), unwraps IPv4-mapped IPv6
        # (``::ffff:127.0.0.1``), and shares the same blocklist with the
        # rest of the bot — so when ops decides to add a new private CIDR
        # we don't have a second copy of the rules drifting out of date.
        # Fall back to the local minimal check if the helper is unavailable
        # for any reason (circular import during early bootstrap, etc.).
        #
        # NOTE (best-effort, not airtight): this guard resolves the hostname
        # once, but yt-dlp/ffmpeg independently re-resolve the same hostname
        # when they actually fetch — so a DNS-rebinding adversary who answers
        # the first lookup with a public IP and the second with 127.0.0.1 /
        # 169.254.169.254 can slip past. We don't pin the validated IP for the
        # fetch (yt-dlp re-resolves internally and exposes no hook for it), so
        # the guard reduces but does not eliminate SSRF against a rebinding
        # attacker. Network-layer egress filtering is the real mitigation.
        host = parsed.hostname if parsed is not None else None
        if not host:
            raise ValueError("URL has no hostname")
        try:
            from utils.web.url_fetcher import _is_private_url

            if await _is_private_url(url):
                raise ValueError(f"Refusing to fetch from private/internal IP for {host!r}")
        except ImportError:
            # Fallback: keep SSRF protection rather than silently disabling it.
            # Resolve via getaddrinfo (NOT gethostbyname) so BOTH A and AAAA
            # records are checked — gethostbyname returns only the first A record
            # and never sees AAAA, so a host with a public A but a loopback/ULA
            # AAAA would slip past and then be dialled over IPv6 by yt-dlp/ffmpeg.
            # Reject if ANY resolved address is non-public, unwrapping
            # IPv4-mapped IPv6 (::ffff:127.0.0.1) first — mirroring the shared
            # resolver in utils.web.url_fetcher.
            import ipaddress
            import socket

            try:
                infos = await loop.run_in_executor(
                    None, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
                )
            except socket.gaierror as exc:
                raise ValueError(f"Could not resolve hostname {host!r}: {exc}") from exc
            for info in infos:
                ip_str = info[4][0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                except ValueError as exc:
                    raise ValueError(f"Could not parse resolved IP {ip_str!r}: {exc}") from exc
                # Unwrap IPv4-mapped IPv6 so ::ffff:127.0.0.1 is judged as 127.0.0.1.
                if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
                    ip_obj = ip_obj.ipv4_mapped
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_link_local
                    or ip_obj.is_multicast
                    or ip_obj.is_reserved
                    or ip_obj.is_unspecified
                ):
                    raise ValueError(
                        f"URL host {host!r} resolves to non-public IP {ip_str} — refusing"
                    )

        # Attempt 1: High Quality / Default (with runtime cookie check)
        try:
            logger.info("⬇️ Downloading: %s (Mode: HQ)", url)
            ytdl_hq = get_ytdl_hq()
            data = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ytdl_hq.extract_info(url, download=not stream)),
                timeout=cls.YTDL_TIMEOUT,
            )
            ytdl_obj = ytdl_hq
        except (TimeoutError, yt_dlp.DownloadError) as e:
            logger.warning("⚠️ HQ Download failed: %s. Switching to Fallback Mode...", e)

            # Attempt 2: Fallback (No cookies, safer format)
            try:
                logger.info("⬇️ Downloading: %s (Mode: Fallback)", url)
                ytdl_fallback = get_ytdl_fallback()
                data = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, lambda: ytdl_fallback.extract_info(url, download=not stream)
                    ),
                    timeout=cls.YTDL_TIMEOUT,
                )
                ytdl_obj = ytdl_fallback
            except (TimeoutError, yt_dlp.DownloadError) as e2:
                logger.error("❌ All download attempts failed: %s", e2)
                # Chain the original HQ failure (``e``) onto the fallback
                # failure: the HQ cause (auth/cookies/format) is often the more
                # informative one and would otherwise be lost from the traceback.
                raise e2 from e  # Give up

        if data is None:
            raise yt_dlp.DownloadError("No data returned from yt-dlp")

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
            # max_filesize (the disk-fill DoS guard in ytdl_opts_hq) is a
            # download-side option only and is NOT applied in stream mode, so
            # enforce an equivalent size bound here from the extracted metadata
            # before handing the upstream URL to ffmpeg. An attacker-supplied
            # URL resolving to an arbitrarily large/endless stream would
            # otherwise be streamed without any cap.
            stream_max_bytes = cast(int, ytdl_opts_hq["max_filesize"])
            advertised_size = data.get("filesize") or data.get("filesize_approx")
            if isinstance(advertised_size, (int, float)) and advertised_size > stream_max_bytes:
                raise ValueError(
                    f"Stream advertises {int(advertised_size)} bytes, "
                    f"exceeding the {stream_max_bytes}-byte cap — refusing"
                )
        else:
            filename = ytdl_obj.prepare_filename(data)

        # In download mode (stream=False) yt-dlp has already written the file to
        # disk by this point. If any post-download validator or the
        # FFmpegPCMAudio construction below raises, we return without a
        # YTDLSource, so the caller never gets a player to clean up and the
        # file would be orphaned (only reclaimed later by the periodic temp
        # janitor). Best-effort unlink the just-downloaded file on any failure
        # before re-raising. Streaming mode has nothing on disk to clean up.
        try:
            # Validate the path/URL we are about to hand to ffmpeg as its input.
            # Anything starting with '-' would be parsed as an ffmpeg flag (e.g.
            # `-i /etc/passwd -y output.wav`), and a non-http(s) URL from a
            # compromised yt-dlp extractor could request unintended schemes.
            # Reject those rather than rely on ffmpeg to do the right thing.
            if not isinstance(filename, str) or not filename:
                raise ValueError("Invalid filename returned by yt-dlp")
            if filename.startswith("-"):
                raise ValueError("yt-dlp returned suspicious filename starting with '-'")
            if stream and not filename.startswith(("http://", "https://")):
                raise ValueError(f"yt-dlp returned non-http(s) stream URL ({filename[:32]}...)")
            # When downloading (stream=False), confirm yt-dlp wrote into the
            # temp/ dir we configured via outtmpl. A compromised extractor that
            # forges absolute paths (e.g. C:\Windows\System32\foo.opus) would
            # otherwise let ffmpeg open arbitrary files for read or get fed
            # back into Discord upload paths. resolve() canonicalises symlinks
            # so a sneaky temp/../etc/passwd is collapsed before the check.
            if not stream:
                from pathlib import Path as _Path

                try:
                    resolved = _Path(filename).resolve()
                    expected_root = _Path("temp").resolve()
                    # ``relative_to`` raises ValueError if resolved is not under
                    # expected_root — that's the signal we want.
                    resolved.relative_to(expected_root)
                except ValueError as exc:
                    raise ValueError(
                        f"yt-dlp wrote outside the temp/ download dir: {filename!r}"
                    ) from exc

            current_options = get_ffmpeg_options(stream=stream)

            return cls(
                discord.FFmpegPCMAudio(
                    filename, **current_options, executable=get_ffmpeg_executable()
                ),
                data=data,
                filename=filename,
            )
        except BaseException:
            # On the download path, reclaim the orphaned file instead of relying
            # solely on the periodic janitor. Only attempt this for a plausible
            # local path (str, not the path-traversal/'-' cases): the unlink must
            # stay confined to temp/ exactly like the read-side check above, so a
            # forged out-of-temp filename is never deleted here. unlink is
            # best-effort and must never mask the original error.
            if (
                not stream
                and isinstance(filename, str)
                and filename
                and not filename.startswith("-")
            ):
                try:
                    cleanup_path = Path(filename).resolve()
                    if cleanup_path.is_relative_to(Path("temp").resolve()):
                        cleanup_path.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    logger.warning(
                        "Failed to clean up orphaned download %r: %s", filename, cleanup_exc
                    )
            raise

    @classmethod
    async def search_source(
        cls, query: str, loop: asyncio.AbstractEventLoop | None = None
    ) -> dict[str, Any] | None:
        """Search specifically for a song on YouTube"""
        loop = loop or asyncio.get_running_loop()

        # If the input looks like a URL we used to forward it straight to
        # yt-dlp, which would happily resolve file://, ftp://, custom
        # protocols, etc. Reject anything that's not http(s) — non-URL
        # queries flow through the search path unchanged.
        from urllib.parse import urlparse as _urlparse

        try:
            scheme = _urlparse(query).scheme.lower() if query else ""
        except (ValueError, TypeError):
            scheme = ""
        # Only treat the input as a URL when it actually looks like one. urlparse()
        # reports a "scheme" for any ``word:rest`` text (e.g. "C418: Sweden" -> "c418",
        # "OST: theme" -> "ost"), which previously rejected ordinary search queries
        # outright. Gate on "://" — mirroring the !play SSRF guard in music/cog.py —
        # so only real URL schemes are checked; plain text flows to ytsearch below.
        if "://" in query and scheme and scheme not in ("http", "https"):
            logger.warning("Rejecting non-http(s) URL scheme in search: %s", scheme)
            return None
        # Handle search query if not a URL. Compare case-insensitively: the
        # scheme guard above lowercases via urlparse, so an uppercase-scheme URL
        # ("HTTP://...") passes that check but would otherwise fail this
        # case-sensitive startswith and get mis-wrapped as a literal
        # ``ytsearch:HTTP://...`` search instead of routing through the
        # SSRF-guarded direct-URL branch below.
        if not query.lower().startswith(("http://", "https://")):
            query = f"ytsearch:{query}"
        else:
            # The input is a direct URL — apply the same SSRF guard as
            # from_url() before handing it to yt-dlp, which would otherwise
            # happily fetch http://127.0.0.1/ or the cloud metadata IP
            # (169.254.169.254). The ytsearch: path above is exempt.
            try:
                from utils.web.url_fetcher import _is_private_url

                if await _is_private_url(query):
                    logger.warning("Rejecting search URL resolving to private/internal IP")
                    return None
            except ImportError:
                # Fail closed for raw URLs if the SSRF helper can't be imported.
                logger.warning("SSRF helper unavailable; refusing direct URL in search")
                return None

        try:
            ytdl_hq = get_ytdl_hq()
            data = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ytdl_hq.extract_info(query, download=False)),
                timeout=cls.YTDL_TIMEOUT,
            )
        except (TimeoutError, yt_dlp.DownloadError):
            # Guard the fallback attempt too. Without this, a TimeoutError or
            # yt_dlp.DownloadError raised here would propagate straight out of
            # search_source, violating its documented `dict | None` return
            # contract — every other failure path returns None. Mirrors the
            # try/except around from_url()'s fallback extract_info.
            try:
                ytdl_fallback = get_ytdl_fallback()
                data = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, lambda: ytdl_fallback.extract_info(query, download=False)
                    ),
                    timeout=cls.YTDL_TIMEOUT,
                )
            except Exception as exc:
                # Broadened from (TimeoutError, yt_dlp.DownloadError): the
                # fallback extract_info can also raise non-DownloadError
                # YoutubeDLError subclasses (ExtractorError/GeoRestrictedError)
                # or a bare ValueError/KeyError from a hostile extractor. Raised
                # inside THIS handler's suite, such an exception escapes the whole
                # try statement — the sibling broad `except Exception` below only
                # guards the try BODY, not another handler's suite — and the music
                # cog caller only handles DownloadError/ValueError, so an escapee
                # would freeze the queue. Normalize every fallback failure to None
                # like the outer catch, honoring the documented dict|None contract.
                logger.warning("Search fallback extraction failed: %s", exc)
                return None
        except Exception as exc:
            # yt-dlp's extract_info can raise YoutubeDLError subclasses that are
            # NOT DownloadError (ExtractorError, GeoRestrictedError) or a bare
            # ValueError/KeyError from a hostile/third-party extractor. Those
            # would otherwise propagate out and violate the documented dict|None
            # contract — and the music cog's caller only handles
            # DownloadError/ValueError, so an escapee would freeze the queue.
            # Normalize to None like every other failure path here.
            logger.warning("Search extraction failed unexpectedly: %s", exc)
            return None

        if data is None:
            logger.warning("No data extracted from search query")
            return None

        if "entries" in data:
            # If it's a search result or playlist, take the first item
            entries = data["entries"]
            if entries and len(entries) > 0:
                data = entries[0]
            else:
                logger.warning("Search result has no entries")
                return None

        if not data:
            logger.warning("No data extracted from search query")
            return None

        return data  # type: ignore[no-any-return]
