"""
Dashboard AI chat streaming handler for Claude (Anthropic).

Mirrors the Gemini handler (dashboard_chat.py) but uses the Anthropic SDK.
Supports streaming, adaptive thinking, and image input.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
logger = logging.getLogger(__name__)
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

import anthropic
from anthropic.types.message_param import MessageParam

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# API Failover integration
try:
    from .api_failover import api_failover as _api_failover
    _FAILOVER_AVAILABLE = True
except Exception:
    _FAILOVER_AVAILABLE = False
    _api_failover = None  # type: ignore[assignment]

# Retryable errors: overloaded (529) and rate limit (429)
_RETRYABLE_ERRORS = (anthropic.InternalServerError, anthropic.RateLimitError)
_RETRY_BASE_DELAY = 2  # seconds
_RETRY_MAX_DELAY = 30  # seconds

# Claude API hard limit for images
_CLAUDE_IMAGE_LIMIT = 5 * 1024 * 1024  # 5MB


def _compress_image_for_claude(image_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    """Compress an image to fit within Claude's 5MB limit.

    Returns (compressed_bytes, mime_type). If already under the limit, returns as-is.
    """
    if len(image_bytes) <= _CLAUDE_IMAGE_LIMIT:
        return image_bytes, mime_type

    from PIL import Image

    img: Image.Image = Image.open(io.BytesIO(image_bytes))

    # Convert RGBA/palette to RGB for JPEG output
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Try progressively lower quality
    for quality in (90, 80, 70, 55, 40):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        if buf.tell() <= _CLAUDE_IMAGE_LIMIT:
            logger.info("📷 Compressed image from %s to %s bytes (quality=%d)", len(image_bytes), buf.tell(), quality)
            return buf.getvalue(), "image/jpeg"

    # Still too large — downscale
    scale = 0.75
    for _ in range(5):
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        resized: Image.Image = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=60, optimize=True)
        if buf.tell() <= _CLAUDE_IMAGE_LIMIT:
            logger.info("📷 Compressed+resized image from %s to %s bytes (%dx%d)", len(image_bytes), buf.tell(), new_w, new_h)
            return buf.getvalue(), "image/jpeg"
        scale *= 0.75

    # Last resort: return whatever we got
    return buf.getvalue(), "image/jpeg"


def _apply_search_replace(original: str, ai_response: str) -> str:
    """Apply SEARCH/REPLACE blocks from AI response to original text.

    If the response contains <<<SEARCH ... >>> <<<REPLACE ... >>> blocks,
    apply them as patches. Otherwise return ai_response as-is (full rewrite).
    """
    pattern = re.compile(
        r"<<<SEARCH\s*\n(.*?)\n?>>>\s*\n<<<REPLACE\s*\n(.*?)\n?>>>",
        re.DOTALL,
    )
    matches = list(pattern.finditer(ai_response))

    if not matches:
        # No search/replace blocks — treat as full rewrite
        return ai_response

    result = original
    applied = 0
    for m in matches:
        search_text = m.group(1)
        replace_text = m.group(2)
        if search_text in result:
            result = result.replace(search_text, replace_text, 1)
            applied += 1
        else:
            # Try with stripped whitespace as fallback
            search_stripped = search_text.strip()
            if search_stripped and search_stripped in result:
                result = result.replace(search_stripped, replace_text.strip(), 1)
                applied += 1
            else:
                logger.warning("AI Edit: SEARCH block not found in original: %r", search_text[:100])

    if applied > 0:
        logger.info("📝 AI Edit applied %d/%d search/replace patches", applied, len(matches))
        return result
    else:
        # None matched — fall back to treating full response as rewrite
        logger.warning("📝 AI Edit: no patches matched, using full response as fallback")
        return ai_response


def _retry_delay_seconds(attempt: int) -> int:
    delay = _RETRY_BASE_DELAY
    for _ in range(1, attempt):
        if delay >= _RETRY_MAX_DELAY:
            break
        delay = min(delay * 2, _RETRY_MAX_DELAY)
    return delay

from ..claude_payloads import (
    CLAUDE_IMAGE_MEDIA_TYPES,
    ClaudeContentBlockParam,
    ClaudeMessageRole,
    build_cached_system_prompt,
    build_claude_base64_image_block,
    build_claude_message,
    build_claude_text_block,
)
from .dashboard_common import (
    LeadingTimestampStripper,
    bangkok_now_iso,
    build_user_context,
    get_db as _get_db,
    normalize_timestamp_to_bangkok,
    strip_leading_timestamp,
)
from .dashboard_config import (
    CLAUDE_CONTEXT_WINDOW,
    CLAUDE_EFFORT,
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    ENI_ESCALATION_FRAMING,
    GENERAL_UNRESTRICTED_FRAMING,
)


async def handle_chat_message_claude(
    ws: WebSocketResponse,
    data: dict[str, Any],
    claude_client: anthropic.AsyncAnthropic,
    *,
    max_content_length: int = 200_000,
    max_history_messages: int = 500,
    max_images: int = 10,
    max_image_size_bytes: int = 10 * 1024 * 1024,
    stream_timeout: int = 300,
) -> None:
    """Handle incoming chat message and stream response via Claude."""
    conversation_id = data.get("conversation_id")
    content = data.get("content", "").strip()
    role_preset = data.get("role_preset", "general")
    thinking_enabled = data.get("thinking_enabled", False)
    unrestricted_mode_requested = data.get("unrestricted_mode", False)
    history = data.get("history", [])
    images = data.get("images", [])
    user_name = data.get("user_name", "User")
    is_regeneration = data.get("is_regeneration", False)
    is_failover_retry = data.get("_failover_retry", False)

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

    if not claude_client:
        await ws.send_json({"type": "error", "message": "Claude AI not available"})
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

    # Build conversation messages for Claude API format
    messages: list[MessageParam] = []
    _db_history_loaded = False
    if DB_AVAILABLE and conversation_id:
        try:
            db = _get_db()
            db_msgs = await db.get_dashboard_messages(conversation_id)
            hist_msgs = db_msgs[:-1] if db_msgs and db_msgs[-1]["role"] == "user" else db_msgs
            if len(hist_msgs) > max_history_messages:
                hist_msgs = hist_msgs[-max_history_messages:]
            for msg in hist_msgs:
                role: ClaudeMessageRole = "user" if msg["role"] == "user" else "assistant"
                text = msg.get("content") or ""
                if msg.get("created_at"):
                    text = f"[{normalize_timestamp_to_bangkok(msg['created_at'])}] {text}"
                if msg.get("images"):
                    text += f"\n[User had attached {len(msg['images'])} image(s) in this message, message_id={msg['id']}]"
                messages.append(build_claude_message(role, text))
            _db_history_loaded = True
        except Exception as e:
            logger.warning("Failed to load DB history, falling back to frontend history: %s", e)

    if not _db_history_loaded:
        for msg in history:
            history_role: ClaudeMessageRole = "user" if msg.get("role") == "user" else "assistant"
            messages.append(build_claude_message(history_role, str(msg.get("content", ""))))

    # Build current message content blocks
    current_content: list[ClaudeContentBlockParam] = []

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
            _ALLOWED_IMAGE_MIMES = set(CLAUDE_IMAGE_MEDIA_TYPES)
            if mime_type not in _ALLOWED_IMAGE_MIMES:
                logger.warning("Rejected image with disallowed MIME type: %s", mime_type)
                await ws.send_json({"type": "error", "message": f"Unsupported image type: {mime_type}"})
                continue

            # Validate base64 string length BEFORE decoding to prevent memory exhaustion
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

            # Compress if exceeding Claude's 5MB API limit
            image_bytes, mime_type = _compress_image_for_claude(image_bytes, mime_type)
            b64_data = base64.b64encode(image_bytes).decode("ascii")

            image_block = build_claude_base64_image_block(b64_data, mime_type)
            if image_block is None:
                logger.warning("Rejected image with Claude-unsupported MIME type: %s", mime_type)
                await ws.send_json({"type": "error", "message": f"Unsupported image type: {mime_type}"})
                continue
            current_content.append(image_block)
            logger.info("📷 Added image to Claude message (%s bytes)", len(image_bytes))
        except Exception as e:
            logger.warning("Failed to process image: %s", e)

    # Add text content — prefix with send timestamp so Claude sees when the
    # newly arrived message was sent, matching the [timestamp] prefix on
    # historical messages above.
    from zoneinfo import ZoneInfo
    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")
    send_timestamp = bangkok_now_iso()
    stamped_content = f"[{send_timestamp}] {content}" if content else content
    if stamped_content:
        current_content.append(build_claude_text_block(stamped_content))

    if not current_content and not stamped_content:
        await ws.send_json({
            "type": "error",
            "message": "Message contains no supported text or images",
        })
        return

    messages.append(build_claude_message(
        "user", current_content if current_content else stamped_content,
    ))

    # Build system prompt

    # Build unrestricted mode injection if enabled
    unrestricted_injection = ""
    allow_unrestricted = os.getenv("DASHBOARD_ALLOW_UNRESTRICTED", "").lower() in ("1", "true", "yes")
    if unrestricted_mode and allow_unrestricted:
        framing = preset.get("unrestricted_framing") or GENERAL_UNRESTRICTED_FRAMING or ENI_ESCALATION_FRAMING
        if framing:
            unrestricted_injection = f"\n\n[Session Mode]\n{framing}\n"
        logger.info("🔓 Unrestricted Mode: ENABLED")

    thinking_prompt_enhancement = ""
    if thinking_enabled:
        thinking_prompt_enhancement = "\n[REASONING DIRECTIVE]\nPlease provide a thorough internal thought process before each response. Analyze the user's intent, context, and potential responses step-by-step regardless of the query's complexity."

    system_prompt = f"""{preset["system_instruction"]}
{unrestricted_injection}
{thinking_prompt_enhancement}
[System Context]
{user_context}
Current Time: {current_time_str} (ICT)
{memories_context}

