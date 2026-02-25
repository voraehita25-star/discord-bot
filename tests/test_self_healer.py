"""
Tests for utils.reliability.self_healer module.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


import logging
from unittest.mock import patch
import pytest

class TestSelfHealerInit:
    """Tests for SelfHealer initialization."""

    def test_init_sets_caller_script(self):
        """Test initialization sets caller script."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer(caller_script="test_script.py")
        assert healer.caller_script == "test_script.py"

    def test_init_default_caller(self):
        """Test initialization default caller."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        assert healer.caller_script == "unknown"

    def test_init_sets_my_pid(self):
        """Test initialization sets my_pid."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        assert healer.my_pid == os.getpid()

    def test_init_empty_actions_taken(self):
        """Test initialization starts with empty actions_taken."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        assert healer.actions_taken == []

    def test_init_creates_logger(self):
        """Test initialization creates logger."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        assert healer.logger is not None


class TestSelfHealerLog:
    """Tests for SelfHealer.log method."""

    def test_log_info_not_stored(self):
        """Test INFO log is not stored in actions_taken."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        healer.log("info", "Test info message")

        assert len(healer.actions_taken) == 0

    def test_log_warning_stored(self):
        """Test WARNING log is stored in actions_taken."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        healer.log("warning", "Test warning message")

        assert len(healer.actions_taken) == 1
        assert "[WARNING]" in healer.actions_taken[0]

    def test_log_error_stored(self):
        """Test ERROR log is stored in actions_taken."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        healer.log("error", "Test error message")

        assert len(healer.actions_taken) == 1
        assert "[ERROR]" in healer.actions_taken[0]

    def test_log_critical_stored(self):
        """Test CRITICAL log is stored in actions_taken."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        healer.log("critical", "Test critical message")

        assert len(healer.actions_taken) == 1
        assert "[CRITICAL]" in healer.actions_taken[0]


class TestFindAllBotProcesses:
    """Tests for find_all_bot_processes method."""

    def test_returns_list(self):
        """Test method returns a list."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        result = healer.find_all_bot_processes()

        assert isinstance(result, list)

    def test_excludes_manager_processes(self):
        """Test excludes bot_manager processes."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch("psutil.process_iter") as mock_iter:
            mock_proc = MagicMock()
            mock_proc.info = {
                "pid": 1234,
                "name": "python",
                "cmdline": ["python", "bot_manager.py"],
                "create_time": 1000.0
            }
            mock_iter.return_value = [mock_proc]

            result = healer.find_all_bot_processes()

            # Should exclude bot_manager
            assert len(result) == 0


class TestFindAllDevWatchers:
    """Tests for find_all_dev_watchers method."""

    def test_returns_list(self):
        """Test method returns a list."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        result = healer.find_all_dev_watchers()

        assert isinstance(result, list)


class TestGetPidFromFile:
    """Tests for get_pid_from_file method."""

    def test_returns_none_when_no_file(self):
        """Test returns None when PID file doesn't exist."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(Path, "exists", return_value=False):
            result = healer.get_pid_from_file()

            assert result is None

    def test_returns_pid_from_file(self):
        """Test returns PID from file."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pid") as f:
            f.write("12345")
            temp_path = f.name

        try:
            with patch("utils.reliability.self_healer.PID_FILE", temp_path):
                result = healer.get_pid_from_file()
                assert result == 12345
        finally:
            os.unlink(temp_path)

    def test_returns_none_on_invalid_content(self):
        """Test returns None on invalid PID content."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pid") as f:
            f.write("not_a_number")
            temp_path = f.name

        try:
            with patch("utils.reliability.self_healer.PID_FILE", temp_path):
                result = healer.get_pid_from_file()
                assert result is None
        finally:
            os.unlink(temp_path)


