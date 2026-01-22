"""
Tests for utils.media.colors module.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys


class TestColorsClass:
    """Tests for Colors class."""

    def test_colors_class_exists(self):
        """Test Colors class exists."""
        from utils.media.colors import Colors
        
        assert Colors is not None

    def test_reset_code(self):
        """Test RESET code."""
        from utils.media.colors import Colors
        
        assert Colors.RESET == "\033[0m"

    def test_bold_code(self):
        """Test BOLD code."""
        from utils.media.colors import Colors
        
        assert Colors.BOLD == "\033[1m"

    def test_dim_code(self):
        """Test DIM code."""
        from utils.media.colors import Colors
        
        assert Colors.DIM == "\033[2m"

    def test_red_code(self):
        """Test RED code."""
        from utils.media.colors import Colors
        
        assert Colors.RED == "\033[31m"

    def test_green_code(self):
        """Test GREEN code."""
        from utils.media.colors import Colors
        
        assert Colors.GREEN == "\033[32m"

    def test_yellow_code(self):
        """Test YELLOW code."""
        from utils.media.colors import Colors
        
        assert Colors.YELLOW == "\033[33m"

    def test_blue_code(self):
        """Test BLUE code."""
        from utils.media.colors import Colors
        
        assert Colors.BLUE == "\033[34m"

    def test_magenta_code(self):
        """Test MAGENTA code."""
        from utils.media.colors import Colors
        
        assert Colors.MAGENTA == "\033[35m"

    def test_cyan_code(self):
        """Test CYAN code."""
        from utils.media.colors import Colors
        
        assert Colors.CYAN == "\033[36m"

    def test_white_code(self):
        """Test WHITE code."""
        from utils.media.colors import Colors
        
        assert Colors.WHITE == "\033[37m"

    def test_bright_red_code(self):
        """Test BRIGHT_RED code."""
        from utils.media.colors import Colors
        
        assert Colors.BRIGHT_RED == "\033[91m"

    def test_bright_green_code(self):
        """Test BRIGHT_GREEN code."""
        from utils.media.colors import Colors
        
        assert Colors.BRIGHT_GREEN == "\033[92m"

    def test_bright_yellow_code(self):
        """Test BRIGHT_YELLOW code."""
        from utils.media.colors import Colors
        
        assert Colors.BRIGHT_YELLOW == "\033[93m"

    def test_bright_blue_code(self):
        """Test BRIGHT_BLUE code."""
        from utils.media.colors import Colors
        
        assert Colors.BRIGHT_BLUE == "\033[94m"

    def test_bright_magenta_code(self):
        """Test BRIGHT_MAGENTA code."""
        from utils.media.colors import Colors
        
        assert Colors.BRIGHT_MAGENTA == "\033[95m"

    def test_bright_cyan_code(self):
        """Test BRIGHT_CYAN code."""
        from utils.media.colors import Colors
        
        assert Colors.BRIGHT_CYAN == "\033[96m"


class TestEnableWindowsANSI:
    """Tests for enable_windows_ansi function."""

    def test_function_exists(self):
        """Test function exists."""
        from utils.media.colors import enable_windows_ansi
        
        assert callable(enable_windows_ansi)

    def test_returns_bool(self):
        """Test function returns bool."""
        from utils.media.colors import enable_windows_ansi
        
        result = enable_windows_ansi()
        assert isinstance(result, bool)

    def test_non_windows_returns_true(self):
        """Test non-Windows platform returns True."""
        from utils.media.colors import enable_windows_ansi
        
        with patch.object(sys, 'platform', 'linux'):
            result = enable_windows_ansi()
            assert result is True


class TestColorsUsage:
    """Tests for using Colors in strings."""

    def test_color_formatting(self):
        """Test color codes can be used in f-strings."""
        from utils.media.colors import Colors
        
        message = f"{Colors.GREEN}Success{Colors.RESET}"
        
        assert "\033[32m" in message
        assert "\033[0m" in message
        assert "Success" in message

    def test_bold_color_combination(self):
        """Test combining bold with color."""
        from utils.media.colors import Colors
        
        message = f"{Colors.BOLD}{Colors.RED}Error{Colors.RESET}"
        
        assert "\033[1m" in message
        assert "\033[31m" in message
        assert "Error" in message
