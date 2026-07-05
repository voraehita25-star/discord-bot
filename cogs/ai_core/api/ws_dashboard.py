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
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar, cast

from aiohttp import WSMsgType, web
from google import genai

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# Import from extracted modules
from ..data.constants import DASHBOARD_HISTORY_MESSAGES
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
    shutdown_prewarm as _shutdown_cli_prewarm,
)
from .dashboard_config import (
    API_FAILOVER_AVAILABLE,
    AVAILABLE_PROVIDERS,
    CLAUDE_API_KEY,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    DEFAULT_AI_PROVIDER,
    GEMINI_API_KEY,
    VALID_AI_PROVIDERS,
    WS_HOST,
    WS_PORT,
    WS_REQUIRE_TLS,
    Database,
)

# Backend toggle for the Claude provider:
#   CLAUDE_BACKEND=cli  → spawn `claude -p` (uses subscription via CLAUDE_CODE_OAUTH_TOKEN)
#   anything else / unset → use anthropic SDK with ANTHROPIC_API_KEY (per-token billing)
#
# Default "cli" — matches dashboard_config.py, api_failover.py,
# memory/summarizer.py, env.example and CLAUDE.md. This file previously
# defaulted to "api", which split a fresh checkout into two contradictory
# modes: dashboard_config computed API_AI_DISABLED=True while this module
# initialised the paid Gemini/Anthropic SDK clients and skipped the working
# CLI backend. (Tests that exercise the SDK path pin CLAUDE_BACKEND=api in
# their fixture instead of relying on the default.)
_CLAUDE_BACKEND = os.getenv("CLAUDE_BACKEND", "cli").strip().lower()

if API_FAILOVER_AVAILABLE:
    from .api_failover import EndpointType, api_failover
from .dashboard_handlers import (
    handle_add_conversation_tag,
    handle_delete_ai_history_message,
    handle_delete_conversation,
    handle_delete_document_memory,
    handle_delete_message,
    handle_edit_ai_history_message,
    handle_edit_message,
    handle_export_conversation,
    handle_get_document_memory_content,
    handle_get_profile,
    handle_like_message,
    handle_list_ai_channels,
    handle_list_all_tags,
    handle_list_conversation_documents,
    handle_list_conversations,
    handle_load_ai_history,
    handle_load_conversation,
    handle_pin_message,
    handle_remove_conversation_tag,
    handle_rename_conversation,
    handle_restore_ai_history_message,
    handle_save_profile,
    handle_star_conversation,
    handle_update_document_memory,
)

logger = logging.getLogger(__name__)


class _ScopedErrorWs:
    """Transparent WebSocketResponse wrapper that tags outgoing error frames.

    Management handlers (conversation list/star/rename/…, tags, document
    memory, profile, provider/endpoint ops) reply with plain
    ``{"type": "error", ...}`` frames. The dashboard client needs to tell those
    apart from CHAT-turn errors: an unscoped error tears down any in-flight
    chat stream (re-enables the composer, discards the eventual stream_end),
    so a failed background sidebar/settings operation used to kill a live
    response. Wrapping the ws per-dispatch injects ``scope=<wire msg type>`` —
    the same value the rate limiter already uses — without touching dozens of
    handler send sites. Frames that already carry a scope (the ai-history
    handlers) and non-error frames pass through untouched.
    """

    __slots__ = ("_scope", "_ws")

    def __init__(self, ws: WebSocketResponse, scope: str) -> None:
        self._ws = ws
        self._scope = scope

    async def send_json(self, data: Any, *args: Any, **kwargs: Any) -> None:
        if isinstance(data, dict) and data.get("type") == "error" and "scope" not in data:
            data = {**data, "scope": self._scope}
        await self._ws.send_json(data, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ws, name)


def _scoped_error_ws(ws: WebSocketResponse, scope: str) -> WebSocketResponse:
    """Wrap ``ws`` for a management dispatch (see _ScopedErrorWs).

    The cast keeps handler signatures honest (they only ever call
    ``send_json``/read-only attrs, all forwarded by the wrapper).
    """
    return cast("WebSocketResponse", _ScopedErrorWs(ws, scope))


# ============================================================================
# WebSocket Dashboard Server
# ============================================================================