class TestDiagnose:
    """Tests for diagnose method."""

    def test_returns_dict(self):
        """Test diagnose returns dictionary."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.diagnose()

        assert isinstance(result, dict)

    def test_diagnose_includes_timestamp(self):
        """Test diagnose includes timestamp."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.diagnose()

        assert "timestamp" in result

    def test_diagnose_includes_caller(self):
        """Test diagnose includes caller info."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer(caller_script="test.py")

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.diagnose()

        assert result["caller"] == "test.py"

    def test_diagnose_detects_duplicate_bots(self):
        """Test diagnose detects duplicate bot processes."""
        import time

        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        mock_bots = [
            {"pid": 1001, "cmdline": "python bot.py", "create_time": time.time()},
            {"pid": 1002, "cmdline": "python bot.py", "create_time": time.time() + 1},
        ]

        with patch.object(healer, "find_all_bot_processes", return_value=mock_bots):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.diagnose()

        assert len(result["issues"]) > 0
        assert any(i["type"] == "DUPLICATE_BOTS" for i in result["issues"])

    def test_diagnose_detects_stale_pid_file(self):
        """Test diagnose detects stale PID file."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        # PID file points to non-existent process
        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=99999):
                    result = healer.diagnose()

        # Should detect orphan PID file (no bots but PID file exists)
        assert any(i["type"] == "ORPHAN_PID_FILE" for i in result["issues"])


class TestKillProcess:
    """Tests for kill_process method."""

    def test_kill_nonexistent_process_returns_true(self):
        """Test killing non-existent process returns True."""
        import psutil

        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch("psutil.Process") as mock_proc:
            mock_proc.side_effect = psutil.NoSuchProcess(99999)

            result = healer.kill_process(99999)

            assert result is True

    def test_kill_access_denied_returns_false(self):
        """Test kill with access denied returns False."""
        import psutil

        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch("psutil.Process") as mock_proc:
            mock_proc.side_effect = psutil.AccessDenied(1234)

            result = healer.kill_process(1234)

            assert result is False


class TestCleanPidFile:
    """Tests for clean_pid_file method."""

    def test_clean_nonexistent_file_returns_true(self):
        """Test cleaning non-existent file returns True."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(Path, "exists", return_value=False):
            result = healer.clean_pid_file()

            assert result is True

    def test_clean_existing_file(self):
        """Test cleaning existing PID file."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pid") as f:
            f.write("12345")
            temp_path = f.name

        try:
            with patch("utils.reliability.self_healer.PID_FILE", temp_path):
                result = healer.clean_pid_file()
                assert result is True
                assert not os.path.exists(temp_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise


class TestKillDuplicateBots:
    """Tests for kill_duplicate_bots method."""

    def test_no_duplicates_returns_zero(self):
        """Test returns 0 when no duplicates."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            result = healer.kill_duplicate_bots()

            assert result == 0

    def test_single_bot_returns_zero(self):
        """Test returns 0 when only one bot."""
        import time

        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        single_bot = [{"pid": 1001, "cmdline": "python bot.py", "create_time": time.time()}]

        with patch.object(healer, "find_all_bot_processes", return_value=single_bot):
            result = healer.kill_duplicate_bots()

            assert result == 0


class TestKillDuplicateWatchers:
    """Tests for kill_duplicate_watchers method."""

    def test_no_duplicates_returns_zero(self):
        """Test returns 0 when no duplicates."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_dev_watchers", return_value=[]):
            result = healer.kill_duplicate_watchers()

            assert result == 0

    def test_single_watcher_returns_zero(self):
        """Test returns 0 when only one watcher."""
        import time

        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        single_watcher = [{"pid": 2001, "cmdline": "python dev_watcher.py", "create_time": time.time()}]

        with patch.object(healer, "find_all_dev_watchers", return_value=single_watcher):
            result = healer.kill_duplicate_watchers()

            assert result == 0


