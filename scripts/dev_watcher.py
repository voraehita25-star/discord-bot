"""
Dev Watcher Script v3.0
Monitors file changes and automatically restarts the bot in development mode.

Features:
- Hot reload on file changes
- Hash-based change detection
- Configurable via .devwatcher.json
- Verbose and Debug modes
- Auto-retry on crash
- Health check after restart
- Session statistics
- File logging
"""

import contextlib
import datetime
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

# Change to project root directory (parent of tools/)
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

# Add project root to path for imports
sys.path.insert(0, str(PROJECT_ROOT))

# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class DevWatcherConfig:
    """Configuration for dev watcher."""

    # Watch settings
    watch_extensions: list[str] = field(default_factory=lambda: [".py"])
    ignore_patterns: list[str] = field(
        default_factory=lambda: [
            "temp",
            "__pycache__",
            ".git",
            ".pyc",
            "logs",
            ".log",
            "bot.pid",
            "dev_watcher.pid",
            ".env",
            "chat_history",
            "history_",
            ".json",
            "assets/",
            "assets\\",
            "RP/",
            "RP\\",
            "data/",
            "data\\",
            "node_modules",
            ".venv",
            "venv",
            "db_export",
            ".db",
            ".sqlite",
            "rvc_env",
            "models/rvc",
        ]
    )

    # Timing settings
    debounce_seconds: float = 1.5
    poll_interval: float = 1.0
    health_check_delay: float = 3.0
    crash_retry_delay: float = 5.0
    max_crash_retries: int = 3

    # Feature flags
    auto_retry_on_crash: bool = True
    health_check_enabled: bool = True
    sound_on_restart: bool = False  # Windows only
    log_to_file: bool = True

    # Modes
    debug_mode: bool = False
    verbose_mode: bool = False

    @classmethod
    def load_from_file(cls, filepath: Path) -> "DevWatcherConfig":
        """Load config from JSON file."""
        config = cls()
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))

                # Update config with file values
                for key, value in data.items():
                    if hasattr(config, key):
                        setattr(config, key, value)

                print(f"  Loaded config from {filepath.name}")
            except (json.JSONDecodeError, OSError) as e:
                print(f"  Warning: Could not load config: {e}")

        return config

    def save_default(self, filepath: Path) -> None:
        """Save default config to file."""
        data = {
            "watch_extensions": self.watch_extensions,
            "ignore_patterns": self.ignore_patterns,
            "debounce_seconds": self.debounce_seconds,
            "poll_interval": self.poll_interval,
            "health_check_delay": self.health_check_delay,
            "crash_retry_delay": self.crash_retry_delay,
            "max_crash_retries": self.max_crash_retries,
            "auto_retry_on_crash": self.auto_retry_on_crash,
            "health_check_enabled": self.health_check_enabled,
            "sound_on_restart": self.sound_on_restart,
            "log_to_file": self.log_to_file,
        }

        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")


# =============================================================================
# LOGGING SETUP
# =============================================================================


