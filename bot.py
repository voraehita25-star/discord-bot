"""
Main Discord Bot Entry Point
Handles initialization, startup checks, and main loop.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import logging
import os
import signal
import sys
import time
import traceback
import uuid
from pathlib import Path

import discord
import psutil
from discord.ext import commands
from dotenv import load_dotenv

# Load .env EARLY - before any modules that might use env vars
load_dotenv()

# Module logger — declared before the optional-import blocks below use it.
# setup_smart_logging() below wires up handlers; until then this logger
# delegates to the root logger's default config.
from utils.monitoring.logger import cleanup_cache, setup_smart_logging

logger = logging.getLogger(__name__)

# Import Health API
try:
    from utils.monitoring.health_api import (
        health_data,
        setup_health_hooks,
        start_health_api,
        stop_health_api,
        update_health_loop,
    )

    HEALTH_API_AVAILABLE = True
except ImportError:
    HEALTH_API_AVAILABLE = False
    health_data = None  # type: ignore
    setup_health_hooks = None  # type: ignore
    start_health_api = None  # type: ignore
    stop_health_api = None  # type: ignore
    update_health_loop = None  # type: ignore
    logger.warning("Health API not available")

# Import Dashboard WebSocket Server
try:
    from cogs.ai_core.api.ws_dashboard import (
        start_dashboard_ws_server,
        stop_dashboard_ws_server,
    )

    DASHBOARD_WS_AVAILABLE = True
except ImportError:
    DASHBOARD_WS_AVAILABLE = False
    start_dashboard_ws_server = None  # type: ignore[assignment]
    stop_dashboard_ws_server = None  # type: ignore[assignment]
    logger.warning("Dashboard WebSocket server not available")

# Import Metrics for monitoring
try:
    from utils.monitoring.metrics import metrics

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    metrics = None  # type: ignore[assignment]

# Import Sentry
try:
    from utils.monitoring.sentry_integration import capture_exception, init_sentry

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    capture_exception = None  # type: ignore[assignment]
    # ``init_sentry`` was previously left as a free name in this branch,
    # which would NameError if the code at the bottom of the module ever
    # changed evaluation order. Stub it consistently with the other
    # optional dependencies.
    init_sentry = None  # type: ignore[assignment]

# Import Self-Healer for smart duplicate detection
try:
    from utils.reliability.self_healer import SelfHealer

    SELF_HEALER_AVAILABLE = True
except ImportError:
    SELF_HEALER_AVAILABLE = False
    SelfHealer = None  # type: ignore
    logger.warning("Self-Healer not available - using basic duplicate detection")

# Import Memory Monitor (tuned for 32GB DDR5)
try:
    from utils.reliability.memory_manager import memory_monitor

    MEMORY_MONITOR_AVAILABLE = True
except ImportError:
    MEMORY_MONITOR_AVAILABLE = False
    memory_monitor = None  # type: ignore
    logger.warning("Memory Monitor not available")

# ==================== Feature Flags Registry ====================
# Imported here (after load_dotenv) so BotSettings reads env vars correctly.
from config import feature_flags, settings

feature_flags.register("health_api", HEALTH_API_AVAILABLE)
feature_flags.register("dashboard_ws", DASHBOARD_WS_AVAILABLE)
feature_flags.register("metrics", METRICS_AVAILABLE)
feature_flags.register("sentry", SENTRY_AVAILABLE)
feature_flags.register("self_healer", SELF_HEALER_AVAILABLE)

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        # AttributeError: stream doesn't support reconfigure (older Python / non-TextIOWrapper)
        # OSError: stream is not a TTY (redirected/piped)
        pass

# Initialize Logging
setup_smart_logging()

# PID file path — anchored to this file's directory so it's stable across
# launchers that change CWD (systemd, dashboard wrapper, IDE run configs).
# A relative ``Path("bot.pid")`` would silently put the file under the
# launcher's CWD and break duplicate-instance detection on next startup.
PID_FILE = Path(__file__).resolve().parent / "bot.pid"

# Read old PID before overwriting (for duplicate detection)
_old_pid: int | None = None
if PID_FILE.exists():
    try:
        _old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        if _old_pid == os.getpid():
            _old_pid = None  # Same process, no conflict
    except (ValueError, OSError):
        _old_pid = None


# Write current PID only when running as main script
# (not on import from tests/scripts)
def _write_pid_file() -> None:
    """Write PID file for process tracking.

    Uses tmp + ``os.replace`` so two startups racing past the duplicate-PID
    check can't tear-write each other's PID — replace is atomic on the same
    filesystem on both POSIX and Windows.
    """
    tmp_path = PID_FILE.with_suffix(PID_FILE.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(str(os.getpid()), encoding="utf-8")
    tmp_path.replace(PID_FILE)


def smart_startup_check() -> bool:
    """Use Self-Healer for intelligent startup check"""
    if SELF_HEALER_AVAILABLE and SelfHealer is not None:
        print(f"\n{'=' * 60}")
        print("  [BOT] Self-Healer Active")
        print(f"{'=' * 60}")

        healer = SelfHealer("bot.py")

        # Run diagnosis first
        diagnosis = healer.diagnose()

        if diagnosis["issues"]:
            print(f"  [!] Found {len(diagnosis['issues'])} issue(s):")
            for issue in diagnosis["issues"]:
                print(f"      - {issue['description']}")
            print("  [*] Auto-healing...")

            # Auto-heal
            results = healer.auto_heal(aggressive=False)

            if results["success"]:
                print(f"  [OK] {results['summary']}")
            else:
                print(f"  [!] Partial fix: {results['summary']}")
        else:
            print("  [OK] System healthy - No issues found")

        print(f"{'=' * 60}\n")
        return True

    # Fallback to basic check
    return basic_startup_check()


def basic_startup_check() -> bool:
    """Basic duplicate check (fallback).

    Security: only terminates processes owned by the current user AND whose cmdline
    unambiguously looks like this bot entry point.
    """
    if _old_pid is None or not psutil.pid_exists(_old_pid):
        return True
    try:
        proc = psutil.Process(_old_pid)
        # Ownership check - never kill another user's process
        try:
            current_user = psutil.Process().username()
            proc_user = proc.username()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return True
        if proc_user != current_user:
            logger.warning(
                "Old PID %s is owned by %s (current user %s); refusing to terminate",
                _old_pid,
                proc_user,
                current_user,
            )
            return True

        # Script path check - resolve argv to an absolute path instead of substring match
        try:
            argv = proc.cmdline()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return True

        bot_script = Path(__file__).resolve()
        is_bot = False
        for token in argv:
            try:
                candidate = Path(token).resolve()
            except (OSError, ValueError):
                continue
            if candidate == bot_script:
                is_bot = True
                break

        if not is_bot:
            return True

        print(f"\n{'=' * 60}")
        print(f"  [!] Found existing bot (PID: {_old_pid})")
        print("  [*] Stopping old instance...")
        print(f"{'=' * 60}")

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()

        if PID_FILE.exists():
            with contextlib.suppress(OSError):
                PID_FILE.unlink()

        time.sleep(1)
        print("  [OK] Ready to start\n")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return True


# NOTE: smart_startup_check() is called in __main__ block only,
# to avoid running side effects (killing processes) on import.


def bootstrap() -> None:
    """Run one-time startup side effects (directories, FFmpeg check, cache cleanup).

    Called from __main__ to avoid side effects on import (e.g. during tests).
    """
    # Ensure required directories exist — use the project-root-anchored paths
    # from settings, NOT the launcher CWD. systemd/dashboard/IDE configs may
    # start us from another directory (same reason PID_FILE is anchored), and
    # components write via settings.temp_dir/data_dir/logs_dir.
    for dir_path in (Path(settings.temp_dir), Path(settings.data_dir), Path(settings.logs_dir)):
        try:
            # exist_ok=True keeps this race-safe if the dir appears between
            # the check and the call (e.g. a concurrent creator); matches config.py.
            dir_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.exception("Cannot create %s directory", dir_path)
            raise

    # Check for FFmpeg — honour FFMPEG_PATH and the bundled ./ffmpeg/bin
    # before falling back to system PATH so installs that ship a vendored
    # binary work without polluting the OS PATH.
    from utils.media import get_ffmpeg_executable, is_ffmpeg_available

    if not is_ffmpeg_available():
        logger.critical(
            "❌ FFmpeg not found! Music features will not work. "
            "Set FFMPEG_PATH in .env, drop a binary at ./ffmpeg/bin/ffmpeg.exe, "
            "or install FFmpeg and add it to PATH."
        )
        global _FFMPEG_MISSING
        _FFMPEG_MISSING = True
    else:
        logger.info("FFmpeg resolved to: %s", get_ffmpeg_executable())

    cleanup_cache()


def remove_pid() -> None:
    """Remove PID file on exit — only when it belongs to this process.

    bot.py is imported by tests and tooling; atexit fires in every importing
    process, so an unconditional unlink let any of them delete the *live*
    bot's PID file on exit, breaking duplicate-instance detection on the
    next startup.
    """
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError as e:
        logger.warning("Failed to remove PID file: %s", e)


atexit.register(remove_pid)

# Module-level flag set by ``bootstrap()`` when FFmpeg can't be resolved.
# Replaces the previous ``os.environ["FFMPEG_MISSING"] = "1"`` pattern which
# leaked the flag into every child process (subprocess spawns, etc.) — this
# bool is local to the running interpreter only.
_FFMPEG_MISSING: bool = False


def _is_ffmpeg_missing() -> bool:
    """Return whether bootstrap() flagged FFmpeg as unavailable."""
    return _FFMPEG_MISSING


# Use config as single source of truth for token
TOKEN = settings.discord_token


# Setup Discord Bot
class MusicBot(commands.AutoShardedBot):
    """Custom Bot Class"""

    # Class attribute for start time
    start_time: float = 0.0

    # Track background tasks and initialization state.
    # Declared up here so setup_hook (and the rest of the class) sees the
    # default values before any instance is constructed — previously these
    # were declared after setup_hook in the source order, which worked at
    # runtime but read confusingly.
    _health_task: asyncio.Task | None = None
    _metrics_started: bool = False
    _shutdown_task: asyncio.Task | None = None
    _default_executor: concurrent.futures.ThreadPoolExecutor | None = None

    async def setup_hook(self) -> None:
        # Optimize thread pool based on CPU count (default: 2x cores, min 8).
        # When running inside a container with CPU limits, prefer the cgroup-aware
        # len(os.sched_getaffinity(0)) (Linux) over os.cpu_count() (which reports host CPUs).
        if hasattr(os, "sched_getaffinity"):
            available = len(os.sched_getaffinity(0)) or (os.cpu_count() or 4)
        else:
            available = os.cpu_count() or 4
        _thread_workers = max(8, available * 2)
        loop = asyncio.get_running_loop()
        # Keep a reference so we can shut it down cleanly during graceful_shutdown.
        self._default_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=_thread_workers,
            thread_name_prefix="bot-worker",
        )
        loop.set_default_executor(self._default_executor)
        logger.info("⚡ ThreadPoolExecutor set to %d workers", _thread_workers)

        # Setup signal handlers for graceful shutdown
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda s=sig: self._schedule_shutdown(s))
            logger.info("🛡️ Signal handlers registered for graceful shutdown")
        else:
            # Windows: asyncio event loop does not support add_signal_handler.
            # Fall back to signal.signal() which dispatches on the main thread only.
            # KeyboardInterrupt (Ctrl+C) is already handled via run_bot_with_confirmation.
            # Capture loop in default arg, then guard against firing after the loop is closed
            # (e.g. SIGTERM arrives between bot.run() returning and the next restart).
            def _win_sigterm(
                *_args: object,
                _loop: asyncio.AbstractEventLoop = loop,
                _self: MusicBot = self,
            ) -> None:
                if _loop.is_closed():
                    return
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        # Pin teardown to the instance whose setup_hook registered
                        # this handler (matches the Unix _schedule_shutdown path),
                        # not the module-level global which a resume may rebind.
                        graceful_shutdown(signal.SIGTERM, bot_instance=_self),
                        _loop,
                    )

                    def _swallow(f: concurrent.futures.Future[None]) -> None:
                        # Mirror the Unix _schedule_shutdown _swallow callback:
                        # swallow cancellation noise but log a real exception so a
                        # failed graceful_shutdown doesn't disappear silently.
                        if f.cancelled():
                            return
                        exc = f.exception()
                        if exc is not None:
                            logger.warning("Windows SIGTERM shutdown ended with: %s", exc)

                    fut.add_done_callback(_swallow)
                except RuntimeError:
                    # Loop closed concurrently between is_closed() and submit
                    pass

            try:
                signal.signal(signal.SIGTERM, _win_sigterm)
                logger.info("🛡️ Signal handler registered (Windows SIGTERM best-effort)")
            except (ValueError, OSError):
                # May fail if not called from main thread - acceptable.
                pass

        # Load Cogs
        # Skip utility modules and old files that have been moved to submodules.
        # ``music.py`` is no longer a flat file (now ``cogs/music/``), so it
        # would never appear in ``cogs_dir.iterdir()`` results that match
        # ``.py`` — kept here only as documentation that this name was
        # previously a sibling cog. Future cleanup: remove if/when the
        # historical context becomes irrelevant.
        skip_modules = ["__init__.py", "music_utils.py", "spotify_handler.py"]

        # Load main cogs from cogs/ directory (sorted for deterministic order across platforms).
        # Sync iterdir is fine here: this runs once at startup, before the bot connects.
        # Anchor to bot.py's directory so a launcher with a different CWD (systemd,
        # dashboard wrapper, tests) still finds the cogs dir.
        cogs_dir = Path(__file__).resolve().parent / "cogs"
        for filename in sorted(cogs_dir.iterdir()):
            if filename.suffix == ".py":
                # Skip utility modules
                if filename.name in skip_modules:
                    continue

                extension = f"cogs.{filename.stem}"
                try:
                    await self.load_extension(extension)
                    logger.info("✅ Loaded Extension: %s", extension)
                except commands.ExtensionError:
                    logger.exception("❌ Failed to load %s", extension)

        # Load Music cog from music submodule
        if not _is_ffmpeg_missing():
            try:
                await self.load_extension("cogs.music")
                logger.info("✅ Loaded Extension: cogs.music")
            except commands.ExtensionError:
                logger.exception("❌ Failed to load cogs.music")
        else:
            logger.warning("⚠️ Skipping music cog because FFmpeg is missing.")

        # Load AI cog from ai_core subdirectory
        try:
            await self.load_extension("cogs.ai_core.ai_cog")
            logger.info("✅ Loaded Extension: cogs.ai_core.ai_cog")
        except commands.ExtensionError:
            logger.exception("❌ Failed to load cogs.ai_core.ai_cog")

        # Start Dashboard WebSocket Server for AI Chat (start early in setup)
        if DASHBOARD_WS_AVAILABLE and start_dashboard_ws_server is not None:
            try:
                success = await start_dashboard_ws_server()
                if success:
                    logger.info("💬 Dashboard AI Chat WebSocket server started")
                else:
                    logger.warning("⚠️ Failed to start Dashboard WebSocket server")
            except Exception:
                logger.exception("❌ Dashboard WebSocket server error")

    def _register_bot_commands(self) -> None:
        """Register bot-level commands (called from create_bot() after construction;
        re-runs on each restart so the commands are re-registered)."""

        @self.command(name="sync")
        @commands.cooldown(1, 60.0, commands.BucketType.user)
        @commands.is_owner()
        async def sync_commands(ctx: commands.Context) -> None:
            """Sync slash commands globally (Owner only). 60-second cooldown per user."""
            msg = await ctx.send("⏳ Syncing commands...")
            try:
                synced = await self.tree.sync()
            except discord.HTTPException as e:
                with contextlib.suppress(discord.HTTPException):
                    await msg.edit(content=f"❌ Failed to sync: {e}")
                return
            with contextlib.suppress(discord.HTTPException):
                await msg.edit(content=f"✅ Synced {len(synced)} commands globally.")

        @self.command(name="health", aliases=["status", "ping"])
        @commands.is_owner()
        async def health_check(ctx: commands.Context) -> None:
            """Check bot health status (Owner only)."""
            import platform  # pylint: disable=import-outside-toplevel

            uptime_seconds = time.monotonic() - self.start_time if self.start_time else 0
            hours, remainder = divmod(int(uptime_seconds), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"

            embed = discord.Embed(title="🏥 Bot Health Check", color=0x00FF00)
            embed.add_field(name="🏓 Latency", value=f"{self.latency * 1000:.0f}ms", inline=True)
            embed.add_field(name="🌐 Guilds", value=str(len(self.guilds)), inline=True)
            embed.add_field(name="🎤 Voice", value=str(len(self.voice_clients)), inline=True)
            embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
            embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
            embed.add_field(name="📦 Discord.py", value=discord.__version__, inline=True)

            memory_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            embed.add_field(name="💾 Memory", value=f"{memory_mb:.1f} MB", inline=True)

            await ctx.send(embed=embed)

    def _schedule_shutdown(self, sig: signal.Signals) -> None:
        """Schedule graceful shutdown, keeping a reference to prevent GC.

        Passes ``self`` so graceful_shutdown tears down THIS bot instance
        even if the module-level `bot` global has been rebound (e.g. after
        a "no, resume" answer to the Ctrl+C prompt rebuilt the bot).
        """
        # Cancel any earlier in-flight shutdown task — re-issuing the signal
        # shouldn't drop the original task on the floor.
        prev = self._shutdown_task
        if prev is not None and not prev.done():
            prev.cancel()

            def _swallow(t: asyncio.Task) -> None:
                # Swallow the cancellation noise but log a real exception
                # so a failed prior shutdown doesn't disappear silently.
                if t.cancelled():
                    return
                exc = t.exception()
                if exc is not None:
                    logger.warning("Previous shutdown task ended with: %s", exc)

            prev.add_done_callback(_swallow)
        self._shutdown_task = asyncio.create_task(graceful_shutdown(sig, bot_instance=self))

    @staticmethod
    def _on_health_task_done(task: asyncio.Task) -> None:
        """Callback when health loop task completes unexpectedly."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Health loop task failed: %s", exc)

    async def on_ready(self) -> None:
        """Called when bot is ready and connected to Discord"""
        # Set custom activity/status
        activity = discord.Activity(
            type=discord.ActivityType.listening, name="🎵 !play | 🤖 AI Chat"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
        logger.info("🤖 %s is Online and Ready!", self.user)
        logger.info("📊 Connected to %d guilds", len(self.guilds))

        # Log performance optimizations status
        perf_status = []
        # Check for orjson
        try:
            import orjson  # noqa: F401 - import-for-availability check

            perf_status.append("orjson")
        except ImportError:
            pass
        if perf_status:
            logger.info("⚡ Performance optimizations active: %s", ", ".join(perf_status))

        # Start Health API background update loop (only once, guard against repeated on_ready)
        if HEALTH_API_AVAILABLE and health_data is not None and update_health_loop is not None:
            health_data.update_from_bot(self)  # type: ignore[arg-type]
            if self._health_task is None or self._health_task.done():
                self._health_task = asyncio.create_task(update_health_loop(self, interval=10.0))  # type: ignore[arg-type]
                self._health_task.add_done_callback(self._on_health_task_done)

        # Initialize metrics (only once, guard against repeated on_ready)
        if METRICS_AVAILABLE and metrics:
            metrics.set_guilds(len(self.guilds))
            metrics.set_voice_clients(len(self.voice_clients))
            metrics.set_memory(psutil.Process().memory_info().rss)
            if not self._metrics_started:
                # Allow deploys to override via PROMETHEUS_PORT; falls back to 9090.
                try:
                    metrics_port = int(os.getenv("PROMETHEUS_PORT", "9090"))
                except ValueError:
                    logger.warning(
                        "Invalid PROMETHEUS_PORT=%r — falling back to 9090",
                        os.getenv("PROMETHEUS_PORT"),
                    )
                    metrics_port = 9090
                if metrics.start_server(port=metrics_port):
                    logger.info(
                        "📊 Prometheus metrics available at http://localhost:%d", metrics_port
                    )
                self._metrics_started = True

        # Start Memory Monitor (tuned for 32GB DDR5: warn 8GB, critical 16GB)
        if MEMORY_MONITOR_AVAILABLE and memory_monitor is not None:
            memory_monitor.start()
            logger.info("🧠 Memory monitor activated (warning: 8GB, critical: 16GB)")

    async def on_command_error(  # pylint: disable=arguments-differ
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        """Global error handler for all commands with Thai messages."""
        # Ignore command not found errors
        if isinstance(error, commands.CommandNotFound):
            return

        # Mirror the stock Bot.on_command_error guards: commands/cogs with a
        # local error handler own the user-facing reply. dispatch_error always
        # re-dispatches the global event after a local handler returns, so
        # without these guards every locally-handled error (e.g. !chat
        # cooldown, !play missing-perms) produced a second duplicate message.
        if ctx.command is not None and ctx.command.has_error_handler():
            return
        if ctx.cog is not None and ctx.cog.has_error_handler():
            return

        # Handle cooldown errors
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ **กรุณารอสักครู่**\nคำสั่งนี้จะพร้อมใช้อีกครั้งใน `{error.retry_after:.1f}` วินาที"
            )
            return

        # Handle missing permissions
        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions)
            await ctx.send(f"❌ **ไม่มีสิทธิ์**\nคุณต้องมีสิทธิ์ `{missing}` เพื่อใช้คำสั่งนี้")
            return

        # Handle bot missing permissions
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            await ctx.send(
                f"❌ **บอทไม่มีสิทธิ์เพียงพอ**\n"
                f"กรุณาให้สิทธิ์ `{missing}` แก่บอท\n"
                f"💡 *ลองตรวจสอบ Role ของบอทใน Server Settings*"
            )
            return

        # Handle missing required arguments
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"❌ **ขาด argument ที่จำเป็น**\n"
                f"ต้องระบุ: `{error.param.name}`\n"
                f"💡 *ลองใช้ `!help {ctx.command}` เพื่อดูวิธีใช้*"
            )
            return

        # Handle bad arguments
        if isinstance(error, commands.BadArgument):
            await ctx.send(
                f"❌ **รูปแบบไม่ถูกต้อง**\nรายละเอียด: {error}\n💡 *ตรวจสอบค่าที่ใส่และลองใหม่อีกครั้ง*"
            )
            return

        # Handle check failures (e.g., is_owner, has_role)
        if isinstance(error, commands.CheckFailure):
            await ctx.send("🔒 **คำสั่งนี้ถูกจำกัดการใช้งาน**\n💡 *คุณอาจไม่มีสิทธิ์หรือต้องใช้ในช่องที่กำหนดเท่านั้น*")
            return

        # Log other errors
        error_id = uuid.uuid4().hex[:6].upper()
        logger.error(
            "Command error in %s (Error ID: %s): %s\n%s",
            ctx.command,
            error_id,
            error,
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )

        # Track error in metrics
        if METRICS_AVAILABLE and metrics:
            metrics.increment_commands(str(ctx.command), success=False)

        # Send to Sentry (without message content to prevent PII leak)
        if SENTRY_AVAILABLE and capture_exception is not None:
            capture_exception(
                error,
                context={
                    "command": str(ctx.command),
                    "channel": str(ctx.channel),
                    "error_id": error_id,
                },
                user_id=ctx.author.id if ctx.author else None,
                guild_id=ctx.guild.id if ctx.guild else None,
            )

        # Send generic error message with unique reference
        try:
            await ctx.send(
                f"❌ **เกิดข้อผิดพลาด**\nกรุณาลองใหม่อีกครั้ง หากยังมีปัญหา ติดต่อ Admin\n🔖 Error ID: `{error_id}`"
            )
        except discord.HTTPException:
            logger.warning(
                "Could not send error message to channel %s (Error ID: %s)", ctx.channel, error_id
            )

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ) -> None:
        """Global error handler for slash (app) commands with Thai messages."""
        error_id = uuid.uuid4().hex[:6].upper()
        logger.error(
            "App command error in %s (Error ID: %s): %s", interaction.command, error_id, error
        )

        # Track error in metrics (interaction.command can be None for
        # command-not-found / sync-mismatch failures).
        if METRICS_AVAILABLE and metrics and interaction.command is not None:
            metrics.increment_commands(str(interaction.command.qualified_name), success=False)

        # Determine the response method (followup if already responded/deferred)
        async def respond(content: str) -> None:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(content, ephemeral=True)
                else:
                    await interaction.response.send_message(content, ephemeral=True)
            except discord.HTTPException:
                logger.warning(
                    "Could not send app command error to interaction (Error ID: %s)", error_id
                )

        original = getattr(error, "original", error)

        if isinstance(original, discord.app_commands.MissingPermissions):
            missing = ", ".join(original.missing_permissions)
            await respond(f"❌ **ไม่มีสิทธิ์**\nคุณต้องมีสิทธิ์ `{missing}` เพื่อใช้คำสั่งนี้")
        elif isinstance(original, discord.app_commands.BotMissingPermissions):
            missing = ", ".join(original.missing_permissions)
            await respond(f"❌ **บอทไม่มีสิทธิ์เพียงพอ**\nกรุณาให้สิทธิ์ `{missing}` แก่บอท")
        elif isinstance(original, discord.app_commands.CommandOnCooldown):
            await respond(
                f"⏳ **กรุณารอสักครู่**\nคำสั่งนี้จะพร้อมใช้อีกครั้งใน `{original.retry_after:.1f}` วินาที"
            )
        else:
            # Send to Sentry (without message content to prevent PII leak).
            # Only non-user-facing errors reach this branch — the handled
            # permission/cooldown cases above are expected, not crashes.
            if SENTRY_AVAILABLE and capture_exception is not None:
                capture_exception(
                    original,
                    context={
                        "command": (
                            interaction.command.qualified_name
                            if interaction.command is not None
                            else None
                        ),
                        "error_id": error_id,
                    },
                    user_id=interaction.user.id,
                    guild_id=interaction.guild_id,
                )
            await respond(f"❌ **เกิดข้อผิดพลาด**\nกรุณาลองใหม่อีกครั้ง\n🔖 Error ID: `{error_id}`")

    async def on_message(self, message: discord.Message) -> None:
        """Track messages for metrics."""
        # Ignore bot messages (own + other bots/webhooks).
        if message.author.bot:
            return

        # Resolve the command context once. process_commands() would call
        # get_context() again internally, so we classify metrics from this ctx
        # and invoke(ctx) directly — avoiding a second prefix-parse/command-
        # lookup on every non-bot message (author.bot is already guarded above).
        ctx = await self.get_context(message)

        # Track message in metrics. Only count as a "command" if the
        # prefix-stripped content actually resolves to a registered
        # command — previously every "!" prefix incremented even when
        # the command didn't exist or was rejected, skewing metrics.
        if METRICS_AVAILABLE and metrics:
            if ctx.valid and ctx.command is not None:
                metrics.increment_messages("command")
            else:
                metrics.increment_messages("other")

        # Process the resolved command (equivalent to process_commands minus the
        # redundant author.bot re-check and second get_context).
        await self.invoke(ctx)

    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Track successful prefix command execution."""
        if METRICS_AVAILABLE and metrics:
            metrics.increment_commands(str(ctx.command), success=True)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        """Track successful slash / context-menu command execution."""
        del interaction  # only used by overrides; kept to satisfy the signature
        if METRICS_AVAILABLE and metrics:
            metrics.increment_commands(str(command.qualified_name), success=True)


def create_bot() -> MusicBot:
    """Create a new bot instance with all commands registered."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True  # Enable members intent for AI features
    # Prevent AI-generated text from triggering mass pings
    safe_mentions = discord.AllowedMentions(
        everyone=False, roles=False, users=True, replied_user=True
    )
    new_bot = MusicBot(
        command_prefix="!",
        intents=intents,
        help_command=None,
        allowed_mentions=safe_mentions,
    )
    new_bot._register_bot_commands()
    # Route CommandTree errors through the slash-command handler. discord.py
    # never dispatches an "app_command_error" client event — app command
    # failures go exclusively to CommandTree.on_error — so without this
    # assignment on_app_command_error is dead code and slash users get no
    # error feedback at all.
    new_bot.tree.on_error = new_bot.on_app_command_error
    return new_bot


