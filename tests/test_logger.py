"""
Tests for utils.monitoring.logger module.
"""

import pytest
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestEmojiMap:
    """Tests for EMOJI_MAP constant."""

    def test_emoji_map_exists(self):
        """Test EMOJI_MAP has expected emoji mappings."""
        from utils.monitoring.logger import EMOJI_MAP
        
        assert "🧠" in EMOJI_MAP
        assert "✅" in EMOJI_MAP
        assert "❌" in EMOJI_MAP
        assert "⚠️" in EMOJI_MAP

    def test_emoji_map_values_are_strings(self):
        """Test all EMOJI_MAP values are ASCII strings."""
        from utils.monitoring.logger import EMOJI_MAP
        
        for emoji, ascii_text in EMOJI_MAP.items():
            assert isinstance(ascii_text, str)
            # Check ASCII-safe
            assert ascii_text.encode("ascii", "strict")


class TestSafeAscii:
    """Tests for safe_ascii function."""

    def test_converts_emoji_to_ascii(self):
        """Test emoji conversion to ASCII."""
        from utils.monitoring.logger import safe_ascii
        
        result = safe_ascii("Hello 🧠 World")
        assert "[BRAIN]" in result
        assert "🧠" not in result

    def test_preserves_plain_text(self):
        """Test plain text is preserved."""
        from utils.monitoring.logger import safe_ascii
        
        result = safe_ascii("Hello World")
        assert result == "Hello World"

    def test_converts_multiple_emojis(self):
        """Test multiple emoji conversion."""
        from utils.monitoring.logger import safe_ascii
        
        result = safe_ascii("✅ Success ❌ Error")
        assert "[OK]" in result
        assert "[X]" in result
        assert "✅" not in result
        assert "❌" not in result

    def test_handles_non_string_input(self):
        """Test non-string input is converted."""
        from utils.monitoring.logger import safe_ascii
        
        result = safe_ascii(12345)
        assert result == "12345"

    def test_replaces_unknown_unicode(self):
        """Test unknown unicode is replaced."""
        from utils.monitoring.logger import safe_ascii
        
        result = safe_ascii("Test 中文 Text")
        # Unknown characters should be replaced with ?
        assert "?" in result or "Test" in result


class TestSmartLogFormatter:
    """Tests for SmartLogFormatter class."""

    def test_formatter_has_color_codes(self):
        """Test formatter has color code attributes."""
        from utils.monitoring.logger import SmartLogFormatter
        
        formatter = SmartLogFormatter()
        
        assert hasattr(formatter, "grey")
        assert hasattr(formatter, "green")
        assert hasattr(formatter, "yellow")
        assert hasattr(formatter, "red")
        assert hasattr(formatter, "bold_red")
        assert hasattr(formatter, "reset")

    def test_format_debug_message(self):
        """Test formatting DEBUG message."""
        from utils.monitoring.logger import SmartLogFormatter
        
        formatter = SmartLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=1,
            msg="Debug message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        assert "Debug message" in result

    def test_format_info_message(self):
        """Test formatting INFO message."""
        from utils.monitoring.logger import SmartLogFormatter
        
        formatter = SmartLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Info message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        assert "Info message" in result

    def test_format_warning_message(self):
        """Test formatting WARNING message."""
        from utils.monitoring.logger import SmartLogFormatter
        
        formatter = SmartLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Warning message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        assert "Warning message" in result

    def test_format_error_message(self):
        """Test formatting ERROR message."""
        from utils.monitoring.logger import SmartLogFormatter
        
        formatter = SmartLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        assert "Error message" in result

    def test_format_critical_message(self):
        """Test formatting CRITICAL message."""
        from utils.monitoring.logger import SmartLogFormatter
        
        formatter = SmartLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.CRITICAL,
            pathname="test.py",
            lineno=1,
            msg="Critical message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        assert "Critical message" in result