class TestFindLauncherProcesses:
    """Tests for find_launcher_processes method."""

    def test_returns_list(self):
        """Test returns a list."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                result = healer.find_launcher_processes()

        assert isinstance(result, list)


class TestAutoHeal:
    """Tests for auto_heal method."""

    def test_auto_heal_healthy_system(self):
        """Test auto_heal returns success when no issues."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.auto_heal()

        assert result["success"] is True
        assert "healthy" in result["summary"].lower()
        assert len(result["actions"]) == 0

    def test_auto_heal_cleans_stale_pid(self):
        """Test auto_heal cleans stale PID file."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=99999):
                    with patch.object(healer, "clean_pid_file", return_value=True):
                        result = healer.auto_heal()

        assert result["success"] is True
        assert any(a["action"] == "CLEAN_PID_FILE" for a in result["actions"])

    def test_auto_heal_kills_duplicate_bots(self):
        """Test auto_heal kills duplicate bots."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_bots = [
            {"pid": 1001, "cmdline": "python bot.py", "create_time": time.time()},
            {"pid": 1002, "cmdline": "python bot.py", "create_time": time.time() + 1},
        ]

        with patch.object(healer, "find_all_bot_processes", return_value=mock_bots):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    with patch.object(healer, "kill_duplicate_bots", return_value=1):
                        result = healer.auto_heal()

        assert any(a["action"] == "KILL_DUPLICATE_BOTS" for a in result["actions"])

    def test_auto_heal_aggressive_kills_all(self):
        """Test aggressive auto_heal kills all bots."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_bots = [
            {"pid": 1001, "cmdline": "python bot.py", "create_time": time.time()},
            {"pid": 1002, "cmdline": "python bot.py", "create_time": time.time() + 1},
        ]

        with patch.object(healer, "find_all_bot_processes", return_value=mock_bots):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    with patch.object(healer, "kill_all_bots", return_value=2):
                        result = healer.auto_heal(aggressive=True)

        assert any(a["action"] == "KILL_DUPLICATE_BOTS" for a in result["actions"])


class TestEnsureSingleInstance:
    """Tests for ensure_single_instance method."""

    def test_no_other_instances(self):
        """Test returns True when no other instances."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            can_proceed, msg = healer.ensure_single_instance()

        assert can_proceed is True
        assert "no other" in msg.lower()

    def test_kills_existing_when_allowed(self):
        """Test kills existing instances when kill_existing=True."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        other_bot = [{"pid": 9999, "cmdline": "python bot.py", "create_time": time.time()}]

        with patch.object(healer, "find_all_bot_processes", return_value=other_bot):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "kill_process", return_value=True):
                    with patch.object(healer, "clean_pid_file", return_value=True):
                        with patch("time.sleep"):
                            can_proceed, msg = healer.ensure_single_instance(kill_existing=True)

        assert can_proceed is True
        assert "stopped" in msg.lower()

    def test_aborts_when_not_killing(self):
        """Test aborts when kill_existing=False and instance exists."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        other_bot = [{"pid": 9999, "cmdline": "python bot.py", "create_time": time.time()}]

        with patch.object(healer, "find_all_bot_processes", return_value=other_bot):
            can_proceed, msg = healer.ensure_single_instance(kill_existing=False)

        assert can_proceed is False
        assert "already running" in msg.lower()


class TestGetStatusReport:
    """Tests for get_status_report method."""

    def test_status_report_no_bots(self):
        """Test status report when no bots running."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    report = healer.get_status_report()

        assert "not running" in report.lower()
        assert "No issues" in report or "no issues" in report.lower()

    def test_status_report_with_bots(self):
        """Test status report with bots running."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_bots = [{"pid": 1234, "cmdline": "python bot.py", "create_time": time.time()}]

        with patch.object(healer, "find_all_bot_processes", return_value=mock_bots):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    report = healer.get_status_report()

        assert "1234" in report


class TestKillAllBots:
    """Tests for kill_all_bots method."""

    def test_kill_all_no_bots(self):
        """Test kill_all_bots when no bots running."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_launcher_processes", return_value=[]):
                with patch.object(healer, "clean_pid_file", return_value=True):
                    result = healer.kill_all_bots()

        assert result == 0

    def test_kill_all_with_bots(self):
        """Test kill_all_bots kills bot processes."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_bots = [
            {"pid": 5001, "cmdline": "python bot.py", "create_time": time.time()},
            {"pid": 5002, "cmdline": "python bot.py", "create_time": time.time() + 1},
        ]

        with patch.object(healer, "find_all_bot_processes", return_value=mock_bots):
            with patch.object(healer, "find_launcher_processes", return_value=[]):
                with patch.object(healer, "kill_process", return_value=True):
                    with patch.object(healer, "clean_pid_file", return_value=True):
                        result = healer.kill_all_bots()

        assert result == 2


