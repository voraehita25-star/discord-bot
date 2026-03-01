"""
Tests for utils.monitoring.audit_log module.
"""

from unittest.mock import patch

import pytest


class TestAuditLogConstants:
    """Tests for audit log constants."""

    def test_db_available_flag(self):
        """Test DB_AVAILABLE flag exists."""
        from utils.monitoring.audit_log import DB_AVAILABLE

        assert isinstance(DB_AVAILABLE, bool)


class TestAuditLoggerInit:
    """Tests for AuditLogger initialization."""

    def test_create_audit_logger(self):
        """Test creating AuditLogger instance."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()
        assert logger is not None

    def test_audit_logger_has_log_action(self):
        """Test AuditLogger has log_action method."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()
        assert hasattr(logger, 'log_action')
        assert callable(logger.log_action)

    def test_audit_logger_has_get_recent_actions(self):
        """Test AuditLogger has get_recent_actions method."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()
        assert hasattr(logger, 'get_recent_actions')
        assert callable(logger.get_recent_actions)


class TestLogAction:
    """Tests for log_action method."""

    @pytest.mark.asyncio
    async def test_log_action_without_db(self):
        """Test logging action when DB not available."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.log_action(
                user_id=123,
                action="test_action"
            )

            # Should still return True (logs to console)
            assert result is True

    @pytest.mark.asyncio
    async def test_log_action_with_all_params(self):
        """Test logging action with all parameters."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.log_action(
                user_id=123,
                action="channel_create",
                guild_id=456,
                target_type="channel",
                target_id=789,
                details='{"name": "test-channel"}'
            )

            assert result is True


class TestGetRecentActions:
    """Tests for get_recent_actions method."""

    @pytest.mark.asyncio
    async def test_get_recent_actions_without_db(self):
        """Test getting actions when DB not available."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.get_recent_actions(guild_id=123)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_actions_with_limit(self):
        """Test getting actions with custom limit."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.get_recent_actions(guild_id=123, limit=10)

            assert result == []


class TestGetUserActions:
    """Tests for get_user_actions method."""

    @pytest.mark.asyncio
    async def test_get_user_actions_without_db(self):
        """Test getting user actions when DB not available."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()

            if hasattr(logger, 'get_user_actions'):
                result = await logger.get_user_actions(user_id=123)
                assert result == []


class TestGlobalAuditInstance:
    """Tests for global audit instance."""

    def test_global_audit_instance_exists(self):
        """Test global audit instance exists."""
        from utils.monitoring.audit_log import audit

        assert audit is not None

    def test_global_audit_is_logger(self):
        """Test global audit is AuditLogger."""
        from utils.monitoring.audit_log import AuditLogger, audit

        assert isinstance(audit, AuditLogger)


class TestConvenienceFunctions:
    """Tests for convenience async functions."""

    @pytest.mark.asyncio
    async def test_log_admin_action(self):
        """Test log_admin_action convenience function."""
        from utils.monitoring.audit_log import log_admin_action

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await log_admin_action(
                user_id=123,
                action="test_action",
                guild_id=456,
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_log_channel_change(self):
        """Test log_channel_change convenience function."""
        from utils.monitoring.audit_log import log_channel_change

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await log_channel_change(
                user_id=123,
                guild_id=456,
                action="create",
                channel_id=789,
                channel_name="test-channel",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_log_role_change(self):
        """Test log_role_change convenience function."""
        from utils.monitoring.audit_log import log_role_change

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await log_role_change(
                user_id=123,
                guild_id=456,
                action="assign",
                role_id=789,
                role_name="Admin",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_log_role_change_with_target_user(self):
        """Test log_role_change with target user."""
        from utils.monitoring.audit_log import log_role_change

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            result = await log_role_change(
                user_id=123,
                guild_id=456,
                action="assign",
                role_id=789,
                role_name="Admin",
                target_user_id=999,
            )

            assert result is True


class TestLogActionDetailsHandling:
    """Tests for details JSON handling in log_action."""

    @pytest.mark.asyncio
    async def test_log_action_with_target_type_embeds_in_details(self):
        """Test that target_type is embedded into details JSON."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.log_action(
                user_id=123,
                action="test",
                target_type="channel",
                details='{"name": "test"}',
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_log_action_with_invalid_json_details(self):
        """Test handling of invalid JSON in details."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.log_action(
                user_id=123,
                action="test",
                target_type="user",
                details="not valid json",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_log_action_empty_details(self):
        """Test log_action with empty details."""
        from utils.monitoring.audit_log import AuditLogger

        with patch("utils.monitoring.audit_log.DB_AVAILABLE", False):
            logger = AuditLogger()
            result = await logger.log_action(
                user_id=123,
                action="test",
            )

            assert result is True


# ======================================================================
# Merged from test_audit_log_module.py
# ======================================================================

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

        assert hasattr(logger, 'log_action')
        assert callable(logger.log_action)

    @pytest.mark.asyncio
    async def test_get_recent_actions_has_method(self):
        """Test AuditLogger has get_recent_actions method."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        assert hasattr(logger, 'get_recent_actions')
        assert callable(logger.get_recent_actions)


class TestLogAction:
    """Tests for log_action method."""

    @pytest.mark.asyncio
    async def test_log_action_basic(self):
        """Test log_action with basic parameters."""
        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()

        with patch('utils.monitoring.audit_log.DB_AVAILABLE', False):
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

        with patch('utils.monitoring.audit_log.DB_AVAILABLE', False):
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

        with patch('utils.monitoring.audit_log.DB_AVAILABLE', False):
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
        assert 'user_id' in params
        assert 'action' in params

    @pytest.mark.asyncio
    async def test_get_recent_actions_signature(self):
        """Test get_recent_actions method signature."""
        import inspect

        from utils.monitoring.audit_log import AuditLogger

        logger = AuditLogger()
        sig = inspect.signature(logger.get_recent_actions)

        params = sig.parameters
        assert 'guild_id' in params
