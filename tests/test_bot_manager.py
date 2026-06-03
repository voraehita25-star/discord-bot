# pylint: disable=protected-access
"""
Unit Tests for the Bot Manager launcher script (scripts/bot_manager.py).

Covers the pure / easily-mockable helpers only — the interactive TUI loop
(main(), print_menu(), print_status(), run_self_healer(), run_kill_all()) is
deliberately NOT exercised since it is terminal/process I/O.

Tested surface:
- Display-width + box-drawing helpers (get_display_width, pad_line, box_*).
- Process discovery / filtering (_find_processes, find_all_bot_processes,
  find_all_dev_watcher_processes) with psutil.process_iter mocked.
- Launcher identification (_get_launcher_info, detect_launcher).
- Status aggregation (get_bot_status) with psutil mocked.
- Process stopping (stop_process_list) and confirmation gating
  (auto_stop_existing_bot) with psutil/input/env/time mocked.
- Script launching (_launch_script) with os.startfile/subprocess mocked.
- Tail-from-end log reader (_tail_lines) against tmp_path files.

Everything is hermetic: no real processes, no real sleeps, no real network.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import psutil
import pytest

from scripts import bot_manager as bm


def _strip_ansi(text: str) -> str:
    """Remove ANSI colour escape codes so we can assert on raw content."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _make_iter_proc(pid, name, cmdline):
    """Build a process suitable for psutil.process_iter (uses ``.info``)."""
    proc = MagicMock()
    proc.info = {"pid": pid, "name": name, "cmdline": cmdline}
    return proc


def _make_obj_proc(name, cmdline):
    """Build a process exposing ``.name()`` / ``.cmdline()`` callables."""
    proc = MagicMock()
    proc.name.return_value = name
    proc.cmdline.return_value = cmdline
    return proc


# ==================== get_display_width ====================


class TestGetDisplayWidth:
    """Tests for get_display_width."""

    def test_plain_ascii(self):
        assert bm.get_display_width("hello") == 5

    def test_empty_string(self):
        assert bm.get_display_width("") == 0

    def test_ansi_codes_are_ignored(self):
        # "\033[31mred\033[0m" -> just "red" counts.
        assert bm.get_display_width("\033[31mred\033[0m") == 3

    def test_emoji_counts_as_two(self):
        # One ASCII letter + one emoji + one ASCII letter -> 1 + 2 + 1.
        assert bm.get_display_width("A\U0001f600B") == 4

    def test_zero_width_space_ignored(self):
        # ZWSP (U+200B) between two letters contributes nothing.
        assert bm.get_display_width("a\u200bb") == 2

    def test_thai_base_char_width_one(self):
        # Thai consonant (base char) counts as width 1.
        assert bm.get_display_width("ก") == 1

    def test_thai_combining_mark_ignored(self):
        # Base consonant + tone mark (combining, 0x0E48) -> width 1, not 2.
        assert bm.get_display_width("ก่") == 1

    def test_box_drawing_char_width_one(self):
        # Box-drawing glyphs (0x2500-0x257F) deliberately count as 1.
        assert bm.get_display_width("─") == 1

    def test_fullwidth_char_counts_as_two(self):
        # Fullwidth Latin A (U+FF21) is East-Asian-Wide -> width 2.
        assert bm.get_display_width("Ａ") == 2

    def test_variation_selector_ignored(self):
        # Variation selector (U+FE0F) is in the zero-width range, so it adds 0.
        # The heart U+2764 is itself in EMOJI_RANGES (width 2), giving 2 total —
        # i.e. the selector contributes nothing on top of the emoji.
        assert bm.get_display_width("❤️") == 2
        # A bare variation selector by itself contributes nothing.
        assert bm.get_display_width("️") == 0


# ==================== box / pad helpers ====================


