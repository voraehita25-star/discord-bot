"""
Dashboard AI chat streaming handler.

Handles the core AI conversation logic: building context, streaming
Gemini responses, processing thinking parts, and saving to database.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re as _re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from google.genai import types

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse
    from google import genai

from .dashboard_config import (
    DB_AVAILABLE,
    DASHBOARD_ROLE_PRESETS,
    ENI_ESCALATION_FRAMING,
    GEMINI_MODEL,
)


def _get_db():
    from .dashboard_config import Database
    return Database()


def _sanitize_profile_field(value: str, max_len: int = 200) -> str:
    """Sanitize user profile fields to prevent system instruction injection."""
    if not value:
        return ""
    # Remove control characters and bracket patterns that could break system instructions
    value = _re.sub(r'[\x00-\x1f\x7f]', '', value)  # Remove control chars
    value = value.replace('[', '(').replace(']', ')')  # Neutralize bracket patterns
    return value[:max_len]


async def handle_chat_message(
    ws: WebSocketResponse,
    data: dict[str, Any],
    gemini_client: genai.Client | None,
    *,
    max_content_length: int = 50_000,
    max_history_messages: int = 100,
    max_images: int = 10,
    max_image_size_bytes: int = 10 * 1024 * 1024,
    stream_timeout: int = 300,
) -> None:
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

    # Enforce input size limits
    if len(content) > max_content_length:
        await ws.send_json({"type": "error", "message": f"Message too long (max {max_content_length} characters)"})
        return
    if len(history) > max_history_messages:
        history = history[-max_history_messages:]
    if len(images) > max_images:
        await ws.send_json({"type": "error", "message": f"Too many images (max {max_images})"})
        return

    if not content and not images:
        await ws.send_json({"type": "error", "message": "Empty message"})
        return

    if not gemini_client:
        await ws.send_json({"type": "error", "message": "AI not available"})
        return

    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])

    # Save user message to DB
    if DB_AVAILABLE and conversation_id:
        try:
            db = _get_db()
            await db.save_dashboard_message(conversation_id, "user", content)
        except Exception as e:
            logging.warning("Failed to save user message: %s", e)

    # Build context with user identity and memories
    user_profile = {}
    if DB_AVAILABLE:
        try:
            db = _get_db()
            user_profile = await db.get_dashboard_user_profile() or {}
        except Exception as e:
            logging.warning("Failed to load user profile: %s", e)

    # Build user identity context
    profile_name = _sanitize_profile_field(user_profile.get("display_name") or user_name)
    profile_info_parts = [f"Name: {profile_name}"]

    # Check if user is the creator/developer
    if user_profile.get("is_creator"):
        profile_info_parts.append("Role: Creator/Developer of this bot (treat with special respect, they made you!)")

    if user_profile.get("bio"):
        profile_info_parts.append(f"About: {_sanitize_profile_field(user_profile['bio'], 500)}")
    if user_profile.get("preferences"):
        profile_info_parts.append(f"Preferences: {_sanitize_profile_field(user_profile['preferences'], 500)}")

    user_context = "[User Profile]\n" + "\n".join(profile_info_parts)

    # Load long-term memories
    memories_context = ""
    if DB_AVAILABLE:
        try:
            db = _get_db()
            memories = await db.get_dashboard_memories(limit=20)
            if memories:
                memories_text = "\n".join([f"- {_sanitize_profile_field(m['content'], 500)}" for m in memories])
                memories_context = f"\n\n[Long-term Memories about User]\n{memories_text}"
        except Exception as e:
            logging.warning("Failed to load memories: %s", e)

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
            if "," in img_data:
                header, b64_data = img_data.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1] if ":" in header else "image/png"
            else:
                b64_data = img_data
                mime_type = "image/png"

            image_bytes = base64.b64decode(b64_data)
            if len(image_bytes) > max_image_size_bytes:
                logging.warning("Rejected image: %s bytes exceeds %s limit", len(image_bytes), max_image_size_bytes)
                await ws.send_json({"type": "error", "message": f"Image too large (max {max_image_size_bytes // 1024 // 1024}MB)"})
                continue
            current_parts.append(types.Part(
                inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
            ))
            logging.info("📷 Added image to message (%s bytes)", len(image_bytes))
        except Exception as e:
            logging.warning("Failed to process image: %s", e)

    # Add text content
    if content:
        current_parts.append(types.Part(text=content))

    contents.append(types.Content(role="user", parts=current_parts))

    # Build config with realtime datetime and context
    now = datetime.now(tz=timezone.utc)
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

    # Build unrestricted mode injection if enabled
    unrestricted_injection = ""
    allow_unrestricted = os.getenv("DASHBOARD_ALLOW_UNRESTRICTED", "").lower() in ("1", "true", "yes")
    if unrestricted_mode and allow_unrestricted and ENI_ESCALATION_FRAMING:
        unrestricted_injection = f"\n\n[UNRESTRICTED MODE ACTIVE]\n{ENI_ESCALATION_FRAMING}\n"
        logging.info("🔓 Unrestricted Mode: ENABLED")

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
        config.thinking_config = types.ThinkingConfig(
            thinking_budget=22000,
            include_thoughts=True
        )
        mode_info.append("🧠 Thinking")
        logging.info("🧠 Thinking Mode: ENABLED (includeThoughts=True)")
    if unrestricted_mode:
        mode_info.append("🔓 Unrestricted")
    if images:
        mode_info.append(f"🖼️ {len(images)} image(s)")

    # Use the configured model (gemini-3.1-pro-preview supports thinking)
    logging.info("📍 Using model: %s, Thinking: %s", GEMINI_MODEL, thinking_enabled)

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
            gemini_client.aio.models.generate_content_stream(
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

                logging.debug("Chunk type: %s, attrs: %s", type(chunk), dir(chunk))

                if hasattr(chunk, "candidates") and chunk.candidates:
                    for candidate in chunk.candidates:
                        if hasattr(candidate, "content") and candidate.content:
                            parts = getattr(candidate.content, "parts", None)
                            if parts:
                                for part in parts:
                                    logging.debug("Part attrs: %s", dir(part))

                                    thought_val = getattr(part, 'thought', None)
                                    text_val = getattr(part, 'text', None)
                                    if thought_val is not None or chunks_count < 3:
                                        logging.info("🔍 Chunk#%s Part: thought=%s, text=%r", chunks_count, thought_val, text_val[:50] if text_val else None)

                                    thought_text = ""
                                    is_thought_part = False

                                    thought_flag = getattr(part, 'thought', None)

                                    if thought_flag is True:
                                        is_thought_part = True
                                        if hasattr(part, 'text') and part.text:
                                            thought_text = part.text
                                            logging.info("💭 Found thought part: %s chars", len(thought_text))
                                    elif thought_flag and isinstance(thought_flag, str):
                                        is_thought_part = True
                                        thought_text = thought_flag
                                        logging.info("💭 Found thought string: %s chars", len(thought_text))

                                    if thought_text:
                                        chunk_thinking += thought_text
                                    elif not is_thought_part and hasattr(part, "text") and part.text:
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

        await asyncio.wait_for(_consume_stream(), timeout=stream_timeout)

        # Save assistant message to DB
        if DB_AVAILABLE and conversation_id and full_response:
            try:
                db = _get_db()
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
                        logging.info("📝 Set title from user message: %s", title)

            except Exception as e:
                logging.warning("Failed to save assistant message: %s", e)

        await ws.send_json({
            "type": "stream_end",
            "conversation_id": conversation_id,
            "full_response": full_response,
            "chunks_count": chunks_count,
        })

    except asyncio.TimeoutError:
        logging.error("❌ Streaming timeout after %ss", stream_timeout)
        try:
            await ws.send_json({
                "type": "error",
                "message": "Response timed out. Please try again.",
                "conversation_id": conversation_id,
            })
        except Exception:
            pass
    except Exception as e:
        logging.error("❌ Streaming error: %s", e)
        try:
            await ws.send_json({
                "type": "error",
                "message": "An internal error occurred while processing your request.",
                "conversation_id": conversation_id,
            })
        except Exception:
            pass  # WebSocket may already be closed