# Global bot instance (module-level for health hooks; recreated on restart)
bot = create_bot()
# Use monotonic clock for uptime — wall-clock can jump backwards on NTP sync.
bot.start_time = time.monotonic()

# Setup Health API hooks
if HEALTH_API_AVAILABLE and setup_health_hooks is not None:
    setup_health_hooks(bot)  # type: ignore[arg-type]


def validate_token(token: str | None) -> bool:
    """Validate Discord token format"""
    if not token:
        return False
    # Discord tokens have 3 parts separated by dots
    # Format: base64.base64.base64
    if token == "your_token_here":
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    # Each of the 3 segments must be non-empty — a stronger structural
    # invariant than a bare global-length heuristic, and it rejects
    # malformed "a..b" / ".x.y" tokens that a length check alone passes.
    if not all(parts):
        return False
    # Length floor: keep out truncated/garbage strings while still accepting
    # valid legacy (v1) bot tokens, which run ~59 chars — Discord does not
    # formally guarantee a 70-char minimum, so 70 false-rejected real tokens.
    return len(token) >= 59


async def graceful_shutdown(
    sig: signal.Signals | None = None,
    bot_instance: MusicBot | None = None,
) -> None:
    """Gracefully shutdown the bot.

    `bot_instance` lets the caller pin the exact bot we should be tearing
    down — important after run_bot_with_confirmation() recreates the global
    `bot`, otherwise we'd close the new instance and leak resources from
    the old one.
    """
    bot = bot_instance if bot_instance is not None else globals().get("bot")
    if bot is None:
        logger.warning("graceful_shutdown invoked with no bot instance; skipping")
        return
    if sig:
        logger.info("🛑 Received signal %s, shutting down gracefully...", sig.name)
    else:
        logger.info("🛑 Shutting down gracefully...")

    # Stop Dashboard WebSocket Server
    if DASHBOARD_WS_AVAILABLE and stop_dashboard_ws_server is not None:
        try:
            await stop_dashboard_ws_server()
            logger.info("💬 Dashboard WebSocket server stopped")
        except Exception:
            logger.exception("Error stopping Dashboard WebSocket server")

    # Cancel health task if running. Use ``getattr`` rather than direct
    # private-attribute access so the shutdown path tolerates Mock/test
    # bots that don't define ``_health_task`` (real code attaches it, but
    # graceful_shutdown is called from many tests with custom doubles).
    _health_task = getattr(bot, "_health_task", None)
    if _health_task is not None and not _health_task.done():
        _health_task.cancel()
        # Awaiting a cancelled task can re-raise non-cancel exceptions
        # that were stored before the cancel landed. Suppress both so the
        # shutdown path doesn't crash on a stale exception from a task
        # that died seconds before signal arrived.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _health_task
        logger.info("🛑 Health loop task cancelled")

    # Flush pending database exports before closing
    try:
        from utils.database import db

        if db is not None:
            await db.flush_pending_exports()
            await db.close_pool()
            logger.info("💾 Database exports flushed and connection pool closed")
    except ImportError:
        pass  # Database module not available
    except Exception:
        logger.exception("Error flushing database exports")

    # Close shared URL fetcher session
    try:
        from utils.web.url_fetcher import close_shared_session

        await close_shared_session()
        logger.info("🌐 URL fetcher session closed")
    except ImportError:
        pass
    except Exception:
        logger.exception("Error closing URL fetcher session")

    # Close alert manager session
    try:
        from utils.monitoring.alerting import alert_manager

        await alert_manager.close()
    except ImportError:
        pass
    except Exception:
        logger.exception("Error closing alert manager")

    # Stop the memory monitor task — without this the monitor coroutine
    # holds a reference to the bot graph and survives ``bot.close()`` until
    # the interpreter exits, blocking GC of cogs/sessions/locks. Hot
    # reloads compounded the leak.
    try:
        from utils.reliability.memory_manager import memory_monitor

        if hasattr(memory_monitor, "astop"):
            await memory_monitor.astop()
        elif hasattr(memory_monitor, "stop"):
            memory_monitor.stop()
    except ImportError:
        pass
    except Exception:
        logger.exception("Error stopping memory monitor")

    # Stop the webhook cache cleanup loop. ``start_webhook_cache_cleanup``
    # is wired via the AI cog but ``stop_webhook_cache_cleanup`` was never
    # called from anywhere — every clean shutdown emitted "Task was
    # destroyed but it is pending!" warnings.
    try:
        from cogs.ai_core.response.webhook_cache import stop_webhook_cache_cleanup

        await stop_webhook_cache_cleanup()
    except ImportError:
        pass
    except Exception:
        logger.exception("Error stopping webhook cache cleanup")

    # Close bot connection. ``bot.is_closed()`` reflects the bot's own
    # ``_closed`` flag but that's only set after ``close()`` actually
    # completes; on the resume path the previous ``bot.run()`` may have
    # returned via Ctrl+C with the loop torn down but ``_closed`` still
    # False. Guard the close call so a freshly-closed loop doesn't
    # raise ``RuntimeError: Event loop is closed`` deep inside aiohttp.
    if not bot.is_closed():
        try:
            await bot.close()
        except RuntimeError as close_err:
            # The "Event loop is closed" / "no running event loop"
            # variants land here — shutdown is best-effort at this
            # point, so log and continue.
            logger.warning("bot.close() skipped: %s", close_err)

    # Shut down the custom default executor if one was installed
    exec_ref = getattr(bot, "_default_executor", None)
    if exec_ref is not None:
        try:
            exec_ref.shutdown(wait=False, cancel_futures=True)
            logger.info("🧵 Default thread pool executor shut down")
        except Exception:
            logger.exception("Error shutting down default executor")

    logger.info("👋 Bot shutdown complete.")


