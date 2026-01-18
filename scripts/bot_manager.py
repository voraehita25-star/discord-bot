"""
Bot Manager Script
CLI tool to manage the Discord bot processes.
"""

import contextlib
import datetime
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import psutil

# Add parent directory to path for imports
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import Self-Healer
try:
    from utils.reliability.self_healer import SelfHealer, kill_everything

    SELF_HEALER_AVAILABLE = True
except ImportError:
    SELF_HEALER_AVAILABLE = False

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


# Constants
STATUS_FILE = "bot_status.json"
PID_FILE = "bot.pid"
STOP_FLAG = "stop_loop.flag"
BOX_WIDTH = 50

# Compact Emoji Ranges
EMOJI_RANGES = [
    (0x1F300, 0x1F9FF),
    (0x1F600, 0x1F64F),
    (0x1F680, 0x1F6FF),
    (0x1F1E0, 0x1F1FF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
    (0x231A, 0x231B),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2614, 0x2615),
    (0x2648, 0x2653),
    (0x267F, 0x267F),
    (0x2693, 0x2693),
    (0x26A1, 0x26A1),
    (0x26AA, 0x26AB),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26CE, 0x26CE),
    (0x26D4, 0x26D4),
    (0x26EA, 0x26EA),
    (0x26F2, 0x26F3),
    (0x26F5, 0x26F5),
    (0x26FA, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
]


def get_display_width(text):
    """Calculate actual display width of text (handles emoji, Thai, and unicode)"""
    clean = re.sub(r"\033\[[0-9;]*m|\x1b\[[0-9;]*m", "", text)
    width = 0
    i = 0
    chars = list(clean)

    while i < len(chars):
        char = chars[i]
        code = ord(char)

        # Zero-width chars
        if code in (0x200B, 0x200C, 0x200D) or 0xFE00 <= code <= 0xFE0F or 0x0300 <= code <= 0x036F:
            i += 1
            continue

        # Emoji detection
        is_emoji = False
        for start, end in EMOJI_RANGES:
            if start <= code <= end:
                is_emoji = True
                break
        if is_emoji:
            width += 2
            i += 1
            continue

        # Thai characters
        if 0x0E00 <= code <= 0x0E7F:
            if code in (
                0x0E31,
                0x0E34,
                0x0E35,
                0x0E36,
                0x0E37,
                0x0E38,
                0x0E39,
                0x0E3A,
                0x0E47,
                0x0E48,
                0x0E49,
                0x0E4A,
                0x0E4B,
                0x0E4C,
                0x0E4D,
                0x0E4E,
            ):
                i += 1
                continue
            width += 1
            i += 1
            continue

        # Box, Fullwidth, Ambiguous
        if 0x2500 <= code <= 0x257F:
            width += 1
        elif unicodedata.east_asian_width(char) in ("F", "W"):
            width += 2
        else:
            width += 1
        i += 1
    return width


def pad_line(text, width=BOX_WIDTH, align="left"):
    """Create a padded line"""
    display_width = get_display_width(text)
    padding_needed = max(0, width - display_width)

    if align == "center":
        pad_left = padding_needed // 2
        pad_right = padding_needed - pad_left
        content = f"{' ' * pad_left}{text}{' ' * pad_right}"
    else:
        content = f"{text}{' ' * padding_needed}"

    return f"{Colors.BRIGHT_CYAN}║{Colors.RESET}{content}{Colors.BRIGHT_CYAN}║{Colors.RESET}"


def box_top(width=BOX_WIDTH):
    """Return top border of the box"""
    return f"{Colors.BRIGHT_CYAN}╔{'═' * width}╗{Colors.RESET}"


def box_mid(width=BOX_WIDTH):
    """Return middle separator of the box"""
    return f"{Colors.BRIGHT_CYAN}╠{'═' * width}╣{Colors.RESET}"


def box_bottom(width=BOX_WIDTH):
    """Return bottom border of the box"""
    return f"{Colors.BRIGHT_CYAN}╚{'═' * width}╝{Colors.RESET}"