class TestPadLine:
    """Tests for pad_line."""

    def test_left_align_pads_to_width(self):
        out = _strip_ansi(bm.pad_line("hi", 10))
        # ║ + "hi" + 8 spaces + ║
        assert out == "║hi        ║"

    def test_center_align_distributes_padding(self):
        out = _strip_ansi(bm.pad_line("hi", 10, "center"))
        assert out == "║    hi    ║"

    def test_overlong_text_never_negative_padding(self):
        # Text wider than width: max(0, ...) keeps it from breaking the border.
        out = _strip_ansi(bm.pad_line("toolongtext", 3))
        assert out == "║toolongtext║"

    def test_keeps_border_characters(self):
        out = bm.pad_line("x", 5)
        assert out.count("║") == 2


class TestBoxBorders:
    """Tests for box_top / box_mid / box_bottom / box_header."""

    def test_box_top(self):
        assert _strip_ansi(bm.box_top(5)) == "╔" + "═" * 5 + "╗"

    def test_box_mid(self):
        assert _strip_ansi(bm.box_mid(5)) == "╠" + "═" * 5 + "╣"

    def test_box_bottom(self):
        assert _strip_ansi(bm.box_bottom(5)) == "╚" + "═" * 5 + "╝"

    def test_box_header_is_centered(self):
        out = _strip_ansi(bm.box_header("X", 9))
        assert out == "║    X    ║"

    def test_default_width_used(self):
        # Default BOX_WIDTH worth of horizontal bars between corners.
        out = _strip_ansi(bm.box_top())
        assert out.count("═") == bm.BOX_WIDTH


# ==================== _find_processes / finders ====================


class TestFindProcesses:
    """Tests for _find_processes and the public finders."""

    def test_matches_all_terms_not_any(self):
        procs = [
            _make_iter_proc(1, "python", ["python", "bot.py"]),
            _make_iter_proc(2, "node", ["node", "server.js"]),  # missing "python"
        ]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            result = bm._find_processes(["python"])
        assert result == [1]

    def test_exclude_terms_filter_out(self):
        procs = [
            _make_iter_proc(1, "python", ["python", "bot.py"]),
            _make_iter_proc(2, "python", ["python", "bot_manager.py"]),
        ]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            result = bm._find_processes(["python"], ["bot_manager"])
        assert result == [1]

    def test_exact_basename_avoids_substring_trap(self):
        # A path that merely *contains* "bot.py" as a substring must NOT match
        # an exact-basename request for bot.py.
        procs = [
            _make_iter_proc(1, "python", ["python", "C:/x/bot.py"]),
            _make_iter_proc(2, "python", ["python", "C:/my-bot.py-fork/run.py"]),
        ]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            result = bm._find_processes(["python"], exact_basenames=["bot.py"])
        assert result == [1]

    def test_non_project_python_processes_excluded(self):
        procs = [
            _make_iter_proc(1, "python", ["python", "/path/vscode/ms-python/x.py", "bot.py"]),
        ]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            result = bm._find_processes(["python"], exact_basenames=["bot.py"])
        assert result == []

    def test_handles_none_cmdline(self):
        # cmdline can legitimately be None for some processes.
        procs = [_make_iter_proc(1, "python", None)]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            result = bm._find_processes(["python"])
        assert result == []

    def test_no_such_process_is_skipped(self):
        bad = MagicMock()
        # Accessing .info raises during iteration handling.
        type(bad).info = property(lambda self: (_ for _ in ()).throw(psutil.NoSuchProcess(1)))
        good = _make_iter_proc(2, "python", ["python", "bot.py"])
        with patch.object(bm.psutil, "process_iter", return_value=[bad, good]):
            result = bm._find_processes(["python"])
        assert result == [2]

    def test_find_all_bot_processes(self):
        procs = [
            _make_iter_proc(1, "python", ["python", "C:/x/bot.py"]),
            _make_iter_proc(2, "python", ["python", "C:/x/scripts/bot_manager.py"]),
            _make_iter_proc(3, "python", ["python", "C:/x/scripts/dev_watcher.py"]),
        ]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            assert bm.find_all_bot_processes() == [1]

    def test_find_all_dev_watcher_processes(self):
        procs = [
            _make_iter_proc(1, "python", ["python", "bot.py"]),
            _make_iter_proc(3, "python", ["python", "scripts/dev_watcher.py"]),
        ]
        with patch.object(bm.psutil, "process_iter", return_value=procs):
            assert bm.find_all_dev_watcher_processes() == [3]


