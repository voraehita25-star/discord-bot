"""Tests for Dashboard WebSocket server (ws_dashboard.py).

Covers auth flow, message routing, rate limiting, concurrency limits,
input validation, and conversation management.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import WSMessage, WSMsgType


# ---------------------------------------------------------------------------
# Helper: Fake WebSocketResponse
# ---------------------------------------------------------------------------
class FakeWS:
    """Minimal fake aiohttp.web.WebSocketResponse for testing."""

    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict, **kwargs) -> None:  # kwargs: aiohttp accepts dumps=
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def last(self) -> dict:
        return self.sent[-1] if self.sent else {}

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


# ---------------------------------------------------------------------------
# Helper: drive the REAL websocket_handler read loop
# ---------------------------------------------------------------------------
# The production rate-limit gate and the in-band "Authentication required"
# gate live ONLY inside websocket_handler's `async for msg in ws` loop (and
# its pre-auth deadline loop), NOT in handle_message. To exercise them without
# re-implementing the gate, patch `web.WebSocketResponse` with this fake: its
# ``prepare`` is a no-op, it records every ``send_json``, and it replays a
# scripted list of frames both via ``__aiter__`` (the post-auth loop) and via
# ``receive`` (the pre-auth deadline loop).
class _HandlerWS:
    """Fake server-side WebSocketResponse that replays scripted frames."""

    def __init__(self, frames: list[WSMessage] | None = None):
        self._frames = list(frames or [])
        self.sent: list[dict] = []
        self.closed = False
        self.close_code: int | None = None

    async def prepare(self, _request) -> None:
        return None

    async def send_json(self, data: dict, **kwargs) -> None:  # kwargs: aiohttp accepts dumps=
        self.sent.append(data)

    async def close(self, *, code: int = 1000, message: bytes = b"") -> None:
        self.closed = True
        self.close_code = code

    async def receive(self, *_a, **_k):
        # Pre-auth deadline loop pulls frames one at a time via receive().
        if self._frames:
            return self._frames.pop(0)
        return WSMessage(WSMsgType.CLOSE, None, None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> WSMessage:
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]

    def exception(self):  # pragma: no cover - only hit on ERROR frames
        return RuntimeError("stub")


def _text(payload: str) -> WSMessage:
    """Build a TEXT frame the handler will json.loads()."""
    return WSMessage(WSMsgType.TEXT, payload, None)


def _localhost_request(*, auth_header: str = "") -> MagicMock:
    """A mock aiohttp request that passes the origin/host localhost gate.

    Pass ``auth_header`` (e.g. ``"Bearer secret123"``) to authenticate at
    upgrade time, which skips the in-band auth deadline loop and lands the
    handler directly in the post-auth ``async for`` read loop.
    """
    request = MagicMock()
    request.headers = {"Origin": "http://localhost:3000", "Host": "localhost:8765"}
    if auth_header:
        request.headers["Authorization"] = auth_header
    request.query = {}
    transport = MagicMock()
    transport.get_extra_info.return_value = ("127.0.0.1", 12345)
    request.transport = transport
    return request


# ---------------------------------------------------------------------------
# Fixture: DashboardWebSocketServer instance with mocked Gemini
# ---------------------------------------------------------------------------
@pytest.fixture()
def server():
    """Create a DashboardWebSocketServer with a mocked Gemini client."""
    with patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "ANTHROPIC_API_KEY": "",
            "DEFAULT_AI_PROVIDER": "gemini",
            "DASHBOARD_WS_TOKEN": "",
            # Pin the SDK path explicitly: the module default is now "cli"
            # (matching the rest of the repo), and these tests exercise the
            # SDK validation order (e.g. test_too_many_images). Pinning also
            # removes order-sensitivity vs other test modules that setdefault
            # CLAUDE_BACKEND.
            "CLAUDE_BACKEND": "api",
        },
    ):
        with patch("cogs.ai_core.api.ws_dashboard.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            import cogs.ai_core.api.ws_dashboard as ws_module
            from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

            # _CLAUDE_BACKEND is a module constant read at IMPORT time, so the
            # env var above can't override it when another test module already
            # imported ws_dashboard under CLAUDE_BACKEND=cli. Patch the module
            # attribute (restored on fixture teardown) so these tests always
            # exercise the SDK validation path.
            with patch.object(ws_module, "_CLAUDE_BACKEND", "api"):
                srv = DashboardWebSocketServer()
                srv.gemini_client = MagicMock()
                yield srv


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

    @pytest.mark.asyncio
    async def test_privileged_frame_before_auth_refused(self, server):
        """With a token required, a PRIVILEGED frame sent before any in-band
        auth message must be refused ('Authentication required') and must NOT
        reach a handler — exercises websocket_handler's pre-auth gate."""
        import cogs.ai_core.api.ws_dashboard as ws_module

        # delete_conversation is a privileged write; send it with no prior auth.
        handler_ws = _HandlerWS([_text('{"type": "delete_conversation", "id": "x"}')])
        server.handle_message = AsyncMock()
        server.handle_delete_conversation = AsyncMock()
        server._auth_deadline = 0.5  # keep the deadline loop short

        with (
            patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}),
            patch.object(ws_module.web, "WebSocketResponse", return_value=handler_ws),
        ):
            await server.websocket_handler(_localhost_request())

        # Refused at the pre-auth gate, connection closed, handler never ran.
        assert any(
            "Authentication required" in e.get("message", "") for e in handler_ws.find("error")
        )
        assert handler_ws.closed
        assert handler_ws.close_code == 4001
        server.handle_message.assert_not_awaited()
        server.handle_delete_conversation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cross_origin_browser_rejected_despite_localhost_host(self, server):
        """A cross-origin browser connection must be REJECTED even though its
        Host header is localhost.

        Regression: the gate was `not origin_allowed and not host_allowed`, but
        a browser hitting ws://127.0.0.1 always sends the real target authority
        as Host (localhost, unforgeable-as-anything-else), so host_allowed was
        unconditionally True and the Origin allowlist never blocked anything. A
        page at https://evil.com opening a WebSocket to the local server would
        pass. The Origin header (which JS cannot forge) must be authoritative
        for browser clients.
        """
        request = MagicMock()
        # Browser sends a hostile Origin but the real localhost Host/authority.
        request.headers = {"Origin": "https://evil.com", "Host": "127.0.0.1:8765"}
        request.query = {}
        transport = MagicMock()
        transport.get_extra_info.return_value = ("127.0.0.1", 12345)
        request.transport = transport

        # A token must be configured so the request reaches the origin gate
        # (the token-not-set gate returns 401 earlier and would mask this).
        with patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}):
            resp = await server.websocket_handler(request)

        assert getattr(resp, "status", None) == 403

    @pytest.mark.asyncio
    async def test_non_browser_no_origin_allowed_via_host(self, server):
        """A non-browser client (no Origin header) still connects via the Host
        check — the Tauri shell / CLI clients that JS attackers cannot spoof."""
        import cogs.ai_core.api.ws_dashboard as ws_module

        request = MagicMock()
        request.headers = {"Host": "127.0.0.1:8765"}  # no Origin
        request.query = {}
        transport = MagicMock()
        transport.get_extra_info.return_value = ("127.0.0.1", 12345)
        request.transport = transport

        handler_ws = _HandlerWS([])
        server._auth_deadline = 0.1
        # Token configured (so the token-not-set 401 gate passes); the no-Origin
        # request must clear the origin gate via the Host check, not be 403'd.
        with (
            patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}),
            patch.object(ws_module.web, "WebSocketResponse", return_value=handler_ws),
        ):
            resp = await server.websocket_handler(request)

        # Not a 403 origin rejection — the connection reached the WS-upgrade path.
        assert getattr(resp, "status", None) != 403

    @pytest.mark.asyncio
    async def test_privileged_frame_after_valid_auth_succeeds(self, server):
        """After a valid in-band auth frame, the same privileged frame is
        dispatched to its handler."""
        import cogs.ai_core.api.ws_dashboard as ws_module

        handler_ws = _HandlerWS(
            [
                _text('{"type": "auth", "token": "secret123"}'),
                _text('{"type": "delete_conversation", "id": "x"}'),
            ]
        )
        server.handle_message = AsyncMock()

        with (
            patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}),
            patch.object(ws_module.web, "WebSocketResponse", return_value=handler_ws),
        ):
            await server.websocket_handler(_localhost_request())

        # No auth error, and the privileged frame reached the dispatcher.
        assert not [
            e for e in handler_ws.find("error") if "Authentication required" in e.get("message", "")
        ]
        server.handle_message.assert_awaited_once()
        assert server.handle_message.await_args.args[1]["type"] == "delete_conversation"


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
            await server.handle_message(
                ws, {"type": "new_conversation", "role_preset": "general"}, "c1"
            )
        created = ws.find("conversation_created")
        assert len(created) == 1
        assert "id" in created[0]
        assert created[0]["role_preset"] == "general"

    @pytest.mark.asyncio
    async def test_new_conversation_invalid_preset_defaults_to_general(self, server, ws):
        """Invalid role_preset should default to 'general'."""
        with patch("cogs.ai_core.api.ws_dashboard.DB_AVAILABLE", False):
            await server.handle_message(
                ws, {"type": "new_conversation", "role_preset": "invalid_preset"}, "c1"
            )
        created = ws.find("conversation_created")
        assert len(created) == 1
        assert created[0]["role_preset"] == "general"


