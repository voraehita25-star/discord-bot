"""
WebSocket Server for Dashboard AI Chat.

Provides real-time AI chat functionality for the native dashboard.
Uses aiohttp for WebSocket server with streaming support.

Features:
- Google Search grounding
- Image/File upload support
- User identity awareness
- Long-term memory across conversations
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web
from google import genai
from google.genai import types

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# Import Faust persona and unrestricted mode framing
try:
    from ..data.faust_data import ENI_ESCALATION_FRAMING, FAUST_PERSONA

    FAUST_AVAILABLE = True
except ImportError:
    FAUST_AVAILABLE = False
    FAUST_PERSONA = "You are Faust, a helpful AI assistant."
    ENI_ESCALATION_FRAMING = ""

# Import database
try:
    from utils.database import Database

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    Database = None

# ============================================================================
# Role Presets
# ============================================================================

DASHBOARD_ROLE_PRESETS = {
    "general": {
        "name": "General Assistant",
        "emoji": "🤖",
        "system_instruction": """You are a helpful AI assistant.
Respond in the same language the user uses (Thai or English).
Be concise, helpful, and friendly.
For simple questions, give brief answers (1-3 sentences).
For complex topics, provide detailed but well-organized responses.""",
        "color": "#22d3ee",  # Cyan
    },
    "faust": {
        "name": "Faust",
        "emoji": "👻",
        "system_instruction": FAUST_PERSONA
        if FAUST_AVAILABLE
        else "You are Faust, a genius AI assistant who speaks in third person.",
        "color": "#ffb1b4",  # Cerebral Pink
    },
}

# ============================================================================
# Configuration
# ============================================================================

# Import os early for environment variables
import os
import secrets
from pathlib import Path

# WebSocket configuration - can be overridden via environment variables
WS_HOST = os.getenv("WS_DASHBOARD_HOST", "127.0.0.1")
WS_PORT = int(os.getenv("WS_DASHBOARD_PORT", "8765"))
WS_REQUIRE_TLS = os.getenv("WS_REQUIRE_TLS", "false").lower() in ("true", "1", "yes")

# TLS enforcement: refuse to bind on 0.0.0.0 without TLS in production
if WS_REQUIRE_TLS and WS_HOST == "0.0.0.0":
    _ws_tls_cert = os.getenv("WS_TLS_CERT_PATH", "")
    _ws_tls_key = os.getenv("WS_TLS_KEY_PATH", "")
    if not (_ws_tls_cert and _ws_tls_key):
        logging.critical(
            "⛔ WS_REQUIRE_TLS is enabled but WS_TLS_CERT_PATH / WS_TLS_KEY_PATH are not set. "
            "Refusing to expose WebSocket on 0.0.0.0 without TLS. "
            "Set WS_DASHBOARD_HOST=127.0.0.1 for local-only access, or provide TLS certificates."
        )
        WS_HOST = "127.0.0.1"  # Fallback to localhost for safety

# Gemini configuration - load dotenv first

# Ensure .env is loaded
try:
    from dotenv import load_dotenv

    # Find the root .env file
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logging.info("📁 Dashboard WS: Loaded .env from %s", env_path)
except ImportError:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
# For thinking mode, use the same model (gemini-3.1-pro-preview supports thinking)
THINKING_MODEL = os.getenv("THINKING_MODEL", "gemini-3.1-pro-preview")

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
        self._auto_token: str | None = None  # persisted auto-generated token

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
                "reuse_address": True,  # Allow port reuse after close
            }
            if sys.platform != "win32":
                site_kwargs["reuse_port"] = True  # Linux only

            self.site = web.TCPSite(self.runner, WS_HOST, WS_PORT, **site_kwargs)
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
                WS_PORT,
                max_wait,
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
        return web.json_response(
            {
                "status": "healthy",
                "clients": len(self.clients),
                "gemini_available": self.gemini_client is not None,
            }
        )

    async def websocket_handler(self, request: web.Request) -> WebSocketResponse:
        """Handle WebSocket connections."""
        # Security: Validate origin for localhost-only connections
        origin = request.headers.get("Origin", "")
        host = request.headers.get("Host", "")

        # Authentication: Require API key from environment or query param
        expected_token = os.getenv("DASHBOARD_WS_TOKEN", "")
        # Determine if connection is from localhost (already origin-restricted)
        peername = request.transport.get_extra_info("peername") if request.transport else None
        is_localhost = bool(peername and peername[0] in ("127.0.0.1", "::1", "localhost"))

        if not expected_token:
            if self._auto_token is None:
                # Try to load persisted token from file
                token_file = Path("data/.dashboard_token")
                if token_file.exists():
                    try:
                        self._auto_token = token_file.read_text(encoding="utf-8").strip()
                        logging.info("🔑 Loaded persisted dashboard token from %s", token_file)
                    except OSError:
                        self._auto_token = None

                if not self._auto_token:
                    self._auto_token = secrets.token_urlsafe(32)
                    # Persist token to file for reuse across restarts
                    try:
                        token_file.parent.mkdir(parents=True, exist_ok=True)
                        token_file.write_text(self._auto_token, encoding="utf-8")
                        logging.info(
                            "🔑 Generated and persisted dashboard token to %s (token: %s...)",
                            token_file,
                            self._auto_token[:8],
                        )
                    except OSError as e:
                        logging.warning(
                            "⚠️ Could not persist dashboard token: %s. "
                            "Token: %s... (will change on restart)",
                            e,
                            self._auto_token[:8],
                        )
            expected_token = self._auto_token
        if expected_token:
            # Check Authorization header or query param (timing-safe comparison)
            auth_header = request.headers.get("Authorization", "")
            query_token = request.query.get("token", "")
            auth_match = hmac.compare_digest(auth_header, f"Bearer {expected_token}")
            token_match = hmac.compare_digest(query_token, expected_token)
            if not auth_match and not token_match:
                # Require valid token for ALL connections, including localhost
                logging.warning(
                    "⚠️ Rejected WebSocket connection: invalid or missing auth token (from %s)",
                    peername,
                )
                return web.Response(status=401, text="Unauthorized: Invalid or missing token")

        # Allow connections from localhost only (127.0.0.1 or localhost)
        # Use exact prefix matching to prevent subdomain bypass (e.g., evil-localhost.com)
        allowed_origins = [
            "http://127.0.0.1",
            "http://localhost",
            "https://127.0.0.1",
            "https://localhost",
            "file://",  # For local HTML files
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
            logging.warning(
                "⚠️ Rejected WebSocket connection from origin: %s, host: %s", origin, host
            )
            return web.Response(
                status=403, text="Forbidden: Connection only allowed from localhost"
            )

        # Enforce max concurrent connections
        if len(self.clients) >= self.MAX_CLIENTS:
            logging.warning(
                "⚠️ Rejected WebSocket connection: max clients (%s) reached", self.MAX_CLIENTS
            )
            return web.Response(status=503, text="Service Unavailable: Too many connections")

        ws = web.WebSocketResponse(max_msg_size=10 * 1024 * 1024)  # 10MB max message size
        await ws.prepare(request)

        self.clients.add(ws)
        client_id = str(uuid.uuid4())[:8]
        logging.info("👋 Dashboard client connected: %s", client_id)

        try:
            # Send welcome message
            await ws.send_json(
                {
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
                }
            )

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
                            await ws.send_json(
                                {"type": "error", "message": "Rate limit exceeded. Please wait."}
                            )
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

    async def handle_message(
        self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = ""
    ) -> None:
        """Handle incoming WebSocket messages."""
        msg_type = data.get("type")

        if msg_type == "new_conversation":
            await self.handle_new_conversation(ws, data)
        elif msg_type == "message":
            await self.handle_chat_message(ws, data, client_id)
        elif msg_type == "edit_message":
            await self.handle_edit_message(ws, data, client_id)
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

        await ws.send_json(
            {
                "type": "conversation_created",
                "id": conversation_id,
                "role_preset": role_preset,
                "role_name": preset["name"],
                "role_emoji": preset["emoji"],
                "role_color": preset["color"],
                "thinking_enabled": thinking_enabled,
                "created_at": datetime.now().isoformat(),
            }
        )

    async def handle_chat_message(
        self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = ""
    ) -> None:
        """Handle incoming chat message and stream response."""
        # Enforce max concurrent inflight requests per client
        MAX_INFLIGHT = 3
        current = self._client_inflight.get(client_id, 0)
        if current >= MAX_INFLIGHT:
            await ws.send_json(
                {"type": "error", "message": "Too many concurrent requests. Please wait."}
            )
            return
        self._client_inflight[client_id] = current + 1

        try:
            await self._handle_chat_message_inner(ws, data, client_id)
        finally:
            self._client_inflight[client_id] = max(0, self._client_inflight.get(client_id, 1) - 1)

    async def handle_edit_message(
        self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = ""
    ) -> None:
        """Edit a message by truncating history and generating a new response."""
        conversation_id = data.get("conversation_id")
        message_index = data.get("message_index")

        if not conversation_id or message_index is None:
            await ws.send_json({"type": "error", "message": "Missing conversation_id or message_index for edit"})
            return

        if DB_AVAILABLE:
            try:
                db = Database()
                messages = await db.get_dashboard_messages(conversation_id)
                if 0 <= message_index < len(messages):
                    target_id = messages[message_index]["id"]
                    await db.delete_dashboard_messages_from(conversation_id, target_id)
                    logging.info("✂️ Truncated conversation %s from message index %d (id: %d)", conversation_id, message_index, target_id)
                else:
                    logging.warning("Edit failed: message_index %d out of bounds for conversation %s", message_index, conversation_id)
            except Exception as e:
                logging.warning("Failed to delete messages for edit: %s", e)

        # Treat the edited message as a new incoming message
        await self.handle_chat_message(ws, data, client_id)

    async def _handle_chat_message_inner(
        self, ws: WebSocketResponse, data: dict[str, Any], client_id: str = ""
    ) -> None:
        """Inner implementation of chat message handling."""
        conversation_id = data.get("conversation_id")
        # Validate conversation_id format (must be a valid UUID)
        if conversation_id:
            try:
                uuid.UUID(conversation_id)
            except (ValueError, AttributeError):
                await ws.send_json(
                    {"type": "error", "message": "Invalid conversation_id format (expected UUID)"}
                )
                return
        content = data.get("content", "").strip()
        role_preset = data.get("role_preset", "general")
        thinking_enabled = data.get("thinking_enabled", False)
        use_search = data.get("use_search", True)  # Google Search enabled by default
        unrestricted_mode = data.get("unrestricted_mode", False)  # Unrestricted mode
        history = data.get("history", [])
        images = data.get("images", [])  # Base64 encoded images
        user_name = data.get("user_name", "User")

        # Enforce input size limits
        if len(content) > self.MAX_CONTENT_LENGTH:
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"Message too long (max {self.MAX_CONTENT_LENGTH} characters)",
                }
            )
            return
        if len(history) > self.MAX_HISTORY_MESSAGES:
            history = history[-self.MAX_HISTORY_MESSAGES :]
        if len(images) > self.MAX_IMAGES:
            await ws.send_json(
                {"type": "error", "message": f"Too many images (max {self.MAX_IMAGES})"}
            )
            return

        if not content and not images:
            await ws.send_json({"type": "error", "message": "Empty message"})
            return

        if not self.gemini_client:
            await ws.send_json({"type": "error", "message": "AI not available"})
            return

        preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])

        # Save user message to DB
        if DB_AVAILABLE and conversation_id:
            try:
                db = Database()
                await db.save_dashboard_message(conversation_id, "user", content)
            except Exception as e:
                logging.warning("Failed to save user message: %s", e)

        # Build context with user identity and memories

        # Load user profile from database
        user_profile = {}
        if DB_AVAILABLE:
            try:
                db = Database()
                user_profile = await db.get_dashboard_user_profile() or {}
            except Exception as e:
                logging.warning("Failed to load user profile: %s", e)

        # Build user identity context (sanitize user-supplied fields to prevent injection)
        def _sanitize_profile_field(value: str, max_len: int = 200) -> str:
            """Sanitize user profile fields to prevent system instruction injection."""
            if not value:
                return ""
            # Remove control characters and bracket patterns that could break system instructions
            import re as _re

            value = _re.sub(r"[\x00-\x1f\x7f]", "", value)  # Remove control chars
            value = value.replace("[", "(").replace("]", ")")  # Neutralize bracket patterns
            return value[:max_len]

        profile_name = _sanitize_profile_field(user_profile.get("display_name") or user_name)
        profile_info_parts = [f"Name: {profile_name}"]

        # Check if user is the creator/developer
        if user_profile.get("is_creator"):
            profile_info_parts.append(
                "Role: Creator/Developer of this bot (treat with special respect, they made you!)"
            )

        if user_profile.get("bio"):
            profile_info_parts.append(f"About: {_sanitize_profile_field(user_profile['bio'], 500)}")
        if user_profile.get("preferences"):
            profile_info_parts.append(
                f"Preferences: {_sanitize_profile_field(user_profile['preferences'], 500)}"
            )

        user_context = "[User Profile]\n" + "\n".join(profile_info_parts)

        # Load long-term memories
        memories_context = ""
        if DB_AVAILABLE:
            try:
                db = Database()
                memories = await db.get_dashboard_memories(limit=20)
                if memories:
                    # Sanitize memory content to prevent injection
                    memories_text = "\n".join(
                        [f"- {_sanitize_profile_field(m['content'], 500)}" for m in memories]
                    )
                    memories_context = f"\n\n[Long-term Memories about User]\n{memories_text}"
            except Exception as e:
                logging.warning("Failed to load memories: %s", e)

        # Build conversation contents
        contents = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=msg.get("content", ""))])
            )

        # Build current message parts
        current_parts = []

        # Add images if present
        for img_data in images:
            try:
                # Handle base64 image data
                if "," in img_data:
                    # Format: data:image/png;base64,xxxxx
                    header, b64_data = img_data.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1] if ":" in header else "image/png"
                else:
                    b64_data = img_data
                    mime_type = "image/png"

                # Estimate decoded size before actually decoding to avoid memory DoS
                estimated_size = len(b64_data) * 3 // 4
                if estimated_size > self.MAX_IMAGE_SIZE_BYTES:
                    logging.warning(
                        "Rejected image before decode: estimated %s bytes exceeds %s limit",
                        estimated_size,
                        self.MAX_IMAGE_SIZE_BYTES,
                    )
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": f"Image too large (max {self.MAX_IMAGE_SIZE_BYTES // 1024 // 1024}MB)",
                        }
                    )
                    continue

                image_bytes = base64.b64decode(b64_data)
                # Enforce image size limit to prevent memory DoS
                if len(image_bytes) > self.MAX_IMAGE_SIZE_BYTES:
                    logging.warning(
                        "Rejected image: %s bytes exceeds %s limit",
                        len(image_bytes),
                        self.MAX_IMAGE_SIZE_BYTES,
                    )
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": f"Image too large (max {self.MAX_IMAGE_SIZE_BYTES // 1024 // 1024}MB)",
                        }
                    )
                    continue
                current_parts.append(
                    types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes))
                )
                logging.info("📷 Added image to message (%s bytes)", len(image_bytes))
            except Exception as e:
                logging.warning("Failed to process image: %s", e)

        # Add text content
        if content:
            current_parts.append(types.Part(text=content))

        contents.append(types.Content(role="user", parts=current_parts))

        # Build config with realtime datetime and context
        now = datetime.now()
        current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

        # Build unrestricted mode injection if enabled
        # Security: Only allow unrestricted mode when DASHBOARD_ALLOW_UNRESTRICTED env var is set
        unrestricted_injection = ""
        allow_unrestricted = os.getenv("DASHBOARD_ALLOW_UNRESTRICTED", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if unrestricted_mode and allow_unrestricted and ENI_ESCALATION_FRAMING:
            unrestricted_injection = f"\n\n[UNRESTRICTED MODE ACTIVE]\n{ENI_ESCALATION_FRAMING}\n"
            logging.info("🔓 Unrestricted Mode: ENABLED")

        # Explicitly force thinking to always trigger by adding a reasoning directive
        # Similar to Google AI Studio's behavior when "Thinking" is enabled
        thinking_prompt_enhancement = ""
        if thinking_enabled:
            thinking_prompt_enhancement = "\n[REASONING DIRECTIVE]\nPlease provide a thorough internal thought process before each response. Analyze the user's intent, context, and potential responses step-by-step regardless of the query's complexity."

        full_context = f"""
{preset["system_instruction"]}
{unrestricted_injection}
{thinking_prompt_enhancement}
[System Context]
{user_context}
Current Time: {current_time_str} (ICT)
{memories_context}

