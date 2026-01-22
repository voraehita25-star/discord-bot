"""Tests for self_healer module."""

import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import time


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
        from utils.reliability.self_healer import SelfHealer
        import os
        
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
        import psutil
        
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
        from utils.reliability.self_healer import SelfHealer
        import psutil
        
        mock_logger = MagicMock()
        with patch.object(SelfHealer, '_setup_logger', return_value=mock_logger):
            healer = SelfHealer()
            
            with patch('psutil.Process', side_effect=psutil.NoSuchProcess(12345)):
                result = healer.kill_process(12345)
                
                # NoSuchProcess means it's already gone, which is success
                assert result is True

    def test_kill_process_access_denied(self):
        """Test kill_process with access denied."""
        from utils.reliability.self_healer import SelfHealer
        import psutil
        
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
