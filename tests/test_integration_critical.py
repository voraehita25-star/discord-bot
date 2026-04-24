"""
Integration tests for critical system paths.

Tests WebSocket auth enforcement, database pool exhaustion timeout,
and graceful shutdown behavior.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# WebSocket Auth Tests
# ============================================================================


class TestWebSocketAuth:
    """Tests for WebSocket authentication enforcement."""

    def _make_request(self, *, origin: str = "http://localhost:3000", host: str = "localhost:8765",
                      token: str = "", auth_header: str = "", query_token: str = "") -> MagicMock:
        """Create a mock aiohttp request."""
        request = MagicMock()
        request.headers = {
            "Origin": origin,
            "Host": host,
        }
        if auth_header:
            request.headers["Authorization"] = auth_header
        request.query = {}
        if query_token:
            request.query["token"] = query_token
        transport = MagicMock()
        transport.get_extra_info.return_value = ("127.0.0.1", 12345)
        request.transport = transport
        return request

    @pytest.mark.asyncio
    async def test_missing_token_rejects_connection(self):
        """WebSocket must reject connections when DASHBOARD_WS_TOKEN is not set."""
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        server = DashboardWebSocketServer.__new__(DashboardWebSocketServer)
        server.clients = set()
        server.MAX_CLIENTS = 20
        server._authenticated_clients = set()
        server._client_message_times = {}
        server._client_inflight = {}
        server._auth_deadline = 5.0

        request = self._make_request()

        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": ""}, clear=False):
            result = await server.websocket_handler(request)
            assert result.status == 401
            assert "required" in result.text.lower()

    @pytest.mark.asyncio
    async def test_invalid_token_rejects(self):
        """WebSocket must reject connections with invalid bearer token."""
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        server = DashboardWebSocketServer.__new__(DashboardWebSocketServer)
        server.clients = set()
        server.MAX_CLIENTS = 20
        server._authenticated_clients = set()
        server._client_message_times = {}
        server._client_inflight = {}
        server._auth_deadline = 5.0

        request = self._make_request(auth_header="Bearer wrong-token")

        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "correct-secret"}, clear=False):
            result = await server.websocket_handler(request)
            assert result.status == 401

    @pytest.mark.asyncio
    async def test_invalid_origin_rejects(self):
        """WebSocket must reject connections from non-localhost origins."""
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        server = DashboardWebSocketServer.__new__(DashboardWebSocketServer)
        server.clients = set()
        server.MAX_CLIENTS = 20
        server._authenticated_clients = set()

        request = self._make_request(origin="https://evil.com", host="evil.com")

        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "test-token"}, clear=False):
            result = await server.websocket_handler(request)
            assert result.status == 403


# ============================================================================
# Database Pool Timeout Tests
# ============================================================================


class TestDatabasePoolTimeout:
    """Tests for database connection pool timeout behavior."""

    @pytest.mark.asyncio
    async def test_pool_timeout_raises(self, temp_db: str):
        """Pool should raise TimeoutError when exhausted beyond timeout."""
        from utils.database.database import Database

        db = Database.__new__(Database)
        db.db_path = temp_db
        db._connection_count = 0
        db._pool_semaphore = asyncio.Semaphore(1)
        db._conn_pool = asyncio.Queue(maxsize=1)
        db._write_lock = None

        # Acquire the only slot
        await db._pool_semaphore.acquire()

        # Now trying to get a connection should timeout
        with pytest.raises(TimeoutError, match="pool exhausted"):
            # Use a very short timeout by patching DB_CONNECTION_TIMEOUT
            with patch("utils.database.database.DB_CONNECTION_TIMEOUT", 0.1):
                async with db.get_connection():
                    pass

        # Release the slot to clean up
        db._pool_semaphore.release()

    @pytest.mark.asyncio
    async def test_pool_semaphore_released_on_error(self, temp_db: str):
        """Semaphore must be released even if connection creation fails."""
        from utils.database.database import Database

        db = Database.__new__(Database)
        db.db_path = "/nonexistent/path/to/db.sqlite"
        db._connection_count = 0
        db._pool_semaphore = asyncio.Semaphore(2)
        db._conn_pool = asyncio.Queue(maxsize=2)
        db._write_lock = None

        import sqlite3

        # Connection will fail due to bad path, but semaphore should be released
        with pytest.raises(sqlite3.OperationalError):
            with patch("utils.database.database.DB_CONNECTION_TIMEOUT", 2):
                async with db.get_connection():
                    pass

        # Semaphore should still be available (was released in finally)
        assert db._pool_semaphore._value == 2


# ============================================================================
# Graceful Shutdown Tests
# ============================================================================


class TestGracefulShutdown:
    """Tests for bot graceful shutdown sequence."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_database_pool(self):
        """Shutdown should flush exports and close the DB pool."""
        mock_db = AsyncMock()
        mock_db.flush_pending_exports = AsyncMock()
        mock_db.close_pool = AsyncMock()

        mock_bot = MagicMock()
        mock_bot.is_closed.return_value = False
        mock_bot.close = AsyncMock()
        mock_bot._health_task = None

        with patch("bot.bot", mock_bot), \
             patch("bot.DASHBOARD_WS_AVAILABLE", False), \
             patch("bot.stop_dashboard_ws_server", None), \
             patch("utils.database.db", mock_db):
            # Import after patching
            from bot import graceful_shutdown
            await graceful_shutdown()

        mock_db.flush_pending_exports.assert_awaited_once()
        mock_db.close_pool.assert_awaited_once()
        mock_bot.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_health_task(self):
        """Shutdown should properly cancel and await the health task."""
        # Create a real cancellable task
        async def _dummy():
            await asyncio.sleep(999)

        health_task = asyncio.create_task(_dummy())

        mock_bot = MagicMock()
        mock_bot.is_closed.return_value = False
        mock_bot.close = AsyncMock()
        mock_bot._health_task = health_task

        with patch("bot.bot", mock_bot), \
             patch("bot.DASHBOARD_WS_AVAILABLE", False), \
             patch("bot.stop_dashboard_ws_server", None):
            from bot import graceful_shutdown
            await graceful_shutdown()

        assert health_task.cancelled()


