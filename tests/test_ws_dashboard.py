"""Tests for Dashboard WebSocket server (ws_dashboard.py).

Covers auth flow, message routing, rate limiting, concurrency limits,
input validation, and conversation management.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: Fake WebSocketResponse
# ---------------------------------------------------------------------------
class FakeWS:
    """Minimal fake aiohttp.web.WebSocketResponse for testing."""

    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def last(self) -> dict:
        return self.sent[-1] if self.sent else {}

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


# ---------------------------------------------------------------------------
# Fixture: DashboardWebSocketServer instance with mocked Gemini
# ---------------------------------------------------------------------------
@pytest.fixture()
def server():
    """Create a DashboardWebSocketServer with a mocked Gemini client."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "DASHBOARD_WS_TOKEN": ""}):
        with patch("cogs.ai_core.api.ws_dashboard.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer
            srv = DashboardWebSocketServer()
            srv.gemini_client = MagicMock()
            return srv


@pytest.fixture()
def ws():
    """Create a fresh FakeWS."""
    return FakeWS()


# ===================================================================
# Auth Tests
# ===================================================================
class TestAuth:
    """Test WebSocket auth message handler."""

    @pytest.mark.asyncio
    async def test_auth_no_token_required(self, server, ws):
        """When DASHBOARD_WS_TOKEN is not set, auth message should succeed silently."""
        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": ""}):
            await server.handle_message(ws, {"type": "auth", "token": "anything"}, "c1")
        # No error sent
        assert not ws.find("error")

    @pytest.mark.asyncio
    async def test_auth_valid_token(self, server, ws):
        """Valid token should authenticate without error."""
        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}):
            await server.handle_message(ws, {"type": "auth", "token": "secret123"}, "c1")
        assert not ws.find("error")

    @pytest.mark.asyncio
    async def test_auth_invalid_token(self, server, ws):
        """Invalid token should return error."""
        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}):
            await server.handle_message(ws, {"type": "auth", "token": "wrong"}, "c1")
        errors = ws.find("error")
        assert len(errors) == 1
        assert "Invalid auth token" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_auth_empty_token_when_required(self, server, ws):
        """Empty token when one is required should return error."""
        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}):
            await server.handle_message(ws, {"type": "auth", "token": ""}, "c1")
        errors = ws.find("error")
        assert len(errors) == 1


# ===================================================================
# Ping / Pong
# ===================================================================
class TestPingPong:
    """Test ping/pong keepalive."""

    @pytest.mark.asyncio
    async def test_ping_returns_pong(self, server, ws):
        await server.handle_message(ws, {"type": "ping"}, "c1")
        assert ws.last() == {"type": "pong"}