def box_header(text, width=BOX_WIDTH):
    """Return a centered header line"""
    return pad_line(f"{Colors.BRIGHT_YELLOW}{text}{Colors.RESET}", width, "center")


def clear_screen():
    """Clear terminal screen"""
    os.system("cls" if sys.platform == "win32" else "clear")


def print_banner():
    """Print the application banner"""
    ascii_lines = [
        "    ____   ____ _____   __  __  ____ ____ ",
        "   | __ ) / _ \\_   _| |  \\/  |/ ___|  _ \\ ",
        "   |  _ \\| | | || |   | |\\/| | |  _| |_) |",
        "   | |_) | |_| || |   | |  | | |_| |  _ < ",
        "   |____/ \\___/ |_|   |_|  |_|\\____|_| \\_\\",
    ]
    print(box_top())
    for line in ascii_lines:
        print(pad_line(f"{Colors.BRIGHT_MAGENTA}{line}{Colors.RESET}", BOX_WIDTH, "center"))
    print(box_mid())
    print(
        pad_line(
            f"{Colors.BRIGHT_YELLOW}Discord Bot Manager{Colors.RESET} {Colors.DIM}v1.0{Colors.RESET}",
            BOX_WIDTH,
            "center",
        )
    )
    print(box_bottom())


def _find_processes(match_terms, exclude_terms=None):
    """Find process IDs matching ALL terms (not ANY)"""
    pids = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmdline_str = " ".join(cmdline).lower()
            # Must match ALL terms (not ANY)
            if not all(term in cmdline_str for term in match_terms):
                continue
            if exclude_terms and any(term in cmdline_str for term in exclude_terms):
                continue
            # Exclude VS Code extensions and other non-project Python processes
            non_project_patterns = [".antigravity", "vscode", "ms-python", "pylance"]
            if any(pattern in cmdline_str for pattern in non_project_patterns):
                continue
            pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def find_all_bot_processes():
    """Find all main bot processes"""
    return _find_processes(["python", "bot.py"], ["bot_manager", "dev_watcher"])


def find_all_dev_watcher_processes():
    """Find all dev watcher processes"""
    return _find_processes(["python", "dev_watcher"])


def _get_launcher_info(proc):
    """Identify launcher type from a process"""
    try:
        cmdline_list = proc.cmdline() or []
        cmdline_str = " ".join(cmdline_list).lower()
        name = proc.name().lower()

        # Check dev watcher
        if "dev_watcher" in cmdline_str or "start_dev_mode" in cmdline_str:
            script = "dev_watcher.py" if "dev_watcher" in cmdline_str else "start_dev_mode.bat"
            return {
                "name": "Dev Mode (Hot Reload)",
                "script": script,
                "type": "development",
                "features": ["Auto-restart on file changes", "Live reload"],
            }

        # Check production
        if "start_bot" in cmdline_str:
            return {
                "name": "Production Mode",
                "script": "start_bot.bat",
                "type": "production",
                "features": ["Standard startup"],
            }

        # Check hidden
        if name in ("wscript.exe", "cscript.exe"):
            return {
                "name": "Hidden Startup",
                "script": "start_bot_hidden.vbs",
                "type": "hidden",
                "features": ["No visible window", "Background execution"],
            }

        # Check Task Scheduler
        if name in ("svchost.exe", "taskeng.exe", "taskhost.exe"):
            return {
                "name": "Scheduled Task",
                "script": "Windows Task Scheduler",
                "type": "scheduled",
                "features": ["Auto-start on schedule", "Background execution"],
            }

        # Check Terminal/Console launching
        if name in ("cmd.exe", "powershell.exe", "pwsh.exe", "wt.exe"):
            if "start_bot" in cmdline_str:
                return {
                    "name": "Production Mode",
                    "script": "start_bot.bat",
                    "type": "production",
                    "features": ["Standard startup"],
                }

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None


def detect_launcher(proc):
    """Detect which launcher started the bot"""
    try:
        # Check direct parent
        parent = proc.parent()
        if parent:
            info = _get_launcher_info(parent)
            if info:
                return info

        # Check up tree (4 levels)
        current = parent
        for _ in range(3):
            if not current:
                break
            current = current.parent()
            if current:
                info = _get_launcher_info(current)
                if info:
                    return info

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return {"name": "Unknown", "script": "Unknown", "type": "unknown", "features": []}