def setup_logging(config: DevWatcherConfig) -> logging.Logger:
    """Setup logging for dev watcher."""
    logger = logging.getLogger("DevWatcher")
    logger.setLevel(logging.DEBUG if config.debug_mode else logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if config.debug_mode else logging.INFO)

    # File handler (if enabled)
    if config.log_to_file:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)

        file_handler = logging.FileHandler(log_dir / "dev_watcher.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(file_handler)

    return logger


# =============================================================================
# WATCHDOG SETUP
# =============================================================================

# Check for watchdog
try:
    if sys.platform == "win32":
        from watchdog.observers.polling import PollingObserver as Observer
    else:
        from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

# Import shared Colors module
try:
    from utils.media.colors import Colors, enable_windows_ansi

    enable_windows_ansi()
except ImportError:

    class Colors:
        """Fallback ANSI Color Codes"""

        RESET = "\033[0m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RED = "\033[31m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        BLUE = "\033[34m"
        MAGENTA = "\033[35m"
        CYAN = "\033[36m"
        WHITE = "\033[37m"
        BRIGHT_RED = "\033[91m"
        BRIGHT_GREEN = "\033[92m"
        BRIGHT_YELLOW = "\033[93m"
        BRIGHT_BLUE = "\033[94m"
        BRIGHT_MAGENTA = "\033[95m"
        BRIGHT_CYAN = "\033[96m"


# =============================================================================
# CONSTANTS
# =============================================================================

PID_FILE = "bot.pid"
CONFIG_FILE = ".devwatcher.json"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_bot_running() -> tuple[bool, int | None]:
    """Check if bot is already running."""
    pid_path = Path(PID_FILE)
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text(encoding="utf-8").strip())

            if psutil.pid_exists(old_pid):
                try:
                    proc = psutil.Process(old_pid)
                    cmdline = " ".join(proc.cmdline()).lower()
                    if "python" in cmdline and "bot.py" in cmdline:
                        return True, old_pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (ValueError, FileNotFoundError):
            pass
    return False, None


def check_and_stop_existing_bot() -> None:
    """Check if bot is running and stop it."""
    # Try Self-Healer first
    try:
        from utils.reliability.self_healer import SelfHealer

        print(f"{Colors.BRIGHT_CYAN}{'=' * 60}{Colors.RESET}")
        print(
            f"{Colors.BRIGHT_CYAN}  🤖 Self-Healer: Checking for existing instances...{Colors.RESET}"
        )
        print(f"{Colors.BRIGHT_CYAN}{'=' * 60}{Colors.RESET}")
        print()

        healer = SelfHealer("dev_watcher")
        diagnosis = healer.diagnose()

        if diagnosis["issues"]:
            print(
                f"{Colors.BRIGHT_YELLOW}  [!] Found {len(diagnosis['issues'])} issue(s):{Colors.RESET}"
            )
            for issue in diagnosis["issues"]:
                print(f"{Colors.YELLOW}      - {issue['description']}{Colors.RESET}")

            print(f"\n{Colors.BRIGHT_YELLOW}  [*] Auto-healing...{Colors.RESET}")
            results = healer.auto_heal(aggressive=True)
            print(f"{Colors.GREEN}  [OK] {results['summary']}{Colors.RESET}")
            time.sleep(1)
        else:
            print(f"{Colors.GREEN}  [OK] No conflicts found{Colors.RESET}")

        print()
        return
    except ImportError:
        pass

    # Fallback to basic check
    running, pid = is_bot_running()
    if running:
        print(f"{Colors.BRIGHT_YELLOW}{'=' * 60}{Colors.RESET}")
        print(f"{Colors.BRIGHT_YELLOW}  [!] Found existing bot (PID: {pid}){Colors.RESET}")
        print(f"{Colors.BRIGHT_YELLOW}  [*] Stopping for Dev Mode...{Colors.RESET}")
        print(f"{Colors.BRIGHT_YELLOW}{'=' * 60}{Colors.RESET}")
        print()

        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

            print(f"{Colors.GREEN}  [OK] Old instance stopped!{Colors.RESET}")
            time.sleep(1)

            pid_path = Path(PID_FILE)
            if pid_path.exists():
                pid_path.unlink()

        except psutil.NoSuchProcess:
            pid_path = Path(PID_FILE)
            if pid_path.exists():
                pid_path.unlink()
        except Exception as e:
            print(f"{Colors.RED}  [X] Failed to stop: {e}{Colors.RESET}")
            sys.exit(1)

        print()


def clear_screen() -> None:
    """Clear terminal screen."""
    os.system("cls" if sys.platform == "win32" else "clear")


def print_banner() -> None:
    """Print ASCII banner."""
    print()
    print(
        f"{Colors.BRIGHT_MAGENTA}  ██████╗ ███████╗██╗   ██╗    ███╗   ███╗ ██████╗ ██████╗ ███████╗{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_MAGENTA}  ██╔══██╗██╔════╝██║   ██║    ████╗ ████║██╔═══██╗██╔══██╗██╔════╝{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_MAGENTA}  ██║  ██║█████╗  ██║   ██║    ██╔████╔██║██║   ██║██║  ██║█████╗{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_MAGENTA}  ██║  ██║██╔══╝  ╚██╗ ██╔╝    ██║╚██╔╝██║██║   ██║██║  ██║██╔══╝{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_MAGENTA}  ██████╔╝███████╗ ╚████╔╝     ██║ ╚═╝ ██║╚██████╔╝██████╔╝███████╗{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_MAGENTA}  ╚═════╝ ╚══════╝  ╚═══╝      ╚═╝     ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝{Colors.RESET}"
    )
    print()
    print(
        f"{Colors.BRIGHT_CYAN}  ================================================================{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_CYAN}  {Colors.BRIGHT_YELLOW}v3.0{Colors.RESET}  {Colors.WHITE}Hot Reload • Auto-Retry • Health Check{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_CYAN}  ================================================================{Colors.RESET}"
    )
    print()


def print_status(message: str, color: str = Colors.GREEN, icon: str = ">") -> None:
    """Print a status message with timestamp."""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"{Colors.DIM}[{timestamp}]{Colors.RESET} {color}{icon} {message}{Colors.RESET}")


