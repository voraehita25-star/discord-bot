"""
WebSocket Server for Dashboard AI Chat.

Provides real-time AI chat functionality for the native dashboard.
Uses aiohttp for WebSocket server with streaming support.

Features:
- Google Search grounding
- Image/File upload support
- User identity awareness
- Long-term memory across conversations

Architecture:
- dashboard_config.py   — Constants, presets, environment configuration
- dashboard_chat.py     — AI chat streaming handler
- dashboard_handlers.py — CRUD handlers (conversations, memories, profiles)
- ws_dashboard.py       — This file: server class, connection, auth, routing
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
logger = logging.getLogger(__name__)
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web
from google import genai

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# Import from extracted modules
from .dashboard_chat import (
    handle_ai_edit_message as _handle_ai_edit_message,
    handle_chat_message as _handle_chat_message,
)
from .dashboard_chat_claude import (
    handle_ai_edit_message_claude as _handle_ai_edit_message_claude,
    handle_chat_message_claude as _handle_chat_message_claude,
)
from .dashboard_chat_claude_cli import (
    handle_ai_edit_message_claude_cli as _handle_ai_edit_message_claude_cli,
    handle_chat_message_claude_cli as _handle_chat_message_claude_cli,
    reset_session as _reset_cli_session,
)
from .dashboard_config import (
    API_FAILOVER_AVAILABLE,
    AVAILABLE_PROVIDERS,
    CLAUDE_API_KEY,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    DEFAULT_AI_PROVIDER,
    GEMINI_API_KEY,
    WS_HOST,
    WS_PORT,
    WS_REQUIRE_TLS,
    Database,
)

# Backend toggle for the Claude provider:
#   CLAUDE_BACKEND=cli  → spawn `claude -p` (uses subscription via CLAUDE_CODE_OAUTH_TOKEN)
#   anything else / unset → use anthropic SDK with ANTHROPIC_API_KEY (per-token billing)
_CLAUDE_BACKEND = os.getenv("CLAUDE_BACKEND", "api").strip().lower()

if API_FAILOVER_AVAILABLE:
    from .api_failover import EndpointType, api_failover
from .dashboard_handlers import (
    handle_add_conversation_tag,
    handle_delete_conversation,
    handle_delete_memory,
    handle_delete_message,
    handle_edit_message,
    handle_export_conversation,
    handle_get_memories,
    handle_get_profile,
    handle_like_message,
    handle_list_all_tags,
    handle_list_conversations,
    handle_load_conversation,
    handle_pin_message,
    handle_remove_conversation_tag,
    handle_rename_conversation,
    handle_save_memory,
    handle_save_profile,
    handle_star_conversation,
)

# ============================================================================
# WebSocket Dashboard Server
# ============================================================================

class DashboardWebSocketServer:
    """WebSocket server for dashboard AI chat."""

    # Limits
    MAX_CLIENTS = 20
    MAX_CONTENT_LENGTH = 50_000  # characters
    MAX_HISTORY_MESSAGES = 100
    MAX_IMAGES = 10
    MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB per image
    STREAM_TIMEOUT = 300  # seconds for full stream consumption
    RATE_LIMIT_MESSAGES_PER_MINUTE = 30  # max messages per client per minute

    def __init__(self):
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.clients: set[WebSocketResponse] = set()
        self.gemini_client: genai.Client | None = None
        self.claude_client: Any | None = None
        self._running = False
        self._client_message_times: dict[str, list[float]] = {}  # rate limit tracking
        self._client_inflight: dict[str, int] = {}  # concurrent request tracking
        self._authenticated_clients: set[str] = set()  # track authenticated client IDs
        self._auth_deadline: float = 5.0  # seconds to authenticate after connecting

        # Initialize Gemini client
        if GEMINI_API_KEY:
            self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("🤖 Dashboard WS: Gemini client initialized")
        else:
            logger.warning("⚠️ Dashboard WS: No GEMINI_API_KEY found")

        # Initialize Claude (Anthropic) client — prefer failover manager
        if API_FAILOVER_AVAILABLE and api_failover.active_config:
            try:
                self.claude_client = api_failover.get_client()
                logger.info(
                    "🟣 Dashboard WS: Claude client initialized via failover (endpoint: %s)",
                    api_failover.active_endpoint.value,
                )
                # Register listener for auto-failover notifications
                api_failover.add_listener(self._on_endpoint_changed)
            except Exception as e:
                logger.warning("⚠️ Dashboard WS: failover init failed: %s, falling back", e)
                if CLAUDE_API_KEY:
                    import anthropic
                    self.claude_client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
        elif CLAUDE_API_KEY:
            try:
                import anthropic
                self.claude_client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
                logger.info("🟣 Dashboard WS: Claude client initialized")
            except ImportError:
                logger.warning("⚠️ Dashboard WS: anthropic package not installed")
        else:
            logger.info("ℹ️ Dashboard WS: No ANTHROPIC_API_KEY found (Claude disabled)")

    async def start(self) -> bool:
        """Start the WebSocket server."""
        if self._running:
            logger.warning("⚠️ Dashboard WebSocket server already running")
            return True

        try:
            # Try to free the port if it's in use
            await self._ensure_port_available()

            self.app = web.Application(middlewares=[self._cors_middleware])
            self.app.router.add_get("/ws", self.websocket_handler)
            self.app.router.add_get("/health", self.health_handler)

            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            # Create TCPSite with reuse_address for faster restart
            # Note: reuse_port is only supported on Linux, not Windows
            import sys
            site_kwargs: dict[str, Any] = {
                'reuse_address': True,  # Allow port reuse after close
            }
            if sys.platform != 'win32':
                site_kwargs['reuse_port'] = True  # Linux only

            scheme = 'ws'
            if WS_REQUIRE_TLS:
                tls_cert_path = os.getenv('WS_TLS_CERT_PATH', '').strip()
                tls_key_path = os.getenv('WS_TLS_KEY_PATH', '').strip()
                if not tls_cert_path or not tls_key_path:
                    logger.error(
                        "❌ WS_REQUIRE_TLS is enabled but WS_TLS_CERT_PATH / WS_TLS_KEY_PATH are not set"
                    )
                    return False

                import ssl

                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(tls_cert_path, tls_key_path)
                site_kwargs['ssl_context'] = ssl_context
                scheme = 'wss'

            self.site = web.TCPSite(
                self.runner,
                WS_HOST,
                WS_PORT,
                **site_kwargs
            )
            await self.site.start()

            self._running = True
            logger.info("🚀 Dashboard WebSocket server started on %s://%s:%s", scheme, WS_HOST, WS_PORT)
            return True

        except Exception:
            logger.exception("❌ Failed to start Dashboard WebSocket server")
            return False

    async def _ensure_port_available(self) -> None:
        """Ensure port is available, killing old process if needed.

        SAFETY: Only kills processes that are confirmed to be our own bot instances
        by checking for specific identifiers in the command line.
        """
        import socket

        # Quick check if port is in use
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex((WS_HOST, WS_PORT))

        if result == 0:  # Port is in use
            logger.warning("⚠️ Port %s is in use, attempting to free it...", WS_PORT)

            # SAFETY: We will NOT auto-kill processes anymore.
            # Instead, we wait for the port to become available or fail gracefully.
            # This prevents accidentally killing unrelated processes.

            max_wait = 5  # Maximum seconds to wait for port
            waited: float = 0

            while waited < max_wait:
                await asyncio.sleep(0.5)
                waited += 0.5

                # Re-check if port is free
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex((WS_HOST, WS_PORT))

                if result != 0:  # Port is now free
                    logger.info("✅ Port %s is now available", WS_PORT)
                    return

            # If still not free, log warning but continue (will fail gracefully on bind)
            logger.warning(
                "⚠️ Port %s still in use after %ss wait. "
                "If this is an old bot instance, please stop it manually.",
                WS_PORT, max_wait
            )

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return

        logger.info("🛑 Stopping Dashboard WebSocket server...")

        # Close all client connections (tolerate individual failures)
        for ws in list(self.clients):
            try:
                await ws.close(code=1001, message=b"Server shutting down")
            except Exception:
                pass
        self.clients.clear()

        # Cleanup
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

        self._running = False
        logger.info("🛑 Dashboard WebSocket server stopped")

    # Allowed origins for CORS — matches the origin check in websocket_handler
    _ALLOWED_ORIGIN_PREFIXES = (
        "http://127.0.0.1",
        "http://localhost",
        "https://127.0.0.1",
        "https://localhost",
        "tauri://localhost",
        "http://tauri.localhost",
    )

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler):
        """Add CORS headers restricting access to localhost origins."""
        origin = request.headers.get("Origin", "")

        # Validate origin against whitelist
        allowed_origin = ""
        for prefix in self._ALLOWED_ORIGIN_PREFIXES:
            if origin == prefix or origin.startswith((prefix + ":", prefix + "/")):
                allowed_origin = origin
                break

        resp = await handler(request)
        if allowed_origin:
            resp.headers["Access-Control-Allow-Origin"] = allowed_origin
            resp.headers["Access-Control-Allow-Methods"] = "GET"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization"
        return resp

    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "clients": len(self.clients),
            "gemini_available": self.gemini_client is not None,
            "claude_available": self.claude_client is not None,
            "available_providers": AVAILABLE_PROVIDERS,
        })

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse | web.Response:
        """Handle WebSocket connections."""
        # Security: Validate origin for localhost-only connections
        origin = request.headers.get("Origin", "")
        host = request.headers.get("Host", "")

        # Authentication: Require API key from environment or query param
        expected_token = os.getenv("DASHBOARD_WS_TOKEN", "")
        peername = request.transport.get_extra_info("peername") if request.transport else None

        if not expected_token:
            logger.error(
                "❌ DASHBOARD_WS_TOKEN not set — rejecting connection. "
                "Set DASHBOARD_WS_TOKEN in .env to allow dashboard access."
            )
            return web.Response(status=401, text="Unauthorized: DASHBOARD_WS_TOKEN is required")
        # Track whether client authenticated at upgrade time
        _upgrade_authenticated = False
        if expected_token:
            # Check Authorization header or query param (timing-safe comparison).
            # If neither is provided, allow connection but require message-based auth
            # within the deadline — the Tauri dashboard sends the token via WebSocket
            # message (type: 'auth') to avoid URL/header leakage.
            auth_header = request.headers.get("Authorization", "")
            query_token = request.query.get("token", "")
            has_credentials = bool(auth_header) or bool(query_token)
            if has_credentials:
                auth_match = hmac.compare_digest(auth_header, f"Bearer {expected_token}") if auth_header else False
                token_match = hmac.compare_digest(query_token, expected_token) if query_token else False
                if not auth_match and not token_match:
                    logger.warning("⚠️ Rejected WebSocket connection: invalid auth token (from %s)", peername)
                    return web.Response(status=401, text="Unauthorized: Invalid token")
                else:
                    _upgrade_authenticated = True

        # Allow connections from localhost only (127.0.0.1 or localhost)
        # Use exact prefix matching to prevent subdomain bypass (e.g., evil-localhost.com)
        allowed_origins = [
            "http://127.0.0.1",
            "http://localhost",
            "https://127.0.0.1",
            "https://localhost",
            "tauri://localhost",
            "http://tauri.localhost",
        ]

        # Check if origin is allowed
        # Require origin header from browser clients—empty origin is only allowed
        # if host header explicitly matches localhost
        def _is_safe_origin(o: str) -> bool:
            """Check if origin matches an allowed prefix followed by port or end-of-string."""
            for allowed in allowed_origins:
                if o == allowed:
                    return True
                if o.startswith((allowed + ":", allowed + "/")):
                    return True
            return False

        origin_allowed = _is_safe_origin(origin) if origin else False

        # Also check host header (require delimiter to prevent subdomain bypass)
        def _is_safe_host(h: str) -> bool:
            for prefix in ("127.0.0.1", "localhost"):
                if h == prefix or h.startswith(prefix + ":"):
                    return True
            return False

        host_allowed = _is_safe_host(host)

        if not origin_allowed and not host_allowed:
            logger.warning("⚠️ Rejected WebSocket connection from origin: %s, host: %s", origin, host)
            return web.Response(status=403, text="Forbidden: Connection only allowed from localhost")

        # Enforce max concurrent connections
        if len(self.clients) >= self.MAX_CLIENTS:
            logger.warning("⚠️ Rejected WebSocket connection: max clients (%s) reached", self.MAX_CLIENTS)
            return web.Response(status=503, text="Service Unavailable: Too many connections")

        ws = web.WebSocketResponse(max_msg_size=10 * 1024 * 1024)  # 10MB max message size
        await ws.prepare(request)

        self.clients.add(ws)
        client_id = str(uuid.uuid4())[:8]
        logger.info("👋 Dashboard client connected: %s", client_id)

        # Mark as authenticated if validated at upgrade time or no token required
        if _upgrade_authenticated or not expected_token:
            self._authenticated_clients.add(client_id)

        try:
            # Send welcome message
            needs_auth = expected_token and not _upgrade_authenticated
            welcome_msg: dict[str, Any] = {
                "type": "connected",
                "client_id": client_id,
                "requires_auth": needs_auth,
                "presets": {
                    key: {
                        "name": preset["name"],
                        "emoji": preset["emoji"],
                        "color": preset["color"],
                    }
                    for key, preset in DASHBOARD_ROLE_PRESETS.items()
                },
                "available_providers": AVAILABLE_PROVIDERS,
                "default_provider": DEFAULT_AI_PROVIDER,
            }
            if API_FAILOVER_AVAILABLE:
                welcome_msg["api_failover"] = api_failover.get_status()
            await ws.send_json(welcome_msg)

            # Enforce auth deadline: if token is required and not yet authenticated,
            # the client must send an 'auth' message within the deadline.
            if needs_auth:
                auth_received = False
                try:
                    deadline_msg = await asyncio.wait_for(
                        ws.receive(), timeout=self._auth_deadline
                    )
                    if deadline_msg.type == WSMsgType.TEXT:
                        try:
                            auth_data = json.loads(deadline_msg.data)
                            if auth_data.get("type") == "auth":
                                token = auth_data.get("token", "")
                                if hmac.compare_digest(str(token), expected_token):
                                    self._authenticated_clients.add(client_id)
                                    auth_received = True
                                    logger.debug("✅ Client %s authenticated via message", client_id)
                                else:
                                    logger.warning("⚠️ Invalid auth token from client %s", client_id)
                        except json.JSONDecodeError:
                            pass
                except TimeoutError:
                    pass

                if not auth_received:
                    logger.warning("⚠️ Client %s failed to authenticate within %.0fs deadline", client_id, self._auth_deadline)
                    await ws.send_json({"type": "error", "message": "Authentication required. Connection closing."})
                    await ws.close(code=4001, message=b"Authentication deadline exceeded")
                    return ws

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        msg_id = str(uuid.uuid4())[:8]
                        msg_type = data.get("type")

                        # Rate limiting per client (skip lightweight read-only ops)
                        _RATE_EXEMPT = {"ping", "auth", "list_conversations", "load_conversation", "get_memories", "get_profile"}
                        if msg_type not in _RATE_EXEMPT:
                            now = asyncio.get_running_loop().time()
                            times = self._client_message_times.get(client_id, [])
                            # Remove entries older than 60s
                            times = [t for t in times if now - t < 60]
                            self._client_message_times[client_id] = times
                            if len(times) >= self.RATE_LIMIT_MESSAGES_PER_MINUTE:
                                await ws.send_json({"type": "error", "message": "Rate limit exceeded. Please wait."})
                                continue
                            times.append(now)
                        logger.debug(
                            "WS msg client=%s msg=%s type=%s",
                            client_id, msg_id, data.get("type", "?"),
                        )
                        # Verify authentication for every request (except auth/ping)
                        if msg_type not in ("auth", "ping") and expected_token and client_id not in self._authenticated_clients:
                            await ws.send_json({"type": "error", "message": "Authentication required"})
                            continue
                        await self.handle_message(ws, data, client_id, msg_id=msg_id)
                    except json.JSONDecodeError:
                        await ws.send_json({"type": "error", "message": "Invalid JSON"})
                elif msg.type == WSMsgType.ERROR:
                    logger.error("WebSocket error: %s", ws.exception())
                    break

        except Exception:
            logger.exception("❌ WebSocket handler error")
        finally:
            self.clients.discard(ws)
            self._authenticated_clients.discard(client_id)
            self._client_message_times.pop(client_id, None)
            self._client_inflight.pop(client_id, None)
            logger.info("👋 Dashboard client disconnected: %s", client_id)

        return ws

    async def handle_message(self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = "", msg_id: str = "") -> None:
        """Handle incoming WebSocket messages."""
        msg_type = data.get("type")

        if msg_type == "new_conversation":
            await self.handle_new_conversation(ws, data)
        elif msg_type == "message":
            # Enforce concurrency limit per client
            inflight = self._client_inflight.get(client_id, 0)
            if inflight >= 2:
                await ws.send_json({
                    "type": "error",
                    "message": "Too many concurrent requests. Please wait for the current response to finish.",
                })
                return
            self._client_inflight[client_id] = inflight + 1
            try:
                logger.debug("WS chat start client=%s msg=%s", client_id, msg_id)
                await self.handle_chat_message(ws, data)
            finally:
                self._client_inflight[client_id] = max(0, self._client_inflight.get(client_id, 1) - 1)
        elif msg_type == "list_conversations":
            await self.handle_list_conversations(ws)
        elif msg_type == "load_conversation":
            await self.handle_load_conversation(ws, data)
        elif msg_type == "delete_conversation":
            await self.handle_delete_conversation(ws, data)
        elif msg_type == "star_conversation":
            await self.handle_star_conversation(ws, data)
        elif msg_type == "rename_conversation":
            await self.handle_rename_conversation(ws, data)
        elif msg_type == "export_conversation":
            await self.handle_export_conversation(ws, data)
        elif msg_type == "edit_message":
            await handle_edit_message(ws, data)
        elif msg_type == "ai_edit_message":
            # AI self-edit: AI rewrites its own message based on user instruction
            inflight = self._client_inflight.get(client_id, 0)
            if inflight >= 2:
                await ws.send_json({
                    "type": "error",
                    "message": "Too many concurrent requests. Please wait for the current response to finish.",
                })
                return
            self._client_inflight[client_id] = inflight + 1
            try:
                await self.handle_ai_edit_message(ws, data)
            finally:
                self._client_inflight[client_id] = max(0, self._client_inflight.get(client_id, 1) - 1)
        elif msg_type == "delete_message":
            await handle_delete_message(ws, data)
        elif msg_type == "pin_message":
            await handle_pin_message(ws, data)
        elif msg_type == "like_message":
            await handle_like_message(ws, data)
        elif msg_type == "add_tag":
            await handle_add_conversation_tag(ws, data)
        elif msg_type == "remove_tag":
            await handle_remove_conversation_tag(ws, data)
        elif msg_type == "list_tags":
            await handle_list_all_tags(ws, data)
        elif msg_type == "save_memory":
            await self.handle_save_memory(ws, data)
        elif msg_type == "get_memories":
            await self.handle_get_memories(ws, data)
        elif msg_type == "delete_memory":
            await self.handle_delete_memory(ws, data)
        elif msg_type == "get_profile":
            await self.handle_get_profile(ws)
        elif msg_type == "save_profile":
            await self.handle_save_profile(ws, data)
        elif msg_type == "auth":
            # Re-auth or late auth via message — already handled at connect deadline,
            # but allow re-validation for token rotation.
            token = data.get("token", "")
            expected = os.getenv("DASHBOARD_WS_TOKEN", "")
            if expected and not hmac.compare_digest(str(token), expected):
                logger.warning("⚠️ Invalid auth token from client %s", client_id)
                await ws.send_json({"type": "error", "message": "Invalid auth token"})
            else:
                self._authenticated_clients.add(client_id)
                logger.debug("✅ Client %s re-authenticated via message", client_id)
        elif msg_type == "update_provider":
            await self.handle_update_provider(ws, data)
        elif msg_type == "get_api_endpoints":
            await self.handle_get_api_endpoints(ws)
        elif msg_type == "switch_api_endpoint":
            await self.handle_switch_api_endpoint(ws, data)
        elif msg_type == "health_check_endpoint":
            await self.handle_health_check_endpoint(ws, data)
        elif msg_type == "ping":
            await ws.send_json({"type": "pong"})
        else:
            await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

    async def handle_new_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Create a new conversation."""
        role_preset = data.get("role_preset", "general")
        thinking_enabled = data.get("thinking_enabled", False)
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)

        if role_preset not in DASHBOARD_ROLE_PRESETS:
            role_preset = "general"

        preset = DASHBOARD_ROLE_PRESETS[role_preset]
        conversation_id = str(uuid.uuid4())

        # Save to database if available
        if DB_AVAILABLE:
            try:
                db = Database()
                await db.create_dashboard_conversation(
                    conversation_id=conversation_id,
                    role_preset=role_preset,
                    thinking_enabled=thinking_enabled,
                    ai_provider=ai_provider,
                )
            except Exception:
                logger.exception("Failed to save conversation to DB")

        await ws.send_json({
            "type": "conversation_created",
            "id": conversation_id,
            "role_preset": role_preset,
            "role_name": preset["name"],
            "role_emoji": preset["emoji"],
            "role_color": preset["color"],
            "thinking_enabled": thinking_enabled,
            "ai_provider": ai_provider,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    async def handle_chat_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle incoming chat message and stream response.
        Routes to Gemini or Claude handler based on ai_provider field.
        For Claude, further routes to the CLI subprocess backend when
        CLAUDE_BACKEND=cli (uses Claude Code subscription instead of API key).
        """
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)

        if ai_provider == "claude":
            if _CLAUDE_BACKEND == "cli":
                # Subscription-based path: no SDK client needed.
                await _handle_chat_message_claude_cli(
                    ws, data, None,
                    max_content_length=self.MAX_CONTENT_LENGTH,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    max_images=self.MAX_IMAGES,
                    max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return
            if self.claude_client:
                # Use latest client from failover manager (may have switched)
                if API_FAILOVER_AVAILABLE:
                    self.claude_client = api_failover.get_client()
                await _handle_chat_message_claude(
                    ws, data, self.claude_client,
                    max_content_length=self.MAX_CONTENT_LENGTH,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    max_images=self.MAX_IMAGES,
                    max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return
            # ai_provider=claude but neither backend is configured — fall through
            # to Gemini so the user still gets a reply instead of silent failure.

        await _handle_chat_message(
            ws, data, self.gemini_client,
            max_content_length=self.MAX_CONTENT_LENGTH,
            max_history_messages=self.MAX_HISTORY_MESSAGES,
            max_images=self.MAX_IMAGES,
            max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
            stream_timeout=self.STREAM_TIMEOUT,
        )

    async def handle_ai_edit_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle AI self-edit request.
        Routes to Gemini or Claude handler based on ai_provider field.
        """
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)

        if ai_provider == "claude":
            if _CLAUDE_BACKEND == "cli":
                # CLI backend supports AI edit via the same SEARCH/REPLACE
                # patch protocol as the SDK backend.
                await _handle_ai_edit_message_claude_cli(
                    ws, data, None,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return
            if self.claude_client:
                await _handle_ai_edit_message_claude(
                    ws, data, self.claude_client,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return

        await _handle_ai_edit_message(
            ws, data, self.gemini_client,
            max_history_messages=self.MAX_HISTORY_MESSAGES,
            stream_timeout=self.STREAM_TIMEOUT,
        )

    # ========================================================================
    # CRUD handlers — delegated to dashboard_handlers module
    # ========================================================================

    async def handle_list_conversations(self, ws: WebSocketResponse) -> None:
        await handle_list_conversations(ws)

    async def handle_load_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        # When the user reloads a conversation from the DB, drop any cached
        # CLI session id for it. The DB-loaded message list is the source of
        # truth; an in-memory Claude session may have expired or carry state
        # the user can no longer see, so re-using --resume would desync the
        # next reply from what's on screen.
        conv_id = data.get("id")
        if isinstance(conv_id, str) and conv_id:
            _reset_cli_session(conv_id)
        await handle_load_conversation(ws, data)

    async def handle_delete_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        # Also forget the CLI session — the conversation is gone, the session
        # would be a leak.
        conv_id = data.get("id")
        if isinstance(conv_id, str) and conv_id:
            _reset_cli_session(conv_id)
        await handle_delete_conversation(ws, data)

    async def handle_star_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_star_conversation(ws, data)

    async def handle_rename_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_rename_conversation(ws, data)

    async def handle_export_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_export_conversation(ws, data)

    async def handle_save_memory(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_save_memory(ws, data)

    async def handle_get_memories(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_get_memories(ws, data)

    async def handle_delete_memory(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_delete_memory(ws, data)

    async def handle_get_profile(self, ws: WebSocketResponse) -> None:
        await handle_get_profile(ws)

    async def handle_save_profile(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_save_profile(ws, data)

    async def handle_update_provider(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Update the AI provider for a conversation."""
        conversation_id = data.get("conversation_id")
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)
        if ai_provider not in ("gemini", "claude"):
            await ws.send_json({
                "type": "error",
                "message": f"Invalid ai_provider: {ai_provider!r} (expected 'gemini' or 'claude')",
            })
            return
        if not conversation_id:
            await ws.send_json({
                "type": "error",
                "message": "conversation_id is required to update provider",
            })
            return
        if DB_AVAILABLE:
            try:
                db = Database()
                await db.update_dashboard_conversation(conversation_id, ai_provider=ai_provider)
            except Exception:
                logger.exception("Failed to update provider")
                await ws.send_json({"type": "error", "message": "Failed to update provider"})
                return
        await ws.send_json({
            "type": "provider_updated",
            "conversation_id": conversation_id,
            "ai_provider": ai_provider,
        })

    # ========================================================================
    # API Endpoint Failover handlers
    # ========================================================================

    async def handle_get_api_endpoints(self, ws: WebSocketResponse) -> None:
        """Return current API endpoint failover status."""
        if not API_FAILOVER_AVAILABLE:
            await ws.send_json({"type": "api_endpoints", "available": False})
            return
        status = api_failover.get_status()
        status["type"] = "api_endpoints"
        status["available"] = True
        await ws.send_json(status)

    async def handle_switch_api_endpoint(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Manually switch API endpoint (direct / proxy)."""
        if not API_FAILOVER_AVAILABLE:
            await ws.send_json({"type": "error", "message": "API failover not available"})
            return
        target = data.get("endpoint", "")
        try:
            ep_type = EndpointType(target)
        except ValueError:
            await ws.send_json({"type": "error", "message": f"Invalid endpoint: {target}"})
            return

        success = await api_failover.switch_endpoint(ep_type, reason="dashboard manual switch")
        if success:
            # Recreate Claude client with new endpoint
            self.claude_client = api_failover.get_client()
            await ws.send_json({
                "type": "api_endpoint_switched",
                "endpoint": api_failover.active_endpoint.value,
                **api_failover.get_status(),
            })
        else:
            await ws.send_json({"type": "error", "message": f"Cannot switch to {target}: not configured"})

    async def handle_health_check_endpoint(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Run a health check on a specific or all endpoints."""
        if not API_FAILOVER_AVAILABLE:
            await ws.send_json({"type": "error", "message": "API failover not available"})
            return
        target = data.get("endpoint")
        if target:
            try:
                ep_type = EndpointType(target)
            except ValueError:
                await ws.send_json({"type": "error", "message": f"Invalid endpoint: {target}"})
                return
            result = await api_failover.health_check(ep_type)
            await ws.send_json({"type": "api_health_result", "results": [result]})
        else:
            # Check all endpoints
            results = []
            for ep_type in EndpointType:
                result = await api_failover.health_check(ep_type)
                if "not configured" not in result.get("error", ""):
                    results.append(result)
            await ws.send_json({"type": "api_health_result", "results": results})

    async def _on_endpoint_changed(self, new_endpoint: EndpointType, reason: str) -> None:
        """Called by api_failover when an auto-switch happens. Notify all connected clients."""
        # Refresh our own Claude client
        if API_FAILOVER_AVAILABLE:
            self.claude_client = api_failover.get_client()

        notification = {
            "type": "api_endpoint_switched",
            "endpoint": new_endpoint.value,
            "reason": reason,
            **api_failover.get_status(),
        }
        # Broadcast to all connected clients
        for client_ws in list(self.clients):
            try:
                await client_ws.send_json(notification)
            except Exception:
                pass


# ============================================================================
# Module-level instance
# ============================================================================

_server_instance: DashboardWebSocketServer | None = None


def get_dashboard_ws_server() -> DashboardWebSocketServer:
    """Get or create the dashboard WebSocket server instance."""
    global _server_instance
    if _server_instance is None:
        _server_instance = DashboardWebSocketServer()
    return _server_instance


async def start_dashboard_ws_server() -> bool:
    """Start the dashboard WebSocket server."""
    server = get_dashboard_ws_server()
    return await server.start()


async def stop_dashboard_ws_server() -> None:
    """Stop the dashboard WebSocket server."""
    global _server_instance
    if _server_instance:
        await _server_instance.stop()
        _server_instance = None