def get_bot_status():
    """Get detailed bot status - finds ALL running instances"""
    status = {
        "running": False,
        "pid": None,
        "all_pids": [],
        "process_name": None,
        "launcher": {"name": "Unknown", "script": "Unknown", "type": "unknown", "features": []},
        "start_time": None,
        "uptime": None,
        "memory_mb": None,
        "cpu_percent": None,
        "python_version": None,
        "working_dir": None,
        "dev_watcher_pids": [],
    }

    all_bot_pids = find_all_bot_processes()
    status["all_pids"] = all_bot_pids
    status["dev_watcher_pids"] = find_all_dev_watcher_processes()

    if all_bot_pids:
        status["running"] = True
        pid = all_bot_pids[0]
        status["pid"] = pid
        try:
            proc = psutil.Process(pid)
            status["process_name"] = proc.name()

            # Stats
            total_mem, total_cpu = 0, 0
            for p in all_bot_pids:
                try:
                    pr = psutil.Process(p)
                    total_mem += pr.memory_info().rss / 1024 / 1024
                    total_cpu += pr.cpu_percent(interval=0.05)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            status["memory_mb"] = round(total_mem, 2)
            status["cpu_percent"] = round(total_cpu, 1)

            # Metadata
            try:
                create_time = datetime.datetime.fromtimestamp(proc.create_time())
                status["start_time"] = create_time.strftime("%Y-%m-%d %H:%M:%S")
                # Fix for complex statement and ambiguous expression
                uptime = datetime.datetime.now() - create_time
                status["uptime"] = str(uptime).split(".", maxsplit=1)[0]
            except OSError:
                pass

            try:
                status["working_dir"] = proc.cwd()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                status["working_dir"] = str(Path.cwd())

            status["launcher"] = detect_launcher(proc)
            try:
                status["python_version"] = sys.version.split()[0]
            except (IndexError, AttributeError):
                pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return status


def print_status():
    """Print detailed bot status"""
    status = get_bot_status()
    print(f"\n{box_top()}\n{box_header('BOT STATUS')}\n{box_mid()}")

    if status["running"]:
        num = len(status["all_pids"])
        if num > 1:
            warning = f"  {Colors.BRIGHT_RED}[!] WARNING: {num} INSTANCES RUNNING!{Colors.RESET}"
            print(pad_line(warning))
            print(pad_line(f"  {Colors.BRIGHT_RED}    PIDs: {status['all_pids']}{Colors.RESET}"))
            print(box_mid())

        print(pad_line(f"  Status:     {Colors.BRIGHT_GREEN}ONLINE{Colors.RESET}"))
        print(pad_line(f"  PID:        {Colors.WHITE}{status['pid']}{Colors.RESET}"))
        if num > 1:
            print(pad_line(f"  Instances:  {Colors.BRIGHT_RED}{num} (should be 1!){Colors.RESET}"))

        start = status["start_time"] or "N/A"
        print(pad_line(f"  Started:    {Colors.WHITE}{start}{Colors.RESET}"))
        print(pad_line(f"  Uptime:     {Colors.WHITE}{status['uptime'] or 'N/A'}{Colors.RESET}"))

        if status["dev_watcher_pids"]:
            count = len(status["dev_watcher_pids"])
            msg = f"  Watchers:   {Colors.CYAN}{count} dev_watcher(s){Colors.RESET}"
            print(pad_line(msg))

        print(f"{box_mid()}\n{box_header('SYSTEM INFO')}\n{box_mid()}")
        print(pad_line(f"  Memory:     {Colors.WHITE}{status['memory_mb'] or 0} MB{Colors.RESET}"))
        print(pad_line(f"  CPU:        {Colors.WHITE}{status['cpu_percent'] or 0}%{Colors.RESET}"))
        print(
            pad_line(
                f"  Python:     {Colors.WHITE}{status['python_version'] or 'N/A'}{Colors.RESET}"
            )
        )

        print(f"{box_mid()}\n{box_header('LAUNCHER INFO')}\n{box_mid()}")
        launcher = status["launcher"]
        print(pad_line(f"  Launcher:   {Colors.BRIGHT_GREEN}{launcher['name']}{Colors.RESET}"))
        print(pad_line(f"  Script:     {Colors.WHITE}{launcher['script']}{Colors.RESET}"))
        print(pad_line(f"  Type:       {Colors.WHITE}{launcher['type']}{Colors.RESET}"))

        if launcher["features"]:
            print(pad_line("  Features:"))
            for feat in launcher["features"]:
                txt = f"    - {Colors.DIM}{feat}{Colors.RESET}"
                if len(re.sub(r"\033\[[0-9;]*m", "", txt)) > BOX_WIDTH - 2:
                    txt = txt[: BOX_WIDTH - 5] + "..." + Colors.RESET
                print(pad_line(txt))
    else:
        print(pad_line(f"  Status:     {Colors.BRIGHT_RED}OFFLINE{Colors.RESET}"))
        print(pad_line(f"  {Colors.DIM}Bot is not running{Colors.RESET}"))

    print(box_bottom())


