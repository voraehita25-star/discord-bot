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
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiohttp import web, WSMsgType

from google import genai
from google.genai import types

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# Import Faust persona and unrestricted mode framing
try:
    from ..data.faust_data import FAUST_PERSONA, ENI_ESCALATION_FRAMING
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
        "system_instruction": FAUST_PERSONA if FAUST_AVAILABLE else "You are Faust, a genius AI assistant who speaks in third person.",
        "color": "#ffb1b4",  # Cerebral Pink
    },
}

# ============================================================================
# Configuration
# ============================================================================

# Import os early for environment variables
import os
from pathlib import Path

# WebSocket configuration - can be overridden via environment variables
WS_HOST = os.getenv("WS_DASHBOARD_HOST", "127.0.0.1")
WS_PORT = int(os.getenv("WS_DASHBOARD_PORT", "8765"))

# Gemini configuration - load dotenv first

# Ensure .env is loaded
try:
    from dotenv import load_dotenv
    # Find the root .env file
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logging.info(f"📁 Dashboard WS: Loaded .env from {env_path}")
except ImportError:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")
# For thinking mode, use the same model (gemini-3-pro supports thinking)

# ============================================================================
# WebSocket Dashboard Server
# ============================================================================

class DashboardWebSocketServer:
    """WebSocket server for dashboard AI chat."""

    def __init__(self):
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.clients: set[WebSocketResponse] = set()
        self.gemini_client: genai.Client | None = None
        self._running = False
        
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
            logging.info(f"🚀 Dashboard WebSocket server started on ws://{WS_HOST}:{WS_PORT}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to start Dashboard WebSocket server: {e}")
            return False

    async def _ensure_port_available(self) -> None:
        """Ensure port is available, killing old process if needed.
        
        SAFETY: Only kills processes that are confirmed to be our own bot instances
        by checking for specific identifiers in the command line.
        """
        import socket
        import subprocess
        import sys
        
        # Quick check if port is in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((WS_HOST, WS_PORT))
        sock.close()
        
        if result == 0:  # Port is in use
            logging.warning(f"⚠️ Port {WS_PORT} is in use, attempting to free it...")
            
            # SAFETY: We will NOT auto-kill processes anymore.
            # Instead, we wait for the port to become available or fail gracefully.
            # This prevents accidentally killing unrelated processes.
            
            max_wait = 5  # Maximum seconds to wait for port
            waited = 0
            
            while waited < max_wait:
                await asyncio.sleep(0.5)
                waited += 0.5
                
                # Re-check if port is free
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((WS_HOST, WS_PORT))
                sock.close()
                
                if result != 0:  # Port is now free
                    logging.info(f"✅ Port {WS_PORT} is now available")
                    return
            
            # If still not free, log warning but continue (will fail gracefully on bind)
            logging.warning(
                f"⚠️ Port {WS_PORT} still in use after {max_wait}s wait. "
                f"If this is an old bot instance, please stop it manually."
            )

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return

        logging.info("🛑 Stopping Dashboard WebSocket server...")
        
        # Close all client connections
        for ws in list(self.clients):
            await ws.close(code=1001, message=b"Server shutting down")
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
        
        # Allow connections from localhost only (127.0.0.1 or localhost)
        allowed_origins = [
            "http://127.0.0.1",
            "http://localhost",
            "https://127.0.0.1",
            "https://localhost",
            "file://",  # For local HTML files
        ]
        
        # Check if origin is allowed (match prefix, or no origin for direct WS tools)
        origin_allowed = origin == "" or any(
            origin.startswith(allowed)
            for allowed in allowed_origins
        )
        
        # Also check host header
        host_allowed = host.startswith("127.0.0.1") or host.startswith("localhost")
        
        if not origin_allowed and not host_allowed:
            logging.warning(f"⚠️ Rejected WebSocket connection from origin: {origin}, host: {host}")
            return web.Response(status=403, text="Forbidden: Connection only allowed from localhost")
        
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.clients.add(ws)
        client_id = str(uuid.uuid4())[:8]
        logging.info(f"👋 Dashboard client connected: {client_id}")

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
                        await self.handle_message(ws, data)
                    except json.JSONDecodeError:
                        await ws.send_json({"type": "error", "message": "Invalid JSON"})
                elif msg.type == WSMsgType.ERROR:
                    logging.error(f"WebSocket error: {ws.exception()}")
                    break

        except Exception as e:
            logging.error(f"❌ WebSocket handler error: {e}")
        finally:
            self.clients.discard(ws)
            logging.info(f"👋 Dashboard client disconnected: {client_id}")

        return ws

    async def handle_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle incoming WebSocket messages."""
        msg_type = data.get("type")

        if msg_type == "new_conversation":
            await self.handle_new_conversation(ws, data)
        elif msg_type == "message":
            await self.handle_chat_message(ws, data)
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
                logging.error(f"Failed to save conversation to DB: {e}")

        await ws.send_json({
            "type": "conversation_created",
            "id": conversation_id,
            "role_preset": role_preset,
            "role_name": preset["name"],
            "role_emoji": preset["emoji"],
            "role_color": preset["color"],
            "thinking_enabled": thinking_enabled,
            "created_at": datetime.now().isoformat(),
        })

    async def handle_chat_message(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Handle incoming chat message and stream response."""
        conversation_id = data.get("conversation_id")
        content = data.get("content", "").strip()
        role_preset = data.get("role_preset", "general")
        thinking_enabled = data.get("thinking_enabled", False)
        use_search = data.get("use_search", True)  # Google Search enabled by default
        unrestricted_mode = data.get("unrestricted_mode", False)  # Unrestricted mode
        history = data.get("history", [])
        images = data.get("images", [])  # Base64 encoded images
        user_name = data.get("user_name", "User")

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
                logging.warning(f"Failed to save user message: {e}")

        # Build context with user identity and memories
        context_parts = []
        
        # Load user profile from database
        user_profile = {}
        if DB_AVAILABLE:
            try:
                db = Database()
                user_profile = await db.get_dashboard_user_profile() or {}
            except Exception as e:
                logging.warning(f"Failed to load user profile: {e}")
        
        # Build user identity context
        profile_name = user_profile.get("display_name") or user_name
        profile_info_parts = [f"Name: {profile_name}"]
        
        # Check if user is the creator/developer
        if user_profile.get("is_creator"):
            profile_info_parts.append("Role: Creator/Developer of this bot (treat with special respect, they made you!)")
        
        if user_profile.get("bio"):
            profile_info_parts.append(f"About: {user_profile['bio']}")
        if user_profile.get("preferences"):
            profile_info_parts.append(f"Preferences: {user_profile['preferences']}")
        
        user_context = "[User Profile]\n" + "\n".join(profile_info_parts)
        
        # Load long-term memories
        memories_context = ""
        if DB_AVAILABLE:
            try:
                db = Database()
                memories = await db.get_dashboard_memories(limit=20)
                if memories:
                    memories_text = "\n".join([f"- {m['content']}" for m in memories])
                    memories_context = f"\n\n[Long-term Memories about User]\n{memories_text}"
            except Exception as e:
                logging.warning(f"Failed to load memories: {e}")

        # Build conversation contents
        contents = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part(text=msg.get("content", ""))]
            ))
        
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
                
                image_bytes = base64.b64decode(b64_data)
                current_parts.append(types.Part(
                    inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
                ))
                logging.info(f"📷 Added image to message ({len(image_bytes)} bytes)")
            except Exception as e:
                logging.warning(f"Failed to process image: {e}")
        
        # Add text content
        if content:
            current_parts.append(types.Part(text=content))
        
        contents.append(types.Content(role="user", parts=current_parts))

        # Build config with realtime datetime and context
        now = datetime.now()
        current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")
        
        # Build unrestricted mode injection if enabled
        unrestricted_injection = ""
        if unrestricted_mode and ENI_ESCALATION_FRAMING:
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
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
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
                include_thoughts=True  # This is REQUIRED to receive thought parts in the stream
            )
            mode_info.append("🧠 Thinking")
            logging.info("🧠 Thinking Mode: ENABLED (includeThoughts=True)")
        if unrestricted_mode:
            mode_info.append("🔓 Unrestricted")
        if images:
            mode_info.append(f"🖼️ {len(images)} image(s)")

        # Use the configured model (gemini-3-pro-preview supports thinking)
        logging.info(f"📍 Using model: {GEMINI_MODEL}, Thinking: {thinking_enabled}")
        
        # Store mode string for saving to DB
        mode_str = " • ".join(mode_info) if mode_info else "💬 Standard"

        # Stream response
        try:
            await ws.send_json({
                "type": "stream_start", 
                "conversation_id": conversation_id,
                "mode": mode_str
            })
            
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

            async for chunk in stream:
                chunk_text = ""
                chunk_thinking = ""
                
                # Debug: Log chunk structure
                logging.debug(f"Chunk type: {type(chunk)}, attrs: {dir(chunk)}")
                
                # Extract text and thinking from chunk
                if hasattr(chunk, "candidates") and chunk.candidates:
                    for candidate in chunk.candidates:
                        if hasattr(candidate, "content") and candidate.content:
                            parts = getattr(candidate.content, "parts", None)
                            if parts:
                                for part in parts:
                                    # Debug log part structure
                                    logging.debug(f"Part attrs: {dir(part)}")
                                    
                                    # Debug: Log ALL parts in every chunk to find thought parts
                                    thought_val = getattr(part, 'thought', None)
                                    text_val = getattr(part, 'text', None)
                                    if thought_val is not None or chunks_count < 3:
                                        logging.info(f"🔍 Chunk#{chunks_count} Part: thought={thought_val}, text={repr(text_val[:50] if text_val else None)}")

                                    # Re-engineered extraction for Gemini 3.0 Thinking
                                    thought_text = ""
                                    is_thought_part = False
                                    
                                    # Check if this part is marked as a "thought" (internal reasoning)
                                    # In google-genai SDK, part.thought is True for thinking parts
                                    thought_flag = getattr(part, 'thought', None)
                                    
                                    if thought_flag is True:
                                        # This is a thought part - the content is in part.text
                                        is_thought_part = True
                                        if hasattr(part, 'text') and part.text:
                                            thought_text = part.text
                                            logging.info(f"💭 Found thought part: {len(thought_text)} chars")
                                    elif thought_flag and isinstance(thought_flag, str):
                                        # Some SDKs might put the thought text directly in the attribute
                                        is_thought_part = True
                                        thought_text = thought_flag
                                        logging.info(f"💭 Found thought string: {len(thought_text)} chars")

                                    if thought_text:
                                        chunk_thinking += thought_text
                                    elif not is_thought_part and hasattr(part, "text") and part.text:
                                        # Only add to chunk_text if it's NOT a thought part
                                        chunk_text += part.text
                elif hasattr(chunk, "text") and chunk.text:
                    chunk_text = chunk.text

                # Send thinking content
                if chunk_thinking:
                    if not is_thinking:
                        is_thinking = True
                        await ws.send_json({
                            "type": "thinking_start",
                            "conversation_id": conversation_id,
                        })
                    thinking_content += chunk_thinking
                    await ws.send_json({
                        "type": "thinking_chunk",
                        "content": chunk_thinking,
                        "conversation_id": conversation_id,
                    })

                # Send response content
                if chunk_text:
                    if is_thinking:
                        is_thinking = False
                        await ws.send_json({
                            "type": "thinking_end",
                            "conversation_id": conversation_id,
                            "full_thinking": thinking_content,
                        })
                    full_response += chunk_text
                    chunks_count += 1
                    await ws.send_json({
                        "type": "chunk",
                        "content": chunk_text,
                        "conversation_id": conversation_id,
                    })

            # Save assistant message to DB (with thinking and mode if available)
            if DB_AVAILABLE and conversation_id and full_response:
                try:
                    db = Database()
                    await db.save_dashboard_message(
                        conversation_id, "assistant", full_response, 
                        thinking=thinking_content if thinking_content else None,
                        mode=mode_str
                    )
                    
                    # Auto-set title from first user message
                    conv = await db.get_dashboard_conversation(conversation_id)
                    if conv and (not conv.get('title') or conv.get('title') == 'New Conversation'):
                        title = content[:40].strip()
                        if title:
                            await db.update_dashboard_conversation(conversation_id, title=title)
                            await ws.send_json({
                                "type": "title_updated",
                                "conversation_id": conversation_id,
                                "title": title,
                            })
                            logging.info(f"📝 Set title from user message: {title}")
                        
                except Exception as e:
                    logging.warning(f"Failed to save assistant message: {e}")

            await ws.send_json({
                "type": "stream_end",
                "conversation_id": conversation_id,
                "full_response": full_response,
                "chunks_count": chunks_count,
            })

        except Exception as e:
            logging.error(f"❌ Streaming error: {e}")
            await ws.send_json({
                "type": "error",
                "message": "An internal error occurred while processing your request.",
                "conversation_id": conversation_id,
            })

    async def _generate_conversation_title(
        self, ws: WebSocketResponse, db, conversation_id: str, user_msg: str, ai_response: str
    ) -> None:
        """Generate a conversation title using AI based on the first exchange."""
        try:
            # Create a simple prompt to generate title
            prompt = f"""You are a title generator. Create a brief, descriptive title (2-5 words) for this chat conversation.

Rules:
- Use the SAME language as the user's message
- Make it descriptive of the topic
- Do NOT start with articles like "การ", "The", "A"
- Output ONLY the title, nothing else

User said: "{user_msg[:100]}"

Title:"""
            
            logging.info(f"📝 Calling gemini-3-flash-preview for title...")
            response = await self.gemini_client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=30,
                )
            )
            logging.info(f"📝 Response text: {response.text if response else 'None'}")
            
            if response and response.text:
                title = response.text.strip().strip('"\'').strip()[:50]
                # Skip if title is too short or just "การ"
                if title and len(title) >= 3 and title != "การ":
                    await db.update_dashboard_conversation(conversation_id, title=title)
                    await ws.send_json({
                        "type": "title_updated",
                        "conversation_id": conversation_id,
                        "title": title,
                    })
                    logging.info(f"📝 AI generated title: {title}")
                else:
                    # Fallback: use user message
                    fallback = user_msg[:40].strip()
                    if fallback:
                        await db.update_dashboard_conversation(conversation_id, title=fallback)
                        await ws.send_json({
                            "type": "title_updated",
                            "conversation_id": conversation_id,
                            "title": fallback,
                        })
                        logging.info(f"📝 Using fallback title: {fallback}")
        except Exception as e:
            logging.warning(f"Failed to generate title: {e}", exc_info=True)

    async def handle_list_conversations(self, ws: WebSocketResponse) -> None:
        """List all dashboard conversations."""
        if not DB_AVAILABLE:
            await ws.send_json({"type": "conversations_list", "conversations": []})
            return

        try:
            db = Database()
            conversations = await db.get_dashboard_conversations()
            await ws.send_json({
                "type": "conversations_list",
                "conversations": conversations,
            })
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
                conversation.get("role_preset", "general"),
                DASHBOARD_ROLE_PRESETS["general"]
            )

            await ws.send_json({
                "type": "conversation_loaded",
                "conversation": {
                    **conversation,
                    "role_name": preset["name"],
                    "role_emoji": preset["emoji"],
                    "role_color": preset["color"],
                },
                "messages": messages,
            })
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
            await ws.send_json({
                "type": "conversation_deleted",
                "id": conversation_id,
            })
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_star_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Toggle star status of a conversation."""
        conversation_id = data.get("id")
        starred = data.get("starred", True)
        
        logging.info(f"Star conversation request: id={conversation_id}, starred={starred}")
        
        if not conversation_id or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot update"})
            return

        try:
            db = Database()
            result = await db.update_dashboard_conversation_star(conversation_id, starred)
            logging.info(f"Star update result: {result}")
            await ws.send_json({
                "type": "conversation_starred",
                "id": conversation_id,
                "starred": starred,
            })
            logging.info(f"Sent conversation_starred response")
        except Exception as e:
            logging.error("WebSocket handler error: %s", e)
            await ws.send_json({"type": "error", "message": "An internal error occurred"})

    async def handle_rename_conversation(self, ws: WebSocketResponse, data: dict[str, Any]) -> None:
        """Rename a conversation."""
        conversation_id = data.get("id")
        new_title = data.get("title", "").strip()
        
        if not conversation_id or not new_title or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot rename"})
            return

        try:
            db = Database()
            await db.rename_dashboard_conversation(conversation_id, new_title)
            await ws.send_json({
                "type": "conversation_renamed",
                "id": conversation_id,
                "title": new_title,
            })
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
            await ws.send_json({
                "type": "conversation_exported",
                "id": conversation_id,
                "format": export_format,
                "data": export_data,
            })
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
        
        if not content or not DB_AVAILABLE:
            await ws.send_json({"type": "error", "message": "Cannot save memory"})
            return

        try:
            db = Database()
            memory_id = await db.save_dashboard_memory(content, category)
            await ws.send_json({
                "type": "memory_saved",
                "id": memory_id,
                "content": content,
                "category": category,
            })
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
            await ws.send_json({
                "type": "memories",
                "memories": memories,
            })
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
            await ws.send_json({
                "type": "memory_deleted",
                "id": memory_id,
            })
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
            await ws.send_json({
                "type": "profile",
                "profile": profile or {},
            })
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
            await ws.send_json({
                "type": "profile_saved",
                "profile": profile_data,
            })
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