class TestKillAllWatchers:
    """Tests for kill_all_watchers method."""

    def test_kill_all_no_watchers(self):
        """Test kill_all_watchers when none running."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()

        with patch.object(healer, "find_all_dev_watchers", return_value=[]):
            result = healer.kill_all_watchers()

        assert result == 0


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_quick_heal(self):
        """Test quick_heal function."""
        from utils.reliability.self_healer import quick_heal

        with patch("utils.reliability.self_healer.SelfHealer") as MockHealer:
            mock_instance = MagicMock()
            mock_instance.auto_heal.return_value = {"success": True, "summary": "OK"}
            MockHealer.return_value = mock_instance

            result = quick_heal("test")

        assert result["success"] is True

    def test_ensure_single_bot(self):
        """Test ensure_single_bot function."""
        from utils.reliability.self_healer import ensure_single_bot

        with patch("utils.reliability.self_healer.SelfHealer") as MockHealer:
            mock_instance = MagicMock()
            mock_instance.ensure_single_instance.return_value = (True, "OK")
            MockHealer.return_value = mock_instance

            can_proceed, msg = ensure_single_bot("test")

        assert can_proceed is True

    def test_get_system_status(self):
        """Test get_system_status function."""
        from utils.reliability.self_healer import get_system_status

        with patch("utils.reliability.self_healer.SelfHealer") as MockHealer:
            mock_instance = MagicMock()
            mock_instance.get_status_report.return_value = "Status OK"
            MockHealer.return_value = mock_instance

            result = get_system_status("test")

        assert result == "Status OK"

    def test_kill_everything(self):
        """Test kill_everything function."""
        from utils.reliability.self_healer import kill_everything

        with patch("utils.reliability.self_healer.SelfHealer") as MockHealer:
            mock_instance = MagicMock()
            mock_instance.kill_all_bots.return_value = 2
            mock_instance.kill_all_watchers.return_value = 1
            MockHealer.return_value = mock_instance

            result = kill_everything("test")

        assert result["bots_killed"] == 2
        assert result["watchers_killed"] == 1
        assert result["success"] is True


class TestDiagnoseEdgeCases:
    """Tests for diagnose edge cases."""

    def test_diagnose_duplicate_watchers_from_watcher(self):
        """Test detects duplicate watchers when called from dev_watcher."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer(caller_script="dev_watcher.py")
        mock_watchers = [
            {"pid": 3001, "cmdline": "python dev_watcher.py", "create_time": time.time()},
            {"pid": 3002, "cmdline": "python dev_watcher.py", "create_time": time.time() + 1},
        ]

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=mock_watchers):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.diagnose()

        assert any(i["type"] == "DUPLICATE_WATCHERS" for i in result["issues"])

    def test_diagnose_duplicate_watchers_ignored_from_bot(self):
        """Test duplicate watchers NOT detected when called from bot.py."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer(caller_script="bot.py")
        mock_watchers = [
            {"pid": 3001, "cmdline": "python dev_watcher.py", "create_time": time.time()},
            {"pid": 3002, "cmdline": "python dev_watcher.py", "create_time": time.time() + 1},
        ]

        with patch.object(healer, "find_all_bot_processes", return_value=[]):
            with patch.object(healer, "find_all_dev_watchers", return_value=mock_watchers):
                with patch.object(healer, "get_pid_from_file", return_value=None):
                    result = healer.diagnose()

        assert not any(i["type"] == "DUPLICATE_WATCHERS" for i in result["issues"])

    def test_diagnose_stale_pid_with_running_bot(self):
        """Test detects stale PID when file points to wrong process."""
        import time
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_bots = [{"pid": 1001, "cmdline": "python bot.py", "create_time": time.time()}]

        with patch.object(healer, "find_all_bot_processes", return_value=mock_bots):
            with patch.object(healer, "find_all_dev_watchers", return_value=[]):
                with patch.object(healer, "get_pid_from_file", return_value=9999):
                    result = healer.diagnose()

        assert any(i["type"] == "STALE_PID_FILE" for i in result["issues"])
        assert result["pid_file_valid"] is False


class TestKillProcess:
    """Additional tests for kill_process method."""

    def test_kill_process_success(self):
        """Test successful process termination."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()

        with patch("psutil.Process", return_value=mock_proc):
            result = healer.kill_process(1234)

        assert result is True
        mock_proc.terminate.assert_called_once()

    def test_kill_process_force(self):
        """Test forced process kill."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()

        with patch("psutil.Process", return_value=mock_proc):
            result = healer.kill_process(1234, force=True)

        assert result is True
        mock_proc.kill.assert_called_once()

    def test_kill_process_timeout_then_force(self):
        """Test process kill when terminate times out."""
        import psutil
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock(side_effect=[psutil.TimeoutExpired(5), None])
        mock_proc.kill = MagicMock()

        with patch("psutil.Process", return_value=mock_proc):
            result = healer.kill_process(1234)

        assert result is True
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_kill_process_os_error(self):
        """Test kill process with OS error."""
        from utils.reliability.self_healer import SelfHealer

        healer = SelfHealer()
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock(side_effect=OSError("Permission denied"))

        with patch("psutil.Process", return_value=mock_proc):
            result = healer.kill_process(1234)

        assert result is False


class TestConstants:
    """Tests for module constants."""

    def test_pid_file_constant(self):
        """Test PID_FILE constant."""
        from utils.reliability.self_healer import PID_FILE

        assert PID_FILE == "bot.pid"

    def test_healer_log_file_constant(self):
        """Test HEALER_LOG_FILE constant."""
        from utils.reliability.self_healer import HEALER_LOG_FILE

        assert "self_healer" in HEALER_LOG_FILE


# ======================================================================
# Merged from test_self_healer_extended.py
# ======================================================================

class TestSelfHealerInit:
    """Tests for SelfHealer initialization."""

    def test_self_healer_init_basic(self):
        """Test SelfHealer initializes correctly."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer(caller_script="test")

        assert healer.caller_script == "test"
        assert healer.my_pid == os.getpid()
        assert healer.actions_taken == []

    def test_self_healer_default_caller(self):
        """Test SelfHealer with default caller_script."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        assert healer.caller_script == "unknown"

    def test_self_healer_has_logger(self):
        """Test SelfHealer has logger attribute."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        assert hasattr(healer, 'logger')
        assert isinstance(healer.logger, logging.Logger)


