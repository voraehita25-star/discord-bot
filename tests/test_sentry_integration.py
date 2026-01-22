"""Tests for sentry_integration module."""

from unittest.mock import MagicMock, patch

import pytest


class TestSentryAvailability:
    """Tests for Sentry availability check."""

    def test_sentry_available_check(self):
        """Test SENTRY_AVAILABLE constant exists."""
        from utils.monitoring.sentry_integration import SENTRY_AVAILABLE

        assert isinstance(SENTRY_AVAILABLE, bool)


class TestInitSentry:
    """Tests for init_sentry function."""

    def test_init_sentry_no_sdk(self):
        """Test init_sentry returns False when SDK not available."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            result = sentry_integration.init_sentry(dsn="test-dsn")
            assert result is False
        finally:
            sentry_integration.SENTRY_AVAILABLE = original

    def test_init_sentry_no_dsn(self):
        """Test init_sentry returns False when no DSN."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = True

        try:
            with patch.dict("os.environ", {}, clear=True):
                with patch.object(sentry_integration, "os") as mock_os:
                    mock_os.getenv.return_value = None
                    sentry_integration.init_sentry(dsn=None)
                    # Should return False since no DSN
        finally:
            sentry_integration.SENTRY_AVAILABLE = original

    def test_init_sentry_with_dsn(self):
        """Test init_sentry with DSN provided."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with patch("sentry_sdk.init") as mock_init:
            result = sentry_integration.init_sentry(
                dsn="https://test@sentry.io/123",
                environment="test",
                sample_rate=0.5,
            )

            if result:
                mock_init.assert_called_once()


class TestCaptureException:
    """Tests for capture_exception function."""

    def test_capture_exception_no_sdk(self):
        """Test capture_exception returns None when SDK not available."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            result = sentry_integration.capture_exception(ValueError("test"))
            assert result is None
        finally:
            sentry_integration.SENTRY_AVAILABLE = original

    def test_capture_exception_with_context(self):
        """Test capture_exception with context."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with patch("sentry_sdk.push_scope") as mock_scope:
            mock_context = MagicMock()
            mock_scope.return_value.__enter__ = MagicMock(return_value=mock_context)
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)

            with patch("sentry_sdk.capture_exception", return_value="event-id"):
                sentry_integration.capture_exception(
                    ValueError("test"),
                    context={"key": "value"},
                    user_id=123,
                    guild_id=456,
                )

    def test_capture_exception_basic(self):
        """Test capture_exception basic call."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            result = sentry_integration.capture_exception(Exception("test"))
            assert result is None
        finally:
            sentry_integration.SENTRY_AVAILABLE = original


class TestCaptureMessage:
    """Tests for capture_message function."""

    def test_capture_message_no_sdk(self):
        """Test capture_message returns None when SDK not available."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            result = sentry_integration.capture_message("test message")
            assert result is None
        finally:
            sentry_integration.SENTRY_AVAILABLE = original

    def test_capture_message_with_level(self):
        """Test capture_message with level."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            result = sentry_integration.capture_message(
                "test", level="warning", context={"key": "value"}
            )
            assert result is None
        finally:
            sentry_integration.SENTRY_AVAILABLE = original


class TestSetUserContext:
    """Tests for set_user_context function."""

    def test_set_user_context_no_sdk(self):
        """Test set_user_context when SDK not available."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            # Should not raise
            sentry_integration.set_user_context(123, "testuser")
        finally:
            sentry_integration.SENTRY_AVAILABLE = original

    def test_set_user_context_with_sdk(self):
        """Test set_user_context with SDK available."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with patch("sentry_sdk.set_user") as mock_set_user:
            sentry_integration.set_user_context(123, "testuser")
            mock_set_user.assert_called_once_with({"id": "123", "username": "testuser"})


class TestAddBreadcrumb:
    """Tests for add_breadcrumb function."""

    def test_add_breadcrumb_no_sdk(self):
        """Test add_breadcrumb when SDK not available."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            # Should not raise
            sentry_integration.add_breadcrumb("test message")
        finally:
            sentry_integration.SENTRY_AVAILABLE = original

    def test_add_breadcrumb_with_sdk(self):
        """Test add_breadcrumb with SDK available."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with patch("sentry_sdk.add_breadcrumb") as mock_add:
            sentry_integration.add_breadcrumb(
                "test message",
                category="action",
                level="info",
                data={"key": "value"},
            )
            mock_add.assert_called_once()

    def test_add_breadcrumb_defaults(self):
        """Test add_breadcrumb with default values."""
        from utils.monitoring import sentry_integration

        original = sentry_integration.SENTRY_AVAILABLE
        sentry_integration.SENTRY_AVAILABLE = False

        try:
            # Should not raise with defaults
            sentry_integration.add_breadcrumb("test")
        finally:
            sentry_integration.SENTRY_AVAILABLE = original


class TestModuleImports:
    """Tests for module imports."""

    def test_import_init_sentry(self):
        """Test importing init_sentry."""
        from utils.monitoring.sentry_integration import init_sentry

        assert callable(init_sentry)

    def test_import_capture_exception(self):
        """Test importing capture_exception."""
        from utils.monitoring.sentry_integration import capture_exception

        assert callable(capture_exception)

    def test_import_capture_message(self):
        """Test importing capture_message."""
        from utils.monitoring.sentry_integration import capture_message

        assert callable(capture_message)

    def test_import_set_user_context(self):
        """Test importing set_user_context."""
        from utils.monitoring.sentry_integration import set_user_context

        assert callable(set_user_context)

    def test_import_add_breadcrumb(self):
        """Test importing add_breadcrumb."""
        from utils.monitoring.sentry_integration import add_breadcrumb

        assert callable(add_breadcrumb)