def stop_process_list(pids, name="process"):
    """Validates and kills list of pids"""
    count = 0
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
            print(f"{Colors.GREEN}  Stopped {name} (PID: {pid}){Colors.RESET}")
            count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except OSError as e:
            print(f"{Colors.RED}  Error stopping PID {pid}: {e}{Colors.RESET}")
    return count


def auto_stop_existing_bot(status):
    """Automatically stop ALL existing bot instances"""
    if not status["running"]:
        return True

    print(f"{Colors.BRIGHT_YELLOW}[*] Automatically stopping existing bot...{Colors.RESET}")

    stop_process_list(status["dev_watcher_pids"], "dev_watcher")
    stop_process_list(status["all_pids"], "bot")

    pid_path = Path(PID_FILE)
    if pid_path.exists():
        with contextlib.suppress(OSError):
            pid_path.unlink()

    print(f"{Colors.GREEN}[OK] Stopped all instances!{Colors.RESET}")
    time.sleep(1)
    return True


def _launch_script(path, name, hidden=False):
    """Helper to launch a script"""
    path_obj = Path(path)
    if not path_obj.exists():
        print(f"{Colors.RED}{name} script not found: {path}{Colors.RESET}")
        return False

    try:
        path_str = str(path_obj.resolve())
        if hidden:
            subprocess.Popen(["wscript", path_str], shell=False, cwd=str(PROJECT_ROOT.resolve()))
        elif sys.platform == "win32":
            os.startfile(path_str)
        else:
            subprocess.Popen([path_str], shell=True, cwd=str(PROJECT_ROOT.resolve()))
        return True
    except (OSError, subprocess.SubprocessError) as e:
        print(f"{Colors.RED}Failed to start {name}: {e}{Colors.RESET}")
        return False


def start_bot(mode="production"):
    """Start the bot (auto-stops existing instance)"""
    status = get_bot_status()
    if status["running"] and not auto_stop_existing_bot(status):
        print(f"{Colors.RED}Cannot start - failed to stop existing instance{Colors.RESET}")
        return False

    # Scripts are now in scripts/startup/ subdirectory
    scripts = PROJECT_ROOT / "scripts" / "startup"
    print(f"{Colors.GREEN}Starting bot in {mode.capitalize()} Mode...{Colors.RESET}")

    if mode == "dev":
        if _launch_script(scripts / "start_dev_mode.bat", "Dev mode"):
            time.sleep(2)
            print(f"{Colors.GREEN}Bot start command sent!{Colors.RESET}")
            return True
    elif mode == "hidden":
        if _launch_script(scripts / "start_bot_hidden.vbs", "Hidden mode", hidden=True):
            time.sleep(2)
            print(f"{Colors.GREEN}Bot start command sent!{Colors.RESET}")
            return True
    else:
        if _launch_script(scripts / "start_bot.bat", "Production"):
            time.sleep(2)
            print(f"{Colors.GREEN}Bot start command sent!{Colors.RESET}")
            return True
    return False