# ==================== _get_launcher_info ====================


class TestGetLauncherInfo:
    """Tests for _get_launcher_info."""

    def test_dev_watcher_detected(self):
        proc = _make_obj_proc("python", ["python", "scripts/dev_watcher.py"])
        info = bm._get_launcher_info(proc)
        assert info["type"] == "development"
        assert info["script"] == "dev_watcher.py"

    def test_start_dev_mode_bat_script_name(self):
        proc = _make_obj_proc("cmd.exe", ["cmd", "/c", "start_dev_mode.bat"])
        info = bm._get_launcher_info(proc)
        assert info["type"] == "development"
        assert info["script"] == "start_dev_mode.bat"

    def test_production_detected(self):
        proc = _make_obj_proc("cmd.exe", ["cmd", "/c", "start_bot.bat"])
        assert bm._get_launcher_info(proc)["type"] == "production"

    def test_hidden_detected_via_bot_py(self):
        # wscript pointing at bot.py (no "start_bot" substring) -> hidden.
        proc = _make_obj_proc("wscript.exe", ["wscript", "run", "bot.py"])
        info = bm._get_launcher_info(proc)
        assert info["type"] == "hidden"
        assert info["script"] == "start_bot_hidden.vbs"

    def test_unrelated_wscript_not_matched(self):
        proc = _make_obj_proc("wscript.exe", ["wscript", "something.vbs"])
        assert bm._get_launcher_info(proc) is None

    def test_scheduled_detected(self):
        proc = _make_obj_proc("svchost.exe", ["svchost", "-k", "x", "bot.py"])
        assert bm._get_launcher_info(proc)["type"] == "scheduled"

    def test_unrelated_svchost_not_matched(self):
        proc = _make_obj_proc("svchost.exe", ["svchost", "-k", "netsvcs"])
        assert bm._get_launcher_info(proc) is None

    def test_terminal_with_start_bot_is_production(self):
        proc = _make_obj_proc("powershell.exe", ["powershell", "start_bot.bat"])
        assert bm._get_launcher_info(proc)["type"] == "production"

    def test_terminal_without_start_bot_returns_none(self):
        proc = _make_obj_proc("powershell.exe", ["powershell", "foo"])
        assert bm._get_launcher_info(proc) is None

    def test_unknown_process_returns_none(self):
        proc = _make_obj_proc("explorer.exe", ["explorer"])
        assert bm._get_launcher_info(proc) is None

    def test_no_such_process_returns_none(self):
        proc = MagicMock()
        proc.cmdline.side_effect = psutil.NoSuchProcess(1)
        assert bm._get_launcher_info(proc) is None


# ==================== detect_launcher ====================


class TestDetectLauncher:
    """Tests for detect_launcher (walks the parent chain)."""

    def test_direct_parent_match(self):
        parent = _make_obj_proc("cmd.exe", ["cmd", "/c", "start_bot.bat"])
        proc = MagicMock()
        proc.parent.return_value = parent
        assert bm.detect_launcher(proc)["type"] == "production"

    def test_grandparent_match(self):
        grandparent = _make_obj_proc("cmd.exe", ["cmd", "/c", "start_bot.bat"])
        middle = _make_obj_proc("python", ["python", "x"])
        middle.parent.return_value = grandparent
        proc = MagicMock()
        proc.parent.return_value = middle
        assert bm.detect_launcher(proc)["type"] == "production"

    def test_no_parent_returns_unknown(self):
        proc = MagicMock()
        proc.parent.return_value = None
        info = bm.detect_launcher(proc)
        assert info["name"] == "Unknown"
        assert info["type"] == "unknown"

    def test_unrecognized_chain_returns_unknown(self):
        # A parent that is not a known launcher yields the Unknown default.
        parent = _make_obj_proc("explorer.exe", ["explorer"])
        parent.parent.return_value = None
        proc = MagicMock()
        proc.parent.return_value = parent
        assert bm.detect_launcher(proc)["name"] == "Unknown"

    def test_psutil_error_returns_unknown(self):
        proc = MagicMock()
        proc.parent.side_effect = psutil.NoSuchProcess(1)
        assert bm.detect_launcher(proc)["name"] == "Unknown"


