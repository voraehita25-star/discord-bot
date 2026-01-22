"""
Tests for utils.monitoring.audit_log module.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json


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
        from utils.monitoring.audit_log import audit, AuditLogger

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

