"""
Dashboard AI chat streaming handler.

Handles the core AI conversation logic: building context, streaming
Gemini responses, processing thinking parts, and saving to database.
"""

from __future__ import annotations

import asyncio
import base64
import logging
logger = logging.getLogger(__name__)
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from google.genai import types

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse
    from google import genai

from .dashboard_common import (
    LeadingTimestampStripper,
    bangkok_now_iso,
    build_user_context,
    get_db as _get_db,
    normalize_timestamp_to_bangkok,
    sanitize_profile_field as _sanitize_profile_field,  # noqa: F401 (re-exported for tests)
    strip_leading_timestamp,
)
from .dashboard_config import (
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    ENI_ESCALATION_FRAMING,
    GEMINI_CONTEXT_WINDOW,
    GEMINI_MODEL,
    GENERAL_UNRESTRICTED_FRAMING,
)


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
    unrestricted_mode_requested = data.get("unrestricted_mode", False)  # Unrestricted mode
    history = data.get("history", [])
    images = data.get("images", [])  # Base64 encoded images
    user_name = data.get("user_name", "User")
    is_regeneration = data.get("is_regeneration", False)

    # Validate conversation_id format (defense in depth)
    if conversation_id and (not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id)):
        await ws.send_json({"type": "error", "message": "Invalid conversation ID format"})
        return

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

    # Save user message to DB (skip for regeneration — the edited message already exists)
    user_msg_id: int = 0
    if DB_AVAILABLE and conversation_id and not is_regeneration:
        try:
            db = _get_db()
            user_msg_id = await db.save_dashboard_message(conversation_id, "user", content, images=images or None)
        except Exception as e:
            logger.warning("Failed to save user message: %s", e)

    # Build context with user identity and memories
    user_context, memories_context, unrestricted_mode = await build_user_context(
        user_name, unrestricted_mode_requested,
    )

    # Build conversation contents
    # Load from DB when available so we can annotate messages that have images
    contents = []
    _db_history_loaded = False
    if DB_AVAILABLE and conversation_id:
        try:
            db = _get_db()
            db_msgs = await db.get_dashboard_messages(conversation_id)
            # Exclude the last message (the current user message just saved above)
            hist_msgs = db_msgs[:-1] if db_msgs and db_msgs[-1]["role"] == "user" else db_msgs
            if len(hist_msgs) > max_history_messages:
                hist_msgs = hist_msgs[-max_history_messages:]
            for msg in hist_msgs:
                role = "user" if msg["role"] == "user" else "model"
                text = msg.get("content") or ""
                if msg.get("created_at"):
                    text = f"[{normalize_timestamp_to_bangkok(msg['created_at'])}] {text}"
                if msg.get("images"):
                    text += f"\n[User had attached {len(msg['images'])} image(s) in this message, message_id={msg['id']}]"
                contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
            _db_history_loaded = True
        except Exception as e:
            logger.warning("Failed to load DB history, falling back to frontend history: %s", e)

    if not _db_history_loaded:
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg.get("content", ""))]))

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

            # Validate MIME type against allowlist
            _ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/heic", "image/heif"}
            if mime_type not in _ALLOWED_IMAGE_MIMES:
                logger.warning("Rejected image with disallowed MIME type: %s", mime_type)
                await ws.send_json({"type": "error", "message": f"Unsupported image type: {mime_type}"})
                continue

            # Validate base64 string length BEFORE decoding to prevent memory exhaustion
            # base64 encodes 3 bytes into 4 chars, so decoded size ≈ len * 3/4
            estimated_size = len(b64_data) * 3 // 4
            if estimated_size > max_image_size_bytes:
                logger.warning("Rejected image: estimated %s bytes exceeds %s limit", estimated_size, max_image_size_bytes)
                await ws.send_json({"type": "error", "message": f"Image too large (max {max_image_size_bytes // 1024 // 1024}MB)"})
                continue

            image_bytes = base64.b64decode(b64_data, validate=True)
            if len(image_bytes) > max_image_size_bytes:
                logger.warning("Rejected image: %s bytes exceeds %s limit", len(image_bytes), max_image_size_bytes)
                await ws.send_json({"type": "error", "message": f"Image too large (max {max_image_size_bytes // 1024 // 1024}MB)"})
                continue
            current_parts.append(types.Part(
                inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
            ))
            logger.info("📷 Added image to message (%s bytes)", len(image_bytes))
        except Exception as e:
            logger.warning("Failed to process image: %s", e)

    # Add text content — prefix with send timestamp so the model can see when
    # the newly arrived message was sent, matching the [timestamp] prefix we
    # inject on historical messages above.
    from zoneinfo import ZoneInfo
    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")
    send_timestamp = bangkok_now_iso()
    if content:
        current_parts.append(types.Part(text=f"[{send_timestamp}] {content}"))

    contents.append(types.Content(role="user", parts=current_parts))

    # Build config with realtime datetime and context

    # Build unrestricted mode injection if enabled
    unrestricted_injection = ""
    allow_unrestricted = os.getenv("DASHBOARD_ALLOW_UNRESTRICTED", "").lower() in ("1", "true", "yes")
    if unrestricted_mode and allow_unrestricted:
        # Use the preset's own unrestricted framing; fall back to GENERAL if not defined
        framing = preset.get("unrestricted_framing") or GENERAL_UNRESTRICTED_FRAMING or ENI_ESCALATION_FRAMING
        if framing:
            unrestricted_injection = f"\n\n[Session Mode]\n{framing}\n"
        logger.info("🔓 Unrestricted Mode: ENABLED")

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
NOTE: User messages (both historical and the current one) may be prefixed with timestamps like [2026-03-25T14:30:22]. These are system-injected metadata indicating when each message was sent. Do NOT include such timestamp prefixes in your own responses. Use them only to understand the timing context of the conversation.
"""

    config = types.GenerateContentConfig(
        system_instruction=full_context,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),  # type: ignore[arg-type]
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),  # type: ignore[arg-type]
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),  # type: ignore[arg-type]
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),  # type: ignore[arg-type]
        ],
    )

    # Add Google Search if enabled (cannot use with thinking mode)
    mode_info: list[str] = []

    # Image retrieval tool: lets AI request historical images from DB on demand
    _function_tools: list[types.FunctionDeclaration] = []
    if DB_AVAILABLE and conversation_id:
        _function_tools.append(types.FunctionDeclaration(
            name="get_message_images",
            description=(
                "Retrieve images from a previous message in this conversation. "
                "Call this when the user references an image they shared earlier, "
                "or when you need to see a previously sent image to answer their question. "
                "The message_id is shown as [message_id=X] in the conversation history."
            ),
            parameters=types.Schema(
                type="OBJECT",  # type: ignore[arg-type]
                properties={
                    "message_id": types.Schema(
                        type="INTEGER",  # type: ignore[arg-type]
                        description="The numeric ID of the message that contains the images",
                    )
                },
                required=["message_id"],
            ),
        ))

    _custom_tools = types.Tool(function_declarations=_function_tools) if _function_tools else None

    if use_search and not thinking_enabled:
        # Google Search grounding — custom tools are incompatible alongside it
        config.tools = [types.Tool(google_search=types.GoogleSearch())]
        mode_info.append("🔍 Google Search")
        logger.info("🔍 Google Search: ENABLED")
    elif _custom_tools and not thinking_enabled:
        # Custom function tools — only when search and thinking are off
        config.tools = [_custom_tools]
    if thinking_enabled:
        config.thinking_config = types.ThinkingConfig(
            thinking_budget=22000,
            include_thoughts=True
        )
        mode_info.append("🧠 Thinking")
        logger.info("🧠 Thinking Mode: ENABLED (includeThoughts=True)")
    if unrestricted_mode:
        mode_info.append("🔓 Unrestricted")
    if images:
        mode_info.append(f"🖼️ {len(images)} image(s)")

    # Use the configured model (gemini-3.1-pro-preview supports thinking)
    logger.info("📍 Using model: %s, Thinking: %s", GEMINI_MODEL, thinking_enabled)

    # Build model display name (e.g. "gemini-3.1-pro-preview" -> "Gemini 3.1 Pro")
    _model_display = GEMINI_MODEL.replace("gemini-", "Gemini ").replace("-preview", "").replace("-", " ").title()
    mode_info.insert(0, f"🤖 {_model_display}")

    # Store mode string for saving to DB
    mode_str = " • ".join(mode_info)

    # Stream response (loop handles function-calling tool rounds)
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
        input_tokens = 0
        output_tokens = 0
        # Strip a leading ``[ISO-timestamp]`` that models occasionally echo
        # from the user turn's timestamp prefix.
        ts_stripper = LeadingTimestampStripper()

        _MAX_TOOL_ROUNDS = 3
        for _tool_round in range(_MAX_TOOL_ROUNDS + 1):
            _tool_calls: list[Any] = []
            _model_parts: list[types.Part] = []

            logger.info("🚀 Starting Gemini stream (round %d)...", _tool_round + 1)
            stream = await asyncio.wait_for(
                gemini_client.aio.models.generate_content_stream(
                    model=GEMINI_MODEL,
                    contents=contents,  # type: ignore[arg-type]
                    config=config,
                ),
                timeout=60.0,
            )
            logger.info("✅ Stream object received: %s", type(stream))

            if stream is None:
                raise ValueError("Failed to start streaming - no response from AI")

            async def _consume_stream(stream=stream, _tool_calls=_tool_calls, _model_parts=_model_parts):
                """Consume the stream, collecting text/thinking chunks and any tool calls."""
                nonlocal full_response, thinking_content, chunks_count, is_thinking, input_tokens, output_tokens

                async for chunk in stream:
                    chunk_text = ""
                    chunk_thinking = ""

                    logger.debug("Chunk type: %s, attrs: %s", type(chunk), dir(chunk))

                    if hasattr(chunk, "candidates") and chunk.candidates:
                        for candidate in chunk.candidates:
                            if hasattr(candidate, "content") and candidate.content:
                                parts = getattr(candidate.content, "parts", None)
                                if parts:
                                    for part in parts:
                                        logger.debug("Part attrs: %s", dir(part))

                                        # Detect function calls (tool use)
                                        fc = getattr(part, "function_call", None)
                                        if fc is not None:
                                            _tool_calls.append(fc)
                                            _model_parts.append(part)
                                            logger.info("🔧 Tool call requested: %s(%s)", fc.name, dict(fc.args or {}))
                                            continue

                                        thought_val = getattr(part, 'thought', None)
                                        text_val = getattr(part, 'text', None)
                                        if thought_val is not None or chunks_count < 3:
                                            logger.info("🔍 Chunk#%s Part: thought=%s, text=%r", chunks_count, thought_val, text_val[:50] if text_val else None)

                                        thought_text = ""
                                        is_thought_part = False

                                        thought_flag = getattr(part, 'thought', None)

                                        if thought_flag is True:
                                            is_thought_part = True
                                            if hasattr(part, 'text') and part.text:
                                                thought_text = part.text
                                                logger.info("💭 Found thought part: %s chars", len(thought_text))
                                        elif thought_flag and isinstance(thought_flag, str):
                                            is_thought_part = True
                                            thought_text = thought_flag
                                            logger.info("💭 Found thought string: %s chars", len(thought_text))

                                        if thought_text:
                                            chunk_thinking += thought_text
                                        elif not is_thought_part and hasattr(part, "text") and part.text:
                                            chunk_text += part.text
                                            _model_parts.append(part)
                    elif hasattr(chunk, "text") and chunk.text:
                        chunk_text = chunk.text
                        _model_parts.append(types.Part(text=chunk.text))

                    # Send thinking content
                    if chunk_thinking and thinking_enabled:
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
                        safe_text = ts_stripper.feed(chunk_text)
                        if safe_text:
                            full_response += safe_text
                            chunks_count += 1
                            await ws.send_json({
                                "type": "chunk",
                                "content": safe_text,
                                "conversation_id": conversation_id,
                            })

                    # Extract token usage from Gemini usage_metadata
                    usage_meta = getattr(chunk, "usage_metadata", None)
                    if usage_meta:
                        _in = getattr(usage_meta, "prompt_token_count", 0)
                        _out = getattr(usage_meta, "candidates_token_count", 0)
                        if _in:
                            input_tokens = _in
                        if _out:
                            output_tokens = _out

            await asyncio.wait_for(_consume_stream(), timeout=stream_timeout)

            # No tool calls → normal completion, exit loop
            if not _tool_calls:
                break

            # Append model's function-call turn to contents
            if _model_parts:
                contents.append(types.Content(role="model", parts=_model_parts))

            # Execute each tool call and build tool response content
            _response_parts: list[types.Part] = []
            for tc in _tool_calls:
                if tc.name == "get_message_images":
                    try:
                        msg_id = int((tc.args or {}).get("message_id", 0))
                    except (TypeError, ValueError):
                        _response_parts.append(types.Part(function_response=types.FunctionResponse(
                            name="get_message_images",
                            response={"error": "Invalid message_id argument"},
                        )))
                        continue

                    logger.info("📷 Fetching historical images for message_id=%s", msg_id)
                    try:
                        db = _get_db()
                        all_msgs = await db.get_dashboard_messages(conversation_id)
                        hist_msg = next((m for m in all_msgs if m.get("id") == msg_id), None)
                        if not hist_msg or not hist_msg.get("images"):
                            _response_parts.append(types.Part(function_response=types.FunctionResponse(
                                name="get_message_images",
                                response={"error": f"No images found for message_id={msg_id}"},
                            )))
                        else:
                            _response_parts.append(types.Part(function_response=types.FunctionResponse(
                                name="get_message_images",
                                response={"status": "success", "image_count": len(hist_msg["images"])},
                            )))
                            for img_data in hist_msg["images"]:
                                try:
                                    if "," in img_data:
                                        header, b64_data = img_data.split(",", 1)
                                        mime_type = header.split(";")[0].split(":")[1] if ":" in header else "image/png"
                                    else:
                                        b64_data = img_data
                                        mime_type = "image/png"
                                    image_bytes = base64.b64decode(b64_data, validate=True)
                                    _response_parts.append(types.Part(
                                        inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
                                    ))
                                except Exception as img_err:
                                    logger.warning("Failed to decode historical image: %s", img_err)
                            logger.info("📷 Retrieved %d image(s) for message_id=%s", len(hist_msg["images"]), msg_id)
                    except Exception as e:
                        logger.warning("Failed to fetch images for message_id=%s: %s", msg_id, e)
                        _response_parts.append(types.Part(function_response=types.FunctionResponse(
                            name="get_message_images",
                            response={"error": str(e)},
                        )))
                else:
                    _response_parts.append(types.Part(function_response=types.FunctionResponse(
                        name=tc.name,
                        response={"error": "Unknown tool"},
                    )))

            if not _response_parts:
                break
            contents.append(types.Content(role="user", parts=_response_parts))
            # Continue loop → next stream round with tool results in context

        # Flush residual buffered text and defensively strip any prefix that slipped through.
        tail = ts_stripper.flush()
        if tail:
            full_response += tail
            chunks_count += 1
            await ws.send_json({
                "type": "chunk",
                "content": tail,
                "conversation_id": conversation_id,
            })
        full_response = strip_leading_timestamp(full_response)

        # Fallback: estimate tokens from content if API didn't return usage
        if not input_tokens:
            input_text = full_context
            for c in contents:
                parts = getattr(c, "parts", []) or []
                for p in parts:
                    t = getattr(p, "text", None)
                    if t:
                        input_text += t
            input_tokens = max(1, len(input_text) // 3)
        if not output_tokens:
            out_text = full_response + thinking_content
            output_tokens = max(1, len(out_text) // 3)

        # Save assistant message to DB
        assistant_msg_id: int = 0
        if DB_AVAILABLE and conversation_id and full_response:
            try:
                db = _get_db()
                assistant_msg_id = await db.save_dashboard_message(
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
                        logger.info("📝 Set title from user message: %s", title)

            except Exception as e:
                logger.warning("Failed to save assistant message: %s", e)

        await ws.send_json({
            "type": "stream_end",
            "conversation_id": conversation_id,
            "full_response": full_response,
            "chunks_count": chunks_count,
            "user_message_id": user_msg_id or None,
            "assistant_message_id": assistant_msg_id or None,
            "token_usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "context_window": GEMINI_CONTEXT_WINDOW,
            },
        })

    except TimeoutError:
        logger.error("❌ Streaming timeout after %ss", stream_timeout)
        try:
            await ws.send_json({
                "type": "error",
                "message": "Response timed out. Please try again.",
                "conversation_id": conversation_id,
            })
        except Exception:
            logger.debug("WebSocket send failed during timeout handling, client may have disconnected")
    except Exception:
        logger.exception("❌ Streaming error")
        try:
            await ws.send_json({
                "type": "error",
                "message": "An internal error occurred while processing your request.",
                "conversation_id": conversation_id,
            })
        except Exception:
            logger.debug("WebSocket send failed during error handling, client may have disconnected")


async def handle_ai_edit_message(
    ws: WebSocketResponse,
    data: dict[str, Any],
    gemini_client: genai.Client | None,
    *,
    max_history_messages: int = 100,
    stream_timeout: int = 300,
) -> None:
    """Handle AI self-edit: AI rewrites one of its own messages based on user instruction."""
    conversation_id = data.get("conversation_id")
    target_message_id = data.get("target_message_id")
    instruction = data.get("instruction", "").strip()
    role_preset = data.get("role_preset", "general")
    thinking_enabled = data.get("thinking_enabled", False)
    user_name = data.get("user_name", "User")

    if not conversation_id or not target_message_id or not instruction:
        await ws.send_json({"type": "error", "message": "Missing data for AI edit"})
        return

    # Validate conversation_id format (defense in depth)
    if not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
        await ws.send_json({"type": "error", "message": "Invalid conversation ID format"})
        return

    # Enforce input size limits
    max_instruction_length = 10_000
    if len(instruction) > max_instruction_length:
        await ws.send_json({"type": "error", "message": f"Instruction too long (max {max_instruction_length} characters)"})
        return
    if user_name and len(str(user_name)) > 200:
        user_name = str(user_name)[:200]

    if not gemini_client:
        await ws.send_json({"type": "error", "message": "AI not available"})
        return

    if not DB_AVAILABLE:
        await ws.send_json({"type": "error", "message": "Database unavailable"})
        return

    # Load target message from DB
    try:
        db = _get_db()
        all_msgs = await db.get_dashboard_messages(conversation_id)
        target_msg = next((m for m in all_msgs if m.get("id") == int(target_message_id)), None)
    except Exception:
        logger.exception("Failed to load target message for AI edit")
        await ws.send_json({"type": "error", "message": "Failed to load message"})
        return

    if not target_msg:
        await ws.send_json({"type": "error", "message": "Target message not found"})
        return

    if target_msg.get("role") != "assistant":
        await ws.send_json({"type": "error", "message": "Can only AI-edit assistant messages"})
        return

    original_content = target_msg.get("content", "")
    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])

    # Build context
    user_context, memories_context, _ = await build_user_context(user_name, False)

    # Build edit prompt
    edit_prompt = (
        "Please edit/rewrite the following message according to the user's instruction.\n\n"
        f"[User's Edit Instruction]\n{instruction}\n\n"
        f"[Original Message to Edit]\n{original_content}\n\n"
        "Rewrite the message following the instruction above. "
        "Output ONLY the edited message content, no explanations or meta-commentary."
    )

    # Build contents with conversation history for context (up to the target message)
    contents: list[Any] = []
    target_idx = next((i for i, m in enumerate(all_msgs) if m.get("id") == int(target_message_id)), -1)
    if target_idx > 0:
        hist = all_msgs[:target_idx]
        if len(hist) > max_history_messages:
            hist = hist[-max_history_messages:]
        for msg in hist:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg.get("content", ""))]))

    contents.append(types.Content(role="user", parts=[types.Part(text=edit_prompt)]))

    # Build config
    from zoneinfo import ZoneInfo
    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

    full_context = (
        f"{preset['system_instruction']}\n"
        f"[System Context]\n{user_context}\n"
        f"Current Time: {current_time_str} (ICT)\n"
        f"{memories_context}"
    )

    config = types.GenerateContentConfig(
        system_instruction=full_context,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),  # type: ignore[arg-type]
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),  # type: ignore[arg-type]
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),  # type: ignore[arg-type]
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),  # type: ignore[arg-type]
        ],
    )

    if thinking_enabled:
        config.thinking_config = types.ThinkingConfig(thinking_budget=22000, include_thoughts=True)

    # Build mode info
    mode_info: list[str] = []
    _model_display = GEMINI_MODEL.replace("gemini-", "Gemini ").replace("-preview", "").replace("-", " ").title()
    mode_info.append(f"🤖 {_model_display}")
    mode_info.append("✏️ AI Edit")
    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    mode_str = " • ".join(mode_info)

    # Stream response
    try:
        await ws.send_json({
            "type": "stream_start",
            "conversation_id": conversation_id,
            "mode": mode_str,
            "is_edit": True,
            "target_message_id": int(target_message_id),
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
            raise ValueError("Failed to start streaming")

        async def _consume_edit_stream(stream=stream):
            nonlocal full_response, thinking_content, chunks_count, is_thinking

            async for chunk in stream:
                chunk_text = ""
                chunk_thinking = ""

                if hasattr(chunk, "candidates") and chunk.candidates:
                    for candidate in chunk.candidates:
                        if hasattr(candidate, "content") and candidate.content:
                            parts = getattr(candidate.content, "parts", None)
                            if parts:
                                for part in parts:
                                    thought_flag = getattr(part, 'thought', None)
                                    if thought_flag is True and hasattr(part, 'text') and part.text:
                                        chunk_thinking += part.text
                                    elif not thought_flag and hasattr(part, "text") and part.text:
                                        chunk_text += part.text
                elif hasattr(chunk, "text") and chunk.text:
                    chunk_text = chunk.text

                if chunk_thinking and thinking_enabled:
                    if not is_thinking:
                        is_thinking = True
                        await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})
                    thinking_content += chunk_thinking
                    await ws.send_json({"type": "thinking_chunk", "content": chunk_thinking, "conversation_id": conversation_id})

                if chunk_text:
                    if is_thinking:
                        is_thinking = False
                        await ws.send_json({"type": "thinking_end", "conversation_id": conversation_id, "full_thinking": thinking_content})
                    full_response += chunk_text
                    chunks_count += 1
                    await ws.send_json({"type": "chunk", "content": chunk_text, "conversation_id": conversation_id})

        await asyncio.wait_for(_consume_edit_stream(), timeout=stream_timeout)

        # Update the message in DB
        if full_response:
            try:
                db = _get_db()
                await db.update_dashboard_message(int(target_message_id), full_response)
            except Exception as e:
                logger.warning("Failed to update AI-edited message in DB: %s", e)

        await ws.send_json({
            "type": "stream_end",
            "conversation_id": conversation_id,
            "full_response": full_response,
            "chunks_count": chunks_count,
            "is_edit": True,
            "target_message_id": int(target_message_id),
        })

    except TimeoutError:
        logger.error("❌ AI edit streaming timeout")
        try:
            await ws.send_json({"type": "error", "message": "Edit timed out. Please try again.", "conversation_id": conversation_id})
        except Exception:
            logger.debug("WebSocket send failed during AI edit timeout handling")
    except Exception:
        logger.exception("❌ AI edit streaming error")
        try:
            await ws.send_json({"type": "error", "message": "Failed to edit message.", "conversation_id": conversation_id})
        except Exception:
            logger.debug("WebSocket send failed during AI edit error handling")