# ==================== get_bot_status ====================


class TestGetBotStatus:
    """Tests for get_bot_status."""

    def test_offline_when_no_bot_processes(self):
        with (
            patch.object(bm, "find_all_bot_processes", return_value=[]),
            patch.object(bm, "find_all_dev_watcher_processes", return_value=[]),
        ):
            status = bm.get_bot_status()
        assert status["running"] is False
        assert status["pid"] is None
        assert status["all_pids"] == []
        assert status["launcher"]["name"] == "Unknown"

    def test_online_aggregates_stats(self):
        import datetime

        proc = MagicMock()
        proc.name.return_value = "python"
        proc.memory_info.return_value = MagicMock(rss=1024 * 1024 * 10)  # 10 MB
        proc.cpu_percent.return_value = 2.5
        proc.create_time.return_value = datetime.datetime(2020, 1, 1).timestamp()
        proc.cwd.return_value = "C:/x"
        with (
            patch.object(bm, "find_all_bot_processes", return_value=[42]),
            patch.object(bm, "find_all_dev_watcher_processes", return_value=[]),
            patch.object(
                bm,
                "detect_launcher",
                return_value={"name": "P", "script": "s", "type": "production", "features": []},
            ),
            patch.object(bm.psutil, "Process", return_value=proc),
        ):
            status = bm.get_bot_status()
        assert status["running"] is True
        assert status["pid"] == 42
        assert status["memory_mb"] == 10.0
        assert status["process_name"] == "python"
        assert status["launcher"]["type"] == "production"
        assert status["start_time"] is not None

    def test_dev_watcher_pids_populated(self):
        with (
            patch.object(bm, "find_all_bot_processes", return_value=[]),
            patch.object(bm, "find_all_dev_watcher_processes", return_value=[5, 6]),
        ):
            status = bm.get_bot_status()
        assert status["dev_watcher_pids"] == [5, 6]

    def test_process_vanishes_after_discovery(self):
        # find returns a PID but psutil.Process() then raises (race) — status
        # should still come back running=True with graceful fallbacks.
        with (
            patch.object(bm, "find_all_bot_processes", return_value=[99]),
            patch.object(bm, "find_all_dev_watcher_processes", return_value=[]),
            patch.object(bm.psutil, "Process", side_effect=psutil.NoSuchProcess(99)),
        ):
            status = bm.get_bot_status()
        assert status["running"] is True
        assert status["pid"] == 99
        assert status["process_name"] is None


# ==================== stop_process_list ====================