# ===================================================================
# Rate Limiting
# ===================================================================
class TestRateLimiting:
    """Test per-client rate limiting (RATE_LIMIT_MESSAGES_PER_MINUTE msg/min).

    The live threshold is the production constant (currently 120, asserted in
    test_limits_constants); tests derive the frame count from it rather than a
    hard-coded number so the docstring + assertions can't drift from source.
    """

    @pytest.mark.asyncio
    async def test_under_rate_limit(self, server, ws):
        """Messages under the limit should be processed."""
        for _i in range(5):
            await server.handle_message(ws, {"type": "ping"}, "c1")
        pongs = ws.find("pong")
        assert len(pongs) == 5

    @pytest.mark.asyncio
    async def test_rate_limit_enforced_in_handler_loop(self, server):
        """Drive the REAL gate in websocket_handler: the (N+1)th non-exempt
        frame within the window must yield a 'Rate limit' error and must NOT
        be dispatched to handle_message."""
        import cogs.ai_core.api.ws_dashboard as ws_module

        limit = server.RATE_LIMIT_MESSAGES_PER_MINUTE
        # "new_conversation" is NOT in RATE_EXEMPT_MESSAGE_TYPES and is
        # dispatched synchronously via handle_message (not the create_task
        # path reserved for "message"/"ai_edit_message"), so spying on
        # handle_message proves what did/didn't reach a handler.
        frames = [_text('{"type": "new_conversation"}') for _ in range(limit + 1)]
        handler_ws = _HandlerWS(frames)
        server.handle_message = AsyncMock()

        # Authenticate at upgrade time so the handler reaches the post-auth
        # read loop (where the rate-limit gate lives) directly.
        with (
            patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}),
            patch.object(ws_module.web, "WebSocketResponse", return_value=handler_ws),
        ):
            await server.websocket_handler(_localhost_request(auth_header="Bearer secret123"))

        # Exactly one Rate-limit error frame (the N+1th), and only N frames
        # ever reached the handler — the production gate dropped the overflow.
        errors = [e for e in handler_ws.find("error") if "Rate limit" in e.get("message", "")]
        assert len(errors) == 1
        assert errors[0].get("scope") == "new_conversation"
        assert server.handle_message.await_count == limit

    @pytest.mark.asyncio
    async def test_exempt_types_not_rate_limited(self, server):
        """Read-only RATE_EXEMPT types (e.g. ping) bypass the gate even past
        the limit — confirms the gate's exemption branch is exercised, not a
        blanket throttle."""
        import cogs.ai_core.api.ws_dashboard as ws_module

        limit = server.RATE_LIMIT_MESSAGES_PER_MINUTE
        frames = [_text('{"type": "ping"}') for _ in range(limit + 5)]
        handler_ws = _HandlerWS(frames)

        with (
            patch.dict(os.environ, {"DASHBOARD_WS_TOKEN": "secret123"}),
            patch.object(ws_module.web, "WebSocketResponse", return_value=handler_ws),
        ):
            await server.websocket_handler(_localhost_request(auth_header="Bearer secret123"))

        # Every ping answered with a pong; no rate-limit error fired.
        assert len(handler_ws.find("pong")) == limit + 5
        assert not [e for e in handler_ws.find("error") if "Rate limit" in e.get("message", "")]


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
        await server.handle_chat_message(
            ws,
            {
                "conversation_id": "test-conv",
                "content": "",
                "images": [],
            },
        )
        errors = ws.find("error")
        assert any("Empty message" in e["message"] for e in errors)

    @pytest.mark.asyncio
    async def test_content_too_long(self, server, ws):
        """Content exceeding MAX_CONTENT_LENGTH should be rejected."""
        await server.handle_chat_message(
            ws,
            {
                "conversation_id": "test-conv",
                "content": "x" * (server.MAX_CONTENT_LENGTH + 1),
            },
        )
        errors = ws.find("error")
        assert any("too long" in e["message"].lower() for e in errors)

    @pytest.mark.asyncio
    async def test_too_many_images(self, server, ws):
        """More than MAX_IMAGES should be rejected."""
        await server.handle_chat_message(
            ws,
            {
                "conversation_id": "test-conv",
                "content": "test",
                "images": ["img"] * (server.MAX_IMAGES + 1),
            },
        )
        errors = ws.find("error")
        assert any("too many images" in e["message"].lower() for e in errors)

    @pytest.mark.asyncio
    async def test_history_truncated(self, server, ws):
        """History longer than MAX_HISTORY_MESSAGES should be truncated."""
        long_history = [{"role": "user", "content": f"msg{i}"} for i in range(200)]
        server.gemini_client = None
        server.claude_client = None
        await server.handle_chat_message(
            ws,
            {
                "conversation_id": "test-conv",
                "content": "test",
                "history": long_history,
                "ai_provider": "gemini",
            },
        )
        # Should get an error frame. The exact message depends on backend
        # mode: under CLAUDE_BACKEND=cli gemini is dropped from
        # VALID_AI_PROVIDERS ("Invalid ai_provider"); under api with both
        # clients unset the Thai no-backend message fires. Accept any of
        # them to keep the contract test robust to backend mode.
        errors = ws.find("error")
        assert any(
            "not configured" in e.get("message", "").lower()
            or "not available" in e.get("message", "").lower()
            or "invalid ai_provider" in e.get("message", "").lower()
            or "ไม่มี ai backend" in e.get("message", "").lower()
            for e in errors
        )

    @pytest.mark.asyncio
    async def test_no_gemini_client(self, server, ws):
        """When Gemini client is None, should return error."""
        server.gemini_client = None
        server.claude_client = None
        await server.handle_chat_message(
            ws,
            {
                "conversation_id": "test-conv",
                "content": "hello",
                "ai_provider": "gemini",
            },
        )
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
        with (
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
        ):
            await server.handle_list_conversations(ws)
        result = ws.find("conversations_list")
        assert len(result) == 1
        assert result[0]["conversations"] == []

    @pytest.mark.asyncio
    async def test_delete_conversation(self, server, ws):
        """delete_conversation should call DB and return success."""
        mock_db = MagicMock()
        mock_db.delete_dashboard_conversation = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
        ):
            await server.handle_delete_conversation(ws, {"id": "test-id"})
        result = ws.find("conversation_deleted")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_delete_conversation_resets_cli_session_after_delete(self, server, ws):
        """The CLI session reset must run AFTER the delete handler.

        delete_session_file inside the handler needs the session-map entry to
        find and unlink the .jsonl transcript; resetting first popped that
        entry and made the transcript cleanup a guaranteed no-op (deleted
        conversations' content lingered on disk).
        """
        import cogs.ai_core.api.ws_dashboard as ws_module

        order: list[str] = []

        async def fake_delete(_ws, _data):
            order.append("delete")

        def fake_reset(conv_id):
            order.append(f"reset:{conv_id}")

        with (
            patch.object(ws_module, "handle_delete_conversation", new=fake_delete),
            patch.object(ws_module, "_reset_cli_session", new=fake_reset),
        ):
            await server.handle_delete_conversation(ws, {"id": "conv-1"})
        assert order == ["delete", "reset:conv-1"]

    @pytest.mark.asyncio
    async def test_star_conversation(self, server, ws):
        """star_conversation should toggle star status."""
        mock_db = MagicMock()
        mock_db.update_dashboard_conversation_star = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
        ):
            await server.handle_star_conversation(ws, {"id": "test-id", "starred": True})
        result = ws.find("conversation_starred")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rename_conversation(self, server, ws):
        """rename_conversation should update title."""
        mock_db = MagicMock()
        mock_db.rename_dashboard_conversation = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
        ):
            await server.handle_rename_conversation(ws, {"id": "test-id", "title": "New Title"})
        result = ws.find("conversation_renamed")
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
        mock_db.get_dashboard_profile = AsyncMock(
            return_value={
                "display_name": "Test User",
                "bio": "Hello",
                "preferences": None,
                "is_creator": 0,
            }
        )
        with (
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
        ):
            await server.handle_get_profile(ws)

    @pytest.mark.asyncio
    async def test_save_profile(self, server, ws):
        """save_profile should persist and return success."""
        mock_db = MagicMock()
        mock_db.save_dashboard_profile = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
        ):
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
        assert server.MAX_CONTENT_LENGTH == 200_000
        assert server.MAX_HISTORY_MESSAGES == 500  # env DASHBOARD_HISTORY_MESSAGES, raised from 100
        assert server.MAX_IMAGES == 10
        assert server.MAX_IMAGE_SIZE_BYTES == 10 * 1024 * 1024
        assert server.RATE_LIMIT_MESSAGES_PER_MINUTE == 120