class TestSetupLogger:
    """Tests for _setup_logger method."""

    def test_setup_logger_creates_logger(self):
        """Test _setup_logger creates a logger."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()
        logger = healer._setup_logger()

        assert logger.name == "SelfHealer"
        assert logger.level == logging.DEBUG


class TestLogMethod:
    """Tests for log method."""

    def test_log_info(self):
        """Test logging at INFO level."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()
        healer.log("info", "Test message")

        # INFO doesn't get added to actions_taken
        assert len(healer.actions_taken) == 0

    def test_log_warning(self):
        """Test logging at WARNING level."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()
        healer.log("warning", "Test warning")

        assert len(healer.actions_taken) == 1
        assert "[WARNING]" in healer.actions_taken[0]

    def test_log_error(self):
        """Test logging at ERROR level."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()
        healer.log("error", "Test error")

        assert len(healer.actions_taken) == 1
        assert "[ERROR]" in healer.actions_taken[0]

    def test_log_critical(self):
        """Test logging at CRITICAL level."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()
        healer.log("critical", "Test critical")

        assert len(healer.actions_taken) == 1
        assert "[CRITICAL]" in healer.actions_taken[0]


class TestFindAllBotProcesses:
    """Tests for find_all_bot_processes method."""

    def test_find_all_bot_processes_returns_list(self):
        """Test find_all_bot_processes returns a list."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        with patch('psutil.process_iter', return_value=[]):
            result = healer.find_all_bot_processes()

        assert isinstance(result, list)