class TestStopProcessList:
    """Tests for stop_process_list (psutil + sleeps mocked)."""

    def test_empty_list_returns_zero(self):
        assert bm.stop_process_list([], "bot") == 0

    def test_graceful_terminate_counts(self):
        proc = MagicMock()
        proc.wait.return_value = None
        with patch.object(bm.psutil, "Process", return_value=proc):
            count = bm.stop_process_list([10], "bot")
        assert count == 1
        assert proc.terminate.called
        assert not proc.kill.called

    def test_timeout_triggers_force_kill(self):
        proc = MagicMock()
        # First wait (after terminate) times out, second (after kill) succeeds.
        proc.wait.side_effect = [psutil.TimeoutExpired(5), None]
        with patch.object(bm.psutil, "Process", return_value=proc):
            count = bm.stop_process_list([7], "bot")
        assert count == 1
        assert proc.kill.called

    def test_no_such_process_not_counted(self):
        with patch.object(bm.psutil, "Process", side_effect=psutil.NoSuchProcess(5)):
            assert bm.stop_process_list([5], "bot") == 0

    def test_access_denied_not_counted(self):
        with patch.object(bm.psutil, "Process", side_effect=psutil.AccessDenied(5)):
            assert bm.stop_process_list([5], "bot") == 0

    def test_os_error_during_stop_not_counted(self):
        proc = MagicMock()
        proc.terminate.side_effect = OSError("boom")
        with patch.object(bm.psutil, "Process", return_value=proc):
            assert bm.stop_process_list([3], "bot") == 0

    def test_counts_multiple_processes(self):
        proc = MagicMock()
        proc.wait.return_value = None
        with patch.object(bm.psutil, "Process", return_value=proc):
            assert bm.stop_process_list([1, 2, 3], "bot") == 3


# ==================== auto_stop_existing_bot ====================


class TestAutoStopExistingBot:
    """Tests for auto_stop_existing_bot confirmation gating."""

    def test_not_running_returns_true(self):
        assert bm.auto_stop_existing_bot({"running": False}) is True

    def test_assume_yes_stops_without_prompt(self):
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": [2]}
        with (
            patch.object(bm, "stop_process_list") as stop,
            patch.object(bm.time, "sleep"),
            patch.object(bm.Path, "unlink"),
        ):
            result = bm.auto_stop_existing_bot(status, assume_yes=True)
        assert result is True
        assert stop.call_count == 2  # dev_watcher list + bot list

    def test_env_var_bypasses_prompt(self, monkeypatch):
        monkeypatch.setenv("BOT_MANAGER_ASSUME_YES", "1")
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": []}
        with (
            patch.object(bm, "stop_process_list") as stop,
            patch.object(bm.time, "sleep"),
            patch.object(bm.Path, "unlink"),
        ):
            result = bm.auto_stop_existing_bot(status)
        assert result is True
        assert stop.call_count == 2

    def test_prompt_yes_stops(self):
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": []}
        with (
            patch("builtins.input", return_value="yes"),
            patch.object(bm, "stop_process_list") as stop,
            patch.object(bm.time, "sleep"),
            patch.object(bm.Path, "unlink"),
        ):
            result = bm.auto_stop_existing_bot(status)
        assert result is True
        assert stop.call_count == 2

    def test_prompt_no_aborts(self):
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": []}
        with (
            patch("builtins.input", return_value="no"),
            patch.object(bm, "stop_process_list") as stop,
        ):
            result = bm.auto_stop_existing_bot(status)
        assert result is False
        assert stop.call_count == 0

    def test_eof_during_prompt_aborts(self):
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": []}
        with patch("builtins.input", side_effect=EOFError):
            assert bm.auto_stop_existing_bot(status) is False

    def test_keyboard_interrupt_during_prompt_aborts(self):
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": []}
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert bm.auto_stop_existing_bot(status) is False

    def test_env_var_falsey_value_still_prompts(self, monkeypatch):
        # A non-truthy env value must NOT bypass the prompt.
        monkeypatch.setenv("BOT_MANAGER_ASSUME_YES", "0")
        status = {"running": True, "all_pids": [1], "dev_watcher_pids": []}
        with patch("builtins.input", return_value="no") as inp:
            result = bm.auto_stop_existing_bot(status)
        assert result is False
        assert inp.called


# ==================== _launch_script ====================