# ============================================================================
# CORS Middleware Tests
# ============================================================================


class TestCORSMiddleware:
    """Tests for CORS header enforcement on WebSocket server."""

    @pytest.mark.asyncio
    async def test_cors_allows_localhost(self):
        """CORS middleware should add headers for localhost origins."""
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        server = DashboardWebSocketServer.__new__(DashboardWebSocketServer)

        mock_request = MagicMock()
        mock_request.headers = {"Origin": "http://localhost:3000"}

        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_handler(req):
            return mock_response

        result = await server._cors_middleware(mock_request, mock_handler)
        assert result.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_cors_blocks_external_origin(self):
        """CORS middleware should NOT add headers for external origins."""
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        server = DashboardWebSocketServer.__new__(DashboardWebSocketServer)

        mock_request = MagicMock()
        mock_request.headers = {"Origin": "https://evil.com"}

        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_handler(req):
            return mock_response

        result = await server._cors_middleware(mock_request, mock_handler)
        assert "Access-Control-Allow-Origin" not in result.headers

    @pytest.mark.asyncio
    async def test_cors_allows_tauri(self):
        """CORS middleware should allow tauri://localhost origin."""
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        server = DashboardWebSocketServer.__new__(DashboardWebSocketServer)

        mock_request = MagicMock()
        mock_request.headers = {"Origin": "tauri://localhost"}

        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_handler(req):
            return mock_response

        result = await server._cors_middleware(mock_request, mock_handler)
        assert result.headers.get("Access-Control-Allow-Origin") == "tauri://localhost"