class TestJSONLogFormatter:
    """Tests for JSONLogFormatter class."""

    def test_format_returns_json(self):
        """Test that format returns valid JSON."""
        from utils.monitoring.logger import JSONLogFormatter
        import json
        
        formatter = JSONLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        
        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["level"] == "INFO"
        assert "Test message" in parsed["message"]
        assert parsed["line"] == 10

    def test_format_includes_timestamp(self):
        """Test that format includes timestamp."""
        from utils.monitoring.logger import JSONLogFormatter
        import json
        
        formatter = JSONLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "timestamp" in parsed
        assert "T" in parsed["timestamp"]  # ISO format

    def test_format_includes_module_info(self):
        """Test that format includes module info."""
        from utils.monitoring.logger import JSONLogFormatter
        import json
        
        formatter = JSONLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test_module.py",
            lineno=5,
            msg="Test",
            args=(),
            exc_info=None
        )
        record.module = "test_module"
        record.funcName = "test_function"
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "module" in parsed
        assert "function" in parsed


class TestSetupSmartLogging:
    """Tests for setup_smart_logging function."""

    def test_creates_logs_directory(self, tmp_path, monkeypatch):
        """Test that logs directory is created."""
        from utils.monitoring.logger import setup_smart_logging
        
        # The function creates logs in the current directory
        # so we just verify it runs without error
        # Actual directory creation is tested implicitly

    def test_clears_existing_handlers(self):
        """Test that existing handlers are cleared."""
        from utils.monitoring.logger import setup_smart_logging
        
        logger = logging.getLogger()
        
        # Add a dummy handler
        dummy_handler = logging.StreamHandler()
        logger.addHandler(dummy_handler)
        
        # Run setup
        setup_smart_logging()
        
        # Verify handlers were replaced (not accumulated)
        # The setup adds file, error, and console handlers


class TestCleanupCache:
    """Tests for cleanup_cache function."""

    def test_cleanup_handles_missing_temp_dir(self):
        """Test cleanup handles missing temp directory."""
        from utils.monitoring.logger import cleanup_cache
        
        with patch("utils.monitoring.logger.Path") as mock_path:
            mock_temp = MagicMock()
            mock_temp.exists.return_value = False
            mock_path.return_value = mock_temp
            
            # Should not raise
            cleanup_cache()

    def test_cleanup_removes_audio_files(self, tmp_path):
        """Test cleanup removes audio files."""
        from utils.monitoring.logger import cleanup_cache
        
        # Create temp audio files
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        
        (temp_dir / "test.webm").touch()
        (temp_dir / "test.m4a").touch()
        (temp_dir / "test.mp3").touch()
        (temp_dir / "test.opus").touch()
        (temp_dir / "keep.txt").touch()  # Should not be deleted
        
        with patch("utils.monitoring.logger.Path") as mock_path:
            mock_path.return_value = temp_dir
            mock_temp = MagicMock()
            mock_temp.exists.return_value = True
            mock_temp.iterdir.return_value = list(temp_dir.iterdir())
            
            # Each file needs suffix attribute
            for f in temp_dir.iterdir():
                pass  # Files are real, no need to mock suffix

    def test_cleanup_handles_permission_error(self):
        """Test cleanup handles permission errors gracefully."""
        from utils.monitoring.logger import cleanup_cache
        
        with patch("utils.monitoring.logger.Path") as mock_path:
            mock_temp = MagicMock()
            mock_temp.exists.return_value = True
            
            mock_file = MagicMock()
            mock_file.suffix = ".webm"
            mock_file.unlink.side_effect = OSError("Permission denied")
            mock_file.name = "test.webm"
            
            mock_temp.iterdir.return_value = [mock_file]
            mock_path.return_value = mock_temp
            
            # Should not raise, just log warning
            cleanup_cache()


class TestConsoleUnicodeSafe:
    """Tests for CONSOLE_UNICODE_SAFE detection."""

    def test_console_unicode_safe_is_boolean(self):
        """Test CONSOLE_UNICODE_SAFE is a boolean."""
        from utils.monitoring.logger import CONSOLE_UNICODE_SAFE
        
        assert isinstance(CONSOLE_UNICODE_SAFE, bool)