class DashboardWebSocketServer:
    """WebSocket server for dashboard AI chat."""

    # Limits
    MAX_CLIENTS = 20
    # Max simultaneously-running AI tasks (chat / ai_edit) per client. Enforced
    # authoritatively by the read-loop gate (which counts not-done tasks in
    # _client_tasks BEFORE spawning); the inner _client_inflight backstops in
    # handle_message reuse the same constant so the two caps can never drift.
    MAX_INFLIGHT_PER_CLIENT = 2
    # Read-only / housekeeping message types that bypass rate limiting.
    # Hoisted to a class-level constant so adding a new lightweight op
    # is a one-line change instead of editing the body of the read loop.
    RATE_EXEMPT_MESSAGE_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "ping",
            "auth",
            "list_conversations",
            "load_conversation",
            "get_profile",
            # Dispatch routes incoming type "list_tags" (not "list_all_tags")
            # to handle_list_all_tags. NOTE: currently an ORPHANED endpoint —
            # no shipped frontend code sends "list_tags" (the tag picker only
            # sends add_tag/remove_tag); kept wired + exempt for a future
            # tag-picker suggestion list.
            "list_tags",
            "list_conversation_documents",
            # AI-history viewer: only the channel-list summary (one cheap
            # GROUP BY) is exempt. "load_ai_history" is NOT — it is the
            # heaviest read op (up to 2000 full-content rows fetched, then
            # serialized synchronously on the event loop the Discord bot
            # shares), so it stays under the RATE_LIMIT_MESSAGES_PER_MINUTE
            # budget (currently 120/min) like the write ops
            # ("edit_ai_history_message" / "delete_ai_history_message" /
            # "restore_ai_history_message").
            "list_ai_channels",
        }
    )
    # Raised from 50K → 200K: matches the direct-API backend ceiling and lets
    # users paste large RP context (character sheets / world bibles / full
    # scenes) in a single message. Claude Opus 4.8 1M context window has
    # plenty of headroom — 200K chars ≈ 50-80K tokens, ~8% of the window.
    MAX_CONTENT_LENGTH = 200_000  # characters
    # Env-driven (DASHBOARD_HISTORY_MESSAGES, default 500): how many prior
    # messages are rendered into a fresh-session prompt. Raised from 100 — the
    # 1M-token window holds long dashboard threads without losing earlier turns.
    MAX_HISTORY_MESSAGES = DASHBOARD_HISTORY_MESSAGES
    MAX_IMAGES = 10
    MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB per image
    # Document attachments (PDF / text / code). 32 MB matches the Anthropic
    # API document-block cap exactly — setting it higher would just surface
    # 413 errors from the server instead of a local-side rejection.
    MAX_DOCUMENTS = 5
    MAX_DOCUMENT_SIZE_BYTES = 32 * 1024 * 1024
    STREAM_TIMEOUT = 300  # seconds for full stream consumption
    RATE_LIMIT_MESSAGES_PER_MINUTE = (
        120  # max messages per client per minute (raised for the owner's dashboard)
    )

    def __init__(self):
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.clients: set[WebSocketResponse] = set()
        self.gemini_client: genai.Client | None = None
        self.claude_client: Any | None = None
        self._running = False
        # Per-client message-send timestamps for rate limiting. Use ``deque``
        # (with bounded maxlen) so eviction of stale entries is O(1) — same
        # reasoning as ``_auth_failures`` below. Without this, a fast
        # client + a list-comp rebuild per message was the dominant CPU
        # cost on the hot path of the WS receive loop.
        self._client_message_times: dict[str, deque[float]] = {}
        self._client_inflight: dict[str, int] = {}  # concurrent request tracking
        self._authenticated_clients: set[str] = set()  # track authenticated client IDs
        # Parallel set of authenticated WS objects. self.clients holds every WS
        # (added on connect, before auth), so broadcasts that carry sensitive
        # data must filter on this set rather than self.clients.
        self._authenticated_ws: set[Any] = set()
        self._auth_deadline: float = 5.0  # seconds to authenticate after connecting
        # Per-IP failed-auth tracker for brute-force throttling. Keys are
        # client IPs (or "unknown"); values are the recent failure
        # timestamps within the lookback window. The handler purges entries
        # older than ``_AUTH_FAIL_WINDOW`` before checking, and rejects
        # with 429 once the bucket reaches ``_AUTH_FAIL_THRESHOLD``.
        # Use ``deque(maxlen)`` over a plain ``list`` so each connection
        # attempt is O(1) eviction instead of O(n) list comprehension —
        # under a brute-force flood the list-comp + reassign was the
        # dominant CPU cost on the rejection path. The maxlen is set at
        # ``_AUTH_FAIL_THRESHOLD`` so older entries fall off naturally
        # once we hit the lockout cap.
        self._AUTH_FAIL_WINDOW = 60.0  # seconds
        self._AUTH_FAIL_THRESHOLD = 5  # fails in window before lockout
        self._AUTH_FAIL_LOCKOUT = 300.0  # seconds locked out after threshold
        self._auth_failures: dict[str, deque[float]] = {}
        # Absolute monotonic unlock time per IP. Decoupled from _auth_failures so
        # a triggered lockout lasts the full _AUTH_FAIL_LOCKOUT instead of being
        # released early when the windowed failure timestamps age out (~60s).
        self._auth_lockouts: dict[str, float] = {}
        # Re-auth bruteforce throttle. The connect-deadline path covers
        # the first auth attempt, but once a WS is established a client
        # can keep sending {type:"auth"} messages indefinitely. Track
        # per-client failures and force-close after a small ceiling.
        self._client_auth_failures: dict[str, int] = {}
        self._MAX_REAUTH_FAILURES = 3
        # Long-running handlers (chat, ai_edit) are dispatched as background
        # tasks so the read loop stays responsive to pings + other messages
        # while the AI streams. We hold strong refs here so tasks aren't GC'd.
        self._background_tasks: set[asyncio.Task[Any]] = set()
        # Maps in-flight tasks → originating client id so disconnect can
        # cancel only that client's tasks without mutating Task internals.
        self._client_tasks: dict[asyncio.Task[Any], str] = {}

        # Initialize Gemini client. Skipped under CLAUDE_BACKEND=cli —
        # Gemini is paid-API-only and dashboard_config drops it from
        # AVAILABLE_PROVIDERS in CLI mode, so its handler is unreachable.
        # Uses the SAME default ("cli") as the module-level
        # ``_CLAUDE_BACKEND`` above and every other CLAUDE_BACKEND reader,
        # so an unset env var consistently means subscription-only CLI mode
        # and never initialises paid SDK clients from lingering .env keys.
        _api_disabled = os.getenv("CLAUDE_BACKEND", "cli").strip().lower() == "cli"
        if _api_disabled:
            logger.info("🚫 Dashboard WS: Gemini disabled (CLAUDE_BACKEND=cli)")
        elif GEMINI_API_KEY:
            self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("🤖 Dashboard WS: Gemini client initialized")
        else:
            logger.warning("⚠️ Dashboard WS: No GEMINI_API_KEY found")

        # Initialize Claude (Anthropic) client — prefer failover manager.
        # Track whether the listener was successfully registered so ``stop()``
        # only tries to remove it when present. Without the flag, an
        # __init__ failure that occurs AFTER add_listener() but BEFORE the
        # rest of init completes leaves a dangling listener forever — every
        # restart compounds the leak.
        self._failover_listener_registered = False
        # True only when THIS instance constructed the Anthropic client
        # directly (CLAUDE_API_KEY fallback branches). The failover manager's
        # pooled client is shared — logic.py's Discord path holds the same
        # object — and the manager's ownership contract forbids closing it
        # (api_failover: closing "would defeat the whole point of pooling and
        # break any in-flight messages.create referencing it"). stop() gates
        # its close on this flag.
        self._claude_client_owned = False
        if _api_disabled:
            logger.info(
                "🚫 Dashboard WS: Anthropic SDK client disabled "
                "(CLAUDE_BACKEND=cli) — chat routes through Claude CLI subprocess"
            )
        elif API_FAILOVER_AVAILABLE and api_failover.active_config:
            try:
                self.claude_client = api_failover.get_client()
                logger.info(
                    "🟣 Dashboard WS: Claude client initialized via failover (endpoint: %s)",
                    api_failover.active_endpoint.value,
                )
                # Register listener for auto-failover notifications
                api_failover.add_listener(self._on_endpoint_changed)
                self._failover_listener_registered = True
            except Exception as e:
                logger.warning("⚠️ Dashboard WS: failover init failed: %s, falling back", e)
                if CLAUDE_API_KEY:
                    import anthropic

                    self.claude_client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
                    self._claude_client_owned = True
        elif CLAUDE_API_KEY:
            try:
                import anthropic

                self.claude_client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
                self._claude_client_owned = True
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
            # Validate TLS configuration BEFORE allocating the AppRunner so the
            # missing-cert early-return below cannot orphan a set-up runner
            # (runner.setup() must always be paired with runner.cleanup()).
            tls_cert_path = ""
            tls_key_path = ""
            if WS_REQUIRE_TLS:
                tls_cert_path = os.getenv("WS_TLS_CERT_PATH", "").strip()
                tls_key_path = os.getenv("WS_TLS_KEY_PATH", "").strip()
                if not tls_cert_path or not tls_key_path:
                    logger.error(
                        "❌ WS_REQUIRE_TLS is enabled but WS_TLS_CERT_PATH / WS_TLS_KEY_PATH are not set"
                    )
                    return False

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
                import ssl

                # ``ssl.create_default_context(Purpose.CLIENT_AUTH)`` is the
                # modern way to build a server-side TLS context. The
                # previous ``SSLContext(PROTOCOL_TLS_SERVER)`` constructor
                # is deprecated since Python 3.10 (PEP 644) and emits a
                # DeprecationWarning. ``create_default_context`` also
                # applies the secure-by-default cipher / option set
                # (TLS 1.2+, server cipher preference, no compression).
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
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
            # site.start() (bind) or the TLS context build can raise AFTER
            # runner.setup(); _running is still False so stop() never runs
            # runner.cleanup(). Tear the half-initialized server down here so the
            # Application/AppRunner are not orphaned across restart attempts.
            await self._cleanup_failed_start()
            return False

    async def _cleanup_failed_start(self) -> None:
        """Best-effort teardown after a failed start() (pairs runner.setup())."""
        with contextlib.suppress(Exception):
            if self.site is not None:
                await self.site.stop()
        with contextlib.suppress(Exception):
            if self.runner is not None:
                await self.runner.cleanup()
        self.site = None
        self.runner = None
        self.app = None

    async def _ensure_port_available(self) -> None:
        """Wait (up to 5s) for the port to become free; never kills any process.

        Polls the port with a short socket connect check. If it stays in use
        after the wait, logs a warning and returns so the subsequent bind
        fails gracefully. (Auto-killing was deliberately removed to avoid
        ever terminating an unrelated process — see the inline note below.)
        """
        import socket

        def _probe() -> int:
            # connect_ex with a 1s timeout can block the full second when the
            # port is filtered/dropping (not just refused). Run it off the
            # event loop via run_in_executor so the up-to-1s wait never stalls
            # the loop the Discord bot shares.
            # Family must match the host: dashboard_config accepts "::1" as a
            # valid localhost bind, and connect_ex on an AF_INET socket raises
            # socket.gaierror for an IPv6 literal (name-resolution errors
            # RAISE; only connect errors come back as codes) — which start()'s
            # broad except turned into "dashboard failed to start" before the
            # bind was even attempted.
            family = socket.AF_INET6 if ":" in WS_HOST else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                try:
                    return sock.connect_ex((WS_HOST, WS_PORT))
                except OSError:
                    # Unresolvable/unprobeable host (e.g. gaierror) — treat as
                    # "not in use" and let the real bind report the truth.
                    return 1

        loop = asyncio.get_running_loop()

        # Quick check if port is in use
        result = await loop.run_in_executor(None, _probe)

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
                result = await loop.run_in_executor(None, _probe)

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
            # Bound the wait so a task that ignores CancelledError (e.g. a
            # blocked subprocess in the CLI handler) can't hang shutdown
            # forever — mirrors the per-client disconnect path's 5s cap.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*self._background_tasks, return_exceptions=True),
                    timeout=5.0,
                )
        self._background_tasks.clear()

        # Kill any speculative pre-warm `claude` processes — they're detached
        # into their own process group, so they'd otherwise linger (blocked on
        # stdin) after the bot exits.
        with contextlib.suppress(Exception):
            _shutdown_cli_prewarm()

        # Detach the failover listener so a server restart doesn't leave a
        # bound-method ref to the previous server instance — without this
        # the old self stays reachable forever and any future endpoint
        # change still tries to push to a dead WS.
        if API_FAILOVER_AVAILABLE and self._failover_listener_registered:
            try:
                api_failover.remove_listener(self._on_endpoint_changed)
            except Exception:
                logger.debug("Failed to remove failover listener", exc_info=True)
            self._failover_listener_registered = False

        # Close all client connections (tolerate individual failures, with a
        # timeout so an unresponsive client can't stall shutdown).
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(
                    ws.close(code=1001, message=b"Server shutting down"),
                    timeout=2.0,
                )
            except Exception:
                # ``Exception`` already catches ``asyncio.TimeoutError`` (and
                # ``builtins.TimeoutError`` since 3.11 where they were unified).
                pass
        self.clients.clear()

        # Close the Anthropic SDK client to release its underlying httpx
        # connection pool (otherwise reload leaves sockets open) — but ONLY
        # when this instance owns it. The failover manager's pooled client is
        # the SAME object logic.py uses for Discord replies; closing it here
        # (graceful_shutdown stops the dashboard FIRST) killed in-flight
        # Discord streams with "client has been closed" and left the
        # manager's cache holding a dead client.
        if self.claude_client is not None and self._claude_client_owned:
            try:
                close_coro = getattr(self.claude_client, "close", None)
                if close_coro is not None:
                    result = close_coro()
                    if asyncio.iscoroutine(result):
                        await asyncio.wait_for(result, timeout=2.0)
            except Exception:
                logger.debug("Failed to close Claude client cleanly", exc_info=True)
        elif self.claude_client is not None:
            logger.debug("Skipping close of failover-manager-owned Claude client")

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

        # Authentication: Require API key from environment or query param.
        # ``.strip()`` defends against leading/trailing whitespace in .env
        # values — without it ``hmac.compare_digest`` would silently fail
        # all auth attempts even when the user's client sent the right
        # token, with no actionable signal in the log.
        expected_token = os.getenv("DASHBOARD_WS_TOKEN", "").strip()
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

        # Hard lockout gate, decoupled from the rolling fail-count window so the
        # full _AUTH_FAIL_LOCKOUT is actually enforced. Previously the lockout was
        # tied to the same deque the 60s window prunes, so all timestamps aged out
        # at ~60s and released the gate — the advertised 5-minute lockout never
        # held and the unlock_in<=0 reset branch was unreachable.
        lockout_until = self._auth_lockouts.get(client_ip)
        if lockout_until is not None:
            if now < lockout_until:
                unlock_in = lockout_until - now
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
            # Lockout expired — clear it and the stale failure bucket.
            self._auth_lockouts.pop(client_ip, None)
            self._auth_failures.pop(client_ip, None)

        # Maintain the windowed failure counter (drives WHEN a lockout starts).
        # ``deque.popleft`` is O(1) per drop; a list-comp here dominated CPU
        # under a brute-force flood.
        prior = self._auth_failures.get(client_ip)
        if prior is not None:
            cutoff_age = self._AUTH_FAIL_WINDOW
            while prior and now - prior[0] >= cutoff_age:
                prior.popleft()
        # Periodic dict-cleanup: drop empty or fully-aged-out fail buckets and
        # expired lockouts so neither grows unbounded across days/weeks of
        # attacker reconnects.
        if len(self._auth_failures) > 1024:
            stale_keys = [
                k
                for k, v in self._auth_failures.items()
                if not v or now - v[-1] >= self._AUTH_FAIL_WINDOW
            ]
            for k in stale_keys:
                self._auth_failures.pop(k, None)
        if len(self._auth_lockouts) > 1024:
            for k in [k for k, until in self._auth_lockouts.items() if now >= until]:
                self._auth_lockouts.pop(k, None)

        # Track whether client authenticated at upgrade time.
        # The outer ``if expected_token:`` wrapper here is dead defense —
        # the empty-token branch returned 401 above (see ``if not
        # expected_token`` early return), so ``expected_token`` is always
        # truthy below.
        _upgrade_authenticated = False
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
                    # Compare as bytes — str compare_digest raises TypeError
                    # on ANY non-ASCII input, turning a crafted token into a
                    # 500 (bypassing the fail bucket) and breaking auth
                    # entirely for a non-ASCII DASHBOARD_WS_TOKEN.
                    auth_match = hmac.compare_digest(
                        parts[1].encode("utf-8"), expected_token.encode("utf-8")
                    )
            token_match = (
                hmac.compare_digest(query_token.encode("utf-8"), expected_token.encode("utf-8"))
                if query_token
                else False
            )
            if not auth_match and not token_match:
                # Use a fresh ``time.monotonic()`` here rather than
                # the ``now`` captured at function entry — a slow
                # filesystem cert load (or a Python GIL stall under
                # heavy load) can leave ``now`` minutes stale,
                # making aged-out fail entries look fresh and
                # mis-tripping the lockout window.
                fail_bucket = self._auth_failures.get(client_ip)
                if fail_bucket is None:
                    fail_bucket = deque(maxlen=self._AUTH_FAIL_THRESHOLD)
                    self._auth_failures[client_ip] = fail_bucket
                fail_bucket.append(time.monotonic())
                # Threshold reached → start the full-duration lockout.
                if len(fail_bucket) >= self._AUTH_FAIL_THRESHOLD:
                    self._auth_lockouts[client_ip] = time.monotonic() + self._AUTH_FAIL_LOCKOUT
                logger.warning(
                    "⚠️ Rejected WebSocket connection: invalid auth token (from %s)", peername
                )
                return web.Response(status=401, text="Unauthorized: Invalid token")
            else:
                _upgrade_authenticated = True
                # Successful auth — clear the bucket AND any lockout so a
                # legitimate user who fat-fingered the token isn't locked out.
                self._auth_failures.pop(client_ip, None)
                self._auth_lockouts.pop(client_ip, None)

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

        # When a browser opens a cross-origin WebSocket it ALWAYS sends an Origin
        # header, and JS cannot forge it — so the Origin is authoritative for any
        # browser client and must be on the allowlist. The Host header is not a
        # substitute: for a direct connection to this local server the browser
        # sends the real target authority (127.0.0.1:<port>), so Host is
        # unconditionally "localhost" and OR-ing it in let any cross-origin page
        # (e.g. https://evil.com hitting ws://127.0.0.1) pass. Only fall back to
        # the Host check when there is no Origin at all (native/non-browser
        # clients such as the Tauri shell or a CLI, which JS-based attackers
        # cannot impersonate). The mandatory DASHBOARD_WS_TOKEN still backstops
        # every sensitive action.
        connection_allowed = origin_allowed if origin else host_allowed

        if not connection_allowed:
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

        # Frame cap sized for the WORST legal payload the handlers themselves
        # accept: MAX_DOCUMENTS docs + MAX_IMAGES images per message, all
        # arriving as base64 data URLs inside one JSON frame (4/3 inflation),
        # plus content and headroom for the JSON envelope/history. The
        # previous cap was computed from DECODED sizes of a SINGLE document +
        # image, so e.g. one 32 MB document (≈44.7 MB encoded) plus any image
        # blew the frame limit — aiohttp killed the socket with
        # MESSAGE_TOO_BIG and no application-level error ever reached the UI.
        # Localhost-only single-user dashboard, so the large transient buffer
        # is acceptable; the per-attachment checks still enforce real limits.
        max_decoded = (
            self.MAX_DOCUMENTS * self.MAX_DOCUMENT_SIZE_BYTES
            + self.MAX_IMAGES * self.MAX_IMAGE_SIZE_BYTES
        )
        max_frame = (max_decoded * 4) // 3 + self.MAX_CONTENT_LENGTH * 4 + 4 * 1024 * 1024
        ws = web.WebSocketResponse(max_msg_size=max_frame)
        await ws.prepare(request)

        self.clients.add(ws)
        client_id = str(uuid.uuid4())[:8]
        logger.info("👋 Dashboard client connected: %s", client_id)

        # Mark as authenticated if validated at upgrade time. The
        # ``not expected_token`` branch is unreachable — the early
        # return at line ~480 already rejects with 401 when the token
        # is empty, so by the time we get here ``expected_token`` is
        # guaranteed truthy. Drop the dead ``or not expected_token``
        # so a future reader doesn't think the no-token path is
        # supported.
        if _upgrade_authenticated:
            self._authenticated_clients.add(client_id)
            self._authenticated_ws.add(ws)

        try:
            # Send welcome message. ``needs_auth`` simplifies similarly:
            # ``expected_token`` is always truthy here, so it's just
            # ``not _upgrade_authenticated``.
            needs_auth = not _upgrade_authenticated
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
            # ``api_failover.get_status()`` exposes endpoint URLs, total
            # request counts, and the last error message — none of which
            # an unauthenticated client should see. Defer until after auth
            # completes; clients that need it can re-request via the
            # ``health_check_endpoint`` handler post-auth.
            if API_FAILOVER_AVAILABLE and not needs_auth:
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
                    # Pre-auth message size cap. The connection-wide
                    # max_msg_size is sized for chat payloads (hundreds of
                    # MB) which is far too generous for an unauthenticated
                    # client. NOTE: this is a post-hoc check — aiohttp has
                    # already buffered the full frame by the time we see it,
                    # so the cap limits what gets PROCESSED pre-auth, not
                    # what can be buffered; the localhost origin/host gate is
                    # what actually bounds that exposure.
                    #
                    # Checked BEFORE the TEXT filter so it actually covers
                    # BINARY frames: the old order `continue`d on non-TEXT
                    # before reaching the cap, leaving the bytes/bytearray
                    # arm unreachable and letting an unauthenticated client
                    # stream large BINARY frames for the whole auth window.
                    if (
                        isinstance(deadline_msg.data, (str, bytes, bytearray))
                        and len(deadline_msg.data) > 4096
                    ):
                        logger.warning(
                            "⚠️ Pre-auth message from %s exceeds 4 KiB cap (%d bytes)",
                            client_id,
                            len(deadline_msg.data),
                        )
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
                    try:
                        auth_data = json.loads(deadline_msg.data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(auth_data, dict):
                        continue
                    msg_type = auth_data.get("type")
                    if msg_type == "ping":
                        # Allow ping before auth — just keep waiting.
                        with contextlib.suppress(Exception):
                            await ws.send_json({"type": "pong"})
                        continue
                    if msg_type == "auth":
                        token = auth_data.get("token", "")
                        # bytes compare — see upgrade-time auth note (str
                        # compare_digest raises TypeError on non-ASCII).
                        if hmac.compare_digest(
                            str(token).encode("utf-8"), expected_token.encode("utf-8")
                        ):
                            self._authenticated_clients.add(client_id)
                            self._authenticated_ws.add(ws)
                            auth_received = True
                            # Successful auth — clear the per-IP fail bucket and
                            # any lockout so a legitimate user who fat-fingered
                            # their token a couple times isn't locked out.
                            self._auth_failures.pop(client_ip, None)
                            self._auth_lockouts.pop(client_ip, None)
                            logger.debug("✅ Client %s authenticated via message", client_id)
                        else:
                            # Record this attempt against the IP bucket so
                            # the upgrade-time check on the NEXT connection
                            # can reject before the WebSocket handshake.
                            fail_bucket = self._auth_failures.get(client_ip)
                            if fail_bucket is None:
                                fail_bucket = deque(maxlen=self._AUTH_FAIL_THRESHOLD)
                                self._auth_failures[client_ip] = fail_bucket
                            fail_bucket.append(time.monotonic())
                            # Threshold reached → start the full-duration lockout.
                            if len(fail_bucket) >= self._AUTH_FAIL_THRESHOLD:
                                self._auth_lockouts[client_ip] = (
                                    time.monotonic() + self._AUTH_FAIL_LOCKOUT
                                )
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
                        if not isinstance(data, dict):
                            await ws.send_json(
                                {"type": "error", "message": "Invalid message format"}
                            )
                            continue
                        msg_id = str(uuid.uuid4())[:8]
                        msg_type = data.get("type")
                        if not isinstance(msg_type, str):
                            # An unhashable JSON "type" (array/object) raised
                            # TypeError on the RATE_EXEMPT set lookup below,
                            # escaping the JSON-only inner except to the outer
                            # handler and tearing down the WHOLE connection —
                            # cancelling the client's in-flight AI tasks. A
                            # hashable non-string just took the unknown-type
                            # path; normalize both to a clean error frame.
                            await ws.send_json(
                                {"type": "error", "message": "Invalid message format"}
                            )
                            continue

                        # Rate limiting per client — exempts the read-only
                        # message types defined at class level.
                        rate_slot_consumed = False
                        if msg_type not in self.RATE_EXEMPT_MESSAGE_TYPES:
                            now = asyncio.get_running_loop().time()
                            times = self._client_message_times.get(client_id)
                            if times is None:
                                times = deque(maxlen=self.RATE_LIMIT_MESSAGES_PER_MINUTE)
                                self._client_message_times[client_id] = times
                            # ``popleft`` is O(1) per drop; the previous
                            # list-comp + reassign was O(n) per inbound
                            # message and dominated CPU under a flood.
                            while times and now - times[0] >= 60:
                                times.popleft()
                            if len(times) >= self.RATE_LIMIT_MESSAGES_PER_MINUTE:
                                # "scope" echoes the rejected request type so
                                # the frontend can attribute the error (e.g. a
                                # rate-limited edit_ai_history_message must
                                # unstick the history editor, not tear down an
                                # unrelated in-flight chat stream).
                                await ws.send_json(
                                    {
                                        "type": "error",
                                        "message": "Rate limit exceeded. Please wait.",
                                        "scope": msg_type,
                                    }
                                )
                                continue
                            times.append(now)
                            rate_slot_consumed = True
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
                            # Per-client cap on simultaneously-running AI
                            # tasks. Without this a single authenticated
                            # client can fire 100+ ``message`` frames in a
                            # row and spawn that many concurrent
                            # ``claude -p`` subprocesses before any
                            # downstream rate limit applies (the
                            # ``_client_inflight`` cap inside
                            # handle_chat_message only sees the task
                            # AFTER create_task). Reject before spawning.
                            # The cap matches the inner ``_client_inflight
                            # >= 2`` guard so a frame can't pass here only to
                            # be rejected inside handle_message — that path
                            # spawned a task and silently burned a rate-limit
                            # slot (the inner guard doesn't roll it back).
                            current_inflight = sum(
                                1
                                for t, cid in self._client_tasks.items()
                                if cid == client_id and not t.done()
                            )
                            if current_inflight >= self.MAX_INFLIGHT_PER_CLIENT:
                                # Roll back the rate-limit slot consumed at
                                # ``times.append(now)`` above: this request is
                                # rejected before any work is spawned, so it must
                                # not burn the client's per-minute budget — a UI
                                # that auto-retries against the concurrency cap
                                # would otherwise exhaust its 30/min allowance on
                                # never-serviced requests and self-lock-out for
                                # up to a minute.
                                #
                                # Structural rollback: pop the slot we appended
                                # for THIS frame (tracked by rate_slot_consumed)
                                # rather than relying on the deque tail being
                                # bit-identical to ``now`` — no await runs
                                # between the append and here today, but a flag
                                # survives a future refactor that adds one.
                                if rate_slot_consumed:
                                    _times = self._client_message_times.get(client_id)
                                    if _times:
                                        _times.pop()
                                await ws.send_json(
                                    {
                                        "type": "error",
                                        "message": "Too many concurrent requests in flight",
                                    }
                                )
                                continue
                            task = asyncio.create_task(
                                self.handle_message(ws, data, client_id, msg_id=msg_id)
                            )
                            # Map task → originating client so disconnect can
                            # cancel only this client's in-flight tasks.
                            self._client_tasks[task] = client_id
                            self._background_tasks.add(task)
                            # Bound method (not a per-frame closure) — it
                            # captures nothing message-specific, so reusing one
                            # callback avoids allocating a fresh function object
                            # on every inbound chat/ai_edit frame.
                            task.add_done_callback(self._on_background_task_done)
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
            self._authenticated_ws.discard(ws)
            self._client_message_times.pop(client_id, None)
            self._client_inflight.pop(client_id, None)
            self._client_auth_failures.pop(client_id, None)
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
            # The cancelled tasks' finally blocks decrement (re-creating) the
            # _client_inflight entry popped above, leaving a {client_id: 0} entry.
            # Pop again now they've unwound so it can't leak permanently (the key
            # is a fresh per-connection uuid and this dict has no periodic prune).
            self._client_inflight.pop(client_id, None)
            logger.info("👋 Dashboard client disconnected: %s", client_id)

        return ws

    def _on_background_task_done(self, t: asyncio.Task[Any]) -> None:
        """Done-callback for dispatched chat/ai_edit tasks.

        Hoisted out of the read loop so it is allocated once instead of per
        inbound frame. Drops the task from the bookkeeping sets and surfaces
        uncaught exceptions explicitly — without this, a handler error inside
        handle_message disappears with only Python's "Task exception was never
        retrieved" warning at GC time, which often loses the stack trace.
        """
        self._background_tasks.discard(t)
        self._client_tasks.pop(t, None)
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.error(
                    "Background WS task failed",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

    async def handle_message(
        self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = "", msg_id: str = ""
    ) -> None:
        """Handle incoming WebSocket messages."""
        msg_type = data.get("type")

        # Management operations (everything that is NOT a chat turn / chat-pane
        # message mutation / AI-history op) get their error frames tagged with
        # scope=<wire msg type> via _scoped_error_ws. The client uses the scope
        # to show a toast WITHOUT running its chat-stream teardown — a failed
        # sidebar/settings operation while a response streams must not kill the
        # live stream (chat-manager.ts CHAT_ERROR_SCOPES). Matches the rate
        # limiter, which already tags rejections with the same value.
        if msg_type == "new_conversation":
            await self.handle_new_conversation(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "message":
            # Redundant backstop: the read-loop gate already caps not-done
            # tasks at MAX_INFLIGHT_PER_CLIENT before spawning, so at most that
            # many handle_message tasks exist and this branch cannot actually
            # fire on the create_task path. Kept (tied to the same constant)
            # so a direct caller of handle_message still gets the guard.
            inflight = self._client_inflight.get(client_id, 0)
            if inflight >= self.MAX_INFLIGHT_PER_CLIENT:
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
            await self.handle_list_conversations(_scoped_error_ws(ws, msg_type))
        elif msg_type == "load_conversation":
            await self.handle_load_conversation(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "delete_conversation":
            await self.handle_delete_conversation(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "star_conversation":
            await self.handle_star_conversation(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "rename_conversation":
            await self.handle_rename_conversation(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "export_conversation":
            await self.handle_export_conversation(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "edit_message":
            await handle_edit_message(ws, data)
        elif msg_type == "ai_edit_message":
            # AI self-edit: AI rewrites its own message based on user instruction.
            # Redundant backstop — see the "message" branch above: the read-loop
            # gate enforces MAX_INFLIGHT_PER_CLIENT before spawning, so this
            # cannot fire on the create_task path. Tied to the same constant.
            inflight = self._client_inflight.get(client_id, 0)
            if inflight >= self.MAX_INFLIGHT_PER_CLIENT:
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
        elif msg_type == "list_ai_channels":
            await handle_list_ai_channels(ws)
        elif msg_type == "load_ai_history":
            await handle_load_ai_history(ws, data)
        elif msg_type == "edit_ai_history_message":
            await handle_edit_ai_history_message(ws, data)
        elif msg_type == "delete_ai_history_message":
            await handle_delete_ai_history_message(ws, data)
        elif msg_type == "restore_ai_history_message":
            # Undo of a history delete — a write op, so it stays rate-limited
            # like edit/delete (NOT in RATE_EXEMPT_MESSAGE_TYPES).
            await handle_restore_ai_history_message(ws, data)
        elif msg_type == "pin_message":
            await handle_pin_message(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "like_message":
            await handle_like_message(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "add_tag":
            await handle_add_conversation_tag(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "remove_tag":
            await handle_remove_conversation_tag(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "list_tags":
            await handle_list_all_tags(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "list_conversation_documents":
            await handle_list_conversation_documents(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "delete_document_memory":
            await handle_delete_document_memory(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "get_document_memory_content":
            await handle_get_document_memory_content(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "update_document_memory":
            await handle_update_document_memory(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "get_profile":
            await self.handle_get_profile(_scoped_error_ws(ws, msg_type))
        elif msg_type == "save_profile":
            await self.handle_save_profile(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "auth":
            # Re-auth or late auth via message — already handled at connect deadline,
            # but allow re-validation for token rotation.
            token = data.get("token", "")
            # ``.strip()`` matches the initial-handshake reader at line 498 —
            # without symmetry, whitespace in .env would make re-auth diverge
            # from initial auth (initial succeeds, re-auth fails or vice versa).
            expected = os.getenv("DASHBOARD_WS_TOKEN", "").strip()
            if not expected:
                # Reject empty-token re-auth: server with no token configured
                # has already rejected the original handshake; a re-auth that
                # would silently grant access if expected becomes "" is unsafe.
                return
            # bytes compare — str compare_digest raises TypeError on non-ASCII
            if not hmac.compare_digest(str(token).encode("utf-8"), expected.encode("utf-8")):
                fails = self._client_auth_failures.get(client_id, 0) + 1
                self._client_auth_failures[client_id] = fails
                logger.warning(
                    "⚠️ Invalid auth token from client %s (failure %d/%d)",
                    client_id,
                    fails,
                    self._MAX_REAUTH_FAILURES,
                )
                await ws.send_json({"type": "error", "message": "Invalid auth token"})
                if fails >= self._MAX_REAUTH_FAILURES:
                    # Hard-close so an attacker can't keep guessing on the
                    # same socket. The connect-deadline IP throttle then
                    # takes over for any reconnect attempts.
                    logger.warning(
                        "⚠️ Closing WS for client %s after %d failed re-auth attempts",
                        client_id,
                        fails,
                    )
                    await ws.close(code=4401, message=b"Too many failed auth attempts")
            else:
                self._authenticated_clients.add(client_id)
                self._authenticated_ws.add(ws)
                self._client_auth_failures.pop(client_id, None)
                logger.debug("✅ Client %s re-authenticated via message", client_id)
        elif msg_type == "update_provider":
            await self.handle_update_provider(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "get_api_endpoints":
            await self.handle_get_api_endpoints(_scoped_error_ws(ws, msg_type))
        elif msg_type == "switch_api_endpoint":
            await self.handle_switch_api_endpoint(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "health_check_endpoint":
            await self.handle_health_check_endpoint(_scoped_error_ws(ws, msg_type), data)
        elif msg_type == "ping":
            await ws.send_json({"type": "pong"})
        else:
            await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

    async def handle_new_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Create a new conversation."""
        role_preset = data.get("role_preset", "general")
        thinking_enabled = data.get("thinking_enabled", False)
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)

        # isinstance first: an unhashable role_preset (JSON array/object)
        # would raise TypeError on the dict membership test and tear down the
        # whole connection instead of falling back to the default preset.
        if not isinstance(role_preset, str) or role_preset not in DASHBOARD_ROLE_PRESETS:
            role_preset = "general"

        # Validate the provider like handle_update_provider does — but fall
        # back to the default instead of rejecting. A stale client value (e.g.
        # "gemini" persisted in localStorage before the server switched to
        # CLAUDE_BACKEND=cli, where VALID_AI_PROVIDERS narrows to {"claude"})
        # used to be persisted verbatim, creating a conversation whose every
        # subsequent message frame is rejected with INVALID_PROVIDER.
        if not isinstance(ai_provider, str) or ai_provider not in VALID_AI_PROVIDERS:
            logger.warning(
                "new_conversation carried invalid ai_provider %r — falling back to %r",
                ai_provider,
                DEFAULT_AI_PROVIDER,
            )
            ai_provider = DEFAULT_AI_PROVIDER

        preset = DASHBOARD_ROLE_PRESETS[role_preset]
        conversation_id = str(uuid.uuid4())

        # Save to database if available. Track success so the client knows
        # whether the conversation is durable: if the DB write fails, the
        # in-memory conversation still works this session but the FK-bound
        # dashboard_messages saves will also fail and nothing survives a reload.
        persisted = True
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
                persisted = False

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
                "persisted": persisted,
            }
        )

    async def handle_chat_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle incoming chat message and stream response.
        Routes to Gemini or Claude handler based on ai_provider field.
        For Claude, further routes to the CLI subprocess backend when
        CLAUDE_BACKEND=cli (uses Claude Code subscription instead of API key).
        """
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)
        # isinstance first: an unhashable JSON value (array/object) would raise
        # TypeError on the frozenset membership test — killing the background
        # task (or tearing down the connection) instead of a clean error frame.
        if not isinstance(ai_provider, str) or ai_provider not in VALID_AI_PROVIDERS:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_PROVIDER",
                    "message": (
                        f"Invalid ai_provider: {ai_provider!r} "
                        f"(expected one of {sorted(VALID_AI_PROVIDERS)})"
                    ),
                }
            )
            return

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
                # Use latest client from failover manager (may have switched).
                # ``get_client()`` can raise ``RuntimeError("No API endpoint
                # configured")`` if all endpoints were dropped at runtime —
                # surface that to the client instead of crashing the WS
                # handler with a backend traceback.
                if API_FAILOVER_AVAILABLE:
                    try:
                        self.claude_client = api_failover.get_client()
                    except RuntimeError as cfg_err:
                        logger.error("API failover get_client failed: %s", cfg_err)
                        with contextlib.suppress(Exception):
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": "ไม่มี API endpoint ที่พร้อมใช้งาน",
                                }
                            )
                        return
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
            # ai_provider=claude but neither backend is configured. Surface
            # the swap so the user knows Claude wasn't actually used, then
            # fall through to Gemini. Previously this was silent — a user
            # selecting Claude got Gemini output with no indication the
            # provider had been switched, which is especially confusing for
            # sensitive RP/long-context conversations where the choice matters.
            await ws.send_json(
                {
                    "type": "info",
                    "code": "PROVIDER_FALLBACK",
                    "message": (
                        "ℹ️ Claude backend is not configured; replying with Gemini instead."
                    ),
                }
            )

        # If Gemini also isn't configured (API_AI_DISABLED narrows
        # VALID_AI_PROVIDERS to {"claude"} and the CLI bin disappeared at
        # runtime), ``self.gemini_client`` is None and the handler below
        # would crash inside the SDK with no user-facing message. Surface
        # a clean error instead.
        if self.gemini_client is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "NO_BACKEND_AVAILABLE",
                    "message": (
                        "ไม่มี AI backend พร้อมใช้งาน (Claude CLI/SDK ล้มเหลว และ Gemini ไม่ได้ตั้งค่า)"
                    ),
                }
            )
            return

        await _handle_chat_message(
            ws,
            data,
            self.gemini_client,
            max_content_length=self.MAX_CONTENT_LENGTH,
            max_history_messages=self.MAX_HISTORY_MESSAGES,
            max_images=self.MAX_IMAGES,
            max_image_size_bytes=self.MAX_IMAGE_SIZE_BYTES,
            max_documents=self.MAX_DOCUMENTS,
            stream_timeout=self.STREAM_TIMEOUT,
        )

    async def handle_ai_edit_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle AI self-edit request.
        Routes to Gemini or Claude handler based on ai_provider field.
        """
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)
        # isinstance first: an unhashable JSON value (array/object) would raise
        # TypeError on the frozenset membership test — killing the background
        # task (or tearing down the connection) instead of a clean error frame.
        if not isinstance(ai_provider, str) or ai_provider not in VALID_AI_PROVIDERS:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_PROVIDER",
                    "message": (
                        f"Invalid ai_provider: {ai_provider!r} "
                        f"(expected one of {sorted(VALID_AI_PROVIDERS)})"
                    ),
                }
            )
            return

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
            # Same silent-fallback footgun as ``handle_chat_message``; surface
            # the swap before falling through to Gemini.
            await ws.send_json(
                {
                    "type": "info",
                    "code": "PROVIDER_FALLBACK",
                    "message": ("ℹ️ Claude backend is not configured; editing with Gemini instead."),
                }
            )

        # Mirror ``handle_chat_message``'s guard: if Claude fell through and
        # Gemini is also unconfigured, ``self.gemini_client`` is None and the
        # handler would crash inside the SDK with no user-facing message.
        if self.gemini_client is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "NO_BACKEND_AVAILABLE",
                    "message": (
                        "ไม่มี AI backend พร้อมใช้งาน (Claude CLI/SDK ล้มเหลว และ Gemini ไม่ได้ตั้งค่า)"
                    ),
                }
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
        # Delete FIRST: delete_session_file inside the handler needs the
        # session-map entry to find and unlink the .jsonl transcript.
        # Resetting before the delete popped that entry, so the transcript
        # cleanup was a guaranteed no-op and deleted conversations' content
        # lingered on disk under <config>/projects/.
        await handle_delete_conversation(ws, data)
        # Then forget the CLI session — this drops the per-conversation send
        # lock, which delete_session_file does not (the map entry is already
        # popped by delete_session_file, so reset_session's pop is a no-op).
        conv_id = data.get("id")
        if isinstance(conv_id, str) and conv_id:
            _reset_cli_session(conv_id)

    async def handle_star_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_star_conversation(ws, data)

    async def handle_rename_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_rename_conversation(ws, data)

    async def handle_export_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_export_conversation(ws, data)

    async def handle_get_profile(self, ws: WebSocketResponse) -> None:
        await handle_get_profile(ws)

    async def handle_save_profile(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        await handle_save_profile(ws, data)

    async def handle_update_provider(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Update the AI provider for a conversation."""
        conversation_id = data.get("conversation_id")
        ai_provider = data.get("ai_provider", DEFAULT_AI_PROVIDER)
        # Use ``VALID_AI_PROVIDERS`` (frozenset from dashboard_config)
        # instead of a hardcoded literal tuple. The chat/edit handlers
        # already use it, so this site was the lone drift point — when
        # a future provider gets added (or ``API_AI_DISABLED`` narrows
        # the set to claude-only), the literal here would silently
        # accept a now-invalid provider name.
        # isinstance first: an unhashable JSON value (array/object) would raise
        # TypeError on the frozenset membership test — killing the background
        # task (or tearing down the connection) instead of a clean error frame.
        if not isinstance(ai_provider, str) or ai_provider not in VALID_AI_PROVIDERS:
            await ws.send_json(
                {
                    "type": "error",
                    "message": (
                        f"Invalid ai_provider: {ai_provider!r} "
                        f"(expected one of {sorted(VALID_AI_PROVIDERS)})"
                    ),
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
        except (ValueError, TypeError):
            # ``TypeError`` covers non-str ``target`` values — a buggy or
            # malicious client could send a dict / list, which would crash
            # the handler instead of returning a clean 4xx-equivalent.
            await ws.send_json({"type": "error", "message": f"Invalid endpoint: {target}"})
            return

        success = await api_failover.switch_endpoint(ep_type, reason="dashboard manual switch")
        if success:
            # Recreate Claude client with new endpoint. ``get_client`` raises
            # RuntimeError if every endpoint is mis-configured — surface that
            # as an error frame instead of letting it kill the WS task with an
            # unhandled exception (previously the only sign was a stack trace
            # in the bot log).
            try:
                self.claude_client = api_failover.get_client()
            except RuntimeError as exc:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Cannot activate {target}: {exc}",
                    }
                )
                return
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
            except (ValueError, TypeError):
                # See companion handler above: a non-str ``target`` (dict /
                # list / int) would crash with TypeError otherwise.
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
        # Refresh our own Claude client. ``get_client`` raises RuntimeError if
        # every endpoint is mis-configured — log and continue rather than let
        # the broadcast callback crash the auto-switch path; clients still
        # get the notification, just without our local client refresh.
        if API_FAILOVER_AVAILABLE:
            try:
                self.claude_client = api_failover.get_client()
            except RuntimeError:
                logger.exception(
                    "api_failover.get_client() raised during endpoint change to %s",
                    new_endpoint.value,
                )

        # Non-sensitive frame for clients still inside the auth-handshake
        # window: just the fact that a switch happened. get_status() additionally
        # exposes endpoint URLs, request counts and the last error message —
        # withheld from unauthenticated clients, mirroring the welcome-message
        # needs_auth gate.
        safe_notification = {
            "type": "api_endpoint_switched",
            "endpoint": new_endpoint.value,
            "reason": reason,
        }
        full_notification = {**safe_notification, **api_failover.get_status()}
        # Broadcast to all connected clients in parallel. Sequential
        # awaits made the worst case = N × 2s timeout, so 20 stuck
        # clients could block the failover-notify path for 40 seconds
        # while real chat tasks waited on the same lock.
        # ``_send_one`` catches every per-client exception internally
        # and returns the exception object as its result, so the
        # gather is invoked with ``return_exceptions=False`` (nothing
        # can actually escape the inner ``try``). We still inspect each
        # result individually below to drop dead WS handles.
        clients_snapshot = list(self.clients)

        async def _send_one(ws_client: Any) -> Any:
            payload = (
                full_notification if ws_client in self._authenticated_ws else safe_notification
            )
            try:
                await asyncio.wait_for(ws_client.send_json(payload), timeout=2.0)
                return None
            except (TimeoutError, ConnectionError, RuntimeError) as exc:
                return exc
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("Broadcast send failed for one client: %s", exc)
                return exc

        results = await asyncio.gather(
            *(_send_one(c) for c in clients_snapshot),
            return_exceptions=False,
        )
        for ws_client, outcome in zip(clients_snapshot, results, strict=False):
            if outcome is None:
                continue
            # Evict only on definite-dead errors. A bare 2s send timeout on a
            # momentarily slow but live client must NOT drop the socket from
            # bookkeeping — that broke MAX_CLIENTS accounting, left the ws in
            # _authenticated_ws (still receiving sensitive broadcasts), and
            # stop() no longer closed it on shutdown.
            is_dead = isinstance(outcome, (ConnectionError, RuntimeError)) or bool(
                getattr(ws_client, "closed", False)
            )
            if not is_dead:
                continue
            self.clients.discard(ws_client)
            self._authenticated_ws.discard(ws_client)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws_client.close(), timeout=2.0)


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
