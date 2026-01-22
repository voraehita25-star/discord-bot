"""
Tests for utils.reliability.self_healer module.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

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
            Path(temp_path).unlink()

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
            Path(temp_path).unlink()


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
                assert not Path(temp_path).exists()
        except:
            if Path(temp_path).exists():
                Path(temp_path).unlink()
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
