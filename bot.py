"""
Main Discord Bot Entry Point
Handles initialization, startup checks, and main loop.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import hashlib
import logging
import os
import shutil
import signal
import sys
import time
import traceback
from pathlib import Path

import discord
import psutil
from discord.ext import commands
from dotenv import load_dotenv

# Load .env EARLY - before any modules that might use env vars
load_dotenv()

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
    logging.warning("Health API not available")

# Import Dashboard WebSocket Server
try:
    from cogs.ai_core.api.ws_dashboard import (
        start_dashboard_ws_server,
        stop_dashboard_ws_server,
    )

    DASHBOARD_WS_AVAILABLE = True
except ImportError:
    DASHBOARD_WS_AVAILABLE = False
    start_dashboard_ws_server = None
    stop_dashboard_ws_server = None
    logging.warning("Dashboard WebSocket server not available")

# Import Metrics for monitoring
try:
    from utils.monitoring.metrics import metrics

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    metrics = None

# Import Sentry
try:
    from utils.monitoring.sentry_integration import capture_exception, init_sentry
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    capture_exception = None

# Import Self-Healer for smart duplicate detection
try:
    from utils.reliability.self_healer import SelfHealer

    SELF_HEALER_AVAILABLE = True
except ImportError:
    SELF_HEALER_AVAILABLE = False
    SelfHealer = None  # type: ignore
    logging.warning("Self-Healer not available - using basic duplicate detection")

# Import Memory Monitor (tuned for 32GB DDR5)
try:
    from utils.reliability.memory_manager import memory_monitor

    MEMORY_MONITOR_AVAILABLE = True
except ImportError:
    MEMORY_MONITOR_AVAILABLE = False
    memory_monitor = None  # type: ignore
    logging.warning("Memory Monitor not available")

# ==================== Feature Flags Registry ====================
from config import feature_flags

feature_flags.register("health_api", HEALTH_API_AVAILABLE)
feature_flags.register("dashboard_ws", DASHBOARD_WS_AVAILABLE)
feature_flags.register("metrics", METRICS_AVAILABLE)
feature_flags.register("sentry", SENTRY_AVAILABLE)
feature_flags.register("self_healer", SELF_HEALER_AVAILABLE)

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except AttributeError:
        # Python < 3.7 fallback
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
    """Basic duplicate check (fallback)"""
    if _old_pid is not None and psutil.pid_exists(_old_pid):
        try:
            proc = psutil.Process(_old_pid)
            cmdline = " ".join(proc.cmdline()).lower()
            # Match only the exact bot.py script, not test_bot.py or similar
            if "python" in cmdline and ("bot.py" in cmdline and "test_" not in cmdline):
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

# Ensure temp directory exists
temp_dir = Path("temp")
if not temp_dir.exists():
    temp_dir.mkdir(parents=True)

# Ensure data directory exists
data_dir = Path("data")
if not data_dir.exists():
    data_dir.mkdir(parents=True)

# Check for FFmpeg
if not shutil.which("ffmpeg"):
    logging.critical(
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
            logging.warning("Failed to remove PID file: %s", e)


atexit.register(remove_pid)

# Use config as single source of truth for token
from config import settings as _config_settings

TOKEN = _config_settings.discord_token or os.getenv("DISCORD_TOKEN")


# Setup Discord Bot
class MusicBot(commands.AutoShardedBot):
    """Custom Bot Class"""

    # Class attribute for start time
    start_time: float = 0.0

    async def setup_hook(self) -> None:
        # Optimize thread pool for R7 9800X3D (8C/16T)
        import concurrent.futures
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="bot-worker")
        )
        logging.info("⚡ ThreadPoolExecutor set to 16 workers for R7 9800X3D")

        # Setup signal handlers for graceful shutdown (Unix only)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig, lambda s=sig: self._schedule_shutdown(s)
                )
            logging.info("🛡️ Signal handlers registered for graceful shutdown")

        # Load Cogs
        # Skip utility modules and old files that have been moved to submodules
        skip_modules = ["__init__.py", "music_utils.py", "spotify_handler.py", "music.py"]

        # Load main cogs from cogs/ directory
        cogs_dir = Path("./cogs")
        for filename in cogs_dir.iterdir():
            if filename.suffix == ".py":
                # Skip utility modules
                if filename.name in skip_modules:
                    continue

                extension = f"cogs.{filename.stem}"
                try:
                    await self.load_extension(extension)
                    logging.info("✅ Loaded Extension: %s", extension)
                except commands.ExtensionError as e:
                    logging.error("❌ Failed to load %s: %s", extension, e)

        # Load Music cog from music submodule
        if os.getenv("FFMPEG_MISSING") != "1":
            try:
                await self.load_extension("cogs.music")
                logging.info("✅ Loaded Extension: cogs.music")
            except commands.ExtensionError as e:
                logging.error("❌ Failed to load cogs.music: %s", e)
        else:
            logging.warning("⚠️ Skipping music cog because FFmpeg is missing.")

        # Load AI cog from ai_core subdirectory
        try:
            await self.load_extension("cogs.ai_core.ai_cog")
            logging.info("✅ Loaded Extension: cogs.ai_core.ai_cog")
        except commands.ExtensionError as e:
            logging.error("❌ Failed to load cogs.ai_core.ai_cog: %s", e)

        # Start Dashboard WebSocket Server for AI Chat (start early in setup)
        if DASHBOARD_WS_AVAILABLE and start_dashboard_ws_server:
            try:
                success = await start_dashboard_ws_server()
                if success:
                    logging.info(
                        "💬 Dashboard AI Chat WebSocket server started on ws://127.0.0.1:8765"
                    )
                else:
                    logging.warning("⚠️ Failed to start Dashboard WebSocket server")
            except Exception as e:
                logging.error("❌ Dashboard WebSocket server error: %s", e)

    # Track background tasks and initialization state
    _health_task: asyncio.Task | None = None
    _metrics_started: bool = False
    _shutdown_task: asyncio.Task | None = None

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
            logging.error("Health loop task failed: %s", exc)

    async def on_ready(self) -> None:
        """Called when bot is ready and connected to Discord"""
        # Set custom activity/status
        activity = discord.Activity(
            type=discord.ActivityType.listening, name="🎵 !play | 🤖 AI Chat"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
        logging.info("🤖 %s is Online and Ready!", self.user)
        logging.info("📊 Connected to %d guilds", len(self.guilds))

        # Log performance optimizations status
        perf_status = []
        # Check for orjson
        try:
            import orjson

            perf_status.append("orjson")
        except ImportError:
            pass
        if perf_status:
            logging.info("⚡ Performance optimizations active: %s", ", ".join(perf_status))

        # Start Health API background update loop (only once, guard against repeated on_ready)
        if HEALTH_API_AVAILABLE and health_data is not None and update_health_loop is not None:
            health_data.update_from_bot(self)  # type: ignore[union-attr]
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
                    logging.info("📊 Prometheus metrics available at http://localhost:9090")
                self._metrics_started = True

        # Start Memory Monitor (tuned for 32GB DDR5: warn 8GB, critical 16GB)
        if MEMORY_MONITOR_AVAILABLE and memory_monitor is not None:
            memory_monitor.start()
            logging.info("🧠 Memory monitor activated (warning: 8GB, critical: 16GB)")

    async def on_command_error(self, ctx, error):  # pylint: disable=arguments-differ
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
        error_id = hashlib.sha256(f"{error}{time.time()}".encode()).hexdigest()[:6].upper()
        logging.error("Command error in %s (Error ID: %s): %s", ctx.command, error_id, error)
        logging.error(
            "Full traceback (Error ID: %s): %s",
            error_id,
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )

        # Track error in metrics
        if METRICS_AVAILABLE and metrics:
            metrics.increment_commands(str(ctx.command), success=False)

        # Send to Sentry (without message content to prevent PII leak)
        if SENTRY_AVAILABLE and capture_exception:
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
            logging.warning("Could not send error message to channel %s (Error ID: %s)", ctx.channel, error_id)

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        """Global error handler for slash (app) commands with Thai messages."""
        error_id = hashlib.sha256(f"{error}{time.time()}".encode()).hexdigest()[:6].upper()
        logging.error("App command error in %s (Error ID: %s): %s", interaction.command, error_id, error)

        # Determine the response method (followup if already responded/deferred)
        async def respond(content: str) -> None:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(content, ephemeral=True)
                else:
                    await interaction.response.send_message(content, ephemeral=True)
            except discord.HTTPException:
                logging.warning("Could not send app command error to interaction (Error ID: %s)", error_id)

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

    async def on_command_completion(self, ctx) -> None:
        """Track successful command execution."""
        if METRICS_AVAILABLE and metrics:
            metrics.increment_commands(str(ctx.command), success=True)


def create_bot() -> MusicBot:
    """Create a new bot instance"""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True  # Enable members intent for AI features
    return MusicBot(command_prefix="!", intents=intents, help_command=None)


# Global bot instance
bot = create_bot()
bot.start_time = time.time()

# Setup Health API hooks
if HEALTH_API_AVAILABLE and setup_health_hooks is not None:
    setup_health_hooks(bot)  # type: ignore[arg-type]


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    """Sync slash commands globally (Owner only)."""
    msg = await ctx.send("⏳ Syncing commands...")
    try:
        synced = await bot.tree.sync()
        await msg.edit(content=f"✅ Synced {len(synced)} commands globally.")
    except discord.HTTPException as e:
        await msg.edit(content=f"❌ Failed to sync: {e}")


@bot.command(name="health", aliases=["status", "ping"])
@commands.is_owner()
async def health_check(ctx):
    """Check bot health status (Owner only)."""
    import platform  # pylint: disable=import-outside-toplevel

    # Calculate uptime
    uptime_seconds = time.time() - bot.start_time if hasattr(bot, "start_time") else 0
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"

    embed = discord.Embed(title="🏥 Bot Health Check", color=0x00FF00)
    embed.add_field(name="🏓 Latency", value=f"{bot.latency * 1000:.0f}ms", inline=True)
    embed.add_field(name="🌐 Guilds", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="🎤 Voice", value=str(len(bot.voice_clients)), inline=True)
    embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
    embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
    embed.add_field(name="📦 Discord.py", value=discord.__version__, inline=True)

    # Memory usage
    memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
    embed.add_field(name="💾 Memory", value=f"{memory_mb:.1f} MB", inline=True)

    await ctx.send(embed=embed)


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
        logging.info("🛑 Received signal %s, shutting down gracefully...", sig.name)
    else:
        logging.info("🛑 Shutting down gracefully...")

    # Stop Dashboard WebSocket Server
    if DASHBOARD_WS_AVAILABLE and stop_dashboard_ws_server:
        try:
            await stop_dashboard_ws_server()
            logging.info("💬 Dashboard WebSocket server stopped")
        except Exception as e:
            logging.error("Error stopping Dashboard WebSocket server: %s", e)

    # Cancel health task if running
    if hasattr(bot, '_health_task') and bot._health_task and not bot._health_task.done():
        bot._health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot._health_task
        logging.info("🛑 Health loop task cancelled")

    # Flush pending database exports before closing
    try:
        from utils.database import db

        if db is not None:
            await db.flush_pending_exports()
    except ImportError:
        pass  # Database module not available
    except Exception as e:
        logging.error("Error flushing database exports: %s", e)

    # Close bot connection
    if not bot.is_closed():
        await bot.close()

    logging.info("👋 Bot shutdown complete.")


# Signal handlers are now set up in MusicBot.setup_hook() using asyncio.get_running_loop()


def confirm_shutdown() -> bool:
    """Ask user to confirm shutdown when Ctrl+C is pressed"""
    print()  # New line after ^C
    try:
        response = input("[!] Stop the bot? (y/n): ").strip().lower()
        return response in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        # User pressed Ctrl+C again during prompt - cancel shutdown
        print("\n[OK] Cancelled - Bot continues running...")
        return False


def run_bot_with_confirmation() -> None:
    """Run the bot with Ctrl+C confirmation"""
    global bot  # pylint: disable=global-statement
    while True:
        try:
            if TOKEN is None:
                logging.critical("❌ DISCORD_TOKEN is not set")
                return
            bot.run(TOKEN)
            break  # Normal exit
        except KeyboardInterrupt:
            if confirm_shutdown():
                logging.info("🛑 Bot stopped by user (Ctrl+C)")
                # Run graceful shutdown on Windows (signal handlers are Unix-only)
                if sys.platform == "win32":
                    try:
                        asyncio.run(graceful_shutdown())
                    except Exception as e:
                        logging.error("Error during Windows shutdown: %s", e)
                break
            else:
                logging.info("✅ Resuming bot operation...")
                print("[SYNC] Restarting bot...")
                # Recreate bot instance for restart (old one is closed)
                bot = create_bot()
                bot.start_time = time.time()
                # Re-setup health hooks for new instance
                if HEALTH_API_AVAILABLE and setup_health_hooks is not None:
                    setup_health_hooks(bot)
                continue


if __name__ == "__main__":
    # Run startup checks only when executed directly (not on import)
    smart_startup_check()

    # Validate required secrets
    from config import settings as _startup_settings

    # Initialize Sentry (deferred from import time to avoid polluting prod tracking)
    if SENTRY_AVAILABLE and init_sentry is not None:
        _sentry_env = os.getenv("SENTRY_ENVIRONMENT", "production")
        init_sentry(environment=_sentry_env)

    secret_errors = _startup_settings.validate_required_secrets()
    if secret_errors:
        for err in secret_errors:
            logging.warning("⚠️ %s", err)

    # Log feature flags summary
    logging.info("📋 Feature Status:\n%s", feature_flags.summary())
    # Register additional runtime features
    feature_flags.register("ffmpeg", os.environ.get("FFMPEG_MISSING") != "1")
    feature_flags.register("spotify", bool(_startup_settings.spotipy_client_id))

    if not validate_token(TOKEN):
        logging.critical("❌ Error: DISCORD_TOKEN is invalid or not set in .env")
        logging.critical(
            "❌ Token should be in format: XXXXXX.XXXXXX.XXXXXX (3 parts separated by dots)"
        )
        sys.exit(1)

    # Write PID file for dashboard process tracking
    _write_pid_file()

    # Start Health API server
    if HEALTH_API_AVAILABLE and start_health_api is not None:
        start_health_api()

    try:
        # Signal handlers are set up in MusicBot.setup_hook() for Unix systems

        run_bot_with_confirmation()
    except discord.LoginFailure:
        logging.critical("❌ Invalid Discord Token! Please check your .env file.")
    except OSError as e:
        logging.critical("❌ Fatal Error: %s", e)
    finally:
        # Stop Health API on exit
        if HEALTH_API_AVAILABLE and stop_health_api is not None:
            stop_health_api()
