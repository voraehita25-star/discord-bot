"""
Tests for utils.media.colors module.
"""

import ctypes
import sys
from unittest.mock import MagicMock, patch


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

        with patch.object(sys, "platform", "linux"):
            result = enable_windows_ansi()
            assert result is True

    @staticmethod
    def _make_fake_kernel32(get_console_mode_result):
        """สร้าง kernel32 ปลอมที่คืน Win64 INVALID_HANDLE_VALUE จาก GetStdHandle.

        get_console_mode_result คือค่าที่ GetConsoleMode จะคืน (0 = ล้มเหลว เช่น
        ตอน stdout ถูก redirect / piped).
        """
        kernel32 = MagicMock()
        # ค่า sentinel แบบ unsigned ของ Win64: 0xFFFFFFFFFFFFFFFF
        kernel32.GetStdHandle.return_value = ctypes.c_void_p(-1).value
        kernel32.GetConsoleMode.return_value = get_console_mode_result
        return kernel32

    def test_win64_invalid_handle_detected_skips_console_mode(self):
        """regression py-utils-mon-1: ต้องตั้ง restype=c_void_p และเทียบกับ
        ค่า unsigned sentinel เพื่อให้ตรวจจับ INVALID_HANDLE_VALUE บน Win64 ได้
        (ไม่ใช่เทียบกับ -1 ตรง ๆ ที่จะพลาดบน 64-bit)."""
        from utils.media.colors import enable_windows_ansi

        kernel32 = self._make_fake_kernel32(get_console_mode_result=1)
        fake_windll = MagicMock()
        fake_windll.kernel32 = kernel32

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(ctypes, "windll", fake_windll, create=True),
            patch.object(sys.stdout, "reconfigure", create=True),
            patch.object(sys.stderr, "reconfigure", create=True),
        ):
            result = enable_windows_ansi()

        assert result is True
        # restype ต้องถูกตั้งเป็น c_void_p เพื่อไม่ให้ ctypes ตัด handle เป็น signed int
        assert kernel32.GetStdHandle.restype is ctypes.c_void_p
        # handle เป็น INVALID_HANDLE_VALUE จึงต้องไม่แตะ console mode เลย
        kernel32.GetConsoleMode.assert_not_called()
        kernel32.SetConsoleMode.assert_not_called()

    def test_set_console_mode_skipped_when_get_console_mode_fails(self):
        """regression py-utils-mon-missed-1: เมื่อ GetConsoleMode ล้มเหลว (คืน 0,
        เช่น handle ถูก redirect) ต้องไม่เรียก SetConsoleMode เพื่อไม่ให้ทับ
        console mode เดิมด้วย 0x0004."""
        from utils.media.colors import enable_windows_ansi

        kernel32 = MagicMock()
        # handle ที่ valid (ไม่ใช่ sentinel) แต่ GetConsoleMode ล้มเหลว
        kernel32.GetStdHandle.return_value = 0x1234
        kernel32.GetConsoleMode.return_value = 0
        fake_windll = MagicMock()
        fake_windll.kernel32 = kernel32

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(ctypes, "windll", fake_windll, create=True),
            patch.object(sys.stdout, "reconfigure", create=True),
            patch.object(sys.stderr, "reconfigure", create=True),
        ):
            result = enable_windows_ansi()

        assert result is True
        kernel32.GetConsoleMode.assert_called_once()
        kernel32.SetConsoleMode.assert_not_called()

    def test_set_console_mode_called_when_get_console_mode_succeeds(self):
        """เมื่อ handle valid และ GetConsoleMode สำเร็จ ต้องเปิด
        ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) โดย OR ทับ mode เดิม."""
        from utils.media.colors import enable_windows_ansi

        kernel32 = MagicMock()
        kernel32.GetStdHandle.return_value = 0x1234
        kernel32.GetConsoleMode.return_value = 1
        fake_windll = MagicMock()
        fake_windll.kernel32 = kernel32

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(ctypes, "windll", fake_windll, create=True),
            patch.object(sys.stdout, "reconfigure", create=True),
            patch.object(sys.stderr, "reconfigure", create=True),
        ):
            result = enable_windows_ansi()

        assert result is True
        kernel32.SetConsoleMode.assert_called_once()
        handle_arg, mode_arg = kernel32.SetConsoleMode.call_args.args
        assert handle_arg == 0x1234
        # console_mode เริ่มต้นที่ 0 (mock ไม่ได้เขียนค่ากลับ) → 0 | 0x0004
        assert mode_arg & 0x0004


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