def print_divider() -> None:
    """Print a horizontal divider."""
    print(f"{Colors.DIM}{'─' * 64}{Colors.RESET}")


def play_sound() -> None:
    """Play a notification sound (Windows only)."""
    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass


# =============================================================================
# STATISTICS
# =============================================================================


@dataclass
class SessionStats:
    """Track session statistics."""

    start_time: datetime.datetime = field(default_factory=datetime.datetime.now)
    restart_count: int = 0
    crash_count: int = 0
    files_changed: int = 0
    last_restart_reason: str = ""
    last_restart_time: datetime.datetime | None = None

    def get_uptime(self) -> str:
        """Get formatted uptime string."""
        delta = datetime.datetime.now() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# =============================================================================
# BOT RESTARTER
# =============================================================================

if WATCHDOG_AVAILABLE:

    class BotRestarter(FileSystemEventHandler):
        """Watchdog event handler to restart bot on file changes."""

        def __init__(self, config: DevWatcherConfig, logger: logging.Logger):
            self.config = config
            self.logger = logger
            self.process: subprocess.Popen | None = None
            self.stats = SessionStats()
            self.last_event_time = 0.0
            self.file_hashes: dict[str, str] = {}
            self.consecutive_crashes = 0

            # Start bot
            self.start_bot("Initial start")

        def start_bot(self, reason: str = "File change") -> bool:
            """Start or restart the bot process."""
            # Debounce
            current_time = time.time()
            if current_time - self.last_event_time < self.config.debounce_seconds:
                return False
            self.last_event_time = current_time

            # Stop existing process
            if self.process:
                try:
                    print_divider()
                    print_status("Shutting down...", Colors.BRIGHT_RED, "[STOP]")
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=2)
                except Exception:
                    with contextlib.suppress(Exception):
                        self.process.kill()

            # Clean up PID file
            pid_path = Path(PID_FILE)
            if pid_path.exists():
                with contextlib.suppress(OSError):
                    pid_path.unlink()

            # Update stats
            self.stats.restart_count += 1
            self.stats.last_restart_reason = reason
            self.stats.last_restart_time = datetime.datetime.now()

            # Start new process
            print_divider()
            print_status(
                f"Starting bot... (#{self.stats.restart_count})", Colors.BRIGHT_GREEN, "[START]"
            )
            if self.config.verbose_mode:
                print_status(f"Reason: {reason}", Colors.DIM, "  └─")
            print_divider()
            print()

            self.logger.info("Starting bot (reason: %s)", reason)

            # Launch process
            try:
                if sys.platform == "win32":
                    self.process = subprocess.Popen(
                        [sys.executable, "bot.py"],
                        stdout=sys.stdout,
                        stderr=sys.stderr,
                        cwd=str(PROJECT_ROOT),
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                else:
                    self.process = subprocess.Popen(
                        [sys.executable, "bot.py"],
                        stdout=sys.stdout,
                        stderr=sys.stderr,
                        cwd=str(PROJECT_ROOT),
                    )

                # Play sound if enabled
                if self.config.sound_on_restart:
                    play_sound()

                # Health check
                if self.config.health_check_enabled:
                    self._perform_health_check()

                self.consecutive_crashes = 0
                return True

            except Exception as e:
                self.logger.error("Failed to start bot: %s", e)
                print_status(f"Failed to start: {e}", Colors.RED, "[ERROR]")
                return False

        def _perform_health_check(self) -> bool:
            """Check if bot started successfully."""
            time.sleep(self.config.health_check_delay)

            if self.process and self.process.poll() is None:
                print_status("Health check passed ✓", Colors.GREEN, "  └─")
                self.logger.info("Health check passed")
                return True
            else:
                print_status("Health check failed ✗", Colors.RED, "  └─")
                self.logger.warning("Health check failed - bot may have crashed")
                return False

        def check_for_crash(self) -> bool:
            """Check if bot has crashed and handle auto-retry."""
            if not self.process:
                return False

            return_code = self.process.poll()
            if return_code is not None:
                # Bot has exited
                if return_code != 0:
                    self.stats.crash_count += 1
                    self.consecutive_crashes += 1
                    self.logger.warning("Bot crashed with code %d", return_code)

                    print()
                    print_status(f"Bot crashed! (exit code: {return_code})", Colors.RED, "[CRASH]")

                    # Auto-retry if enabled
                    if self.config.auto_retry_on_crash:
                        if self.consecutive_crashes <= self.config.max_crash_retries:
                            print_status(
                                f"Auto-retry in {self.config.crash_retry_delay}s "
                                f"({self.consecutive_crashes}/{self.config.max_crash_retries})",
                                Colors.YELLOW,
                                "[RETRY]",
                            )
                            time.sleep(self.config.crash_retry_delay)
                            self.start_bot("Auto-retry after crash")
                        else:
                            print_status(
                                f"Max retries ({self.config.max_crash_retries}) exceeded!",
                                Colors.RED,
                                "[STOP]",
                            )
                            print_status(
                                "Fix the error and save a file to restart", Colors.YELLOW, "  └─"
                            )

                    return True

            return False

        def on_modified(self, event):
            self._handle_change(event)

        def on_created(self, event):
            self._handle_change(event)

        def _get_file_hash(self, filepath: str) -> str | None:
            """Get MD5 hash of file content."""
            import hashlib

            try:
                return hashlib.md5(Path(filepath).read_bytes()).hexdigest()
            except OSError:
                return None

        def _should_ignore(self, path: str) -> bool:
            """Check if path should be ignored."""
            path_lower = path.lower()

            # Check ignore patterns
            for pattern in self.config.ignore_patterns:
                if pattern.lower() in path_lower:
                    return True

            # Check hidden directories
            return bool(any(part.startswith(".") for part in Path(path).parts))

        def _handle_change(self, event) -> None:
            """Handle file change events."""
            # Debug mode
            if self.config.debug_mode:
                print(f"{Colors.DIM}[DEBUG] {event.event_type}: {event.src_path}{Colors.RESET}")

            # Ignore directories
            if event.is_directory:
                return

            # Check extension
            file_ext = Path(event.src_path).suffix.lower()
            if file_ext not in self.config.watch_extensions:
                return

            # Check ignore patterns
            if self._should_ignore(event.src_path):
                if self.config.debug_mode:
                    print(f"{Colors.DIM}[DEBUG] Ignored by pattern{Colors.RESET}")
                return

            # Check file exists
            if not Path(event.src_path).exists():
                return

            # Hash-based change detection
            current_hash = self._get_file_hash(event.src_path)
            if current_hash is None:
                return

            old_hash = self.file_hashes.get(event.src_path)
            if old_hash == current_hash:
                if self.config.debug_mode:
                    print(f"{Colors.DIM}[DEBUG] Content unchanged{Colors.RESET}")
                return

            self.file_hashes[event.src_path] = current_hash
            self.stats.files_changed += 1

            # Get relative path
            try:
                rel_path = Path(event.src_path).relative_to(Path.cwd())
            except ValueError:
                rel_path = event.src_path

            # Verbose output
            if self.config.verbose_mode:
                print()
                print_status(f"File: {rel_path}", Colors.CYAN, "[CHANGE]")
                print_status(f"Hash: {current_hash[:8]}...", Colors.DIM, "  └─")
            else:
                print()
                print_status(
                    f"Change: {Colors.CYAN}{rel_path}{Colors.RESET}", Colors.BRIGHT_YELLOW, "[EDIT]"
                )

            self.logger.info("File changed: %s", rel_path)
            self.start_bot(f"File changed: {rel_path}")


# =============================================================================
# DEV WATCHER SERVICE
# =============================================================================


class DevWatcherService:
    """Service to manage dev watcher lifecycle."""

    def __init__(self):
        self.shutdown_requested = False

    def graceful_shutdown(self, _signum, _frame) -> None:
        """Handle shutdown signal."""
        print()
        print(f"\n{Colors.BRIGHT_YELLOW}{'=' * 50}{Colors.RESET}")
        print(f"{Colors.BRIGHT_YELLOW}  Ctrl+C detected! Stop dev mode?{Colors.RESET}")
        print(f"{Colors.BRIGHT_YELLOW}{'=' * 50}{Colors.RESET}")
        try:
            response = input(f"{Colors.BRIGHT_CYAN}  Stop? (y/n): {Colors.RESET}").strip().lower()
            if response == "y":
                self.shutdown_requested = True
            else:
                print(f"{Colors.GREEN}  Continuing...{Colors.RESET}")
                print(f"{Colors.DIM}  (Watching for changes...){Colors.RESET}\n")
        except Exception:
            print(f"{Colors.GREEN}  Continuing...{Colors.RESET}\n")


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Main entry point."""
    # Check watchdog
    if not WATCHDOG_AVAILABLE:
        print(f"{Colors.RED}Error: watchdog module not found!{Colors.RESET}")
        print(f"{Colors.YELLOW}Install with: pip install watchdog{Colors.RESET}")
        sys.exit(1)

    # Load config
    config_path = PROJECT_ROOT / CONFIG_FILE
    config = DevWatcherConfig.load_from_file(config_path)

    # Override with environment variables
    if os.getenv("DEV_WATCHER_DEBUG", "").lower() in ("1", "true", "yes"):
        config.debug_mode = True
    if os.getenv("DEV_WATCHER_VERBOSE", "").lower() in ("1", "true", "yes"):
        config.verbose_mode = True

    # Setup logging
    logger = setup_logging(config)
    logger.info("=" * 60)
    logger.info("Dev Watcher v3.0 Starting")
    logger.info("=" * 60)

    # Clear and show banner
    clear_screen()
    print_banner()

    # Check existing instances
    check_and_stop_existing_bot()

    # Print info
    print(
        f"  {Colors.BRIGHT_CYAN}Monitoring:{Colors.RESET} {Colors.WHITE}{Path.cwd()}{Colors.RESET}"
    )
    print(
        f"  {Colors.BRIGHT_CYAN}Extensions:{Colors.RESET} {Colors.WHITE}{', '.join(config.watch_extensions)}{Colors.RESET}"
    )
    print(f"  {Colors.BRIGHT_CYAN}Features:{Colors.RESET}")
    print(
        f"    {Colors.GREEN}✓{Colors.RESET} Auto-retry on crash"
        if config.auto_retry_on_crash
        else f"    {Colors.DIM}○ Auto-retry disabled{Colors.RESET}"
    )
    print(
        f"    {Colors.GREEN}✓{Colors.RESET} Health check"
        if config.health_check_enabled
        else f"    {Colors.DIM}○ Health check disabled{Colors.RESET}"
    )
    print(
        f"    {Colors.GREEN}✓{Colors.RESET} Logging to file"
        if config.log_to_file
        else f"    {Colors.DIM}○ File logging disabled{Colors.RESET}"
    )
    print()

    if config.debug_mode:
        print(f"  {Colors.BRIGHT_YELLOW}[DEBUG MODE]{Colors.RESET}")
    if config.verbose_mode:
        print(f"  {Colors.BRIGHT_YELLOW}[VERBOSE MODE]{Colors.RESET}")

    print(f"  {Colors.BRIGHT_GREEN}Watching for changes...{Colors.RESET}")
    print(f"  {Colors.DIM}Press {Colors.BRIGHT_RED}Ctrl+C{Colors.DIM} to stop{Colors.RESET}")
    print()

    # Create config file if not exists
    if not config_path.exists():
        print(f"  {Colors.DIM}Tip: Create {CONFIG_FILE} to customize settings{Colors.RESET}")

    # Setup event handler and observer
    event_handler = BotRestarter(config, logger)
    observer = Observer(timeout=config.poll_interval)
    observer.schedule(event_handler, path=".", recursive=True)
    observer.start()

    if sys.platform == "win32":
        print(
            f"  {Colors.DIM}Using Polling Observer (interval: {config.poll_interval}s){Colors.RESET}"
        )
    print()

    # Setup signal handlers
    service = DevWatcherService()
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, service.graceful_shutdown)
        signal.signal(signal.SIGBREAK, service.graceful_shutdown)

    # Main loop
    try:
        while not service.shutdown_requested:
            time.sleep(0.5)
            # Check for crashes
            event_handler.check_for_crash()
    except (KeyboardInterrupt, SystemExit):
        pass

    # Shutdown sequence
    print()
    print_divider()
    print_status("Shutting down...", Colors.BRIGHT_RED, "[STOP]")

    logger.info("Shutting down...")
    observer.stop()

    if event_handler.process:
        try:
            print_status("Stopping bot...", Colors.YELLOW, ">>")
            event_handler.process.terminate()
            event_handler.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            event_handler.process.kill()
        except Exception:
            pass

    observer.join()

    # Clean up
    pid_path = Path(PID_FILE)
    if pid_path.exists():
        with contextlib.suppress(OSError):
            pid_path.unlink()

    # Print session summary
    stats = event_handler.stats
    print()
    print(
        f"{Colors.BRIGHT_CYAN}  ================================================================{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_CYAN}                    {Colors.BRIGHT_YELLOW}Session Summary{Colors.RESET}"
    )
    print(
        f"{Colors.BRIGHT_CYAN}  ================================================================{Colors.RESET}"
    )
    print(f"  {Colors.WHITE}Uptime:{Colors.RESET}         {stats.get_uptime()}")
    print(f"  {Colors.WHITE}Restarts:{Colors.RESET}       {stats.restart_count}")
    print(f"  {Colors.WHITE}Crashes:{Colors.RESET}        {stats.crash_count}")
    print(f"  {Colors.WHITE}Files Changed:{Colors.RESET}  {stats.files_changed}")
    print(
        f"{Colors.BRIGHT_CYAN}  ================================================================{Colors.RESET}"
    )
    print()

    logger.info(
        "Session ended - Uptime: %s, Restarts: %d, Crashes: %d",
        stats.get_uptime(),
        stats.restart_count,
        stats.crash_count,
    )

    print_status("Goodbye!", Colors.BRIGHT_MAGENTA, ">>")
    print()


if __name__ == "__main__":
    main()
