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
import os
import uuid
from datetime import timezone, datetime
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web
from google import genai

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# Import from extracted modules
from .dashboard_chat import handle_chat_message as _handle_chat_message
from .dashboard_config import (
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    GEMINI_API_KEY,
    WS_HOST,
    WS_PORT,
    Database,
)
from .dashboard_handlers import (
    handle_delete_conversation,
    handle_delete_memory,
    handle_delete_message,
    handle_edit_message,
    handle_export_conversation,
    handle_get_memories,
    handle_get_profile,
    handle_list_conversations,
    handle_load_conversation,
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
        self._running = False
        self._client_message_times: dict[str, list[float]] = {}  # rate limit tracking
        self._client_inflight: dict[str, int] = {}  # concurrent request tracking

        # Initialize Gemini client
        if GEMINI_API_KEY:
            self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            logging.info("🤖 Dashboard WS: Gemini client initialized")
        else:
            logging.warning("⚠️ Dashboard WS: No GEMINI_API_KEY found")

    async def start(self) -> bool:
        """Start the WebSocket server."""
        if self._running:
            logging.warning("⚠️ Dashboard WebSocket server already running")
            return True

        try:
            # Try to free the port if it's in use
            await self._ensure_port_available()

            self.app = web.Application()
            self.app.router.add_get("/ws", self.websocket_handler)
            self.app.router.add_get("/health", self.health_handler)

            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            # Create TCPSite with reuse_address for faster restart
            # Note: reuse_port is only supported on Linux, not Windows
            import sys
            site_kwargs = {
                'reuse_address': True,  # Allow port reuse after close
            }
            if sys.platform != 'win32':
                site_kwargs['reuse_port'] = True  # Linux only

            self.site = web.TCPSite(
                self.runner,
                WS_HOST,
                WS_PORT,
                **site_kwargs
            )
            await self.site.start()

            self._running = True
            logging.info("🚀 Dashboard WebSocket server started on ws://%s:%s", WS_HOST, WS_PORT)
            return True

        except Exception as e:
            logging.error("❌ Failed to start Dashboard WebSocket server: %s", e)
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
            logging.warning("⚠️ Port %s is in use, attempting to free it...", WS_PORT)

            # SAFETY: We will NOT auto-kill processes anymore.
            # Instead, we wait for the port to become available or fail gracefully.
            # This prevents accidentally killing unrelated processes.

            max_wait = 5  # Maximum seconds to wait for port
            waited = 0

            while waited < max_wait:
                await asyncio.sleep(0.5)
                waited += 0.5

                # Re-check if port is free
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex((WS_HOST, WS_PORT))

                if result != 0:  # Port is now free
                    logging.info("✅ Port %s is now available", WS_PORT)
                    return

            # If still not free, log warning but continue (will fail gracefully on bind)
            logging.warning(
                "⚠️ Port %s still in use after %ss wait. "
                "If this is an old bot instance, please stop it manually.",
                WS_PORT, max_wait
            )

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return

        logging.info("🛑 Stopping Dashboard WebSocket server...")

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
        logging.info("🛑 Dashboard WebSocket server stopped")

    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "clients": len(self.clients),
            "gemini_available": self.gemini_client is not None,
        })

    async def websocket_handler(self, request: web.Request) -> WebSocketResponse:
        """Handle WebSocket connections."""
        # Security: Validate origin for localhost-only connections
        origin = request.headers.get("Origin", "")
        host = request.headers.get("Host", "")

        # Authentication: Require API key from environment or query param
        expected_token = os.getenv("DASHBOARD_WS_TOKEN", "")
        # Determine if connection is from localhost (already origin-restricted)
        peername = request.transport.get_extra_info("peername") if request.transport else None
        peername and peername[0] in ("127.0.0.1", "::1", "localhost")

        if not expected_token:
            logging.warning(
                "⚠️ DASHBOARD_WS_TOKEN not set — WebSocket server has NO authentication! "
                "Set DASHBOARD_WS_TOKEN in .env for security."
            )
        if expected_token:
            # Check Authorization header or query param (timing-safe comparison).
            # If neither is provided, allow connection — the Tauri dashboard sends
            # the token via WebSocket message (type: 'auth') to avoid URL/header leakage.
            # Only reject here if a token IS provided but is invalid.
            auth_header = request.headers.get("Authorization", "")
            query_token = request.query.get("token", "")
            has_credentials = bool(auth_header) or bool(query_token)
            if has_credentials:
                auth_match = hmac.compare_digest(auth_header, f"Bearer {expected_token}") if auth_header else False
                token_match = hmac.compare_digest(query_token, expected_token) if query_token else False
                if not auth_match and not token_match:
                    logging.warning("⚠️ Rejected WebSocket connection: invalid auth token (from %s)", peername)
                    return web.Response(status=401, text="Unauthorized: Invalid token")

        # Allow connections from localhost only (127.0.0.1 or localhost)
        # Use exact prefix matching to prevent subdomain bypass (e.g., evil-localhost.com)
        allowed_origins = [
            "http://127.0.0.1",
            "http://localhost",
            "https://127.0.0.1",
            "https://localhost",
            # Note: file:// origin removed for security — Tauri uses tauri://localhost
        ]

        # Check if origin is allowed
        # Require origin header from browser clients—empty origin is only allowed
        # if host header explicitly matches localhost
        def _is_safe_origin(o: str) -> bool:
            """Check if origin matches an allowed prefix followed by port or end-of-string."""
            for allowed in allowed_origins:
                if o == allowed:
                    return True
                if o.startswith(allowed + ":") or o.startswith(allowed + "/"):
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
            logging.warning("⚠️ Rejected WebSocket connection from origin: %s, host: %s", origin, host)
            return web.Response(status=403, text="Forbidden: Connection only allowed from localhost")

        # Enforce max concurrent connections
        if len(self.clients) >= self.MAX_CLIENTS:
            logging.warning("⚠️ Rejected WebSocket connection: max clients (%s) reached", self.MAX_CLIENTS)
            return web.Response(status=503, text="Service Unavailable: Too many connections")

        ws = web.WebSocketResponse(max_msg_size=10 * 1024 * 1024)  # 10MB max message size
        await ws.prepare(request)

        self.clients.add(ws)
        client_id = str(uuid.uuid4())[:8]
        logging.info("👋 Dashboard client connected: %s", client_id)

        try:
            # Send welcome message
            await ws.send_json({
                "type": "connected",
                "client_id": client_id,
                "presets": {
                    key: {
                        "name": preset["name"],
                        "emoji": preset["emoji"],
                        "color": preset["color"],
                    }
                    for key, preset in DASHBOARD_ROLE_PRESETS.items()
                },
            })

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        # Rate limiting per client
                        now = asyncio.get_running_loop().time()
                        times = self._client_message_times.get(client_id, [])
                        # Remove entries older than 60s
                        times = [t for t in times if now - t < 60]
                        self._client_message_times[client_id] = times
                        if len(times) >= self.RATE_LIMIT_MESSAGES_PER_MINUTE:
                            await ws.send_json({"type": "error", "message": "Rate limit exceeded. Please wait."})
                            continue
                        times.append(now)
                        await self.handle_message(ws, data, client_id)
                    except json.JSONDecodeError:
                        await ws.send_json({"type": "error", "message": "Invalid JSON"})
                elif msg.type == WSMsgType.ERROR:
                    logging.error("WebSocket error: %s", ws.exception())
                    break

        except Exception as e:
            logging.error("❌ WebSocket handler error: %s", e)
        finally:
            self.clients.discard(ws)
            self._client_message_times.pop(client_id, None)
            self._client_inflight.pop(client_id, None)
            logging.info("👋 Dashboard client disconnected: %s", client_id)

        return ws

    async def handle_message(self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = "") -> None:
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
        elif msg_type == "delete_message":
            await handle_delete_message(ws, data)
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
            # Frontend sends token via message (not URL) to avoid leaking in logs.
            # HTTP-level auth already validates headers/query params during upgrade;
            # this handler covers the message-based auth flow from the Tauri dashboard.
            token = data.get("token", "")
            expected = os.getenv("DASHBOARD_WS_TOKEN", "")
            if expected and not hmac.compare_digest(str(token), expected):
                logging.warning("⚠️ Invalid auth token from client %s", client_id)
                await ws.send_json({"type": "error", "message": "Invalid auth token"})
            else:
                logging.debug("✅ Client %s authenticated via message", client_id)
        elif msg_type == "ping":
            await ws.send_json({"type": "pong"})
        else:
            await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

    async def handle_new_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Create a new conversation."""
        role_preset = data.get("role_preset", "general")
        thinking_enabled = data.get("thinking_enabled", False)

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
                )
            except Exception as e:
                logging.error("Failed to save conversation to DB: %s", e)

        await ws.send_json({
            "type": "conversation_created",
            "id": conversation_id,
            "role_preset": role_preset,
            "role_name": preset["name"],
            "role_emoji": preset["emoji"],
            "role_color": preset["color"],
            "thinking_enabled": thinking_enabled,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    async def handle_chat_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle incoming chat message and stream response.
        Delegates to dashboard_chat module.
        """
        await _handle_chat_message(
            ws, data, self.gemini_client,
            max_content_length=self.MAX_CONTENT_LENGTH,
            max_history_messages=self.MAX_HISTORY_MESSAGES,
            max_images=self.MAX_IMAGES,
            max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
            stream_timeout=self.STREAM_TIMEOUT,
        )

    # ========================================================================
    # CRUD handlers — delegated to dashboard_handlers module
    # ========================================================================

    async def handle_list_conversations(self, ws: WebSocketResponse) -> None:
        await handle_list_conversations(ws)

    async def handle_load_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_load_conversation(ws, data)

    async def handle_delete_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
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