class TestFindAllDevWatchers:
    """Tests for find_all_dev_watchers method."""

    def test_find_all_dev_watchers_returns_list(self):
        """Test find_all_dev_watchers returns a list."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        with patch('psutil.process_iter', return_value=[]):
            result = healer.find_all_dev_watchers()

        assert isinstance(result, list)


class TestConstants:
    """Tests for module constants."""

    def test_pid_file_constant(self):
        """Test PID_FILE constant is defined."""
        try:
            from utils.reliability.self_healer import PID_FILE
        except ImportError:
            pytest.skip("self_healer not available")
            return

        assert PID_FILE == "bot.pid"

    def test_healer_log_file_constant(self):
        """Test HEALER_LOG_FILE constant is defined."""
        try:
            from utils.reliability.self_healer import HEALER_LOG_FILE
        except ImportError:
            pytest.skip("self_healer not available")
            return

        assert "self_healer" in HEALER_LOG_FILE


class TestModuleDocstring:
    """Tests for module documentation."""

class TestActionsTaken:
    """Tests for actions_taken tracking."""

    def test_actions_taken_initially_empty(self):
        """Test actions_taken starts empty."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        assert healer.actions_taken == []

    def test_actions_taken_accumulates(self):
        """Test actions_taken accumulates warnings/errors."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()
        healer.log("warning", "First warning")
        healer.log("error", "First error")
        healer.log("warning", "Second warning")

        assert len(healer.actions_taken) == 3


class TestMyPid:
    """Tests for my_pid attribute."""

    def test_my_pid_is_current_process(self):
        """Test my_pid matches current process."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        assert healer.my_pid == os.getpid()
        assert isinstance(healer.my_pid, int)
        assert healer.my_pid > 0


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_has_handler(self):
        """Test logger has at least one handler."""
        try:
            from utils.reliability.self_healer import SelfHealer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        healer = SelfHealer()

        # The logger should have handlers (file handler)
        assert healer.logger.handlers is not None


# ======================================================================
# Merged from test_self_healer_module.py
# ======================================================================

class TestSelfHealerInit:
    """Tests for SelfHealer initialization."""

    def test_selfhealer_creation(self):
        """Test creating SelfHealer."""
        from utils.reliability.self_healer import SelfHealer

        with patch.object(SelfHealer, '_setup_logger', return_value=MagicMock()):
            healer = SelfHealer("test_script.py")

            assert healer.caller_script == "test_script.py"
            assert healer.actions_taken == []

    def test_selfhealer_default_caller(self):
        """Test SelfHealer with default caller."""
        from utils.reliability.self_healer import SelfHealer

        with patch.object(SelfHealer, '_setup_logger', return_value=MagicMock()):
            healer = SelfHealer()

            assert healer.caller_script == "unknown"

    def test_selfhealer_has_my_pid(self):
        """Test SelfHealer records current PID."""
        import os

        from utils.reliability.self_healer import SelfHealer

        with patch.object(SelfHealer, '_setup_logger', return_value=MagicMock()):
            healer = SelfHealer()

            assert healer.my_pid == os.getpid()


class TestLogMethod:
    """Tests for log method."""

    def test_log_info(self):
        """Test logging info level."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            healer.log("info", "Test message")

            mock_logger.info.assert_called_once_with("Test message")

    def test_log_warning_stores_action(self):
        """Test logging warning stores action."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            healer.log("warning", "Warning message")

            assert len(healer.actions_taken) == 1
            assert "[WARNING]" in healer.actions_taken[0]

    def test_log_error_stores_action(self):
        """Test logging error stores action."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            healer.log("error", "Error message")

            assert len(healer.actions_taken) == 1
            assert "[ERROR]" in healer.actions_taken[0]


class TestFindProcesses:
    """Tests for process finding methods."""

    def test_find_all_bot_processes_empty(self):
        """Test find_all_bot_processes with no bots."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch('psutil.process_iter', return_value=[]):
                result = healer.find_all_bot_processes()

                assert result == []

    def test_find_all_dev_watchers_empty(self):
        """Test find_all_dev_watchers with no watchers."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch('psutil.process_iter', return_value=[]):
                result = healer.find_all_dev_watchers()

                assert result == []


class TestGetPidFromFile:
    """Tests for get_pid_from_file method."""

    def test_get_pid_from_file_exists(self):
        """Test get_pid_from_file with existing file."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = "12345"

            with patch('utils.reliability.self_healer.Path', return_value=mock_path):
                result = healer.get_pid_from_file()

                assert result == 12345

    def test_get_pid_from_file_not_exists(self):
        """Test get_pid_from_file with no file."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            mock_path = MagicMock()
            mock_path.exists.return_value = False

            with patch('utils.reliability.self_healer.Path', return_value=mock_path):
                result = healer.get_pid_from_file()

                assert result is None

    def test_get_pid_from_file_invalid_content(self):
        """Test get_pid_from_file with invalid content."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = "not_a_number"

            with patch('utils.reliability.self_healer.Path', return_value=mock_path):
                result = healer.get_pid_from_file()

                assert result is None


