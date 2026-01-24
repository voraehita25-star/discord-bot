"""
Spotify Handler Module for Music Cog.
Handles Spotify link processing and track extraction with retry logic.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from collections.abc import Callable
from http.client import RemoteDisconnected
from typing import TYPE_CHECKING, Any

import discord
import spotipy
from requests.exceptions import ConnectionError as RequestsConnectionError, ReadTimeout
from spotipy.oauth2 import SpotifyClientCredentials
from urllib3.exceptions import ProtocolError

from cogs.music.utils import Colors, Emojis, format_duration

# Import Circuit Breaker for Spotify API protection
try:
    from utils.reliability.circuit_breaker import spotify_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False

if TYPE_CHECKING:
    from discord.ext.commands import Bot, Context


class SpotifyHandler:
    """Handles Spotify API interactions for the Music cog."""

    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 2  # seconds

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.sp: spotipy.Spotify | None = None
        self._setup_client()

    def _setup_client(self) -> None:
        """Initialize Spotify client with credentials from environment."""
        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")

        if client_id and client_secret:
            try:
                self.sp = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=client_id, client_secret=client_secret
                    ),
                    requests_timeout=60,  # Increased timeout for slow connections
                    retries=5,  # More built-in retries
                )
                logging.info("✅ Spotify Client Initialized")
            except (spotipy.SpotifyException, ValueError) as e:
                logging.error("❌ Spotify Init Failed: %s", e)
        else:
            logging.warning("⚠️ Spotify credentials not found. Spotify links won't work.")

    def is_available(self) -> bool:
        """Check if Spotify client is available."""
        return self.sp is not None

    async def _api_call_with_retry(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute Spotify API call with retry logic and circuit breaker protection."""
        # Check circuit breaker before making API call
        if CIRCUIT_BREAKER_AVAILABLE and not spotify_circuit.can_execute():
            logging.warning("⚡ Spotify Circuit breaker OPEN - skipping API call")
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
                result = await self.bot.loop.run_in_executor(
                    None, functools.partial(func, *captured_args, **captured_kwargs)
                )
                # Record success for circuit breaker
                if CIRCUIT_BREAKER_AVAILABLE:
                    spotify_circuit.record_success()
                return result
            except (
                RequestsConnectionError,
                ReadTimeout,
                RemoteDisconnected,
                ProtocolError,
                ConnectionResetError,
                OSError,
            ) as e:
                # Record failure for circuit breaker
                if CIRCUIT_BREAKER_AVAILABLE:
                    spotify_circuit.record_failure()

                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff: 2s, 4s, 8s
                    delay = self.RETRY_DELAY * (2**attempt)
                    logging.warning(
                        "Spotify connection error (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        self.MAX_RETRIES,
                        type(e).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)

                    # Recreate client on 2nd+ failure (token might be stale)
                    if attempt >= 1:
                        logging.info("🔄 Recreating Spotify client...")
                        self._setup_client()
                else:
                    logging.error("Spotify connection failed after %d attempts", self.MAX_RETRIES)
                    raise

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
            if "track" in query:
                return await self._handle_track(ctx, query, queue)
            elif "playlist" in query:
                return await self._handle_playlist(ctx, query, queue)
            elif "album" in query:
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

        except (spotipy.SpotifyException, RequestsConnectionError, ReadTimeout) as e:
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ข้อผิดพลาด Spotify",
                description=(
                    f"ไม่สามารถเชื่อมต่อ Spotify ได้\n```{type(e).__name__}: {str(e)[:100]}```"
                ),
                color=Colors.ERROR,
            )
            embed.set_footer(text="ลองใหม่อีกครั้ง หรือใช้ชื่อเพลงแทน")
            await ctx.send(embed=embed)
            logging.error("Spotify error: %s", e)
            return False

    async def _handle_track(self, ctx: Context, query: str, queue: list[dict[str, Any]]) -> bool:
        """Handle a single Spotify track."""
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

        duration_ms = track.get("duration_ms", 0)
        embed.add_field(name=f"{Emojis.MICROPHONE} ศิลปิน", value=artist_name, inline=True)
        album_name = album.get("name", "Unknown Album")[:25]
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
        loading_embed = discord.Embed(
            title=f"{Emojis.LOADING} กำลังโหลด Spotify Playlist",
            description="กรุณารอสักครู่...",
            color=Colors.SPOTIFY,
        )
        msg = await ctx.send(embed=loading_embed)

        def get_all_playlist_tracks(url):
            results = self.sp.playlist_tracks(url)
            tracks = results.get("items", [])
            while results.get("next"):
                results = self.sp.next(results)
                if results and results.get("items"):
                    tracks.extend(results["items"])
            return tracks

        try:
            results = await self._api_call_with_retry(get_all_playlist_tracks, query)
        except (RequestsConnectionError, ReadTimeout) as e:
            await msg.delete()
            # Send error message before re-raising so user sees what happened
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ข้อผิดพลาด Spotify",
                description=f"ไม่สามารถโหลด Playlist ได้\n```{type(e).__name__}```",
                color=Colors.ERROR,
            )
            embed.set_footer(text="ลองใหม่อีกครั้ง")
            await ctx.send(embed=embed)
            raise

        if not results or not isinstance(results, list):
            await msg.delete()
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ไม่พบเพลงใน Playlist", color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return False

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

        await msg.delete()

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
        embed.set_footer(
            text=f"ขอโดย {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)
        return True

    async def _handle_album(self, ctx: Context, query: str, queue: list[dict[str, Any]]) -> bool:
        """Handle a Spotify album."""
        results = await self._api_call_with_retry(self.sp.album_tracks, query)

        if not results:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบข้อมูล Album", color=Colors.ERROR)
            await ctx.send(embed=embed)
            return False

        count = 0
        items = results.get("items", [])
        if not items:
            embed = discord.Embed(description=f"{Emojis.CROSS} Album นี้ไม่มีเพลง", color=Colors.ERROR)
            await ctx.send(embed=embed)
            return False

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
        embed.set_footer(
            text=f"ขอโดย {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)
        return True