# Signal handlers are now set up in MusicBot.setup_hook() using asyncio.get_running_loop()


def confirm_shutdown() -> bool:
    """Ask user to confirm shutdown when Ctrl+C is pressed.

    In headless / non-TTY environments (systemd, docker without -it, CI) skip the
    prompt and shut down immediately — otherwise the bot would hang on input().
    """
    print()  # New line after ^C
    if not sys.stdin.isatty():
        return True
    try:
        response = input("[!] Stop the bot? (y/n): ").strip().lower()
        return response in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        # User pressed Ctrl+C again during prompt - cancel shutdown
        print("\n[OK] Cancelled - Bot continues running...")
        return False


def run_bot_with_confirmation() -> None:
    """Run the bot with Ctrl+C confirmation."""
    global bot  # pylint: disable=global-statement
    token = TOKEN
    while True:
        try:
            if not token:
                logger.critical("❌ DISCORD_TOKEN is not set")
                sys.exit(1)
            # Re-validate the token on every loop iteration. The
            # __main__ entry point validates once at startup, but on
            # resume the user may have edited ``.env`` to fix a bad
            # token — without this check, a malformed token bombs deep
            # inside discord.py with a confusing stack trace.
            if not validate_token(token):
                logger.critical(
                    "❌ Token format invalid — refusing to start. Check DISCORD_TOKEN in .env"
                )
                sys.exit(1)
            # Run the connect loop ourselves instead of bot.run(): discord.py's
            # Client.run() swallows KeyboardInterrupt internally (client.py:
            # `except KeyboardInterrupt: return`), which made the confirm/resume
            # branch below unreachable — Ctrl+C must land in *this* frame.
            _current_bot = bot

            async def _runner(_b: MusicBot = _current_bot, _token: str = token) -> None:
                async with _b:
                    await _b.start(_token)

            asyncio.run(_runner())
            break  # Normal exit
        except discord.LoginFailure as exc:
            # Bad token surfaces here rather than as a generic Exception.
            # Without this branch the LoginFailure escaped the loop to
            # the outer ``except Exception`` below, which logged and
            # exited but skipped any "retry with refreshed .env" path
            # the user might have set up. Log explicitly + exit clean.
            logger.critical(
                "❌ Discord login refused (bad token?): %s — refusing to retry",
                exc,
            )
            sys.exit(1)
        except OSError as exc:
            # Transient network failure (DNS, refused connection) at
            # gateway-connect time. ``bot.run`` re-raises these instead
            # of retrying internally. Surface clearly and exit — the
            # outer process manager (systemd / Docker / native_dashboard)
            # is in a better position to restart-with-backoff than us.
            logger.critical("❌ Network error contacting Discord: %s", exc)
            sys.exit(1)
        except KeyboardInterrupt:
            if confirm_shutdown():
                logger.info("🛑 Bot stopped by user (Ctrl+C)")
                # Run graceful shutdown on any platform where no running loop exists yet.
                # bot.run() has already returned so its internal loop is closed; a fresh
                # asyncio.run() is safe here. Pass the current bot explicitly
                # so we don't accidentally clean up a different instance if
                # the global was rebound elsewhere.
                _current_bot = bot
                try:
                    asyncio.run(graceful_shutdown(bot_instance=_current_bot))
                except RuntimeError as e:
                    logger.warning("Skipping graceful_shutdown (%s)", e)
                except Exception:
                    logger.exception("Error during shutdown")
                break
            else:
                logger.info("✅ Resuming bot operation...")
                # Tear down the previous bot fully: dashboard ws / health task /
                # DB pool / URL fetcher / alert / memory monitor / webhook cache
                # all need to be released before we spin up a fresh instance,
                # otherwise we leak loop-bound resources across the restart.
                old_bot = bot
                try:
                    asyncio.run(graceful_shutdown(bot_instance=old_bot))
                except RuntimeError as e:
                    logger.warning("Could not graceful-shutdown old bot instance: %s", e)
                except Exception:
                    logger.exception("Error during graceful shutdown of old bot instance")
                # Re-read token in case .env was updated
                load_dotenv(override=True)
                token = os.getenv("DISCORD_TOKEN") or ""
                # Recreate bot instance for restart
                bot = create_bot()
                bot.start_time = time.monotonic()
                # Re-setup health hooks for new instance
                if HEALTH_API_AVAILABLE and setup_health_hooks is not None:
                    setup_health_hooks(bot)  # type: ignore[arg-type]
                continue


