"""
Bot Self-Healer System
Automatic problem detection and correction system for the bot.

Features:
- Detect duplicate instances
- Auto-fix issues
- Self-healing mechanisms
- Smart decision making
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import time
from pathlib import Path

import psutil

# Constants
PID_FILE = "bot.pid"
HEALER_LOG_FILE = "logs/self_healer.log"


class SelfHealer:
    """Automatic Bot Problem Detection and Correction System"""

    def __init__(self, caller_script: str = "unknown"):
        self.caller_script = caller_script
        self.my_pid = os.getpid()
        self.actions_taken = []
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Setup dedicated logger for self-healer"""
        logger = logging.getLogger("SelfHealer")
        logger.setLevel(logging.DEBUG)

        # Create logs directory if not exists
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # File handler
        if not logger.handlers:
            file_h = logging.FileHandler(HEALER_LOG_FILE, encoding="utf-8")
            file_h.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_h.setFormatter(formatter)
            logger.addHandler(file_h)

        return logger

    def log(self, level: str, message: str):
        """Log message and store action"""
        getattr(self.logger, level.lower())(message)
        if level.upper() in ["WARNING", "ERROR", "CRITICAL"]:
            self.actions_taken.append(f"[{level.upper()}] {message}")

    # ==================== DETECTION ====================

    def find_all_bot_processes(self) -> list[dict]:
        """Find ALL bot.py processes with details"""
        bot_processes = []

        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                cmdline_str = " ".join(cmdline).lower()

                # Look for bot.py but exclude manager, watcher, etc.
                if "python" in cmdline_str and "bot.py" in cmdline_str:
                    ignore_list = ["bot_manager", "dev_watcher", "self_healer"]
                    if not any(x in cmdline_str for x in ignore_list):
                        bot_processes.append(
                            {
                                "pid": proc.info["pid"],
                                "cmdline": cmdline_str,
                                "create_time": proc.info.get("create_time", 0),
                                "process": psutil.Process(proc.info["pid"]),
                            }
                        )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by creation time (oldest first)
        bot_processes.sort(key=lambda x: x["create_time"])
        return bot_processes

    def find_all_dev_watchers(self) -> list[dict]:
        """Find ALL dev_watcher.py processes"""
        watchers = []

        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                cmdline_str = " ".join(cmdline).lower()

                if "python" in cmdline_str and "dev_watcher" in cmdline_str:
                    watchers.append(
                        {
                            "pid": proc.info["pid"],
                            "cmdline": cmdline_str,
                            "create_time": proc.info.get("create_time", 0),
                            "process": psutil.Process(proc.info["pid"]),
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        watchers.sort(key=lambda x: x["create_time"])
        return watchers

    def get_pid_from_file(self) -> int | None:
        """Get PID from bot.pid file"""
        pid_path = Path(PID_FILE)
        if pid_path.exists():
            try:
                return int(pid_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
        return None

    def diagnose(self) -> dict:
        """Analyze system status"""
        diag_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "caller": self.caller_script,
            "my_pid": self.my_pid,
            "issues": [],
            "bot_processes": [],
            "dev_watchers": [],
            "pid_file_pid": None,
            "pid_file_valid": False,
            "recommendations": [],
        }

        # Find all processes
        bots = self.find_all_bot_processes()
        watchers = self.find_all_dev_watchers()
        pid_from_file = self.get_pid_from_file()

        diag_data["bot_processes"] = [
            {"pid": b["pid"], "age": time.time() - b["create_time"]} for b in bots
        ]
        diag_data["dev_watchers"] = [
            {"pid": w["pid"], "age": time.time() - w["create_time"]} for w in watchers
        ]
        diag_data["pid_file_pid"] = pid_from_file

        # Check PID file validity
        if pid_from_file:
            diag_data["pid_file_valid"] = any(b["pid"] == pid_from_file for b in bots)

        # Detect issues
        if len(bots) > 1:
            diag_data["issues"].append(
                {
                    "type": "DUPLICATE_BOTS",
                    "severity": "HIGH",
                    "description": f"Found {len(bots)} bot instances running simultaneously",
                    "pids": [b["pid"] for b in bots],
                }
            )
            diag_data["recommendations"].append("KILL_DUPLICATE_BOTS")

        # Only report duplicate watchers if called from dev_watcher itself
        # bot.py should NOT try to kill dev_watcher (it's the parent process)
        if len(watchers) > 1 and "dev_watcher" in self.caller_script.lower():
            diag_data["issues"].append(
                {
                    "type": "DUPLICATE_WATCHERS",
                    "severity": "MEDIUM",
                    "description": f"Found {len(watchers)} dev_watcher instances",
                    "pids": [w["pid"] for w in watchers],
                }
            )
            diag_data["recommendations"].append("KILL_DUPLICATE_WATCHERS")

        if pid_from_file and not diag_data["pid_file_valid"]:
            diag_data["issues"].append(
                {
                    "type": "STALE_PID_FILE",
                    "severity": "LOW",
                    "description": f"PID file points to non-existent process ({pid_from_file})",
                    "pids": [pid_from_file],
                }
            )
            diag_data["recommendations"].append("CLEAN_PID_FILE")

        if not bots and pid_from_file:
            diag_data["issues"].append(
                {
                    "type": "ORPHAN_PID_FILE",
                    "severity": "LOW",
                    "description": "PID file exists but no bot is running",
                    "pids": [],
                }
            )
            diag_data["recommendations"].append("CLEAN_PID_FILE")

        return diag_data

    # ==================== HEALING ACTIONS ====================

    def kill_process(self, pid: int, force: bool = False) -> bool:
        """Kill a specific process"""
        try:
            proc = psutil.Process(pid)

            if force:
                proc.kill()
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

            self.log("info", f"Successfully stopped process PID {pid}")
            return True

        except psutil.NoSuchProcess:
            self.log("info", f"Process PID {pid} already terminated")
            return True
        except psutil.AccessDenied:
            self.log("error", f"Access denied when trying to stop PID {pid}")
            return False
        except OSError as e:
            self.log("error", f"Failed to stop PID {pid}: {e}")
            return False

    def clean_pid_file(self) -> bool:
        """Remove stale PID file"""
        pid_path = Path(PID_FILE)
        if pid_path.exists():
            try:
                pid_path.unlink()
                self.log("info", "Cleaned up PID file")
                return True
            except OSError as e:
                self.log("error", f"Failed to clean PID file: {e}")
                return False
        return True

    def kill_duplicate_bots(self, keep_newest: bool = False) -> int:
        """Kill duplicate bot instances, keep oldest (or newest) one"""
        bots = self.find_all_bot_processes()

        if len(bots) <= 1:
            return 0

        killed = 0

        # Decide which to keep
        if keep_newest:
            # Keep newest, kill older ones
            bots_to_kill = bots[:-1]
            keeper = bots[-1]
        else:
            # Keep oldest, kill newer ones (default - original instance wins)
            bots_to_kill = bots[1:]
            keeper = bots[0]

        self.log(
            "warning",
            f"Found {len(bots)} bot instances! "
            f"Keeping PID {keeper['pid']}, killing {len(bots_to_kill)} others",
        )

        for bot in bots_to_kill:
            if bot["pid"] != self.my_pid:  # Don't kill ourselves
                if self.kill_process(bot["pid"]):
                    killed += 1

        return killed

    def kill_duplicate_watchers(self) -> int:
        """Kill duplicate dev_watcher instances, keep oldest"""
        watchers = self.find_all_dev_watchers()

        if len(watchers) <= 1:
            return 0

        killed = 0
        # Keep oldest watcher
        watchers_to_kill = watchers[1:]

        self.log(
            "warning",
            f"Found {len(watchers)} dev_watcher instances! "
            f"Killing {len(watchers_to_kill)} duplicates",
        )

        for watcher in watchers_to_kill:
            if watcher["pid"] != self.my_pid and self.kill_process(watcher["pid"]):
                killed += 1

        return killed

    def find_launcher_processes(self) -> list[int]:
        """Find CMD/batch launcher processes that auto-restart bots"""
        launcher_pids = set()
        bots = self.find_all_bot_processes()
        watchers = self.find_all_dev_watchers()

        # Get parent PIDs of all bot processes
        for bot in bots:
            try:
                proc = bot["process"]
                parent = proc.parent()
                if parent:
                    try:
                        parent_name = parent.name().lower()
                        # CMD or PowerShell running batch files can auto-restart
                        if parent_name in ["cmd.exe", "powershell.exe", "pwsh.exe"]:
                            launcher_pids.add(parent.pid)
                            self.log(
                                "info",
                                f"Found launcher: {parent_name} (PID {parent.pid}) "
                                f"for bot PID {bot['pid']}",
                            )
                    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                        # Parent process may have terminated or no name attribute
                        continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Get parent PIDs of all watcher processes
        for watcher in watchers:
            try:
                proc = watcher["process"]
                parent = proc.parent()
                if parent:
                    try:
                        parent_name = parent.name().lower()
                        if parent_name in ["cmd.exe", "powershell.exe", "pwsh.exe"]:
                            launcher_pids.add(parent.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                        # Parent process may have terminated or no name attribute
                        continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return list(launcher_pids)

    def kill_all_bots(self, kill_launchers: bool = True) -> int:
        """Kill ALL bot instances and their launcher processes"""
        bots = self.find_all_bot_processes()
        killed = 0

        # First, find and kill launcher processes (CMD windows with restart loops)
        if kill_launchers:
            launcher_pids = self.find_launcher_processes()
            for launcher_pid in launcher_pids:
                if launcher_pid != self.my_pid:
                    self.log("info", f"Killing launcher process PID {launcher_pid}")
                    self.kill_process(launcher_pid)

        # Then kill bot processes
        for bot in bots:
            if bot["pid"] != self.my_pid and self.kill_process(bot["pid"]):
                killed += 1

        self.clean_pid_file()
        return killed

    def kill_all_watchers(self) -> int:
        """Kill ALL dev_watcher instances"""
        watchers = self.find_all_dev_watchers()
        killed = 0

        for watcher in watchers:
            if watcher["pid"] != self.my_pid and self.kill_process(watcher["pid"]):
                killed += 1

        return killed

    # ==================== AUTO-HEAL ====================

    def auto_heal(self, aggressive: bool = False) -> dict:
        """
        Automatically diagnose and fix issues.

        Args:
            aggressive: If True, kill everything and restart.

        Returns:
            Dict with healing results
        """
        heal_results = {
            "timestamp": datetime.datetime.now().isoformat(),
            "diagnosis": None,
            "actions": [],
            "success": True,
            "summary": "",
        }

        self.log("info", f"=== Auto-Heal Started (aggressive={aggressive}) ===")

        # Step 1: Diagnose
        diag_data = self.diagnose()
        heal_results["diagnosis"] = diag_data

        if not diag_data["issues"]:
            heal_results["summary"] = "System healthy, no issues found"
            self.log("info", "No issues found - system healthy")
            return heal_results

        self.log("warning", f"Found {len(diag_data['issues'])} issues to fix")

        # Step 2: Execute recommendations
        for rec in diag_data["recommendations"]:
            action_result = {"action": rec, "success": False, "details": ""}

            try:
                if rec == "KILL_DUPLICATE_BOTS":
                    if aggressive:
                        # Kill all except the one that will start fresh
                        killed_count = self.kill_all_bots()
                        action_result["details"] = f"Killed all {killed_count} bot instances"
                    else:
                        # Keep oldest, kill duplicates
                        killed_count = self.kill_duplicate_bots(keep_newest=False)
                        action_result["details"] = f"Killed {killed_count} duplicate bot(s)"
                    action_result["success"] = True

                elif rec == "KILL_DUPLICATE_WATCHERS":
                    killed_count = self.kill_duplicate_watchers()
                    action_result["details"] = f"Killed {killed_count} duplicate watcher(s)"
                    action_result["success"] = True

                elif rec == "CLEAN_PID_FILE":
                    self.clean_pid_file()
                    action_result["details"] = "Cleaned stale PID file"
                    action_result["success"] = True

            except (psutil.Error, OSError) as e:
                action_result["details"] = f"Error: {e}"
                heal_results["success"] = False

            heal_results["actions"].append(action_result)
            self.log("info", f"Action {rec}: {action_result['details']}")

        # Generate summary
        successful_actions = sum(1 for a in heal_results["actions"] if a["success"])
        total_actions = len(heal_results["actions"])
        heal_results["summary"] = f"Resolved {successful_actions}/{total_actions} issues"

        self.log("info", f"=== Auto-Heal Complete: {heal_results['summary']} ===")

        return heal_results

    def ensure_single_instance(self, kill_existing: bool = True) -> tuple[bool, str]:
        """
        Ensure only one instance is running.

        Args:
            kill_existing: True to kill old instances, False to abort if exists.

        Returns:
            (can_proceed, message)
        """
        bots = self.find_all_bot_processes()

        # Filter out ourselves
        other_bots = [b for b in bots if b["pid"] != self.my_pid]

        if not other_bots:
            self.log("info", "No other bot instances found - OK to proceed")
            return True, "No other instances found - Starting..."

        if kill_existing:
            self.log("warning", f"Found {len(other_bots)} existing instance(s) - killing them")

            # Also kill any dev_watchers to prevent auto-restart
            watchers = self.find_all_dev_watchers()
            other_watchers = [w for w in watchers if w["pid"] != self.my_pid]

            for watcher in other_watchers:
                self.kill_process(watcher["pid"])

            for bot in other_bots:
                self.kill_process(bot["pid"])

            self.clean_pid_file()
            time.sleep(1)  # Wait for resources to be released

            return True, f"Stopped {len(other_bots)} old instances - Restarting..."

        if other_bots:
            pid = other_bots[0]["pid"]
            self.log("info", f"Instance already running (PID: {pid}) - aborting new instance")
            return False, f"Instance already running (PID: {pid})"
        return False, "Unknown error: no instances found but check failed"

    def get_status_report(self) -> str:
        """Get human-readable status report"""
        diag_data = self.diagnose()

        lines = [
            "+========================================+",
            "|     [BOT] Self-Healer Report          |",
            "+========================================+",
        ]

        # Bot processes
        bots = diag_data["bot_processes"]
        if bots:
            lines.append(f"|  Bot Instances: {len(bots):<22}|")
            for b in bots[:3]:  # Show max 3
                lines.append(f"|    - PID {b['pid']:<28}|")
        else:
            lines.append("|  Bot Instances: 0 (not running)        |")

        # Dev watchers
        watchers = diag_data["dev_watchers"]
        if watchers:
            lines.append(f"|  Dev Watchers: {len(watchers):<23}|")

        # Issues
        issues = diag_data["issues"]
        if issues:
            lines.append("+========================================+")
            lines.append(f"|  [!] Issues Found: {len(issues):<19}|")
            for issue in issues[:3]:
                lines.append(f"|    - {issue['type']:<32}|")
        else:
            lines.append("+========================================+")
            lines.append("|  [OK] No issues detected               |")

        lines.append("+========================================+")

        return "\n".join(lines)


# ==================== CONVENIENCE FUNCTIONS ====================


def quick_heal(caller: str = "unknown") -> dict:
    """Quick function to auto-heal the system"""
    healer_obj = SelfHealer(caller)
    return healer_obj.auto_heal()


def ensure_single_bot(caller: str = "unknown", kill_existing: bool = True) -> tuple[bool, str]:
    """Quick function to ensure only one bot instance"""
    healer_obj = SelfHealer(caller)
    return healer_obj.ensure_single_instance(kill_existing)


def get_system_status(caller: str = "unknown") -> str:
    """Quick function to get system status"""
    healer_obj = SelfHealer(caller)
    return healer_obj.get_status_report()


def kill_everything(caller: str = "unknown") -> dict:
    """Nuclear option - kill all bot-related processes"""
    healer_obj = SelfHealer(caller)

    bots_killed = healer_obj.kill_all_bots()
    watchers_killed = healer_obj.kill_all_watchers()
    healer_obj.clean_pid_file()

    return {"bots_killed": bots_killed, "watchers_killed": watchers_killed, "success": True}


# ==================== CLI ====================


def main():
    """CLI Entry point"""

    parser = argparse.ArgumentParser(description="Bot Self-Healer System")
    parser.add_argument("--diagnose", action="store_true", help="Run diagnosis only")
    parser.add_argument("--heal", action="store_true", help="Auto-heal issues")
    parser.add_argument("--aggressive", action="store_true", help="Aggressive healing (kill all)")
    parser.add_argument("--status", action="store_true", help="Show status report")
    parser.add_argument("--kill-all", action="store_true", help="Kill all bot processes")

    args = parser.parse_args()

    main_healer = SelfHealer("cli")

    if args.diagnose:
        diagnosis_result = main_healer.diagnose()
        print(json.dumps(diagnosis_result, indent=2, default=str))

    elif args.heal:
        results = main_healer.auto_heal(aggressive=args.aggressive)
        # Safe print for Windows
        try:
            print(f"\n{results['summary']}")
            for action_item in results["actions"]:
                status_str = "[OK]" if action_item["success"] else "[X]"
                print(f"  {status_str} {action_item['action']}: {action_item['details']}")
        except UnicodeEncodeError:
            # Fallback for systems that can't handle unicode
            print(f"\n{results['summary'].encode('ascii', 'replace').decode()}")
            for action_item in results["actions"]:
                status_str = "[OK]" if action_item["success"] else "[X]"
                cleaned_details = str(action_item["details"]).encode("ascii", "replace").decode()
                print(f"  {status_str} {action_item['action']}: {cleaned_details}")

    elif args.status:
        try:
            print(main_healer.get_status_report())
        except UnicodeEncodeError:
            print(
                "[Info] Status report contains unicode characters "
                "and cannot be displayed in this terminal."
            )

    elif args.kill_all:
        kill_result = kill_everything("cli")
        print(
            f"Killed {kill_result['bots_killed']} bots "
            f"and {kill_result['watchers_killed']} watchers"
        )

    else:
        # Default: show status
        try:
            print(main_healer.get_status_report())
        except UnicodeEncodeError:
            print(
                "[Info] Status report contains unicode characters "
                "and cannot be displayed in this terminal."
            )


if __name__ == "__main__":
    main()
