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
import contextlib
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

import psutil

# Constants — PID_FILE anchored to the repo root, matching bot.py's own
# anchoring (a CWD-relative "bot.pid" silently broke stale-PID detection
# whenever the process was launched from another directory: systemd,
# dashboard wrapper, IDE run configs).
PID_FILE = str(Path(__file__).resolve().parents[2] / "bot.pid")
# Repo-root-anchored for the same reason as PID_FILE above: a CWD-relative
# "logs/self_healer.log" scattered the diagnostic trail under whatever
# directory the bot/healer happened to be launched from (systemd, the
# dashboard wrapper, an IDE), and scripts/bot_manager.py reads it at the
# repo-root path.
HEALER_LOG_FILE = str(Path(__file__).resolve().parents[2] / "logs" / "self_healer.log")

# Authorization gate for bulk-kill operations. Without this, a stray
# `import utils.reliability.self_healer; kill_everything()` from any module
# (or a third-party plugin) could nuke the running bot tree without consent.
# Callers must either pass ``authorized=True`` explicitly or set
# SELF_HEALER_ALLOW_KILL=1 in the environment.
_KILL_AUTH_ENV_VAR = "SELF_HEALER_ALLOW_KILL"


def _kill_authorized(authorized: bool) -> tuple[bool, str]:
    """Return (allowed, reason) for a bulk-kill operation."""
    if authorized:
        return True, "explicit authorized=True"
    env_val = os.environ.get(_KILL_AUTH_ENV_VAR, "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        return True, f"{_KILL_AUTH_ENV_VAR}={env_val}"
    return False, (
        f"Refusing bulk-kill: pass authorized=True or set {_KILL_AUTH_ENV_VAR}=1 to confirm."
    )


# Lockfile for serialising single-instance enforcement (see
# ``_singleton_enforcement_lock``). Separate from PID_FILE — it's an OS advisory
# lock, never read for content. Repo-root-anchored like PID_FILE: a
# CWD-relative path would let two bots launched from different working
# directories open two different lock files, so the advisory lock (bound to the
# open file object) would provide no mutual exclusion and both would proceed
# into the kill step — the exact mutual-kill race this lock prevents.
_SINGLETON_LOCK_FILE = str(Path(__file__).resolve().parents[2] / "bot.singleton.lock")


@contextlib.contextmanager
def _singleton_enforcement_lock(timeout: float = 5.0):
    """Hold an OS advisory lock during single-instance enforcement.

    Two bots starting at the same instant would otherwise each see the other as
    "an existing instance" and kill it — leaving BOTH dead. Serialising the
    kill step fixes that: the first holder kills the rest and survives; the
    others are killed (or find nothing to do) before they enforce.

    Two safety properties make this safe to add to the startup-critical path:

    * **Stale-safe** — it's an OS advisory lock (``msvcrt`` on Windows,
      ``fcntl`` on POSIX), automatically released when the holding process
      exits. A crash can never leave a lock that blocks future starts.
    * **Fails open** — if locking is unavailable or errors for any reason we
      yield anyway, so startup is never blocked (worst case = the previous
      no-lock behaviour).

    Yields ``True`` if the lock was actually held, ``False`` if we proceeded
    without it.
    """
    fh = None
    locked = False
    try:
        fh = Path(_SINGLETON_LOCK_FILE).open("a+")  # noqa: SIM115 — closed in finally
        deadline = time.time() + timeout
        if sys.platform == "win32":
            import msvcrt

            while time.time() < deadline:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    time.sleep(0.1)
        else:
            import fcntl

            while time.time() < deadline:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    time.sleep(0.1)
    except Exception:
        # Fail open — never block startup because of a locking problem.
        locked = False
    try:
        yield locked
    finally:
        if fh is not None:
            if locked:
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        fh.seek(0)
                        with contextlib.suppress(OSError):
                            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        with contextlib.suppress(OSError):
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            with contextlib.suppress(Exception):
                fh.close()


class SelfHealer:
    """Automatic Bot Problem Detection and Correction System"""

    def __init__(self, caller_script: str = "unknown"):
        self.caller_script = caller_script
        self.my_pid = os.getpid()
        self.actions_taken: list[str] = []
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Setup dedicated logger for self-healer"""
        logger = logging.getLogger("SelfHealer")
        logger.setLevel(logging.DEBUG)

        # Create logs directory if not exists (anchored to HEALER_LOG_FILE so
        # it lands at the repo root, not the launch CWD).
        log_dir = Path(HEALER_LOG_FILE).parent
        log_dir.mkdir(parents=True, exist_ok=True)

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
        """Find ALL bot.py processes with details.

        Handles races where a process exits between ``process_iter`` yielding
        it and our calls back into psutil. The catch lists cover every
        psutil-raised condition we've actually observed in the wild
        (NoSuchProcess on exit; AccessDenied on protected procs;
        ZombieProcess on Linux when a child has exited but not been reaped;
        and the generic psutil.Error catch-all for transient platform
        errors). Without these, a single process exit during enumeration
        propagates out and aborts the whole sweep.
        """
        bot_processes = []

        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue

                # Look for Python processes running a script that is exactly 'bot.py'
                cmdline_str = " ".join(cmdline).lower()
                if "python" not in cmdline_str:
                    continue

                # Check each argument for an exact 'bot.py' script name.
                # The exact basename match already rejects false positives like
                # 'test_bot.py' or 'bot.py_backup'; a real `python bot.py` whose
                # path merely contains a token like 'test_' (e.g.
                # C:\test_env\bot.py) is correctly kept, so duplicate detection
                # never undercounts. Use PurePosixPath().name so the check works
                # on both Windows (\) and POSIX (/) paths regardless of host.
                is_bot = False
                for arg in cmdline:
                    name = PurePosixPath(arg.replace("\\", "/")).name
                    if name.lower() == "bot.py":
                        is_bot = True
                        break

                if is_bot:
                    # ``psutil.Process(pid)`` itself can raise NoSuchProcess
                    # if the process exited between ``process_iter`` yielding
                    # us its info dict and this call.
                    try:
                        proc_handle = psutil.Process(proc.info["pid"])
                    except psutil.NoSuchProcess:
                        continue
                    bot_processes.append(
                        {
                            "pid": proc.info["pid"],
                            "cmdline": cmdline_str,
                            "create_time": proc.info.get("create_time", 0),
                            "process": proc_handle,
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except psutil.Error:
                # Any other transient psutil error — skip this process,
                # don't abort the enumeration.
                continue

        # Sort by creation time (oldest first)
        bot_processes.sort(key=lambda x: x["create_time"])

        # Filter out venv launcher/redirector processes (Python 3.12+).
        # On Windows, .venv/Scripts/python.exe is a small launcher that spawns
        # the real python.exe as a child with identical arguments.  Both appear
        # as "python running bot.py" but only the child is the real instance.
        if len(bot_processes) > 1:
            bot_pids = {b["pid"] for b in bot_processes}
            launcher_pids: set[int] = set()
            for b in bot_processes:
                try:
                    ppid = psutil.Process(b["pid"]).ppid()
                    if ppid in bot_pids:
                        launcher_pids.add(ppid)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process exited between enumeration and ppid lookup —
                    # safe to skip, the row will simply not be flagged as
                    # a launcher.
                    continue
                except psutil.Error:
                    continue
            if launcher_pids:
                bot_processes = [b for b in bot_processes if b["pid"] not in launcher_pids]

        return bot_processes

    def find_all_dev_watchers(self) -> list[dict]:
        """Find ALL dev_watcher.py processes"""
        watchers = []

        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue
                cmdline_str = " ".join(cmdline).lower()
                if "python" not in cmdline_str:
                    continue

                # Exact basename match, mirroring find_all_bot_processes.
                # A loose "dev_watcher" substring test would also match e.g.
                # `python -m pytest tests/test_dev_watcher.py`, so a heal action
                # could kill the test runner or other unrelated processes that
                # merely reference the name; the exact basename match avoids that.
                is_watcher = False
                for arg in cmdline:
                    name = PurePosixPath(arg.replace("\\", "/")).name
                    if name.lower() == "dev_watcher.py":
                        is_watcher = True
                        break

                if is_watcher:
                    # Wrap the late `psutil.Process(pid)` lookup in the same
                    # NoSuchProcess guard as `find_all_bot_processes`; if
                    # the watcher exits between `process_iter` yielding it
                    # and our follow-up call, NoSuchProcess would otherwise
                    # bubble up and abort the entire scan.
                    try:
                        proc_obj = psutil.Process(proc.info["pid"])
                    except psutil.NoSuchProcess:
                        continue
                    watchers.append(
                        {
                            "pid": proc.info["pid"],
                            "cmdline": cmdline_str,
                            "create_time": proc.info.get("create_time", 0),
                            "process": proc_obj,
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except psutil.Error:
                # Any other transient psutil error — skip this process,
                # don't abort the enumeration.
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
        diag_data: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
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

        # Check PID file validity. find_all_bot_processes strips venv-launcher
        # PIDs from `bots`, so a still-live launcher PID written to bot.pid would
        # be misread as STALE_PID_FILE and trigger a spurious CLEAN_PID_FILE.
        # Fall back to a liveness check so a filtered-but-alive PID isn't treated
        # as a dead process.
        if pid_from_file:
            diag_data["pid_file_valid"] = any(
                b["pid"] == pid_from_file for b in bots
            ) or psutil.pid_exists(pid_from_file)

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
        except psutil.TimeoutExpired:
            # kill() + wait(timeout=2) can still time out on a stuck/uninterruptible
            # process. TimeoutExpired is a psutil.Error, not OSError, so it would
            # otherwise escape kill_process and crash the admin CLI callers.
            self.log("error", f"PID {pid} did not exit after kill signal")
            return False
        except OSError as e:
            self.log("error", f"Failed to stop PID {pid}: {e}")
            return False
        except psutil.Error as e:
            # Base-class catch-all for any other psutil.Error subclass (e.g.
            # ZombieProcess on platforms where it isn't a NoSuchProcess, or a
            # future subclass). psutil.Error does NOT subclass OSError, so
            # without this an unexpected psutil failure would escape and crash
            # the startup-critical callers (ensure_single_instance, the kill
            # sweeps). Matches the file's own psutil.Error catch-all elsewhere.
            self.log("error", f"psutil error when stopping PID {pid}: {e}")
            return False

    def clean_pid_file(self, *, force: bool = False) -> bool:
        """Remove stale PID file.

        Refuses to unlink when the file points at a *live* process that is
        not us — without this, a second importer of this module could wipe
        the running bot's PID file and break the duplicate-detection guard.
        Pass ``force=True`` after an authorized bulk-kill to override.
        """
        pid_path = Path(PID_FILE)
        if not pid_path.exists():
            return True

        if not force:
            try:
                stored_pid: int | None = int(pid_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                stored_pid = None
            if (
                stored_pid is not None
                and stored_pid != self.my_pid
                and psutil.pid_exists(stored_pid)
            ):
                self.log(
                    "warning",
                    f"Refusing to clean PID file: PID {stored_pid} is alive "
                    "and not our process. Pass force=True to override.",
                )
                return False

        try:
            pid_path.unlink(missing_ok=True)
            self.log("info", "Cleaned up PID file")
            return True
        except OSError as e:
            self.log("error", f"Failed to clean PID file: {e}")
            return False

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

    @staticmethod
    def _is_launcher_script(parent: psutil.Process) -> bool:
        """Return True only if the parent shell is clearly running a launcher
        script (a .bat/.cmd/.ps1 file), not an interactive terminal session.

        We refuse to treat a plain `cmd.exe` / `powershell.exe` as a launcher
        because that would include VS Code terminals, Windows Terminal tabs,
        etc. — killing those destroys the user's interactive session.
        """
        try:
            cmdline = [str(arg).lower() for arg in parent.cmdline()]
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            return False
        # Any cmdline token that ends with a script extension signals an
        # auto-restart wrapper (e.g. `start_bot.bat`, `watcher.ps1`).
        launcher_exts = (".bat", ".cmd", ".ps1")
        return any(arg.endswith(launcher_exts) for arg in cmdline)

    def find_launcher_processes(self) -> list[int]:
        """Find CMD/batch launcher processes that auto-restart bots.

        Only processes whose cmdline includes a .bat/.cmd/.ps1 script qualify;
        plain interactive shells are skipped so we never close a user's
        VS Code terminal / Windows Terminal tab.
        """
        launcher_pids = set()
        bots = self.find_all_bot_processes()
        watchers = self.find_all_dev_watchers()
        shell_names = {"cmd.exe", "powershell.exe", "pwsh.exe"}

        def _inspect(proc_entry: dict) -> None:
            try:
                parent = proc_entry["process"].parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            if parent is None:
                return
            try:
                parent_name = parent.name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                return
            if parent_name not in shell_names:
                return
            if not self._is_launcher_script(parent):
                # Interactive terminal — leave it alone
                return
            launcher_pids.add(parent.pid)
            self.log(
                "info",
                f"Found launcher: {parent_name} (PID {parent.pid}) for PID {proc_entry['pid']}",
            )

        for bot in bots:
            _inspect(bot)
        for watcher in watchers:
            _inspect(watcher)

        return list(launcher_pids)

    def kill_all_bots(self, kill_launchers: bool = True, *, authorized: bool = False) -> int:
        """Kill ALL bot instances and their launcher processes.

        Destructive — gated by ``_kill_authorized`` (pass ``authorized=True``
        or set ``SELF_HEALER_ALLOW_KILL=1``). Returns 0 when the gate denies.
        """
        ok, reason = _kill_authorized(authorized)
        if not ok:
            self.log("error", reason)
            return 0

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

        # force=True is safe here: we just authorized killing every bot.
        self.clean_pid_file(force=True)
        return killed

    def kill_all_watchers(self, *, authorized: bool = False) -> int:
        """Kill ALL dev_watcher instances.

        Destructive — gated by ``_kill_authorized``.
        """
        ok, reason = _kill_authorized(authorized)
        if not ok:
            self.log("error", reason)
            return 0

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
        heal_results: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
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

        # Step 2: Execute recommendations. De-dup first: a single condition (e.g.
        # a PID file with no running bots) can be flagged by two diagnostic checks
        # (STALE_PID_FILE + ORPHAN_PID_FILE), both appending CLEAN_PID_FILE — so
        # without dedup the action runs twice and inflates the action counters.
        for rec in dict.fromkeys(diag_data["recommendations"]):
            action_result = {"action": rec, "success": False, "details": ""}

            try:
                if rec == "KILL_DUPLICATE_BOTS":
                    if aggressive:
                        # ``aggressive=True`` is the caller's explicit consent
                        # to nuke every instance, so we forward that as the
                        # bulk-kill authorization.
                        killed_count = self.kill_all_bots(authorized=True)
                        action_result["details"] = f"Killed all {killed_count} bot instances"
                    else:
                        # Keep the NEWEST instance, kill older duplicates. This
                        # matches ensure_single_instance (the restart path keeps
                        # the freshly-started process), so a git-pull+restart —
                        # or auto-heal racing that restart — doesn't kill the new
                        # process and leave a stale one running.
                        killed_count = self.kill_duplicate_bots(keep_newest=True)
                        action_result["details"] = f"Killed {killed_count} duplicate bot(s)"
                    # Success = duplicates are actually GONE. kill_process can
                    # fail per-PID (AccessDenied → False) with no exception, so
                    # a blind True let smart_startup_check print "[OK] Resolved"
                    # and boot a second instance alongside the survivor.
                    remaining = self.find_all_bot_processes()
                    action_result["success"] = len(remaining) <= (0 if aggressive else 1)
                    if not action_result["success"]:
                        action_result["details"] += (
                            f" — {len(remaining)} instance(s) still running (kill failed?)"
                        )
                        heal_results["success"] = False

                elif rec == "KILL_DUPLICATE_WATCHERS":
                    killed_count = self.kill_duplicate_watchers()
                    action_result["details"] = f"Killed {killed_count} duplicate watcher(s)"
                    # Mirror the bots branch: verify the duplicates are actually
                    # gone. kill_process can fail per-PID (AccessDenied → False)
                    # with no exception, so a blind True would overstate the heal.
                    remaining = self.find_all_dev_watchers()
                    action_result["success"] = len(remaining) <= 1
                    if not action_result["success"]:
                        action_result["details"] += (
                            f" — {len(remaining)} watcher(s) still running (kill failed?)"
                        )
                        heal_results["success"] = False

                elif rec == "CLEAN_PID_FILE":
                    # Honor the return value: clean_pid_file() refuses (returns
                    # False) when the PID points to a live non-bot process, so a
                    # blind success=True would falsely report a heal that didn't
                    # happen.
                    cleaned = self.clean_pid_file()
                    action_result["success"] = cleaned
                    action_result["details"] = (
                        "Cleaned stale PID file"
                        if cleaned
                        else "PID file left in place (points to a live non-bot process)"
                    )
                    if not cleaned:
                        heal_results["success"] = False

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
            # Serialise the kill with an OS advisory lock so two bots starting
            # simultaneously don't kill EACH OTHER (each would otherwise see the
            # other as an existing instance). Stale-safe + fails open.
            with _singleton_enforcement_lock():
                # Re-scan inside the lock: a concurrent start that ran just
                # before us may already have cleared the duplicates, in which
                # case we must NOT kill (there's nothing left but us).
                bots_now = self.find_all_bot_processes()
                other_now = [b for b in bots_now if b["pid"] != self.my_pid]
                if not other_now:
                    self.log(
                        "info", "Duplicates already cleared by a concurrent start - proceeding"
                    )
                    return True, "No other instances found - Starting..."

                self.log("warning", f"Found {len(other_now)} existing instance(s) - killing them")

                # Also kill any dev_watchers to prevent auto-restart — but
                # NEVER our own parent: a bot spawned by dev_watcher (the
                # documented dev flow) would otherwise kill its own watcher
                # and destroy hot-reload (diagnose() documents this rule).
                parent_pid = os.getppid()
                watchers = self.find_all_dev_watchers()
                other_watchers = [w for w in watchers if w["pid"] not in (self.my_pid, parent_pid)]

                for watcher in other_watchers:
                    self.kill_process(watcher["pid"])

                survivors = [bot["pid"] for bot in other_now if not self.kill_process(bot["pid"])]

                self.clean_pid_file()
                time.sleep(1)  # Wait for resources to be released

                # Confirm the kills actually took. kill_process returns False on
                # AccessDenied / post-kill TimeoutExpired; re-check liveness
                # after the settle delay so a process that was merely slow to
                # exit isn't counted as a survivor. If a duplicate is still
                # alive, report failure so the caller aborts instead of running
                # concurrently with it — the exact condition this guard prevents.
                survivors = [pid for pid in survivors if psutil.pid_exists(pid)]
                if survivors:
                    self.log("error", f"Could not stop existing instance(s): {survivors}")
                    return False, f"Could not stop existing instance(s): {survivors}"

                return True, f"Stopped {len(other_now)} old instances - Restarting..."

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


def kill_everything(caller: str = "unknown", *, authorized: bool = False) -> dict:
    """Nuclear option - kill all bot-related processes.

    Destructive — gated by ``_kill_authorized``. Returns zeroed counters
    when the gate denies, so accidental imports cannot trigger the kill.
    """
    healer_obj = SelfHealer(caller)

    ok, reason = _kill_authorized(authorized)
    if not ok:
        healer_obj.log("error", reason)
        return {"bots_killed": 0, "watchers_killed": 0, "success": False, "reason": reason}

    bots_killed = healer_obj.kill_all_bots(authorized=True)
    watchers_killed = healer_obj.kill_all_watchers(authorized=True)
    healer_obj.clean_pid_file(force=True)

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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the y/N confirmation prompt for --kill-all (use with care)",
    )

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
        if not args.force:
            print(
                "[!] WARNING: This will terminate ALL bot, watcher, and "
                "launcher processes on this host."
            )
            try:
                answer = input("    Type 'yes' to proceed: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("Aborted.")
                sys.exit(1)
            if answer != "yes":
                print("Aborted.")
                sys.exit(0)
        kill_result = kill_everything("cli", authorized=True)
        if kill_result.get("success"):
            print(
                f"Killed {kill_result['bots_killed']} bots "
                f"and {kill_result['watchers_killed']} watchers"
            )
        else:
            print(f"Refused: {kill_result.get('reason', 'authorization denied')}")
            sys.exit(1)

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
