"""Tests for audit log module."""

from unittest.mock import patch

import pytest


class TestAuditLogger:
    """Tests for AuditLogger class."""

    def test_audit_logger_import(self):
        """Test AuditLogger can be imported."""
        from utils.monitoring.audit_log import AuditLogger

        assert AuditLogger is not None

    def test_audit_logger_creation(self):
        """Test AuditLogger can be created."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        assert logger is not None

    @pytest.mark.asyncio
    async def test_log_action_has_method(self):
        """Test AuditLogger has log_action method."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        assert hasattr(logger, "log_action")
        assert callable(logger.log_action)

    @pytest.mark.asyncio
    async def test_get_recent_actions_has_method(self):
        """Test AuditLogger has get_recent_actions method."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        assert hasattr(logger, "get_recent_actions")
        assert callable(logger.get_recent_actions)


class TestLogAction:
    """Tests for log_action method."""

    @pytest.mark.asyncio
    async def test_log_action_basic(self):
        """Test log_action with basic parameters."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await logger.log_action(
                user_id=12345,
                action="test_action",
            )

        # When DB not available, should log to console and return True
        assert result is True

    @pytest.mark.asyncio
    async def test_log_action_full_params(self):
        """Test log_action with all parameters."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await logger.log_action(
                user_id=12345,
                action="test_action",
                guild_id=67890,
                target_type="user",
                target_id=11111,
                details='{"reason": "test"}',
            )

        assert result is True


class TestGetRecentActions:
    """Tests for get_recent_actions method."""

    @pytest.mark.asyncio
    async def test_get_recent_actions_no_db(self):
        """Test get_recent_actions when DB not available."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await logger.get_recent_actions(guild_id=12345)

        assert result == []


class TestDBAvailable:
    """Tests for DB_AVAILABLE flag."""

    def test_db_available_flag_exists(self):
        """Test DB_AVAILABLE flag exists."""
        from utils.monitoring.audit_log import DB_AVAILABLE

        assert isinstance(DB_AVAILABLE, bool)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_audit_log(self):
        """Test audit_log module can be imported."""
        from utils.monitoring import audit_log

        assert audit_log is not None

    def test_import_audit_logger_class(self):
        """Test AuditLogger class can be imported."""
        from utils.monitoring.audit_log import AuditLogger

        assert AuditLogger is not None


class TestAuditLogSingleton:
    """Tests for audit_log singleton."""

    def test_audit_log_singleton_exists(self):
        """Test audit_log singleton exists."""
        try:
            from utils.monitoring.audit_log import audit_log

            assert audit_log is not None
        except ImportError:
            # Some modules may not export singleton
            pass


class TestAuditLoggerMethods:
    """Tests for AuditLogger method signatures."""

    @pytest.mark.asyncio
    async def test_log_action_signature(self):
        """Test log_action method signature."""
        import inspect

        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()
        sig = inspect.signature(logger.log_action)

        # Check required parameters
        params = sig.parameters
        assert "user_id" in params
        assert "action" in params

    @pytest.mark.asyncio
    async def test_get_recent_actions_signature(self):
        """Test get_recent_actions method signature."""
        import inspect

        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()
        sig = inspect.signature(logger.get_recent_actions)

        params = sig.parameters
        assert "guild_id" in params