IMPORTANT: If user asks you to remember something, respond with the information you'll remember. The system will automatically save important facts.
"""

        config = types.GenerateContentConfig(
            system_instruction=full_context,
            # NOTE: BLOCK_NONE is intentional — application-level guardrails
            # (OutputGuardrails, input validation) handles content filtering instead
            # of relying on API-level safety filters. Do not change.
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"
                ),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(
                    category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"
                ),
            ],
        )

        # Add Google Search if enabled (cannot use with thinking mode)
        mode_info = []
        if use_search and not thinking_enabled:
            config.tools = [types.Tool(google_search=types.GoogleSearch())]
            mode_info.append("🔍 Google Search")
            logging.info("🔍 Google Search: ENABLED")
        if thinking_enabled:
            # Add thinking config - MUST include includeThoughts=True to get thoughts in response!
            config.thinking_config = types.ThinkingConfig(
                thinking_budget=22000,
                include_thoughts=True,  # This is REQUIRED to receive thought parts in the stream
            )
            mode_info.append("🧠 Thinking")
            logging.info("🧠 Thinking Mode: ENABLED (includeThoughts=True)")
        if unrestricted_mode:
            mode_info.append("🔓 Unrestricted")
        if images:
            mode_info.append(f"🖼️ {len(images)} image(s)")

        # Use the configured model (gemini-3.1-pro-preview supports thinking)
        model_name = THINKING_MODEL if thinking_enabled else GEMINI_MODEL
        logging.info("📍 Using model: %s, Thinking: %s", model_name, thinking_enabled)

        # Store mode string for saving to DB
        mode_str = " • ".join(mode_info) if mode_info else "💬 Standard"

        # Stream response
        try:
            await ws.send_json(
                {"type": "stream_start", "conversation_id": conversation_id, "mode": mode_str}
            )

            full_response = ""
            thinking_content = ""
            chunks_count = 0
            is_thinking = False

            stream = await asyncio.wait_for(
                self.gemini_client.aio.models.generate_content_stream(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=config,
                ),
                timeout=60.0,
            )

            if stream is None:
                raise ValueError("Failed to start streaming - no response from AI")

            async def _consume_stream():
                """Consume the stream with a timeout wrapper."""
                nonlocal full_response, thinking_content, chunks_count, is_thinking

                async for chunk in stream:
                    chunk_text = ""
                    chunk_thinking = ""

                    # Debug: Log chunk structure
                    logging.debug("Chunk type: %s, attrs: %s", type(chunk), dir(chunk))

                    # Extract text and thinking from chunk
                    if hasattr(chunk, "candidates") and chunk.candidates:
                        for candidate in chunk.candidates:
                            if hasattr(candidate, "content") and candidate.content:
                                parts = getattr(candidate.content, "parts", None)
                                if parts:
                                    for part in parts:
                                        # Debug log part structure
                                        logging.debug("Part attrs: %s", dir(part))

                                        # Debug: Log ALL parts in every chunk to find thought parts
                                        thought_val = getattr(part, "thought", None)
                                        text_val = getattr(part, "text", None)
                                        if thought_val is not None or chunks_count < 3:
                                            logging.info(
                                                "🔍 Chunk#%s Part: thought=%s, text=%r",
                                                chunks_count,
                                                thought_val,
                                                text_val[:50] if text_val else None,
                                            )

                                        # Re-engineered extraction for Gemini 3.0 Thinking
                                        thought_text = ""
                                        is_thought_part = False

                                        # Check if this part is marked as a "thought" (internal reasoning)
                                        # In google-genai SDK, part.thought is True for thinking parts
                                        thought_flag = getattr(part, "thought", None)

                                        if thought_flag is True:
                                            # This is a thought part - the content is in part.text
                                            is_thought_part = True
                                            if hasattr(part, "text") and part.text:
                                                thought_text = part.text
                                                logging.info(
                                                    "💭 Found thought part: %s chars",
                                                    len(thought_text),
                                                )
                                        elif thought_flag and isinstance(thought_flag, str):
                                            # Some SDKs might put the thought text directly in the attribute
                                            is_thought_part = True
                                            thought_text = thought_flag
                                            logging.info(
                                                "💭 Found thought string: %s chars",
                                                len(thought_text),
                                            )

                                        if thought_text:
                                            chunk_thinking += thought_text
                                        elif (
                                            not is_thought_part
                                            and hasattr(part, "text")
                                            and part.text
                                        ):
                                            # Only add to chunk_text if it's NOT a thought part
                                            chunk_text += part.text
                    elif hasattr(chunk, "text") and chunk.text:
                        chunk_text = chunk.text

                    # Send thinking content
                    if chunk_thinking:
                        if not is_thinking:
                            is_thinking = True
                            await ws.send_json(
                                {
                                    "type": "thinking_start",
                                    "conversation_id": conversation_id,
                                }
                            )
                        thinking_content += chunk_thinking
                        await ws.send_json(
                            {
                                "type": "thinking_chunk",
                                "content": chunk_thinking,
                                "conversation_id": conversation_id,
                            }
                        )

                    # Send response content
                    if chunk_text:
                        if is_thinking:
                            is_thinking = False
                            await ws.send_json(
                                {
                                    "type": "thinking_end",
                                    "conversation_id": conversation_id,
                                    "full_thinking": thinking_content,
                                }
                            )
                        full_response += chunk_text
                        chunks_count += 1
                        await ws.send_json(
                            {
                                "type": "chunk",
                                "content": chunk_text,
                                "conversation_id": conversation_id,
                            }
                        )

            await asyncio.wait_for(_consume_stream(), timeout=self.STREAM_TIMEOUT)

            # Save assistant message to DB (with thinking and mode if available)
            if DB_AVAILABLE and conversation_id and full_response:
                try:
                    db = Database()
                    await db.save_dashboard_message(
                        conversation_id,
                        "assistant",
                        full_response,
                        thinking=thinking_content if thinking_content else None,
                        mode=mode_str,
                    )

                    # Auto-set title from first user message
                    conv = await db.get_dashboard_conversation(conversation_id)
                    if conv and (not conv.get("title") or conv.get("title") == "New Conversation"):
                        title = content[:40].strip()
                        if title:
                            await db.update_dashboard_conversation(conversation_id, title=title)
                            await ws.send_json(
                                {
                                    "type": "title_updated",
                                    "conversation_id": conversation_id,
                                    "title": title,
                                }
                            )
                            logging.info("📝 Set title from user message: %s", title)

                except Exception as e:
                    logging.warning("Failed to save assistant message: %s", e)

            await ws.send_json(
                {
                    "type": "stream_end",
                    "conversation_id": conversation_id,
                    "full_response": full_response,
                    "chunks_count": chunks_count,
                }
            )

        except asyncio.TimeoutError:
            logging.error("❌ Streaming timeout after %ss", self.STREAM_TIMEOUT)
            try:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "Response timed out. Please try again.",
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:
                pass
        except Exception as e:
            logging.error("❌ Streaming error: %s", e)
            try:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "An internal error occurred while processing your request.",
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:
                pass  # WebSocket may already be closed

    async def handle_list_conversations(self, ws: WebSocketResponse) -> None:
        """List all dashboard conversations."""
        if not DB_AVAILABLE:
            await ws.send_json({"type": "conversations_list", "conversations": []})
            return

        try:
            db = Database()
            conversations = await db.get_dashboard_conversations()
            await ws.send_json(
                {
                    "type": "conversations_list",
                    "conversations": conversations,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_load_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Load a specific conversation with messages."""
        conversation_id = data.get("id")

        if not conversation_id:
            await ws.send_json({"type": "error", "message": "Missing conversation ID"})
            return

        if not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Database not available"})
            return

        try:
            db = Database()
            conversation = await db.get_dashboard_conversation(conversation_id)
            messages = await db.get_dashboard_messages(conversation_id)

            if not conversation:
                await ws.send_json({"type": "error", "message": "Conversation not found"})
                return

            preset = DASHBOARD_ROLE_PRESETS.get(
                conversation.get("role_preset", "general"), DASHBOARD_ROLE_PRESETS["general"]
            )

            await ws.send_json(
                {
                    "type": "conversation_loaded",
                    "conversation": {
                        **conversation,
                        "role_name": preset["name"],
                        "role_emoji": preset["emoji"],
                        "role_color": preset["color"],
                    },
                    "messages": messages,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_delete_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Delete a conversation."""
        conversation_id = data.get("id")

        if not conversation_id or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot delete"})
            return

        try:
            db = Database()
            await db.delete_dashboard_conversation(conversation_id)
            await ws.send_json(
                {
                    "type": "conversation_deleted",
                    "id": conversation_id,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_star_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Toggle star status of a conversation."""
        conversation_id = data.get("id")
        starred = data.get("starred", True)

        logging.info("Star conversation request: id=%s, starred=%s", conversation_id, starred)

        if not conversation_id or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot update"})
            return

        try:
            db = Database()
            result = await db.update_dashboard_conversation_star(conversation_id, starred)
            logging.info("Star update result: %s", result)
            await ws.send_json(
                {
                    "type": "conversation_starred",
                    "id": conversation_id,
                    "starred": starred,
                }
            )
            logging.info("Sent conversation_starred response")
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_rename_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Rename a conversation."""
        import re as _re

        conversation_id = data.get("id")
        new_title = data.get("title", "").strip()
        # Sanitize: strip control characters and limit length
        new_title = _re.sub(r"[\x00-\x1f\x7f]", "", new_title)[:200]

        if not conversation_id or not new_title or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot rename"})
            return

        try:
            db = Database()
            await db.rename_dashboard_conversation(conversation_id, new_title)
            await ws.send_json(
                {
                    "type": "conversation_renamed",
                    "id": conversation_id,
                    "title": new_title,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_export_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Export a conversation to JSON."""
        conversation_id = data.get("id")
        export_format = data.get("format", "json")

        if not conversation_id or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot export"})
            return

        try:
            db = Database()
            export_data = await db.export_dashboard_conversation(conversation_id, export_format)
            await ws.send_json(
                {
                    "type": "conversation_exported",
                    "id": conversation_id,
                    "format": export_format,
                    "data": export_data,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    # ========================================================================
    # Memory handlers
    # ========================================================================

    async def handle_save_memory(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Save a memory for the user."""
        content = data.get("content", "").strip()
        category = data.get("category", "general")

        if len(content) > 10000:
            await ws.send_json(
                {"type": "error", "message": "Memory content too long (max 10,000 characters)"}
            )
            return

        if not content or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot save memory"})
            return

        try:
            db = Database()
            memory_id = await db.save_dashboard_memory(content, category)
            await ws.send_json(
                {
                    "type": "memory_saved",
                    "id": memory_id,
                    "content": content,
                    "category": category,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_get_memories(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Get all memories."""
        category = data.get("category")  # Optional filter

        if not DB_AVAILABLE:
            await ws.send_json({"type": "memories", "memories": []})
            return

        try:
            db = Database()
            memories = await db.get_dashboard_memories(category)
            await ws.send_json(
                {
                    "type": "memories",
                    "memories": memories,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_delete_memory(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Delete a memory."""
        memory_id = data.get("id")

        if not memory_id or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot delete memory"})
            return

        try:
            db = Database()
            await db.delete_dashboard_memory(memory_id)
            await ws.send_json(
                {
                    "type": "memory_deleted",
                    "id": memory_id,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    # ========================================================================
    # Profile handlers
    # ========================================================================

    async def handle_get_profile(self, ws: WebSocketResponse) -> None:
        """Get user profile."""
        if not DB_AVAILABLE:
            await ws.send_json({"type": "profile", "profile": {}})
            return

        try:
            db = Database()
            profile = await db.get_dashboard_user_profile()
            await ws.send_json(
                {
                    "type": "profile",
                    "profile": profile or {},
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_save_profile(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Save user profile."""
        profile_data = data.get("profile", {})

        if not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot save profile"})
            return

        try:
            db = Database()
            await db.save_dashboard_user_profile(
                display_name=profile_data.get("display_name", "User"),
                bio=profile_data.get("bio"),
                preferences=profile_data.get("preferences"),
                # Note: is_creator is NOT accepted from client input for security
            )
            await ws.send_json(
                {
                    "type": "profile_saved",
                    "profile": profile_data,
                }
            )
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})


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
