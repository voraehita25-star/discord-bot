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
import shutil
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
logger = logging.getLogger(__name__)

from utils.monitoring.logger import cleanup_cache, setup_smart_logging

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

# PID file path
PID_FILE = Path("bot.pid")

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
    """Write PID file for process tracking."""
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


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
                _old_pid, proc_user, current_user,
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
    # Ensure required directories exist
    for dir_name in ("temp", "data", "logs"):
        dir_path = Path(dir_name)
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True)
            except PermissionError:
                logger.exception("Cannot create %s directory", dir_name)
                raise

    # Check for FFmpeg
    if not shutil.which("ffmpeg"):
        logger.critical(
            "❌ FFmpeg not found! Music features will not work. "
            "Please install FFmpeg and add it to PATH."
        )
        os.environ["FFMPEG_MISSING"] = "1"

    cleanup_cache()


def remove_pid() -> None:
    """Remove PID file on exit"""
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except OSError as e:
            logger.warning("Failed to remove PID file: %s", e)


atexit.register(remove_pid)

# Use config as single source of truth for token
TOKEN = settings.discord_token


# Setup Discord Bot
class MusicBot(commands.AutoShardedBot):
    """Custom Bot Class"""

    # Class attribute for start time
    start_time: float = 0.0

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
            max_workers=_thread_workers, thread_name_prefix="bot-worker",
        )
        loop.set_default_executor(self._default_executor)
        logger.info("⚡ ThreadPoolExecutor set to %d workers", _thread_workers)

        # Setup signal handlers for graceful shutdown
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig, lambda s=sig: self._schedule_shutdown(s)
                )
            logger.info("🛡️ Signal handlers registered for graceful shutdown")
        else:
            # Windows: asyncio event loop does not support add_signal_handler.
            # Fall back to signal.signal() which dispatches on the main thread only.
            # KeyboardInterrupt (Ctrl+C) is already handled via run_bot_with_confirmation.
            # Capture loop in default arg, then guard against firing after the loop is closed
            # (e.g. SIGTERM arrives between bot.run() returning and the next restart).
            def _win_sigterm(*_args: object, _loop: asyncio.AbstractEventLoop = loop) -> None:
                if _loop.is_closed():
                    return
                try:
                    asyncio.run_coroutine_threadsafe(
                        graceful_shutdown(signal.SIGTERM), _loop,
                    )
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
        # Skip utility modules and old files that have been moved to submodules
        skip_modules = ["__init__.py", "music_utils.py", "spotify_handler.py", "music.py"]

        # Load main cogs from cogs/ directory (sorted for deterministic order across platforms).
        # Sync iterdir is fine here: this runs once at startup, before the bot connects.
        cogs_dir = Path("./cogs")
        for filename in sorted(cogs_dir.iterdir()):  # noqa: ASYNC240 - startup-only, bot not yet connected
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
        if os.getenv("FFMPEG_MISSING") != "1":
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

    # Track background tasks and initialization state
    _health_task: asyncio.Task | None = None
    _metrics_started: bool = False
    _shutdown_task: asyncio.Task | None = None
    _default_executor: concurrent.futures.ThreadPoolExecutor | None = None

    def _register_bot_commands(self) -> None:
        """Register bot-level commands (called from __init__ so they survive restart)."""

        @self.command(name="sync")
        @commands.cooldown(1, 60.0, commands.BucketType.user)
        @commands.is_owner()
        async def sync_commands(ctx: commands.Context) -> None:
            """Sync slash commands globally (Owner only). 60-second cooldown per user."""
            msg = await ctx.send("⏳ Syncing commands...")
            try:
                synced = await self.tree.sync()
                await msg.edit(content=f"✅ Synced {len(synced)} commands globally.")
            except discord.HTTPException as e:
                await msg.edit(content=f"❌ Failed to sync: {e}")

        @self.command(name="health", aliases=["status", "ping"])
        @commands.is_owner()
        async def health_check(ctx: commands.Context) -> None:
            """Check bot health status (Owner only)."""
            import platform  # pylint: disable=import-outside-toplevel

            uptime_seconds = time.time() - self.start_time if self.start_time else 0
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

    def _schedule_shutdown(self, sig) -> None:
        """Schedule graceful shutdown, keeping a reference to prevent GC."""
        self._shutdown_task = asyncio.create_task(graceful_shutdown(sig))

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
            import orjson  # noqa: F401

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
                if metrics.start_server(port=9090):
                    logger.info("📊 Prometheus metrics available at http://localhost:9090")
                self._metrics_started = True

        # Start Memory Monitor (tuned for 32GB DDR5: warn 8GB, critical 16GB)
        if MEMORY_MONITOR_AVAILABLE and memory_monitor is not None:
            memory_monitor.start()
            logger.info("🧠 Memory monitor activated (warning: 8GB, critical: 16GB)")

    async def on_command_error(  # pylint: disable=arguments-differ
        self, ctx: commands.Context, error: commands.CommandError,
    ) -> None:
        """Global error handler for all commands with Thai messages."""
        # Ignore command not found errors
        if isinstance(error, commands.CommandNotFound):
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
            logger.warning("Could not send error message to channel %s (Error ID: %s)", ctx.channel, error_id)

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        """Global error handler for slash (app) commands with Thai messages."""
        error_id = uuid.uuid4().hex[:6].upper()
        logger.error("App command error in %s (Error ID: %s): %s", interaction.command, error_id, error)

        # Determine the response method (followup if already responded/deferred)
        async def respond(content: str) -> None:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(content, ephemeral=True)
                else:
                    await interaction.response.send_message(content, ephemeral=True)
            except discord.HTTPException:
                logger.warning("Could not send app command error to interaction (Error ID: %s)", error_id)

        original = getattr(error, "original", error)

        if isinstance(original, discord.app_commands.MissingPermissions):
            missing = ", ".join(original.missing_permissions)
            await respond(f"❌ **ไม่มีสิทธิ์**\nคุณต้องมีสิทธิ์ `{missing}` เพื่อใช้คำสั่งนี้")
        elif isinstance(original, discord.app_commands.BotMissingPermissions):
            missing = ", ".join(original.missing_permissions)
            await respond(f"❌ **บอทไม่มีสิทธิ์เพียงพอ**\nกรุณาให้สิทธิ์ `{missing}` แก่บอท")
        elif isinstance(original, discord.app_commands.CommandOnCooldown):
            await respond(f"⏳ **กรุณารอสักครู่**\nคำสั่งนี้จะพร้อมใช้อีกครั้งใน `{original.retry_after:.1f}` วินาที")
        else:
            await respond(f"❌ **เกิดข้อผิดพลาด**\nกรุณาลองใหม่อีกครั้ง\n🔖 Error ID: `{error_id}`")

    async def on_message(self, message: discord.Message) -> None:
        """Track messages for metrics."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Track message in metrics
        if METRICS_AVAILABLE and metrics:
            if message.content.startswith("!"):
                metrics.increment_messages("command")
            else:
                metrics.increment_messages("other")

        # Process commands
        await self.process_commands(message)

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
        command_prefix="!", intents=intents, help_command=None,
        allowed_mentions=safe_mentions,
    )
    new_bot._register_bot_commands()
    return new_bot


# Global bot instance (module-level for health hooks; recreated on restart)
bot = create_bot()
bot.start_time = time.time()

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
    # Basic length check (tokens are usually 59+ chars)
    return len(token) >= 50


async def graceful_shutdown(sig: signal.Signals | None = None) -> None:
    """Gracefully shutdown the bot"""
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

    # Cancel health task if running
    if bot._health_task is not None and not bot._health_task.done():
        bot._health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot._health_task
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

    # Close bot connection
    if not bot.is_closed():
        await bot.close()

    # Shut down the custom default executor if one was installed
    exec_ref = getattr(bot, "_default_executor", None)
    if exec_ref is not None:
        try:
            exec_ref.shutdown(wait=False, cancel_futures=True)  # type: ignore[attr-defined]
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
            bot.run(token)
            break  # Normal exit
        except KeyboardInterrupt:
            if confirm_shutdown():
                logger.info("🛑 Bot stopped by user (Ctrl+C)")
                # Run graceful shutdown on any platform where no running loop exists yet.
                # bot.run() has already returned so its internal loop is closed; a fresh
                # asyncio.run() is safe here.
                try:
                    asyncio.run(graceful_shutdown())
                except RuntimeError as e:
                    logger.warning("Skipping graceful_shutdown (%s)", e)
                except Exception:
                    logger.exception("Error during shutdown")
                break
            else:
                logger.info("✅ Resuming bot operation...")
                # Explicitly close old bot to free connections/tasks
                old_bot = bot
                try:
                    if not old_bot.is_closed():
                        asyncio.run(old_bot.close())
                except RuntimeError as e:
                    # Loop still running in rare re-entrance scenarios - skip
                    logger.warning("Could not close old bot instance: %s", e)
                except Exception:
                    logger.exception("Error closing old bot instance")
                # Re-read token in case .env was updated
                load_dotenv(override=True)
                token = os.getenv("DISCORD_TOKEN")
                # Recreate bot instance for restart
                bot = create_bot()
                bot.start_time = time.time()
                # Re-setup health hooks for new instance
                if HEALTH_API_AVAILABLE and setup_health_hooks is not None:
                    setup_health_hooks(bot)  # type: ignore[arg-type]
                continue


if __name__ == "__main__":
    # Mark that we are running as the bot so config.__post_init__ creates directories.
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

    # Log feature flags summary
    logger.info("📋 Feature Status:\n%s", feature_flags.summary())
    # Register additional runtime features
    feature_flags.register("ffmpeg", os.environ.get("FFMPEG_MISSING") != "1")
    feature_flags.register("spotify", bool(settings.spotipy_client_id))

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