def stop_bot():
    """Stop ALL bot instances"""
    status = get_bot_status()
    if not status["running"]:
        print(f"{Colors.YELLOW}Bot is not running{Colors.RESET}")
        return False

    try:
        Path(STOP_FLAG).write_text("stop", encoding="utf-8")
    except OSError:
        pass

    stopped = 0
    stopped += stop_process_list(status["dev_watcher_pids"], "dev_watcher")
    stopped += stop_process_list(status["all_pids"], "bot")

    pid_path = Path(PID_FILE)
    if pid_path.exists():
        with contextlib.suppress(OSError):
            pid_path.unlink()

    if stopped > 0:
        print(f"{Colors.GREEN}[OK] Stopped {stopped} process(es){Colors.RESET}")
        return True
    print(f"{Colors.YELLOW}No processes were stopped{Colors.RESET}")
    return False


def restart_bot():
    """Restart the bot"""
    status = get_bot_status()
    mode = "production"
    if status["running"]:
        if status["launcher"]["type"] == "development":
            mode = "dev"
        print(f"{Colors.YELLOW}Restarting bot...{Colors.RESET}")
        stop_bot()
        time.sleep(2)
    start_bot(mode)


def print_menu():
    """Print menu options"""
    print(f"\n{box_top()}\n{box_header('MENU OPTIONS')}\n{box_mid()}")
    opts = [
        "[1] View Status",
        "[2] Start Bot (Production)",
        "[3] Start Bot (Dev Mode)",
        "[4] Start Bot (Hidden)",
        "[5] Stop Bot",
        "[6] Restart Bot",
        "[7] View Logs",
        "---",
        "[8] Self-Healer (Auto Fix)",
        "[9] Kill All Processes",
        "---",
        "[0] Exit",
    ]
    for opt in opts:
        if opt == "---":
            print(box_mid())
        else:
            first_part = opt.split(" ", maxsplit=1)[0]
            rest_part = " ".join(opt.split(" ")[1:])
            col = Colors.BRIGHT_GREEN
            if "8" in opt:
                col = Colors.BRIGHT_CYAN
            elif "9" in opt:
                col = Colors.BRIGHT_RED

            print(pad_line(f"  {col}{first_part}{Colors.RESET} {rest_part}"))
    print(box_bottom())


def run_self_healer():
    """Run Self-Healer diagnostic and auto-fix"""
    if not SELF_HEALER_AVAILABLE:
        print(f"{Colors.RED}Self-Healer not available!{Colors.RESET}")
        return
    print(f"\n{box_top()}\n{box_header('🤖 Bot Self-Healer')}\n{box_mid()}")
    print(pad_line(f"  {Colors.BRIGHT_GREEN}[1]{Colors.RESET} Quick Diagnosis"))
    print(pad_line(f"  {Colors.BRIGHT_GREEN}[2]{Colors.RESET} Auto-Heal (Conservative)"))
    print(pad_line(f"  {Colors.BRIGHT_GREEN}[3]{Colors.RESET} Auto-Heal (Aggressive)"))
    print(
        f"{box_mid()}\n{pad_line(f'  {Colors.BRIGHT_GREEN}[0]{Colors.RESET} Back')}\n{box_bottom()}"
    )

    choice = input(f"\n{Colors.BRIGHT_CYAN}➤{Colors.RESET} Choose: ").strip()
    healer = SelfHealer("bot_manager")

    if choice == "1":
        print(f"\n{Colors.BRIGHT_YELLOW}Running diagnosis...{Colors.RESET}\n")
        diag = healer.diagnose()
        print(f"{Colors.BRIGHT_CYAN}Bot Processes:{Colors.RESET} {len(diag['bot_processes'])}")
        for bp in diag["bot_processes"]:
            print(f"  - PID {bp['pid']} (running {bp['age']:.0f}s)")
        print(f"{Colors.BRIGHT_CYAN}Dev Watchers:{Colors.RESET} {len(diag['dev_watchers'])}")

        print(f"\n{Colors.BRIGHT_CYAN}Issues Found:{Colors.RESET} {len(diag['issues'])}")
        for i in diag["issues"]:
            severity_col = Colors.BRIGHT_RED if i["severity"] == "HIGH" else Colors.YELLOW
            print(f"  {severity_col}[{i['severity']}]{Colors.RESET} {i['description']}")
        if not diag["issues"]:
            print(f"  {Colors.GREEN}✓ No issues detected{Colors.RESET}")

    elif choice in ("2", "3"):
        aggressive = choice == "3"
        if aggressive:
            print(f"{Colors.YELLOW}This will kill ALL bot processes!{Colors.RESET}")
            if input("Continue? (y/n): ").strip().lower() != "y":
                return
        results = healer.auto_heal(aggressive=aggressive)
        print(f"\n{Colors.BRIGHT_CYAN}Results:{Colors.RESET} {results['summary']}")
        for a in results["actions"]:
            if a["success"]:
                icon = f"{Colors.GREEN}✓{Colors.RESET}"
            else:
                icon = f"{Colors.RED}✗{Colors.RESET}"
            print(f"  {icon} {a['action']}: {a['details']}")


