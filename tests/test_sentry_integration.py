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

    def test_before_send_redacts_exception_value(self):
        """The before_send scrubber must redact the exception's own message
        string (exc['value']) — a secret in exception text is the single most
        common place secrets appear, and it isn't covered by the stack/message
        scrubs. exc['type'] (the grouping/fingerprint identifier) stays intact.
        """
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with patch("sentry_sdk.init") as mock_init:
            sentry_integration.init_sentry(dsn="https://test@sentry.io/123")

        before_send = mock_init.call_args.kwargs["before_send"]
        # Real sk-ant token shape (40+ chars after the prefix) so the REAL
        # _redact_sensitive regex actually fires — do not mock the redactor.
        token = "sk-ant-api03-" + "A" * 45
        event = {
            "exception": {
                "values": [{"type": "RuntimeError", "value": f"auth failed with token {token}"}]
            }
        }
        out = before_send(event, {})

        redacted = out["exception"]["values"][0]["value"]
        assert "sk-ant" not in redacted
        assert "[REDACTED]" in redacted
        # Exception type must be untouched (used for Sentry issue grouping).
        assert out["exception"]["values"][0]["type"] == "RuntimeError"

    def test_scrub_hooks_redact_secrets_nested_in_data_and_extra(self):
        """The before_breadcrumb/before_send hooks must redact secrets nested
        inside crumb['data'] / event['extra'] (audit 2026-06-28: the hooks
        discard _deep_redact's return, so a non-mutating _deep_redact silently
        stops redacting nested secrets — the always-on production path)."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with (
            patch("sentry_sdk.init") as mock_init,
            patch(
                "utils.monitoring.logger._redact_sensitive",
                side_effect=lambda v: "[REDACTED]" if isinstance(v, str) else v,
            ),
        ):
            sentry_integration.init_sentry(dsn="https://test@sentry.io/123", environment="test")

        kwargs = mock_init.call_args.kwargs
        before_breadcrumb = kwargs["before_breadcrumb"]
        before_send = kwargs["before_send"]

        crumb = {"data": {"request": {"headers": {"Authorization": "sk-ant-supersecret"}}}}
        scrubbed = before_breadcrumb(crumb, {})
        assert scrubbed["data"]["request"]["headers"]["Authorization"] == "[REDACTED]"

        event = {"extra": {"ctx": {"api_key": "sk-ant-supersecret"}}}
        scrubbed_event = before_send(event, {})
        assert scrubbed_event["extra"]["ctx"]["api_key"] == "[REDACTED]"


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

    def test_capture_exception_does_not_mutate_context(self):
        """capture_exception must redact a COPY of the caller's context. Passing
        a reused mutable object (e.g. self._config) must not have its live
        secret overwritten with '[REDACTED]' as a side effect of the report.
        """
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        # Real sk-ant token shape so the REAL redactor fires — without the
        # deep-copy fix this exact leaf would be overwritten in the caller's dict.
        secret = "sk-ant-api03-" + "B" * 45
        ctx = {"cfg": {"api_key": secret}}

        mock_scope = MagicMock()
        with (
            patch("sentry_sdk.new_scope") as mock_new_scope,
            patch("sentry_sdk.capture_exception", return_value="event-id"),
        ):
            mock_new_scope.return_value.__enter__ = MagicMock(return_value=mock_scope)
            mock_new_scope.return_value.__exit__ = MagicMock(return_value=False)

            sentry_integration.capture_exception(ValueError("x"), context=ctx)

        # Caller's live object is untouched...
        assert ctx["cfg"]["api_key"] == secret
        # ...while the redacted COPY is what reached Sentry.
        mock_scope.set_extra.assert_called_once_with("cfg", {"api_key": "[REDACTED]"})


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

    def test_capture_message_redacts_context(self):
        """capture_message must redact string context values (parity with
        capture_exception) so a secret passed in context can't leak to Sentry."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        mock_scope = MagicMock()
        with (
            patch("sentry_sdk.new_scope") as mock_new_scope,
            patch("sentry_sdk.capture_message", return_value="event-id"),
            patch(
                "utils.monitoring.logger._redact_sensitive",
                side_effect=lambda _v: "[REDACTED]",
            ),
        ):
            mock_new_scope.return_value.__enter__ = MagicMock(return_value=mock_scope)
            mock_new_scope.return_value.__exit__ = MagicMock(return_value=False)

            sentry_integration.capture_message("boom", context={"api_key": "sk-ant-supersecret"})

        # The string value must have been redacted before reaching set_extra.
        mock_scope.set_extra.assert_called_once_with("api_key", "[REDACTED]")


class TestDeepRedactNonMutation:
    """_deep_redact must redact into a fresh structure without mutating the
    caller-owned dict (audit 2026-06-28: capture_exception/capture_message
    fed caller-owned context values through it)."""

    def test_deep_redact_does_not_mutate_caller_dict(self):
        from utils.monitoring import sentry_integration

        original = {
            "request": {"headers": {"Authorization": "secret-token"}},
            "items": ["a", "b"],
        }
        redacted = sentry_integration._deep_redact(original, lambda _v: "[REDACTED]")

        # Caller-owned input is left untouched (no in-place mutation).
        assert original == {
            "request": {"headers": {"Authorization": "secret-token"}},
            "items": ["a", "b"],
        }
        # A fresh object is returned, fully redacted at every depth.
        assert redacted is not original
        assert redacted == {
            "request": {"headers": {"Authorization": "[REDACTED]"}},
            "items": ["[REDACTED]", "[REDACTED]"],
        }


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
        """Test set_user_context writes to the isolation scope when available.

        ``set_user_context`` was changed to honour its docstring — it now
        targets the per-task isolation scope rather than the global one
        when the installed sentry_sdk exposes ``get_isolation_scope``.
        Falls back to the global ``sentry_sdk.set_user`` only on older SDKs.
        """
        import sentry_sdk

        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        if hasattr(sentry_sdk, "get_isolation_scope"):
            with patch("sentry_sdk.get_isolation_scope") as mock_iso:
                sentry_integration.set_user_context(123, "testuser")
                mock_iso.return_value.set_user.assert_called_once_with(
                    {"id": "123", "username": "testuser"}
                )
        else:
            with patch("sentry_sdk.set_user") as mock_set_user:
                sentry_integration.set_user_context(123, "testuser")
                mock_set_user.assert_called_once_with({"id": "123", "username": "testuser"})

    def test_set_user_global_with_sdk(self):
        """Test set_user_global still writes to the global scope."""
        from utils.monitoring import sentry_integration

        if not sentry_integration.SENTRY_AVAILABLE:
            pytest.skip("Sentry SDK not available")

        with patch("sentry_sdk.set_user") as mock_set_user:
            sentry_integration.set_user_global(123, "testuser")
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