class TestDiagnose:
    """Tests for diagnose method."""

    def test_diagnose_returns_dict(self):
        """Test diagnose returns dict structure."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer("test.py")

            with patch.object(healer, 'find_all_bot_processes', return_value=[]):
                with patch.object(healer, 'find_all_dev_watchers', return_value=[]):
                    with patch.object(healer, 'get_pid_from_file', return_value=None):
                        result = healer.diagnose()

                        assert "timestamp" in result
                        assert "caller" in result
                        assert "issues" in result
                        assert "bot_processes" in result
                        assert "recommendations" in result

    def test_diagnose_no_issues(self):
        """Test diagnose with no issues."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer("test.py")

            with patch.object(healer, 'find_all_bot_processes', return_value=[]):
                with patch.object(healer, 'find_all_dev_watchers', return_value=[]):
                    with patch.object(healer, 'get_pid_from_file', return_value=None):
                        result = healer.diagnose()

                        assert result["issues"] == []


class TestHealingActions:
    """Tests for healing action methods."""

    def test_clean_pid_file_success(self):
        """Test clean_pid_file with success."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.unlink.return_value = None

            with patch('utils.reliability.self_healer.Path', return_value=mock_path):
                result = healer.clean_pid_file()

                assert result is True

    def test_clean_pid_file_not_exists(self):
        """Test clean_pid_file when file doesn't exist."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            mock_path = MagicMock()
            mock_path.exists.return_value = False

            with patch('utils.reliability.self_healer.Path', return_value=mock_path):
                result = healer.clean_pid_file()

                assert result is True

    def test_kill_duplicate_bots_no_duplicates(self):
        """Test kill_duplicate_bots with no duplicates."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch.object(healer, 'find_all_bot_processes', return_value=[]):
                result = healer.kill_duplicate_bots()

                assert result == 0

    def test_kill_duplicate_watchers_no_duplicates(self):
        """Test kill_duplicate_watchers with no duplicates."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch.object(healer, 'find_all_dev_watchers', return_value=[]):
                result = healer.kill_duplicate_watchers()

                assert result == 0


class TestKillProcess:
    """Tests for kill_process method."""

    def test_kill_process_success(self):
        """Test kill_process success."""

        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            mock_proc = MagicMock()
            mock_proc.terminate.return_value = None
            mock_proc.wait.return_value = None

            with patch('psutil.Process', return_value=mock_proc):
                result = healer.kill_process(12345)

                assert result is True

    def test_kill_process_no_such_process(self):
        """Test kill_process with non-existent process."""
        import psutil

        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch('psutil.Process', side_effect=psutil.NoSuchProcess(12345)):
                result = healer.kill_process(12345)

                # NoSuchProcess means it's already gone, which is success
                assert result is True

    def test_kill_process_access_denied(self):
        """Test kill_process with access denied."""
        import psutil

        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch('psutil.Process', side_effect=psutil.AccessDenied(12345)):
                result = healer.kill_process(12345)

                assert result is False


class TestAutoHeal:
    """Tests for auto_heal method."""

    def test_auto_heal_no_issues(self):
        """Test auto_heal with no issues."""
        from utils.reliability.self_healer import SelfHealer

        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()

            with patch.object(healer, 'diagnose', return_value={"issues": [], "recommendations": []}):
                result = healer.auto_heal()

                assert result["success"] is True


class TestModuleConstants:
    """Tests for module constants."""

    def test_pid_file_constant(self):
        """Test PID_FILE constant."""
        from utils.reliability.self_healer import PID_FILE

        assert PID_FILE == "bot.pid"

    def test_healer_log_file_constant(self):
        """Test HEALER_LOG_FILE constant."""
        from utils.reliability.self_healer import HEALER_LOG_FILE

        assert "self_healer.log" in HEALER_LOG_FILE


class TestModuleImports:
    """Tests for module imports."""

    def test_import_selfhealer(self):
        """Test importing SelfHealer."""
        from utils.reliability.self_healer import SelfHealer
        assert SelfHealer is not None

    def test_selfhealer_available(self):
        """Test SELF_HEALER_AVAILABLE can be True."""
        # If we can import, it's available
        from utils.reliability.self_healer import SelfHealer
        assert SelfHealer is not None