def run_kill_all():
    """Kill all bot-related processes"""
    if not SELF_HEALER_AVAILABLE:
        return
    print(f"\n{Colors.BRIGHT_RED}⚠️  WARNING: Kill ALL bot processes? (yes/no){Colors.RESET}")
    if input(f"{Colors.BRIGHT_CYAN}➤{Colors.RESET} ").strip().lower() == "yes":
        result = kill_everything("bot_manager")
        killed_bots = result["bots_killed"]
        killed_watchers = result["watchers_killed"]
        print(
            f"\n{Colors.GREEN}Done! Killed {killed_bots} bots, "
            f"{killed_watchers} watchers.{Colors.RESET}"
        )
    else:
        print("Cancelled.")


def view_logs():
    """View recent logs"""
    for f_name in ["bot.log", "bot_errors.log", "logs/self_healer.log"]:
        log_path = Path(f_name)
        if log_path.exists():
            print(f"\n{Colors.BRIGHT_CYAN}═══ {f_name} (Last 20 lines) ═══{Colors.RESET}")
            try:
                lines = log_path.read_text(encoding="utf-8").splitlines()[-20:]
                for line in lines:
                    col = Colors.DIM
                    if "ERROR" in line:
                        col = Colors.RED
                    elif "WARN" in line:
                        col = Colors.YELLOW
                    elif "INFO" in line:
                        col = Colors.GREEN
                    print(f"{col}{line.rstrip()}{Colors.RESET}")
            except OSError as e:
                print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        else:
            print(f"\n{Colors.YELLOW}⚠️  {f_name} not found{Colors.RESET}")


def main():
    """Main CLI Loop"""
    while True:
        clear_screen()
        print_banner()
        print_status()
        print_menu()
        try:
            choice = input(f"\n{Colors.BRIGHT_CYAN}➤{Colors.RESET} Enter choice: ").strip()
            if choice == "1":
                # Refresh - status is already shown at top, just show a message
                print(f"\n{Colors.CYAN}[*]{Colors.RESET} Status refreshed!{Colors.RESET}")
            elif choice == "2":
                start_bot("production")
            elif choice == "3":
                start_bot("dev")
            elif choice == "4":
                start_bot("hidden")
            elif choice == "5":
                stop_bot()
            elif choice == "6":
                restart_bot()
            elif choice == "7":
                view_logs()
            elif choice == "8":
                run_self_healer()
            elif choice == "9":
                run_kill_all()
            elif choice == "0":
                break
            else:
                print(f"{Colors.RED}❌ Invalid choice{Colors.RESET}")
                time.sleep(1)
                continue

            if choice != "0":
                input(f"\n{Colors.DIM}Press Enter to continue...{Colors.RESET}")
        except KeyboardInterrupt:
            break
    print(f"\n{Colors.BRIGHT_MAGENTA}✨ Goodbye! 👋{Colors.RESET}")


if __name__ == "__main__":
    main()