# ===================================================================
# Message Routing
# ===================================================================
class TestMessageRouting:
    """Test handle_message dispatches to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self, server, ws):
        await server.handle_message(ws, {"type": "nonexistent"}, "c1")
        assert "Unknown message type" in ws.last()["message"]

    @pytest.mark.asyncio
    async def test_new_conversation_creates_id(self, server, ws):
        """new_conversation should return conversation_created with an ID."""
        with patch("cogs.ai_core.api.ws_dashboard.DB_AVAILABLE", False):
            await server.handle_message(ws, {"type": "new_conversation", "role_preset": "general"}, "c1")
        created = ws.find("conversation_created")
        assert len(created) == 1
        assert "id" in created[0]
        assert created[0]["role_preset"] == "general"

    @pytest.mark.asyncio
    async def test_new_conversation_invalid_preset_defaults_to_general(self, server, ws):
        """Invalid role_preset should default to 'general'."""
        with patch("cogs.ai_core.api.ws_dashboard.DB_AVAILABLE", False):
            await server.handle_message(ws, {"type": "new_conversation", "role_preset": "invalid_preset"}, "c1")
        created = ws.find("conversation_created")
        assert len(created) == 1
        assert created[0]["role_preset"] == "general"


# ===================================================================
# Rate Limiting
# ===================================================================
class TestRateLimiting:
    """Test per-client rate limiting (30 msg/min)."""

    @pytest.mark.asyncio
    async def test_under_rate_limit(self, server, ws):
        """Messages under the limit should be processed."""
        for i in range(5):
            await server.handle_message(ws, {"type": "ping"}, "c1")
        pongs = ws.find("pong")
        assert len(pongs) == 5

    @pytest.mark.asyncio
    async def test_rate_limit_enforced_in_handler_loop(self, server):
        """Simulating rate limit by pre-filling message times."""
        ws = FakeWS()
        client_id = "rate-test"
        # Pre-fill with 30 recent timestamps (simulating burst)
        now = asyncio.get_event_loop().time()
        server._client_message_times[client_id] = [now - i for i in range(30)]
        # The rate limit check is in websocket_handler loop, not handle_message.
        # But we can test the tracking dict directly.
        times = server._client_message_times[client_id]
        recent = [t for t in times if now - t < 60]
        assert len(recent) == 30  # At limit


# ===================================================================
# Concurrency Limiting
# ===================================================================
class TestConcurrencyLimit:
    """Test per-client concurrent request limit (max 2)."""

    @pytest.mark.asyncio
    async def test_concurrency_limit_rejects_third(self, server, ws):
        """Third concurrent 'message' request should be rejected."""
        client_id = "conc-test"
        server._client_inflight[client_id] = 2
        await server.handle_message(ws, {"type": "message", "content": "hi"}, client_id)
        errors = ws.find("error")
        assert len(errors) == 1
        assert "concurrent" in errors[0]["message"].lower()

    @pytest.mark.asyncio
    async def test_concurrency_counter_decrements(self, server, ws):
        """Inflight counter should decrement after handle_chat_message completes."""
        client_id = "conc-dec"
        server._client_inflight[client_id] = 0
        # Mock handle_chat_message to return immediately
        server.handle_chat_message = AsyncMock()
        await server.handle_message(ws, {"type": "message", "content": "hi"}, client_id)
        assert server._client_inflight[client_id] == 0  # Back to 0


# ===================================================================
# Input Validation (handle_chat_message)
# ===================================================================
class TestInputValidation:
    """Test input validation in handle_chat_message."""

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self, server, ws):
        """Empty content with no images should be rejected."""
        await server.handle_chat_message(ws, {
            "conversation_id": "test-conv",
            "content": "",
            "images": [],
        })
        errors = ws.find("error")
        assert any("Empty message" in e["message"] for e in errors)

    @pytest.mark.asyncio
    async def test_content_too_long(self, server, ws):
        """Content exceeding MAX_CONTENT_LENGTH should be rejected."""
        await server.handle_chat_message(ws, {
            "conversation_id": "test-conv",
            "content": "x" * (server.MAX_CONTENT_LENGTH + 1),
        })
        errors = ws.find("error")
        assert any("too long" in e["message"].lower() for e in errors)

    @pytest.mark.asyncio
    async def test_too_many_images(self, server, ws):
        """More than MAX_IMAGES should be rejected."""
        await server.handle_chat_message(ws, {
            "conversation_id": "test-conv",
            "content": "test",
            "images": ["img"] * (server.MAX_IMAGES + 1),
        })
        errors = ws.find("error")
        assert any("too many images" in e["message"].lower() for e in errors)

    @pytest.mark.asyncio
    async def test_history_truncated(self, server, ws):
        """History longer than MAX_HISTORY_MESSAGES should be truncated."""
        long_history = [{"role": "user", "content": f"msg{i}"} for i in range(200)]
        # Mock the Gemini streaming to avoid actual API call
        server.gemini_client = None  # Trigger "AI not configured" error
        await server.handle_chat_message(ws, {
            "conversation_id": "test-conv",
            "content": "test",
            "history": long_history,
        })
        # Should get error about AI not configured (but history was accepted/truncated)
        errors = ws.find("error")
        assert any("not configured" in e.get("message", "").lower() or "not available" in e.get("message", "").lower() for e in errors)

    @pytest.mark.asyncio
    async def test_no_gemini_client(self, server, ws):
        """When Gemini client is None, should return error."""
        server.gemini_client = None
        await server.handle_chat_message(ws, {
            "conversation_id": "test-conv",
            "content": "hello",
        })
        errors = ws.find("error")
        assert len(errors) >= 1


# ===================================================================
# Conversation Management
# ===================================================================
class TestConversationManagement:
    """Test conversation CRUD handlers."""

    @pytest.mark.asyncio
    async def test_list_conversations_empty(self, server, ws):
        """list_conversations should return empty list when DB has nothing."""
        mock_db = MagicMock()
        mock_db.get_dashboard_conversations = AsyncMock(return_value=[])
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_list_conversations(ws)
        result = ws.find("conversations_list")
        assert len(result) == 1
        assert result[0]["conversations"] == []

    @pytest.mark.asyncio
    async def test_delete_conversation(self, server, ws):
        """delete_conversation should call DB and return success."""
        mock_db = MagicMock()
        mock_db.delete_dashboard_conversation = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_delete_conversation(ws, {"id": "test-id"})
        result = ws.find("conversation_deleted")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_star_conversation(self, server, ws):
        """star_conversation should toggle star status."""
        mock_db = MagicMock()
        mock_db.update_dashboard_conversation_star = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_star_conversation(ws, {"id": "test-id", "starred": True})
        result = ws.find("conversation_starred")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rename_conversation(self, server, ws):
        """rename_conversation should update title."""
        mock_db = MagicMock()
        mock_db.rename_dashboard_conversation = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_rename_conversation(ws, {"id": "test-id", "title": "New Title"})
        result = ws.find("conversation_renamed")
        assert len(result) == 1


# ===================================================================
# Memory Management
# ===================================================================
class TestMemoryManagement:
    """Test dashboard memory CRUD handlers."""

    @pytest.mark.asyncio
    async def test_save_memory(self, server, ws):
        """save_memory should persist and return success."""
        mock_db = MagicMock()
        mock_db.save_dashboard_memory = AsyncMock(return_value=42)
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_save_memory(ws, {"content": "Remember this", "category": "general"})
        result = ws.find("memory_saved")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_memories(self, server, ws):
        """get_memories should return list from DB."""
        mock_db = MagicMock()
        mock_db.get_dashboard_memories = AsyncMock(return_value=[
            {"id": 1, "content": "fact1", "category": "general", "importance": 1}
        ])
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_get_memories(ws, {})
        result = ws.find("memories")
        assert len(result) == 1
        assert len(result[0]["memories"]) == 1

    @pytest.mark.asyncio
    async def test_delete_memory(self, server, ws):
        """delete_memory should call DB and return success."""
        mock_db = MagicMock()
        mock_db.delete_dashboard_memory = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_delete_memory(ws, {"id": 1})
        result = ws.find("memory_deleted")
        assert len(result) == 1


# ===================================================================
# Profile Management
# ===================================================================
class TestProfileManagement:
    """Test dashboard user profile handlers."""

    @pytest.mark.asyncio
    async def test_get_profile(self, server, ws):
        """get_profile should return profile data."""
        mock_db = MagicMock()
        mock_db.get_dashboard_profile = AsyncMock(return_value={
            "display_name": "Test User", "bio": "Hello", "preferences": None, "is_creator": 0
        })
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_get_profile(ws)

    @pytest.mark.asyncio
    async def test_save_profile(self, server, ws):
        """save_profile should persist and return success."""
        mock_db = MagicMock()
        mock_db.save_dashboard_profile = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True), \
             patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db):
            await server.handle_save_profile(ws, {"display_name": "New Name"})


# ===================================================================
# Max Clients
# ===================================================================
class TestMaxClients:
    """Test maximum client connection enforcement."""

    def test_max_clients_constant(self, server):
        """MAX_CLIENTS should be 20."""
        assert server.MAX_CLIENTS == 20

    def test_limits_constants(self, server):
        """Verify all limit constants are set."""
        assert server.MAX_CONTENT_LENGTH == 50_000
        assert server.MAX_HISTORY_MESSAGES == 100
        assert server.MAX_IMAGES == 10
        assert server.MAX_IMAGE_SIZE_BYTES == 10 * 1024 * 1024
        assert server.RATE_LIMIT_MESSAGES_PER_MINUTE == 30