IMPORTANT: If user asks you to remember something, respond with the information you'll remember. The system will automatically save important facts.
NOTE: User messages (both historical and the current one) may be prefixed with timestamps like [2026-03-25T14:30:22]. These are system-injected metadata indicating when each message was sent. Do NOT include such timestamp prefixes in your own responses. Use them only to understand the timing context of the conversation."""

    # Build mode info for display
    mode_info: list[str] = []

    _model_display = CLAUDE_MODEL.replace("claude-", "Claude ").replace("-", " ").title()
    mode_info.insert(0, f"🟣 {_model_display}")

    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    if unrestricted_mode:
        mode_info.append("🔓 Unrestricted")
    if images:
        mode_info.append(f"🖼️ {len(images)} image(s)")

    mode_str = " • ".join(mode_info)

    logger.info("📍 Using Claude model: %s, Thinking: %s", CLAUDE_MODEL, thinking_enabled)

    # Build API kwargs
    # Prompt caching (Hybrid strategy):
    # - Explicit cache_control on system: persona/role/memory prefix is stable,
    #   so pin it with a dedicated breakpoint -> guaranteed cache hits.
    # - Top-level cache_control: automatic caching lets Anthropic move the
    #   breakpoint forward along the growing message history each turn.
    # Together this caches the full (system + prior history) prefix for ~5 min
    # and bills only the latest user turn at full input price.
    api_kwargs: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "cache_control": {"type": "ephemeral"},
        "system": build_cached_system_prompt(system_prompt),
        "messages": messages,
    }

    # Opus 4.7 effort level (low/medium/high/xhigh/max). Must be nested under
    # `output_config` per Anthropic API (per /build-with-claude/effort docs).
    # Only forwarded when explicitly configured so older models are unaffected.
    if CLAUDE_EFFORT:
        api_kwargs["output_config"] = {"effort": CLAUDE_EFFORT}

    # Thinking config:
    # - Opus 4.7 REJECTS `type: "enabled"` with budget_tokens. Use adaptive
    #   thinking instead; effort controls thinking depth.
    # - Older models (Opus 4.6, Sonnet 4.6, Opus 4.5) still accept the
    #   enabled+budget_tokens form, kept for backward compatibility.
    if thinking_enabled:
        _model_lower = CLAUDE_MODEL.lower()
        if "opus-4-7" in _model_lower or "mythos" in _model_lower:
            api_kwargs["thinking"] = {"type": "adaptive"}
        else:
            _think_budget = min(32000, CLAUDE_MAX_TOKENS - 1024)
            api_kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(_think_budget, 1024)}

    # Stream response
    try:
        stream_start_msg: dict[str, Any] = {
            "type": "stream_start",
            "conversation_id": conversation_id,
            "mode": mode_str,
        }
        if is_failover_retry:
            stream_start_msg["_failover_retry"] = True
        await ws.send_json(stream_start_msg)

        full_response = ""
        thinking_content = ""
        chunks_count = 0
        is_thinking = False
        input_tokens = 0
        output_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
        # Strip a leading ``[ISO-timestamp]`` that models sometimes echo from
        # the user turn. Stateful so we can defer the first chunks until we
        # know whether the response starts with such a prefix.
        ts_stripper = LeadingTimestampStripper()

        async def _stream_once() -> None:
            nonlocal full_response, thinking_content, chunks_count, is_thinking, input_tokens, output_tokens
            nonlocal cache_creation_tokens, cache_read_tokens

            async with claude_client.messages.stream(**api_kwargs) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", "")

                    # Extract token usage from message lifecycle events
                    if event_type == "message_start":
                        msg = getattr(event, "message", None)
                        if msg:
                            usage = getattr(msg, "usage", None)
                            if usage:
                                input_tokens = getattr(usage, "input_tokens", 0)
                                cache_creation_tokens = (
                                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                                )
                                cache_read_tokens = (
                                    getattr(usage, "cache_read_input_tokens", 0) or 0
                                )

                    elif event_type == "message_delta":
                        usage = getattr(event, "usage", None)
                        if usage:
                            output_tokens = getattr(usage, "output_tokens", 0)

                    elif event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "thinking":
                            if not is_thinking and thinking_enabled:
                                is_thinking = True
                                await ws.send_json({
                                    "type": "thinking_start",
                                    "conversation_id": conversation_id,
                                })

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        delta_type = getattr(delta, "type", "")

                        if delta_type == "thinking_delta":
                            thought_text = getattr(delta, "thinking", "")
                            if thought_text and thinking_enabled:
                                thinking_content += thought_text
                                await ws.send_json({
                                    "type": "thinking_chunk",
                                    "content": thought_text,
                                    "conversation_id": conversation_id,
                                })

                        elif delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                if is_thinking:
                                    is_thinking = False
                                    await ws.send_json({
                                        "type": "thinking_end",
                                        "conversation_id": conversation_id,
                                        "full_thinking": thinking_content,
                                    })
                                safe_text = ts_stripper.feed(text)
                                if safe_text:
                                    full_response += safe_text
                                    chunks_count += 1
                                    await ws.send_json({
                                        "type": "chunk",
                                        "content": safe_text,
                                        "conversation_id": conversation_id,
                                    })

                    elif event_type == "content_block_stop":
                        if is_thinking:
                            is_thinking = False
                            await ws.send_json({
                                "type": "thinking_end",
                                "conversation_id": conversation_id,
                                "full_thinking": thinking_content,
                            })

                try:
                    final_msg = await stream.get_final_message()
                    if final_msg and hasattr(final_msg, "usage") and final_msg.usage:
                        input_tokens = getattr(final_msg.usage, "input_tokens", 0) or input_tokens
                        output_tokens = getattr(final_msg.usage, "output_tokens", 0) or output_tokens
                        cache_creation_tokens = (
                            getattr(final_msg.usage, "cache_creation_input_tokens", 0)
                            or cache_creation_tokens
                        )
                        cache_read_tokens = (
                            getattr(final_msg.usage, "cache_read_input_tokens", 0)
                            or cache_read_tokens
                        )
                except Exception:
                    pass

        _MAX_STREAM_RETRIES = 6
        _MAX_RESPONSE_SIZE = 500_000  # 500KB cap to prevent unbounded accumulation

        async def _consume_claude_stream():
            nonlocal full_response, thinking_content, chunks_count, is_thinking, input_tokens, output_tokens
            nonlocal cache_creation_tokens, cache_read_tokens
            attempt = 1
            # Save original messages to prevent accumulation on each retry
            original_messages = list(api_kwargs["messages"])

            while attempt <= _MAX_STREAM_RETRIES:
                try:
                    if stream_timeout > 0:
                        await asyncio.wait_for(_stream_once(), timeout=stream_timeout)
                    else:
                        await _stream_once()
                    return
                except _RETRYABLE_ERRORS as retry_err:
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⚠️ Claude overloaded (attempt %d), retrying in %ds: %s",
                        attempt, delay, retry_err,
                    )
                    retry_notice = f"\n\n⏳ *Server busy, retrying (attempt {attempt})...*\n\n"
                except TimeoutError:
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⏱️ Claude stream timed out on attempt %d, retrying in %ds",
                        attempt, delay,
                    )
                    retry_notice = f"\n\n⏳ *Request timed out, retrying (attempt {attempt})...*\n\n"

                # Send retry notice to frontend (appends to current streaming bubble)
                await ws.send_json({
                    "type": "chunk",
                    "content": retry_notice,
                    "conversation_id": conversation_id,
                })

                # Prefill: inject partial response so Claude continues from where it stopped
                partial = full_response
                # Cap accumulated response size to prevent unbounded memory growth
                if len(partial) > _MAX_RESPONSE_SIZE:
                    logger.warning("⚠️ Claude stream response exceeded %d chars, stopping retries", _MAX_RESPONSE_SIZE)
                    break
                # Reset only counters, keep full_response accumulating
                thinking_content = ""
                chunks_count = 0
                is_thinking = False
                input_tokens = 0
                output_tokens = 0

                if partial:
                    if thinking_enabled:
                        # Thinking mode doesn't support assistant prefill —
                        # ask Claude to continue via a user message with the partial text.
                        # Always rebuild from original_messages to prevent accumulation.
                        api_kwargs["messages"] = [
                            *original_messages,
                            {"role": "assistant", "content": partial},
                            {"role": "user", "content": (
                                "Your previous response was interrupted mid-stream. "
                                "The text above is what you had written so far. "
                                "Continue writing from EXACTLY where you left off. "
                                "Do NOT repeat any of the text above — only output the continuation."
                            )},
                        ]
                        # Disable thinking for continuation to avoid repetition overhead
                        api_kwargs.pop("thinking", None)
                    else:
                        # Non-thinking mode: use standard assistant prefill
                        # Always rebuild from original_messages to prevent accumulation.
                        api_kwargs["messages"] = [
                            *original_messages,
                            {"role": "assistant", "content": partial},
                        ]

                attempt += 1
                await asyncio.sleep(delay)

            # All retries exhausted
            logger.error("💀 Claude dashboard stream retries exhausted after %d attempts", attempt - 1)

        await _consume_claude_stream()

        # Log prompt-caching effectiveness for this request. A healthy
        # cache_read_tokens value means Anthropic reused the cached prefix
        # (~90% cost reduction on those tokens).
        if cache_creation_tokens or cache_read_tokens:
            logger.info(
                "💾 Prompt cache: read=%s, created=%s, fresh_input=%s, output=%s",
                cache_read_tokens, cache_creation_tokens, input_tokens, output_tokens,
            )

        # Flush any residual buffered text from the leading-timestamp stripper.
        tail = ts_stripper.flush()
        if tail:
            full_response += tail
            chunks_count += 1
            await ws.send_json({
                "type": "chunk",
                "content": tail,
                "conversation_id": conversation_id,
            })
        # Defense in depth: also strip if a prefix slipped through (e.g. after
        # a retry reset or split exactly at the probe boundary).
        full_response = strip_leading_timestamp(full_response)

        # Strip <think>...</think> from full_response (proxy may embed thinking in text)
        think_match = re.search(r'<think>(.*?)</think>', full_response, re.DOTALL)
        if think_match:
            if not thinking_content:
                thinking_content = think_match.group(1).strip()
            full_response = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL).strip()

        # Fallback: estimate tokens from content if API didn't return usage
        if not input_tokens:
            # Estimate input tokens from system prompt + conversation history
            input_text = system_prompt
            for msg in messages:
                c = msg.get("content", "")
                if isinstance(c, str):
                    input_text += c
                elif isinstance(c, list):
                    for block in c:
                        if isinstance(block, dict) and block.get("type") == "text":
                            input_text += block.get("text", "")
            # ~3 chars/token for mixed Thai/English with Claude tokenizer
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
                    mode=mode_str,
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
                "cache_creation_input_tokens": cache_creation_tokens,
                "cache_read_input_tokens": cache_read_tokens,
                "context_window": CLAUDE_CONTEXT_WINDOW,
            },
        })

        # Record success for API failover tracking
        if _FAILOVER_AVAILABLE:
            await _api_failover.record_success()

    except TimeoutError:
        logger.error("❌ Claude streaming timeout after %ss", stream_timeout)
        if _FAILOVER_AVAILABLE and not is_failover_retry:
            switched = await _api_failover.record_failure(TimeoutError("stream timeout"))
            if switched:
                logger.info("🔀 Retrying with new endpoint after timeout failover...")
                try:
                    retry_data = {**data, "_failover_retry": True, "is_regeneration": True}
                    new_client = _api_failover.get_client()
                    await handle_chat_message_claude(
                        ws, retry_data, new_client,
                        max_content_length=max_content_length,
                        max_history_messages=max_history_messages,
                        max_images=max_images,
                        max_image_size_bytes=max_image_size_bytes,
                        stream_timeout=stream_timeout,
                    )
                    return
                except Exception as retry_err:
                    logger.error("❌ Retry after failover also failed: %s", retry_err)
        elif _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(TimeoutError("stream timeout"))
        try:
            await ws.send_json({
                "type": "error",
                "message": "Response timed out. Please try again.",
                "conversation_id": conversation_id,
            })
        except Exception:
            logger.debug("WebSocket send failed during timeout handling, client may have disconnected")
    except Exception as e:
        error_str = str(e)
        logger.exception("❌ Claude streaming error")

        # Detect quota/billing limit — no point retrying or failing over
        if "usage limits" in error_str or "billing" in error_str.lower():
            try:
                await ws.send_json({
                    "type": "error",
                    "message": "Claude API quota reached — please switch to Gemini in the provider selector, or wait until your quota resets.",
                    "conversation_id": conversation_id,
                })
            except Exception:
                pass
            return

        if _FAILOVER_AVAILABLE and not is_failover_retry:
            switched = await _api_failover.record_failure(e)
            if switched:
                logger.info("🔀 Retrying with new endpoint after failover...")
                try:
                    retry_data = {**data, "_failover_retry": True, "is_regeneration": True}
                    new_client = _api_failover.get_client()
                    await handle_chat_message_claude(
                        ws, retry_data, new_client,
                        max_content_length=max_content_length,
                        max_history_messages=max_history_messages,
                        max_images=max_images,
                        max_image_size_bytes=max_image_size_bytes,
                        stream_timeout=stream_timeout,
                    )
                    return
                except Exception as retry_err:
                    logger.error("❌ Retry after failover also failed: %s", retry_err)
        elif _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(e)
        try:
            await ws.send_json({
                "type": "error",
                "message": "An internal error occurred while processing your request.",
                "conversation_id": conversation_id,
            })
        except Exception:
            logger.debug("WebSocket send failed during error handling, client may have disconnected")


async def handle_ai_edit_message_claude(
    ws: WebSocketResponse,
    data: dict[str, Any],
    claude_client: anthropic.AsyncAnthropic,
    *,
    max_history_messages: int = 500,
    stream_timeout: int = 300,
) -> None:
    """Handle AI self-edit via Claude: AI rewrites one of its own messages based on user instruction."""
    conversation_id = data.get("conversation_id")
    target_message_id = data.get("target_message_id")
    instruction = data.get("instruction", "").strip()
    role_preset = data.get("role_preset", "general")
    thinking_enabled = data.get("thinking_enabled", False)
    user_name = data.get("user_name", "User")

    if not conversation_id or not target_message_id or not instruction:
        await ws.send_json({"type": "error", "message": "Missing data for AI edit"})
        return

    if not claude_client:
        await ws.send_json({"type": "error", "message": "Claude AI not available"})
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

    # Build edit prompt — use search/replace format for partial edits
    edit_prompt = (
        "Edit the following message according to the user's instruction.\n\n"
        f"[User's Edit Instruction]\n{instruction}\n\n"
        f"[Original Message]\n{original_content}\n\n"
        "RESPONSE FORMAT:\n"
        "If the edit is a PARTIAL change (only some parts need to change), respond using SEARCH/REPLACE blocks:\n"
        "<<<SEARCH\n"
        "exact text to find\n"
        ">>>\n"
        "<<<REPLACE\n"
        "new text to replace with\n"
        ">>>\n\n"
        "You can use multiple SEARCH/REPLACE blocks for multiple changes.\n"
        "The SEARCH text must be an EXACT substring from the original message (including whitespace and formatting).\n\n"
        "If the edit requires a FULL rewrite (e.g., 'rewrite everything', 'change the tone completely', 'translate'), "
        "respond with JUST the new message content directly (no SEARCH/REPLACE blocks).\n\n"
        "RULES:\n"
        "- For partial edits: use SEARCH/REPLACE blocks. Only include the parts that change.\n"
        "- For full rewrites: output the complete new message directly.\n"
        "- No explanations or meta-commentary."
    )

    # Build messages with conversation history for context
    messages: list[MessageParam] = []
    target_idx = next((i for i, m in enumerate(all_msgs) if m.get("id") == int(target_message_id)), -1)
    if target_idx > 0:
        hist = all_msgs[:target_idx]
        if len(hist) > max_history_messages:
            hist = hist[-max_history_messages:]
        for msg in hist:
            role: ClaudeMessageRole = "user" if msg["role"] == "user" else "assistant"
            messages.append(build_claude_message(role, str(msg.get("content", ""))))

    messages.append(build_claude_message("user", edit_prompt))

    # Build system prompt
    from zoneinfo import ZoneInfo
    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

    system_prompt = (
        f"{preset['system_instruction']}\n"
        f"[System Context]\n{user_context}\n"
        f"Current Time: {current_time_str} (ICT)\n"
        f"{memories_context}"
    )

    # Build mode info
    mode_info: list[str] = []
    _model_display = CLAUDE_MODEL.replace("claude-", "Claude ").replace("-", " ").title()
    mode_info.append(f"🟣 {_model_display}")
    mode_info.append("✏️ AI Edit")
    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    mode_str = " • ".join(mode_info)

    # Build API kwargs (Hybrid prompt caching: explicit system + auto history).
    api_kwargs: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "cache_control": {"type": "ephemeral"},
        "system": build_cached_system_prompt(system_prompt),
        "messages": messages,
    }

    if CLAUDE_EFFORT:
        api_kwargs["output_config"] = {"effort": CLAUDE_EFFORT}

    if thinking_enabled:
        _model_lower = CLAUDE_MODEL.lower()
        if "opus-4-7" in _model_lower or "mythos" in _model_lower:
            api_kwargs["thinking"] = {"type": "adaptive"}
        else:
            _think_budget = min(32000, CLAUDE_MAX_TOKENS - 1024)
            api_kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(_think_budget, 1024)}

    logger.info("📍 AI Edit via Claude model: %s", CLAUDE_MODEL)

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

        def _reset_stream_state() -> None:
            nonlocal full_response, thinking_content, chunks_count, is_thinking
            full_response = ""
            thinking_content = ""
            chunks_count = 0
            is_thinking = False

        async def _stream_once() -> None:
            nonlocal full_response, thinking_content, chunks_count, is_thinking

            async with claude_client.messages.stream(**api_kwargs) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "thinking":
                            if not is_thinking and thinking_enabled:
                                is_thinking = True
                                await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        delta_type = getattr(delta, "type", "")

                        if delta_type == "thinking_delta":
                            thought_text = getattr(delta, "thinking", "")
                            if thought_text and thinking_enabled:
                                thinking_content += thought_text
                                await ws.send_json({"type": "thinking_chunk", "content": thought_text, "conversation_id": conversation_id})

                        elif delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                if is_thinking:
                                    is_thinking = False
                                    await ws.send_json({"type": "thinking_end", "conversation_id": conversation_id, "full_thinking": thinking_content})
                                full_response += text
                                chunks_count += 1
                                await ws.send_json({"type": "chunk", "content": text, "conversation_id": conversation_id})

                    elif event_type == "content_block_stop":
                        if is_thinking:
                            is_thinking = False
                            await ws.send_json({"type": "thinking_end", "conversation_id": conversation_id, "full_thinking": thinking_content})

        _MAX_EDIT_RETRIES = 6

        async def _consume_claude_edit_stream():
            attempt = 1

            while attempt <= _MAX_EDIT_RETRIES:
                try:
                    if stream_timeout > 0:
                        await asyncio.wait_for(_stream_once(), timeout=stream_timeout)
                    else:
                        await _stream_once()
                    return
                except _RETRYABLE_ERRORS as retry_err:
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⚠️ Claude AI edit overloaded (attempt %d), retrying in %ds: %s",
                        attempt, delay, retry_err,
                    )
                    await ws.send_json({
                        "type": "chunk",
                        "content": f"\n\n⏳ *Server busy, retrying (attempt {attempt})...*\n\n",
                        "conversation_id": conversation_id,
                    })
                except TimeoutError:
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⏱️ Claude AI edit stream timed out on attempt %d, retrying in %ds",
                        attempt, delay,
                    )
                    await ws.send_json({
                        "type": "chunk",
                        "content": f"\n\n⏳ *Request timed out, retrying (attempt {attempt})...*\n\n",
                        "conversation_id": conversation_id,
                    })

                _reset_stream_state()
                attempt += 1
                await asyncio.sleep(delay)

            # All retries exhausted
            logger.error("💀 Claude AI edit stream retries exhausted after %d attempts", attempt - 1)

        await _consume_claude_edit_stream()

        # Apply search/replace patches if present, otherwise use full response
        final_content = _apply_search_replace(original_content, full_response) if full_response else ""

        # Update the message in DB
        if final_content:
            try:
                db = _get_db()
                await db.update_dashboard_message(int(target_message_id), final_content)
            except Exception as e:
                logger.warning("Failed to update AI-edited message in DB: %s", e)

        await ws.send_json({
            "type": "stream_end",
            "conversation_id": conversation_id,
            "full_response": final_content,
            "chunks_count": chunks_count,
            "is_edit": True,
            "target_message_id": int(target_message_id),
        })

        if _FAILOVER_AVAILABLE:
            await _api_failover.record_success()

    except TimeoutError:
        logger.error("❌ Claude AI edit streaming timeout")
        if _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(TimeoutError("edit stream timeout"))
        try:
            await ws.send_json({"type": "error", "message": "Edit timed out. Please try again.", "conversation_id": conversation_id})
        except Exception:
            logger.debug("WebSocket send failed during Claude AI edit timeout handling")
    except Exception as e:
        logger.exception("❌ Claude AI edit streaming error")
        if _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(e)
        try:
            await ws.send_json({"type": "error", "message": "Failed to edit message.", "conversation_id": conversation_id})
        except Exception:
            logger.debug("WebSocket send failed during Claude AI edit error handling")
