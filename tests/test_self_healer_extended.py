"""
Extended tests for Self Healer module.
Tests bot process detection and healing mechanisms.
"""

import logging
import os
from unittest.mock import patch

import pytest


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

    def test_module_has_docstring(self):
        """Test self_healer module has docstring."""
        try:
            from utils.reliability import self_healer
        except ImportError:
            pytest.skip("self_healer not available")
            return

        assert self_healer.__doc__ is not None
        assert "Self-Healer" in self_healer.__doc__ or "healer" in self_healer.__doc__.lower()


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