class TestLaunchScript:
    """Tests for _launch_script."""

    def test_missing_script_returns_false(self, tmp_path):
        missing = tmp_path / "does_not_exist.bat"
        assert bm._launch_script(str(missing), "X") is False

    def test_startfile_launch_on_win32(self, tmp_path, monkeypatch):
        script = tmp_path / "s.bat"
        script.write_text("echo hi", encoding="utf-8")
        monkeypatch.setattr(bm.sys, "platform", "win32")
        with patch.object(bm.os, "startfile", create=True) as startfile:
            result = bm._launch_script(str(script), "X")
        assert result is True
        assert startfile.called

    def test_subprocess_launch_on_posix(self, tmp_path, monkeypatch):
        script = tmp_path / "s.sh"
        script.write_text("echo hi", encoding="utf-8")
        monkeypatch.setattr(bm.sys, "platform", "linux")
        with patch.object(bm.subprocess, "Popen") as popen:
            result = bm._launch_script(str(script), "X")
        assert result is True
        assert popen.called

    def test_hidden_launch_uses_powershell(self, tmp_path):
        script = tmp_path / "start.ps1"
        script.write_text("Write-Host hi", encoding="utf-8")
        with patch.object(bm.subprocess, "Popen") as popen:
            result = bm._launch_script(str(script), "Hidden", hidden=True)
        assert result is True
        assert popen.called
        # PowerShell invocation must request a hidden window.
        args = popen.call_args[0][0]
        assert "Hidden" in args

    def test_launch_error_returns_false(self, tmp_path, monkeypatch):
        script = tmp_path / "s.bat"
        script.write_text("echo hi", encoding="utf-8")
        monkeypatch.setattr(bm.sys, "platform", "win32")
        with patch.object(bm.os, "startfile", create=True, side_effect=OSError("boom")):
            assert bm._launch_script(str(script), "X") is False


# ==================== _tail_lines ====================


class TestTailLines:
    """Tests for _tail_lines (last-N-lines reader)."""

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "log.txt"
        p.write_text("", encoding="utf-8")
        assert bm._tail_lines(p, 5) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert bm._tail_lines(tmp_path / "nope.txt", 5) == []

    def test_fewer_lines_than_n(self, tmp_path):
        p = tmp_path / "log.txt"
        p.write_text("a\nb\nc\n", encoding="utf-8")
        assert bm._tail_lines(p, 10) == ["a", "b", "c"]

    def test_more_lines_than_n_returns_last_n(self, tmp_path):
        p = tmp_path / "log.txt"
        p.write_text("\n".join(str(i) for i in range(100)) + "\n", encoding="utf-8")
        assert bm._tail_lines(p, 3) == ["97", "98", "99"]

    def test_no_trailing_newline(self, tmp_path):
        p = tmp_path / "log.txt"
        p.write_text("x\ny\nz", encoding="utf-8")
        assert bm._tail_lines(p, 2) == ["y", "z"]

    def test_decodes_with_replacement(self, tmp_path):
        # Invalid UTF-8 bytes must not raise — errors="replace".
        p = tmp_path / "log.txt"
        p.write_bytes(b"good line\n\xff\xfe bad\n")
        lines = bm._tail_lines(p, 5)
        assert lines[0] == "good line"
        assert len(lines) == 2

    def test_chunked_read_across_boundary(self, tmp_path):
        # File larger than a single 64 KiB chunk still tails correctly.
        p = tmp_path / "log.txt"
        big = "\n".join(f"line{i}" for i in range(20000)) + "\n"
        p.write_text(big, encoding="utf-8")
        result = bm._tail_lines(p, 2)
        assert result == ["line19998", "line19999"]


# ==================== module constants ====================


class TestModuleConstants:
    """Sanity checks on resolved module-level constants."""

    def test_paths_anchored_to_project_root(self):
        root = str(bm.PROJECT_ROOT)
        assert bm.STATUS_FILE.startswith(root)
        assert bm.PID_FILE.startswith(root)
        assert bm.STOP_FLAG.startswith(root)

    def test_pid_and_status_filenames(self):
        assert bm.PID_FILE.endswith("bot.pid")
        assert bm.STATUS_FILE.endswith("bot_status.json")
        assert bm.STOP_FLAG.endswith("stop_loop.flag")

    def test_box_width_positive(self):
        assert isinstance(bm.BOX_WIDTH, int)
        assert bm.BOX_WIDTH > 0
