# pyright: reportAttributeAccessIssue=false
# pyright: reportOptionalMemberAccess=false
"""
Spotify Handler Module for Music Cog.
Handles Spotify link processing and track extraction with retry logic.

Note: Type checker warnings for optional Spotify client methods are suppressed
because the is_available() check ensures sp is not None at runtime.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
from collections.abc import Callable
from http.client import RemoteDisconnected
from typing import TYPE_CHECKING, Any

import discord
import spotipy
from requests.exceptions import (  # type: ignore[import-untyped, unused-ignore]
    ConnectionError as RequestsConnectionError,
    ReadTimeout,
)
from spotipy.oauth2 import SpotifyClientCredentials
from urllib3.exceptions import ProtocolError

from cogs.music.utils import Colors, Emojis, format_duration

# Import Circuit Breaker for Spotify API protection
try:
    from utils.reliability.circuit_breaker import spotify_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    spotify_circuit = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from discord.ext.commands import Bot, Context


class SpotifyHandler:
    """Handles Spotify API interactions for the Music cog."""

    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 2  # seconds
    MAX_PLAYLIST_TRACKS: int = 500  # Limit to prevent memory issues with huge playlists
    RATE_LIMIT_DELAY: float = 0.1  # Delay between pagination requests to avoid rate limits

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.sp: spotipy.Spotify | None = None
        # Serialise ``_setup_client`` so two concurrent retry paths can't
        # both recreate the client, leak a freshly-built one to GC, and
        # leave bound-method ``func`` arguments pointing at a now-closed
        # ``requests.Session``. Lazily allocated because the handler is
        # constructed before the event loop in some test setups.
        self._setup_lock: asyncio.Lock | None = None
        self._setup_client()

    def _get_setup_lock(self) -> asyncio.Lock:
        if self._setup_lock is None:
            self._setup_lock = asyncio.Lock()
        return self._setup_lock

    def _setup_client(self) -> None:
        """Initialize Spotify client with credentials from environment.

        Prefer ``SPOTIPY_*`` (the spotipy library convention) over
        ``SPOTIFY_*`` for backwards compatibility. Warn if both are set
        with different values so an operator who left a stale value in
        their env after a credential rotation isn't silently using the
        wrong identity.
        """
        spotipy_id = os.getenv("SPOTIPY_CLIENT_ID")
        spotify_id = os.getenv("SPOTIFY_CLIENT_ID")
        spotipy_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        spotify_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if spotipy_id and spotify_id and spotipy_id != spotify_id:
            logger.warning(
                "SPOTIPY_CLIENT_ID and SPOTIFY_CLIENT_ID are both set with "
                "different values; preferring SPOTIPY_CLIENT_ID. Remove the "
                "unused one to avoid surprise credential swaps."
            )
        if spotipy_secret and spotify_secret and spotipy_secret != spotify_secret:
            logger.warning(
                "SPOTIPY_CLIENT_SECRET and SPOTIFY_CLIENT_SECRET differ; "
                "preferring SPOTIPY_CLIENT_SECRET."
            )
        client_id = spotipy_id or spotify_id
        client_secret = spotipy_secret or spotify_secret

        # Close any pre-existing session before reassigning self.sp.
        # Recreate-on-retry would otherwise keep the old requests.Session
        # alive, leaking sockets/file descriptors each time.
        if self.sp is not None:
            old_session = getattr(self.sp, "_session", None) or (
                getattr(self.sp.auth_manager, "_session", None)
                if hasattr(self.sp, "auth_manager")
                else None
            )
            if old_session is not None:
                try:
                    old_session.close()
                except Exception:
                    pass

        if client_id and client_secret:
            try:
                self.sp = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=client_id, client_secret=client_secret
                    ),
                    # Bound spotipy's internal request timeout so a stalled
                    # connection can't pin the executor thread for the full
                    # 60s window (which also pins the run_in_executor await
                    # and stalls ffmpeg/discord traffic). 15s is generous
                    # for Spotify's normal latency.
                    requests_timeout=15,
                    # Limit spotipy's own retries — we wrap calls in
                    # ``_api_call_with_retry`` (MAX_RETRIES=3) on top of
                    # this, so retries=5 × MAX_RETRIES = up to 15 retries
                    # per user request. retries=2 caps worst-case at ~6.
                    retries=2,
                )
                logger.info("✅ Spotify Client Initialized")
            except (spotipy.SpotifyException, ValueError):
                logger.exception("❌ Spotify Init Failed")
        else:
            logger.warning("⚠️ Spotify credentials not found. Spotify links won't work.")

    def cleanup(self) -> None:
        """Cleanup Spotify client resources.

        Call this when the Music cog unloads to release resources.

        Tries the public `session` attribute first, then the legacy `_session`
        private attribute as a fallback for older spotipy versions. If neither
        is present (e.g., spotipy upgraded again and renamed it), we log at
        debug level so an upgrade surfaces this site instead of silently
        leaking the underlying requests Session.
        """
        if self.sp:
            session = getattr(self.sp, "session", None) or getattr(self.sp, "_session", None)
            if session is not None:
                try:
                    session.close()
                except Exception:
                    logger.debug("Failed to close Spotify session during cleanup")
            else:
                logger.debug(
                    "Spotify client has no session/_session attribute — "
                    "spotipy may have changed; sockets may leak until GC"
                )
        self.sp = None
        logger.debug("🧹 Spotify handler cleaned up")

    def is_available(self) -> bool:
        """Check if Spotify client is available."""
        return self.sp is not None

    async def _api_call_with_retry(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute Spotify API call with retry logic and circuit breaker protection."""
        # Check circuit breaker before making API call
        if CIRCUIT_BREAKER_AVAILABLE and spotify_circuit and not spotify_circuit.can_execute():
            logger.warning("⚡ Spotify Circuit breaker OPEN - skipping API call")
            raise ConnectionError(
                "Spotify API circuit breaker is open - service temporarily unavailable"
            )

        # Capture args/kwargs at call time to prevent closure issues
        # If we use lambda: func(*args, **kwargs) directly, args/kwargs
        # could be modified before the executor runs
        captured_args = args
        captured_kwargs = kwargs

        for attempt in range(self.MAX_RETRIES):
            try:
                # Use functools.partial to avoid closure capturing mutable variables
                result = await asyncio.get_running_loop().run_in_executor(
                    None, functools.partial(func, *captured_args, **captured_kwargs)
                )
                # Record success ONCE for the whole user request — independent
                # of how many internal retries happened. This is the inverse
                # of the failure path below: the circuit breaker tracks
                # "user-visible Spotify call outcomes", not "every transport
                # blip the bot quietly retried past".
                if CIRCUIT_BREAKER_AVAILABLE and spotify_circuit:
                    spotify_circuit.record_success()
                return result
            except (
                RequestsConnectionError,
                ReadTimeout,
                RemoteDisconnected,
                ProtocolError,
                # ``ConnectionResetError`` is a subclass of ``OSError``; the
                # explicit entry is redundant but kept for grep-ability —
                # ``OSError`` catches every transient socket-level failure
                # raised by urllib3.
                OSError,
            ) as e:
                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff: 2s, 4s, 8s
                    delay = self.RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "Spotify connection error (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        self.MAX_RETRIES,
                        type(e).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)

                    # Recreate client on 2nd+ failure (token might be stale).
                    # Serialise so two parallel retry paths don't both invoke
                    # ``_setup_client`` and leak one of the freshly-built
                    # Spotify objects. Skip the rebuild if another coroutine
                    # already swapped ``self.sp`` while we were waiting on
                    # the lock — re-binding the bound-method ``func`` to the
                    # fresh client is enough.
                    if attempt >= 1:
                        bound_target = getattr(func, "__self__", None)
                        async with self._get_setup_lock():
                            if self.sp is None or self.sp is bound_target:
                                logger.info("🔄 Recreating Spotify client...")
                                self._setup_client()
                            if self.sp is None:
                                logger.error("Failed to recreate Spotify client")
                                if CIRCUIT_BREAKER_AVAILABLE and spotify_circuit:
                                    spotify_circuit.record_failure()
                                raise ConnectionError("Spotify client recreation failed") from None
                            # Re-bind func to the current ``self.sp`` if it
                            # was a bound method. Inside the lock the target
                            # cannot be swapped out from under us mid-rebind.
                            if isinstance(bound_target, spotipy.Spotify):
                                func = getattr(self.sp, func.__name__)
                else:
                    # Only record failure ONCE — when retries are exhausted.
                    # Previously we recorded every transient retry which made
                    # a single flaky-network user request burn the breaker's
                    # whole failure budget (3 retries == 3 failures), tripping
                    # the open state for everyone else.
                    if CIRCUIT_BREAKER_AVAILABLE and spotify_circuit:
                        spotify_circuit.record_failure()
                    logger.error("Spotify connection failed after %d attempts", self.MAX_RETRIES)
                    raise

        # Unreachable when MAX_RETRIES >= 1 (the loop either returns,
        # raises in the final-attempt branch, or sleeps + continues).
        # Guard anyway so a future MAX_RETRIES=0 misconfiguration
        # doesn't silently fall off the end and return None into a
        # caller that expects a real result.
        raise RuntimeError(
            f"_api_call_with_retry exhausted with MAX_RETRIES={self.MAX_RETRIES} "
            "without producing a result"
        )

    async def process_spotify_url(
        self, ctx: Context, query: str, queue: list[dict[str, Any]]
    ) -> bool:
        """
        Process a Spotify URL and add tracks to queue.
        Returns True if successful, False otherwise.
        """
        if not self.sp:
            return False

        query = query.strip("<>")

        try:
            if "/track/" in query or "track:" in query:
                return await self._handle_track(ctx, query, queue)
            elif "/playlist/" in query or "playlist:" in query:
                return await self._handle_playlist(ctx, query, queue)
            elif "/album/" in query or "album:" in query:
                return await self._handle_album(ctx, query, queue)
            else:
                embed = discord.Embed(
                    description=(
                        f"{Emojis.CROSS} รองรับเฉพาะ Spotify Track, Playlist, และ Album เท่านั้น"
                    ),
                    color=Colors.ERROR,
                )
                await ctx.send(embed=embed)
                return False

        except (
            spotipy.SpotifyException,
            RequestsConnectionError,
            ReadTimeout,
            ConnectionError,
            OSError,
        ) as e:
            # Catch a wider net so circuit-breaker ConnectionError + low-level
            # OSError surface as a friendly Spotify error instead of crashing
            # the command handler. ``OSError`` is intentionally broad here
            # because the requests stack wraps low-level networking errors
            # in OSError subclasses (BrokenPipeError, ConnectionResetError);
            # callers that need narrower handling should not rely on
            # ``process_spotify_url`` to surface a specific subtype.
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ข้อผิดพลาด Spotify",
                description=(
                    f"ไม่สามารถเชื่อมต่อ Spotify ได้ ({type(e).__name__})\nกรุณาลองใหม่อีกครั้ง หรือใช้ชื่อเพลงแทน"
                ),
                color=Colors.ERROR,
            )
            embed.set_footer(text="ลองใหม่อีกครั้ง หรือใช้ชื่อเพลงแทน")
            await ctx.send(embed=embed)
            # Use ``logger.exception`` so the traceback is captured for
            # the broader OSError category — without it, debugging an
            # unexpected OSError subclass requires re-running the whole
            # command path.
            logger.exception("Spotify error: %s", e)
            return False

    async def _handle_track(self, ctx: Context, query: str, queue: list[dict[str, Any]]) -> bool:
        """Handle a single Spotify track."""
        if not self.sp:
            return False

        # Enforce queue size cap (the play command checks for non-Spotify
        # paths but the Spotify path used to bypass it).
        from cogs.music.queue import MAX_QUEUE_SIZE

        if len(queue) >= MAX_QUEUE_SIZE:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Queue is full (max {MAX_QUEUE_SIZE} tracks)",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return False

        track = await self._api_call_with_retry(self.sp.track, query)

        if not track:
            return False

        # Validate track data
        if not track.get("artists") or len(track["artists"]) == 0:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ไม่พบข้อมูลศิลปินใน Spotify track", color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return False

        track_name = track.get("name", "Unknown Track")
        artist_name = track["artists"][0]["name"]
        external_url = track.get("external_urls", {}).get("spotify", query)

        search_query = f"{artist_name} - {track_name} audio"
        queue.append(
            {"url": search_query, "title": f"{artist_name} - {track_name}", "type": "search"}
        )

        # Premium Spotify Embed
        embed = discord.Embed(
            title=f"{Emojis.MUSIC} เพิ่มจาก Spotify",
            description=f"**[{track_name}]({external_url})**",
            color=Colors.SPOTIFY,
        )

        album = track.get("album", {})
        if album.get("images") and len(album["images"]) > 0:
            embed.set_thumbnail(url=album["images"][0]["url"])

        # `.get(..., 0)` only covers a MISSING key; Spotify can return
        # ``duration_ms: null`` (e.g. some episodes/local tracks), and
        # ``None // 1000`` raises TypeError. ``or 0`` coerces null too.
        duration_ms = track.get("duration_ms") or 0
        embed.add_field(name=f"{Emojis.MICROPHONE} ศิลปิน", value=artist_name, inline=True)
        # ``or`` (not a get-default) so an explicit ``name: null`` also coerces,
        # mirroring the duration_ms handling above — else None[:25] raises.
        album_name = (album.get("name") or "Unknown Album")[:25]
        embed.add_field(name=f"{Emojis.DISC} อัลบั้ม", value=album_name, inline=True)
        embed.add_field(
            name=f"{Emojis.CLOCK} ความยาว", value=format_duration(duration_ms // 1000), inline=True
        )

        embed.set_footer(
            text=(f"ขอโดย {ctx.author.display_name} • ลำดับในคิว: {len(queue)}"),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)
        return True

    async def _handle_playlist(self, ctx: Context, query: str, queue: list[dict[str, Any]]) -> bool:
        """Handle a Spotify playlist."""
        if not self.sp:
            return False

        loading_embed = discord.Embed(
            title=f"{Emojis.LOADING} กำลังโหลด Spotify Playlist",
            description="กรุณารอสักครู่...",
            color=Colors.SPOTIFY,
        )
        msg = await ctx.send(embed=loading_embed)

        def get_all_playlist_tracks(url):
            # Capture the current client into a local so this whole pagination
            # uses ONE consistent client, even if another thread recreates
            # self.sp mid-loop (e.g. a concurrent operation's retry calling
            # _setup_client). Reading self.sp repeatedly across the loop could
            # otherwise mix an old session's cursor with a new client.
            # _api_call_with_retry re-invokes this closure on retry, so a
            # recreated client is still picked up on the next attempt.
            sp = self.sp
            # cleanup() can set self.sp = None between the guard at the top of
            # _handle_playlist and this closure running in the executor. Raise a
            # ConnectionError (caught by process_spotify_url) instead of letting
            # `None.playlist_tracks` surface as an unhandled AttributeError.
            if sp is None:
                raise ConnectionError("Spotify client unavailable")
            results = sp.playlist_tracks(url)
            tracks = results.get("items", []) if results else []
            # Limit total tracks to prevent memory issues
            # Also check results is not None to prevent infinite loop if sp.next() returns None
            while results and results.get("next") and len(tracks) < self.MAX_PLAYLIST_TRACKS:
                # Note: sleep is inside executor, which is acceptable
                # as it doesn't block the main event loop
                import time

                time.sleep(self.RATE_LIMIT_DELAY)
                results = sp.next(results)
                if results and results.get("items"):
                    tracks.extend(results["items"])
            return tracks[: self.MAX_PLAYLIST_TRACKS]  # Ensure limit

        try:
            results = await self._api_call_with_retry(get_all_playlist_tracks, query)
        except asyncio.CancelledError:
            # If the user navigated away or the parent command was
            # cancelled, the loading embed would otherwise sit forever
            # showing "กำลังโหลด..." even though no work is happening.
            # Clean up before re-raising the cancellation.
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await msg.delete()
            raise
        except (RequestsConnectionError, ReadTimeout) as e:
            # Try to delete loading message, but don't fail if already deleted
            try:
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            # Send error message (caller will also handle, so just log)
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ข้อผิดพลาด Spotify",
                description=f"ไม่สามารถโหลด Playlist ได้\n```{type(e).__name__}```",
                color=Colors.ERROR,
            )
            embed.set_footer(text="ลองใหม่อีกครั้ง")
            await ctx.send(embed=embed)
            return False

        if not results or not isinstance(results, list):
            try:
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ไม่พบเพลงใน Playlist", color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return False

        # Enforce queue size cap (the play command checks for non-Spotify
        # paths but the Spotify path used to bypass it). Truncate the
        # incoming playlist so we never exceed MAX_QUEUE_SIZE.
        from cogs.music.queue import MAX_QUEUE_SIZE

        capacity_remaining = MAX_QUEUE_SIZE - len(queue)
        truncated = False
        if capacity_remaining <= 0:
            try:
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Queue is full (max {MAX_QUEUE_SIZE} tracks)",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return False
        if len(results) > capacity_remaining:
            results = results[:capacity_remaining]
            truncated = True

        count = 0
        for item in results:
            if not item:
                continue
            track = item.get("track")
            if track and track.get("artists") and len(track["artists"]) > 0 and track.get("name"):
                artist_name = track["artists"][0]["name"]
                track_name = track["name"]
                search_query = f"{artist_name} - {track_name} audio"
                queue.append(
                    {
                        "url": search_query,
                        "title": f"{artist_name} - {track_name}",
                        "type": "search",
                    }
                )
                count += 1

        # Delete loading message safely
        try:
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        if count == 0:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ไม่พบเพลงที่สามารถเพิ่มได้ใน Playlist", color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return False

        embed = discord.Embed(
            title=f"{Emojis.CHECK} เพิ่ม Playlist แล้ว",
            description=f"เพิ่ม **{count}** เพลงจาก Spotify Playlist",
            color=Colors.SPOTIFY,
        )
        embed.add_field(name="ขนาดคิว", value=f"`{len(queue)}` เพลง", inline=True)
        if truncated:
            embed.add_field(
                name=f"{Emojis.WARNING} Truncated",
                value=f"คิวเต็ม • เพิ่มได้สูงสุด `{MAX_QUEUE_SIZE}` เพลงเท่านั้น",
                inline=False,
            )
        embed.set_footer(
            text=f"ขอโดย {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)
        return True

    async def _handle_album(self, ctx: Context, query: str, queue: list[dict[str, Any]]) -> bool:
        """Handle a Spotify album."""
        if not self.sp:
            return False

        results = await self._api_call_with_retry(self.sp.album_tracks, query)

        if not results:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบข้อมูล Album", color=Colors.ERROR)
            await ctx.send(embed=embed)
            return False

        count = 0
        items = results.get("items", [])

        # Paginate to get all tracks (album_tracks returns max 50 per page)
        while results and results.get("next") and len(items) < self.MAX_PLAYLIST_TRACKS:
            await asyncio.sleep(self.RATE_LIMIT_DELAY)
            results = await self._api_call_with_retry(self.sp.next, results)
            if results and results.get("items"):
                items.extend(results["items"])

        # Apply cap to prevent memory issues with huge albums
        items = items[: self.MAX_PLAYLIST_TRACKS]

        if not items:
            embed = discord.Embed(description=f"{Emojis.CROSS} Album นี้ไม่มีเพลง", color=Colors.ERROR)
            await ctx.send(embed=embed)
            return False

        # Enforce queue size cap (the play command checks for non-Spotify
        # paths but the Spotify path used to bypass it). Truncate the
        # incoming album so we never exceed MAX_QUEUE_SIZE.
        from cogs.music.queue import MAX_QUEUE_SIZE

        capacity_remaining = MAX_QUEUE_SIZE - len(queue)
        truncated = False
        if capacity_remaining <= 0:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Queue is full (max {MAX_QUEUE_SIZE} tracks)",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return False
        if len(items) > capacity_remaining:
            items = items[:capacity_remaining]
            truncated = True

        for track in items:
            if track and track.get("artists") and len(track["artists"]) > 0 and track.get("name"):
                artist_name = track["artists"][0]["name"]
                track_name = track["name"]
                search_query = f"{artist_name} - {track_name} audio"
                queue.append(
                    {
                        "url": search_query,
                        "title": f"{artist_name} - {track_name}",
                        "type": "search",
                    }
                )
                count += 1

        if count == 0:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ไม่สามารถเพิ่มเพลงจาก Album ได้", color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return False

        embed = discord.Embed(
            title=f"{Emojis.CHECK} เพิ่ม Album แล้ว",
            description=f"เพิ่ม **{count}** เพลงจาก Spotify Album",
            color=Colors.SPOTIFY,
        )
        embed.add_field(name="ขนาดคิว", value=f"`{len(queue)}` เพลง", inline=True)
        if truncated:
            embed.add_field(
                name=f"{Emojis.WARNING} Truncated",
                value=f"คิวเต็ม • เพิ่มได้สูงสุด `{MAX_QUEUE_SIZE}` เพลงเท่านั้น",
                inline=False,
            )
        embed.set_footer(
            text=f"ขอโดย {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)
        return True