if __name__ == "__main__":
    # Mark that we are running as the real bot — other modules gate side
    # effects on this (e.g. storage.py). Note: config's `settings` singleton
    # was already constructed during import, so its __post_init__ ran *before*
    # this line; directory creation is handled by bootstrap() below instead.
    os.environ["BOT_RUNNING"] = "1"

    # Run startup side effects only when executed directly (not on import)
    bootstrap()
    smart_startup_check()

    # Initialize Sentry (deferred from import time to avoid polluting prod tracking)
    if SENTRY_AVAILABLE and init_sentry is not None:
        _sentry_env = os.getenv("SENTRY_ENVIRONMENT", "production")
        init_sentry(environment=_sentry_env)

    secret_errors = settings.validate_required_secrets()
    if secret_errors:
        for err in secret_errors:
            logger.critical("❌ %s", err)
        sys.exit(1)
    secret_warnings = settings.validate_optional_secrets()
    if secret_warnings:
        for warn in secret_warnings:
            logger.warning("⚠️ %s", warn)

    # Register additional runtime features BEFORE summary so the printed
    # banner reflects ffmpeg/spotify state. Earlier ordering printed the
    # summary first, omitting these flags from the observability log even
    # though they were registered seconds later.
    feature_flags.register("ffmpeg", not _is_ffmpeg_missing())
    feature_flags.register("spotify", bool(settings.spotipy_client_id))
    logger.info("📋 Feature Status:\n%s", feature_flags.summary())

    if not validate_token(TOKEN):
        logger.critical("❌ Error: DISCORD_TOKEN is invalid or not set in .env")
        logger.critical(
            "❌ Token should be in format: XXXXXX.XXXXXX.XXXXXX (3 parts separated by dots)"
        )
        sys.exit(1)

    # Write PID file for dashboard process tracking
    _write_pid_file()

    # Start Health API server
    if HEALTH_API_AVAILABLE and start_health_api is not None:
        start_health_api()

    try:
        # Signal handlers are set up in MusicBot.setup_hook() (Unix add_signal_handler;
        # Windows best-effort SIGTERM via signal.signal).
        run_bot_with_confirmation()
    except discord.LoginFailure:
        logger.critical("❌ Invalid Discord Token! Please check your .env file.")
    except OSError as e:
        logger.critical("❌ Fatal Error: %s", e)
    finally:
        # Stop Health API on exit
        if HEALTH_API_AVAILABLE and stop_health_api is not None:
            stop_health_api()
