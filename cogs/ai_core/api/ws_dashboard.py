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
import contextlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

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
    handle_delete_document_memory,
    handle_delete_memory,
    handle_delete_message,
    handle_edit_message,
    handle_export_conversation,
    handle_get_document_memory_content,
    handle_get_memories,
    handle_get_profile,
    handle_like_message,
    handle_list_all_tags,
    handle_list_conversation_documents,
    handle_list_conversations,
    handle_load_conversation,
    handle_pin_message,
    handle_remove_conversation_tag,
    handle_rename_conversation,
    handle_save_memory,
    handle_save_profile,
    handle_star_conversation,
    handle_update_document_memory,
)

logger = logging.getLogger(__name__)

# ============================================================================
# WebSocket Dashboard Server
# ============================================================================


class DashboardWebSocketServer:
    """WebSocket server for dashboard AI chat."""

    # Limits
    MAX_CLIENTS = 20
    # Read-only / housekeeping message types that bypass rate limiting.
    # Hoisted to a class-level constant so adding a new lightweight op
    # is a one-line change instead of editing the body of the read loop.
    RATE_EXEMPT_MESSAGE_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "ping",
            "auth",
            "list_conversations",
            "load_conversation",
            "get_memories",
            "get_profile",
            "list_all_tags",
            "list_conversation_documents",
        }
    )
    # Raised from 50K → 200K: matches the direct-API backend ceiling and lets
    # users paste large RP context (character sheets / world bibles / full
    # scenes) in a single message. Claude Opus 4.7 1M context window has
    # plenty of headroom — 200K chars ≈ 50-80K tokens, ~8% of the window.
    MAX_CONTENT_LENGTH = 200_000  # characters
    MAX_HISTORY_MESSAGES = 100
    MAX_IMAGES = 10
    MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB per image
    # Document attachments (PDF / text / code). 32 MB matches the Anthropic
    # API document-block cap exactly — setting it higher would just surface
    # 413 errors from the server instead of a local-side rejection.
    MAX_DOCUMENTS = 5
    MAX_DOCUMENT_SIZE_BYTES = 32 * 1024 * 1024
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
        # Per-IP failed-auth tracker for brute-force throttling. Keys are
        # client IPs (or "unknown"); values are the recent failure
        # timestamps within the lookback window. The handler purges entries
        # older than ``_AUTH_FAIL_WINDOW`` before checking, and rejects
        # with 429 once the bucket reaches ``_AUTH_FAIL_THRESHOLD``.
        self._auth_failures: dict[str, list[float]] = {}
        self._AUTH_FAIL_WINDOW = 60.0  # seconds
        self._AUTH_FAIL_THRESHOLD = 5  # fails in window before lockout
        self._AUTH_FAIL_LOCKOUT = 300.0  # seconds locked out after threshold
        # Long-running handlers (chat, ai_edit) are dispatched as background
        # tasks so the read loop stays responsive to pings + other messages
        # while the AI streams. We hold strong refs here so tasks aren't GC'd.
        self._background_tasks: set[asyncio.Task[Any]] = set()
        # Maps in-flight tasks → originating client id so disconnect can
        # cancel only that client's tasks without mutating Task internals.
        self._client_tasks: dict[asyncio.Task[Any], str] = {}

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
                "reuse_address": True,  # Allow port reuse after close
            }
            if sys.platform != "win32":
                site_kwargs["reuse_port"] = True  # Linux only

            scheme = "ws"
            if WS_REQUIRE_TLS:
                tls_cert_path = os.getenv("WS_TLS_CERT_PATH", "").strip()
                tls_key_path = os.getenv("WS_TLS_KEY_PATH", "").strip()
                if not tls_cert_path or not tls_key_path:
                    logger.error(
                        "❌ WS_REQUIRE_TLS is enabled but WS_TLS_CERT_PATH / WS_TLS_KEY_PATH are not set"
                    )
                    return False

                import ssl

                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_context.load_cert_chain(tls_cert_path, tls_key_path)
                site_kwargs["ssl_context"] = ssl_context
                scheme = "wss"

            self.site = web.TCPSite(self.runner, WS_HOST, WS_PORT, **site_kwargs)
            await self.site.start()

            self._running = True
            logger.info(
                "🚀 Dashboard WebSocket server started on %s://%s:%s", scheme, WS_HOST, WS_PORT
            )
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
                WS_PORT,
                max_wait,
            )

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return

        logger.info("🛑 Stopping Dashboard WebSocket server...")

        # Cancel any in-flight chat/edit background tasks so they don't keep
        # writing to a closed WS or holding subprocess pipes after shutdown.
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        # Detach the failover listener so a server restart doesn't leave a
        # bound-method ref to the previous server instance — without this
        # the old self stays reachable forever and any future endpoint
        # change still tries to push to a dead WS.
        if API_FAILOVER_AVAILABLE:
            try:
                api_failover.remove_listener(self._on_endpoint_changed)
            except Exception:
                logger.debug("Failed to remove failover listener", exc_info=True)

        # Close all client connections (tolerate individual failures, with a
        # timeout so an unresponsive client can't stall shutdown).
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(
                    ws.close(code=1001, message=b"Server shutting down"),
                    timeout=2.0,
                )
            except (TimeoutError, Exception):
                pass
        self.clients.clear()

        # Close the Anthropic SDK client to release its underlying httpx
        # connection pool (otherwise reload leaves sockets open).
        if self.claude_client is not None:
            try:
                close_coro = getattr(self.claude_client, "close", None)
                if close_coro is not None:
                    result = close_coro()
                    if asyncio.iscoroutine(result):
                        await asyncio.wait_for(result, timeout=2.0)
            except Exception:
                logger.debug("Failed to close Claude client cleanly", exc_info=True)

        # Close the Gemini SDK client to release its underlying httpx
        # connection pool (mirrors the Claude close above).
        if self.gemini_client is not None:
            try:
                close_coro = getattr(self.gemini_client, "close", None)
                if close_coro is not None:
                    result = close_coro()
                    if asyncio.iscoroutine(result):
                        await asyncio.wait_for(result, timeout=2.0)
            except Exception:
                logger.debug("Failed to close Gemini client cleanly", exc_info=True)

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

    @staticmethod
    @web.middleware
    async def _cors_middleware(request: web.Request, handler):
        """Add CORS headers restricting access to localhost origins."""
        origin = request.headers.get("Origin", "")

        # Validate origin against whitelist
        allowed_origin = ""
        for prefix in DashboardWebSocketServer._ALLOWED_ORIGIN_PREFIXES:
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
        """Health check endpoint.

        Public-shaped response (no auth) for load balancer / liveness
        probes. Don't enumerate provider availability or client count
        here — that's capability/operational info that should sit behind
        the protected `/health/deep` endpoint instead. A scraper hitting
        this URL just needs "is the server up".
        """
        return web.json_response({"status": "healthy"})

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse | web.Response:
        """Handle WebSocket connections."""
        # Security: Validate origin for localhost-only connections
        origin = request.headers.get("Origin", "")
        host = request.headers.get("Host", "")

        # Authentication: Require API key from environment or query param
        expected_token = os.getenv("DASHBOARD_WS_TOKEN", "")
        peername = request.transport.get_extra_info("peername") if request.transport else None
        # Resolve the bucket key once. peername is (ip, port[, ...]); take ip.
        client_ip = peername[0] if isinstance(peername, tuple) and peername else "unknown"

        if not expected_token:
            logger.error(
                "❌ DASHBOARD_WS_TOKEN not set — rejecting connection. "
                "Set DASHBOARD_WS_TOKEN in .env to allow dashboard access."
            )
            return web.Response(status=401, text="Unauthorized: DASHBOARD_WS_TOKEN is required")

        # Per-IP failed-auth backoff. Without this, an attacker on the same
        # host can fire token guesses without rate limit until they crack
        # the token (10–20 chars of entropy is not enough against unbounded
        # online guessing). 5 fails in 60s → 5-minute lockout per IP.
        now = time.monotonic()
        prior = self._auth_failures.get(client_ip, [])
        # Drop attempts that have aged out of the window.
        prior = [t for t in prior if now - t < self._AUTH_FAIL_WINDOW]
        if len(prior) >= self._AUTH_FAIL_THRESHOLD:
            oldest = prior[0]
            unlock_in = self._AUTH_FAIL_LOCKOUT - (now - oldest)
            if unlock_in > 0:
                logger.warning(
                    "⚠️ Rejected WS connection: auth-fail lockout for %s (retry in %.0fs)",
                    client_ip,
                    unlock_in,
                )
                return web.Response(
                    status=429,
                    text=f"Too many failed authentications; retry in {int(unlock_in)}s",
                    headers={"Retry-After": str(max(1, int(unlock_in)))},
                )
            # Lockout expired — reset and continue.
            prior = []
        self._auth_failures[client_ip] = prior

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
                # Bearer scheme is case-insensitive per RFC 7235; normalise the
                # scheme prefix before comparing so "bearer foo" / "BEARER foo"
                # don't get rejected. Token portion stays exact + timing-safe.
                auth_match = False
                if auth_header:
                    parts = auth_header.split(" ", 1)
                    if len(parts) == 2 and parts[0].lower() == "bearer":
                        auth_match = hmac.compare_digest(parts[1], expected_token)
                token_match = (
                    hmac.compare_digest(query_token, expected_token) if query_token else False
                )
                if not auth_match and not token_match:
                    self._auth_failures.setdefault(client_ip, []).append(now)
                    logger.warning(
                        "⚠️ Rejected WebSocket connection: invalid auth token (from %s)", peername
                    )
                    return web.Response(status=401, text="Unauthorized: Invalid token")
                else:
                    _upgrade_authenticated = True
                    # Successful auth — clear the bucket so a legitimate user
                    # who fat-fingered the token a few times isn't locked out.
                    self._auth_failures.pop(client_ip, None)

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
            logger.warning(
                "⚠️ Rejected WebSocket connection from origin: %s, host: %s", origin, host
            )
            return web.Response(
                status=403, text="Forbidden: Connection only allowed from localhost"
            )

        # Enforce max concurrent connections
        if len(self.clients) >= self.MAX_CLIENTS:
            logger.warning(
                "⚠️ Rejected WebSocket connection: max clients (%s) reached", self.MAX_CLIENTS
            )
            return web.Response(status=503, text="Service Unavailable: Too many connections")

        # Frame cap derived from the per-attachment limits the handler itself
        # advertises (MAX_DOCUMENT_SIZE_BYTES + MAX_IMAGE_SIZE_BYTES + content
        # + ~1MB headroom for headers/history). The previous fixed 10 MB cap
        # contradicted MAX_DOCUMENT_SIZE_BYTES=32 MB and silently rejected any
        # single-document payload over 10 MB before the handler could process it.
        max_frame = (
            self.MAX_DOCUMENT_SIZE_BYTES
            + self.MAX_IMAGE_SIZE_BYTES
            + self.MAX_CONTENT_LENGTH
            + 1 * 1024 * 1024
        )
        ws = web.WebSocketResponse(max_msg_size=max_frame)
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
            # Tolerate non-auth frames (pings, etc.) before auth so a quick
            # ping doesn't disconnect the client — keep waiting until auth
            # arrives or the deadline elapses.
            if needs_auth:
                auth_received = False
                deadline = asyncio.get_running_loop().time() + self._auth_deadline
                while not auth_received:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        deadline_msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
                    except TimeoutError:
                        break
                    if deadline_msg.type != WSMsgType.TEXT:
                        # Non-text (close, error) — exit loop.
                        if deadline_msg.type in (
                            WSMsgType.CLOSE,
                            WSMsgType.CLOSING,
                            WSMsgType.CLOSED,
                            WSMsgType.ERROR,
                        ):
                            break
                        continue
                    # Pre-auth message size cap. The connection-wide
                    # max_msg_size is sized for chat payloads (~43 MB) which
                    # is far too generous for an unauthenticated client.
                    # Enforce a 4 KiB cap until the client has authenticated.
                    if isinstance(deadline_msg.data, str) and len(deadline_msg.data) > 4096:
                        logger.warning(
                            "⚠️ Pre-auth message from %s exceeds 4 KiB cap (%d bytes)",
                            client_id,
                            len(deadline_msg.data),
                        )
                        break
                    try:
                        auth_data = json.loads(deadline_msg.data)
                    except json.JSONDecodeError:
                        continue
                    msg_type = auth_data.get("type")
                    if msg_type == "ping":
                        # Allow ping before auth — just keep waiting.
                        with contextlib.suppress(Exception):
                            await ws.send_json({"type": "pong"})
                        continue
                    if msg_type == "auth":
                        token = auth_data.get("token", "")
                        if hmac.compare_digest(str(token), expected_token):
                            self._authenticated_clients.add(client_id)
                            auth_received = True
                            # Successful auth — clear the per-IP fail bucket
                            # so a legitimate user who fat-fingered their
                            # token a couple times isn't locked out.
                            self._auth_failures.pop(client_ip, None)
                            logger.debug("✅ Client %s authenticated via message", client_id)
                        else:
                            # Record this attempt against the IP bucket so
                            # the upgrade-time check on the NEXT connection
                            # can reject before the WebSocket handshake.
                            self._auth_failures.setdefault(client_ip, []).append(time.monotonic())
                            logger.warning("⚠️ Invalid auth token from client %s", client_id)
                            break
                    else:
                        # Anything else before auth → reject.
                        break

                if not auth_received:
                    logger.warning(
                        "⚠️ Client %s failed to authenticate within %.0fs deadline",
                        client_id,
                        self._auth_deadline,
                    )
                    await ws.send_json(
                        {"type": "error", "message": "Authentication required. Connection closing."}
                    )
                    await ws.close(code=4001, message=b"Authentication deadline exceeded")
                    return ws

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        msg_id = str(uuid.uuid4())[:8]
                        msg_type = data.get("type")

                        # Rate limiting per client — exempts the read-only
                        # message types defined at class level.
                        if msg_type not in self.RATE_EXEMPT_MESSAGE_TYPES:
                            now = asyncio.get_running_loop().time()
                            times = self._client_message_times.get(client_id, [])
                            # Remove entries older than 60s
                            times = [t for t in times if now - t < 60]
                            self._client_message_times[client_id] = times
                            if len(times) >= self.RATE_LIMIT_MESSAGES_PER_MINUTE:
                                await ws.send_json(
                                    {
                                        "type": "error",
                                        "message": "Rate limit exceeded. Please wait.",
                                    }
                                )
                                continue
                            times.append(now)
                        logger.debug(
                            "WS msg client=%s msg=%s type=%s",
                            client_id,
                            msg_id,
                            data.get("type", "?"),
                        )
                        # Verify authentication for every request (except auth/ping)
                        if (
                            msg_type not in ("auth", "ping")
                            and expected_token
                            and client_id not in self._authenticated_clients
                        ):
                            await ws.send_json(
                                {"type": "error", "message": "Authentication required"}
                            )
                            continue
                        # Long-running AI ops are dispatched as background tasks so
                        # the read loop keeps draining pings + other messages while
                        # the AI streams. Without this, a 60s+ AI turn starves the
                        # client's ping/pong loop and triggers a forced reconnect,
                        # surfacing as "Not connected to AI server" mid-response.
                        if msg_type in ("message", "ai_edit_message"):
                            task = asyncio.create_task(
                                self.handle_message(ws, data, client_id, msg_id=msg_id)
                            )
                            # Map task → originating client so disconnect can
                            # cancel only this client's in-flight tasks.
                            self._client_tasks[task] = client_id
                            self._background_tasks.add(task)

                            def _on_task_done(t: asyncio.Task[Any]) -> None:
                                self._background_tasks.discard(t)
                                self._client_tasks.pop(t, None)

                            task.add_done_callback(_on_task_done)
                        else:
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
            # Cancel any chat/edit tasks still running for this client so they
            # don't keep streaming to a closed WS or holding subprocesses.
            cancelled: list[asyncio.Task[Any]] = []
            for task in list(self._background_tasks):
                if not task.done() and self._client_tasks.get(task) == client_id:
                    task.cancel()
                    cancelled.append(task)
            if cancelled:
                # Await cancellation so subprocesses / streams really stop
                # before we log the disconnect. Bounded so a stuck task can't
                # stall close.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(*cancelled, return_exceptions=True),
                        timeout=5.0,
                    )
            logger.info("👋 Dashboard client disconnected: %s", client_id)

        return ws

    async def handle_message(
        self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = "", msg_id: str = ""
    ) -> None:
        """Handle incoming WebSocket messages."""
        msg_type = data.get("type")

        if msg_type == "new_conversation":
            await self.handle_new_conversation(ws, data)
        elif msg_type == "message":
            # Enforce concurrency limit per client
            inflight = self._client_inflight.get(client_id, 0)
            if inflight >= 2:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "Too many concurrent requests. Please wait for the current response to finish.",
                    }
                )
                return
            self._client_inflight[client_id] = inflight + 1
            try:
                logger.debug("WS chat start client=%s msg=%s", client_id, msg_id)
                await self.handle_chat_message(ws, data)
            finally:
                self._client_inflight[client_id] = max(
                    0, self._client_inflight.get(client_id, 1) - 1
                )
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
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "Too many concurrent requests. Please wait for the current response to finish.",
                    }
                )
                return
            self._client_inflight[client_id] = inflight + 1
            try:
                await self.handle_ai_edit_message(ws, data)
            finally:
                self._client_inflight[client_id] = max(
                    0, self._client_inflight.get(client_id, 1) - 1
                )
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
        elif msg_type == "list_conversation_documents":
            await handle_list_conversation_documents(ws, data)
        elif msg_type == "delete_document_memory":
            await handle_delete_document_memory(ws, data)
        elif msg_type == "get_document_memory_content":
            await handle_get_document_memory_content(ws, data)
        elif msg_type == "update_document_memory":
            await handle_update_document_memory(ws, data)
        elif msg_type == "get_profile":
            await self.handle_get_profile(ws)
        elif msg_type == "save_profile":
            await self.handle_save_profile(ws, data)
        elif msg_type == "auth":
            # Re-auth or late auth via message — already handled at connect deadline,
            # but allow re-validation for token rotation.
            token = data.get("token", "")
            expected = os.getenv("DASHBOARD_WS_TOKEN", "")
            if not expected:
                # Reject empty-token re-auth: server with no token configured
                # has already rejected the original handshake; a re-auth that
                # would silently grant access if expected becomes "" is unsafe.
                return
            if not hmac.compare_digest(str(token), expected):
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

        await ws.send_json(
            {
                "type": "conversation_created",
                "id": conversation_id,
                "role_preset": role_preset,
                "role_name": preset["name"],
                "role_emoji": preset["emoji"],
                "role_color": preset["color"],
                "thinking_enabled": thinking_enabled,
                "ai_provider": ai_provider,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )

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
                    ws,
                    data,
                    None,
                    max_content_length=self.MAX_CONTENT_LENGTH,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    max_images=self.MAX_IMAGES,
                    max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
                    max_documents=self.MAX_DOCUMENTS,
                    max_document_size_bytes=self.MAX_DOCUMENT_SIZE_BYTES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return
            if self.claude_client:
                # Use latest client from failover manager (may have switched)
                if API_FAILOVER_AVAILABLE:
                    self.claude_client = api_failover.get_client()
                await _handle_chat_message_claude(
                    ws,
                    data,
                    self.claude_client,
                    max_content_length=self.MAX_CONTENT_LENGTH,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    max_images=self.MAX_IMAGES,
                    max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
                    max_documents=self.MAX_DOCUMENTS,
                    max_document_size_bytes=self.MAX_DOCUMENT_SIZE_BYTES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return
            # ai_provider=claude but neither backend is configured — fall through
            # to Gemini so the user still gets a reply instead of silent failure.

        await _handle_chat_message(
            ws,
            data,
            self.gemini_client,
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
                    ws,
                    data,
                    None,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return
            if self.claude_client:
                await _handle_ai_edit_message_claude(
                    ws,
                    data,
                    self.claude_client,
                    max_history_messages=self.MAX_HISTORY_MESSAGES,
                    stream_timeout=self.STREAM_TIMEOUT,
                )
                return

        await _handle_ai_edit_message(
            ws,
            data,
            self.gemini_client,
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
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"Invalid ai_provider: {ai_provider!r} (expected 'gemini' or 'claude')",
                }
            )
            return
        if not conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "conversation_id is required to update provider",
                }
            )
            return
        if DB_AVAILABLE:
            try:
                db = Database()
                await db.update_dashboard_conversation(conversation_id, ai_provider=ai_provider)
            except Exception:
                logger.exception("Failed to update provider")
                await ws.send_json({"type": "error", "message": "Failed to update provider"})
                return
        await ws.send_json(
            {
                "type": "provider_updated",
                "conversation_id": conversation_id,
                "ai_provider": ai_provider,
            }
        )

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
            await ws.send_json(
                {
                    "type": "api_endpoint_switched",
                    "endpoint": api_failover.active_endpoint.value,
                    **api_failover.get_status(),
                }
            )
        else:
            await ws.send_json(
                {"type": "error", "message": f"Cannot switch to {target}: not configured"}
            )

    async def handle_health_check_endpoint(
        self, ws: WebSocketResponse, data: dict[str, Any]
    ) -> None:
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
        # Broadcast to all connected clients. Drop dead clients from the
        # active set so subsequent broadcasts don't keep retrying them
        # (silent loss + log spam previously).
        dead: list[Any] = []
        for client_ws in list(self.clients):
            try:
                await asyncio.wait_for(client_ws.send_json(notification), timeout=2.0)
            except (TimeoutError, ConnectionError, RuntimeError):
                dead.append(client_ws)
            except Exception as e:
                logger.debug("Broadcast send failed for one client: %s", e)
                dead.append(client_ws)
        for ws in dead:
            self.clients.discard(ws)


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
