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
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import anthropic
from anthropic.types.message_param import MessageParam

from ..claude_payloads import (
    CLAUDE_IMAGE_MEDIA_TYPES,
    ClaudeContentBlockParam,
    ClaudeMessageRole,
    build_claude_base64_image_block,
    build_claude_message,
    build_claude_pdf_document_block,
    build_claude_text_block,
    build_claude_text_document_block,
    build_split_cached_system_prompt,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

# API Failover integration. Narrow to ``ImportError`` only — the
# previous broad ``except Exception`` silently swallowed any
# initialisation bug inside ``api_failover`` (TypeError, AttributeError,
# etc.) as "failover unavailable", so a real wiring regression would
# look like a benign disable instead of a crash that surfaces in CI.
try:
    from .api_failover import api_failover as _api_failover

    _FAILOVER_AVAILABLE = True
except ImportError:
    _FAILOVER_AVAILABLE = False
    _api_failover = None  # type: ignore[assignment]

# Retryable errors: overloaded (529), rate limit (429), and transient
# network failures. APIConnectionError covers DNS / TCP / TLS hiccups and
# APITimeoutError is what the SDK raises when its own client-side timeout
# fires before the server responds. Without these, a single flaky packet
# aborts the whole turn instead of retrying with backoff.
_RETRYABLE_ERRORS = (
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)
_RETRY_BASE_DELAY = 2  # seconds
_RETRY_MAX_DELAY = 30  # seconds

# Claude API hard limit for images
_CLAUDE_IMAGE_LIMIT = 5 * 1024 * 1024  # 5MB

# Image MIME allowlist — module-level so we don't rebuild this set inside
# the per-image validation loop on every chat turn.
_ALLOWED_IMAGE_MIMES = frozenset(CLAUDE_IMAGE_MEDIA_TYPES)

# Conversation ID validator — same shape as the dashboard_handlers one,
# duplicated here intentionally to avoid pulling that whole module in
# (circular import risk via shared handlers).
_CONVERSATION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}\Z")


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
            logger.info(
                "📷 Compressed image from %s to %s bytes (quality=%d)",
                len(image_bytes),
                buf.tell(),
                quality,
            )
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
            logger.info(
                "📷 Compressed+resized image from %s to %s bytes (%dx%d)",
                len(image_bytes),
                buf.tell(),
                new_w,
                new_h,
            )
            return buf.getvalue(), "image/jpeg"
        scale *= 0.75

    # Last resort: still oversized after every compress/downscale pass.
    # Returning the bloated buffer used to silently trigger a Claude API
    # 400 ("image too large"), which the failover layer treated as a
    # transient error and retried — wasting quota in a tight loop. Log a
    # warning so the operator can see it and raise a clear ValueError so
    # the caller can route it to a "image too large" UI message.
    final_size = buf.tell()
    logger.warning(
        "📷 Image still %d bytes after compression+downscale (limit=%d); rejecting",
        final_size,
        _CLAUDE_IMAGE_LIMIT,
    )
    raise ValueError(
        f"image too large: {final_size} bytes after compression "
        f"(Claude limit is {_CLAUDE_IMAGE_LIMIT} bytes)"
    )


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
            if result.count(search_text) > 1:
                logger.warning("Multiple SEARCH matches; ambiguous, skipping replace")
                continue
            result = result.replace(search_text, replace_text, 1)
            applied += 1
        else:
            # Try with stripped whitespace as fallback
            search_stripped = search_text.strip()
            if search_stripped and search_stripped in result:
                if result.count(search_stripped) > 1:
                    logger.warning("Multiple SEARCH matches; ambiguous, skipping replace")
                    continue
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

# Models that use adaptive thinking (``thinking: {type: "adaptive"}``) rather than
# the deprecated manual ``budget_tokens`` form. Opus 4.7+ (incl. 4.8) REJECT
# ``budget_tokens`` with a 400, so matching them here is essential. Older
# extended-thinking-only models (Opus 4.5/4.1, Sonnet 4.5) fall through to the
# budget_tokens branch for backward compatibility.
_ADAPTIVE_THINKING_MODELS: tuple[str, ...] = (
    "opus-4-8",
    "opus-4-7",
    "opus-4-6",
    "sonnet-4-6",
    "mythos",
)


def _uses_adaptive_thinking(model: str) -> bool:
    """True if the model uses adaptive thinking instead of manual budget_tokens."""
    model_lower = model.lower()
    return any(tag in model_lower for tag in _ADAPTIVE_THINKING_MODELS)


async def handle_chat_message_claude(
    ws: WebSocketResponse,
    data: dict[str, Any],
    claude_client: anthropic.AsyncAnthropic,
    *,
    max_content_length: int = 200_000,
    max_history_messages: int = 500,
    max_images: int = 10,
    max_image_size_bytes: int = 10 * 1024 * 1024,
    max_documents: int = 5,
    max_document_size_bytes: int = 32 * 1024 * 1024,
    stream_timeout: int = 300,
    _failover_retry: bool = False,
) -> None:
    """Handle incoming chat message and stream response via Claude.

    `_failover_retry` is a SERVER-internal flag used by the failover/retry
    code paths. It must NEVER be honored from the client `data` dict — a
    malicious client setting `_failover_retry: True` could bypass user
    message persistence and document extraction (since both branches skip
    those when this flag is True).
    """
    conversation_id = data.get("conversation_id")
    raw = data.get("content")
    content = (raw if isinstance(raw, str) else "").strip()
    role_preset = data.get("role_preset", "general")
    thinking_enabled = data.get("thinking_enabled", False)
    unrestricted_mode_requested = data.get("unrestricted_mode", False)
    history = data.get("history", [])
    images = data.get("images", [])
    documents = data.get("documents", [])
    user_name = data.get("user_name", "User")
    # is_regeneration IS legitimately client-controlled (the regenerate
    # button) but we ignore _failover_retry from the wire — only honor the
    # server-set parameter.
    is_regeneration = data.get("is_regeneration", False)
    is_failover_retry = _failover_retry

    # Validate conversation_id format (defense in depth). Reuse the
    # module-level compiled pattern instead of recompiling per call.
    if conversation_id and (
        not isinstance(conversation_id, str) or not _CONVERSATION_ID_RE.match(conversation_id)
    ):
        await ws.send_json({"type": "error", "message": "Invalid conversation ID format"})
        return

    # ``history`` must be a list of dicts. A client sending ``"history": "x"``
    # would otherwise slice the string character-by-character below and
    # produce garbage MessageParam entries that Anthropic rejects with 400.
    if not isinstance(history, list):
        history = []
    # ``images`` must likewise be a list — a payload like ``{"images": 5}`` would
    # otherwise raise TypeError at ``len(images)`` below (the only one of the three
    # list inputs previously left unguarded), and a string would iterate char-by-char
    # into garbage image blocks. Mirror the Gemini twin's coercion.
    if not isinstance(images, list):
        images = []

    # Enforce input size limits
    if len(content) > max_content_length:
        await ws.send_json(
            {"type": "error", "message": f"Message too long (max {max_content_length} characters)"}
        )
        return
    if len(history) > max_history_messages:
        history = history[-max_history_messages:]
    if len(images) > max_images:
        await ws.send_json({"type": "error", "message": f"Too many images (max {max_images})"})
        return
    # Validate + cap documents the same way — defense against a malicious or
    # buggy client sending an unbounded list.
    if not isinstance(documents, list):
        documents = []
    if len(documents) > max_documents:
        await ws.send_json(
            {"type": "error", "message": f"Too many documents (max {max_documents})"}
        )
        return

    if not content and not images and not documents:
        await ws.send_json({"type": "error", "message": "Empty message"})
        return

    if not claude_client:
        await ws.send_json({"type": "error", "message": "Claude AI not available"})
        return

    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])

    # Validate client-supplied is_regeneration by checking that the last DB
    # message is a user message with matching content. This stops a malicious
    # client from setting is_regeneration=True to skip user-message persistence
    # and document extraction. Server-set _failover_retry bypasses this check
    # because the original turn already persisted things.
    if is_regeneration and not is_failover_retry and DB_AVAILABLE and conversation_id:
        try:
            db = _get_db()
            recent_msgs = await db.get_dashboard_messages(conversation_id)
            last_msg = recent_msgs[-1] if recent_msgs else None
            last_content = (last_msg or {}).get("content") or ""
            # Strip any leading [timestamp] prefix saved by historical messages
            last_content_stripped = strip_leading_timestamp(last_content) if last_content else ""
            if not (
                last_msg
                and last_msg.get("role") == "user"
                and (last_content == content or last_content_stripped == content)
            ):
                logger.warning(
                    "is_regeneration=True from client did not match last user msg; treating as new message",
                )
                is_regeneration = False
        except Exception:
            logger.warning(
                "Failed to validate is_regeneration; treating as new message",
                exc_info=True,
            )
            is_regeneration = False

    # Save user message to DB (skip for regeneration — the edited message already exists)
    user_msg_id: int = 0
    if DB_AVAILABLE and conversation_id and not is_regeneration:
        try:
            db = _get_db()
            user_msg_id = await db.save_dashboard_message(
                conversation_id, "user", content, images=images or None
            )
        except Exception as e:
            logger.warning("Failed to save user message: %s", e, exc_info=True)

    # Persistent document memory — extract + save uploaded PDFs / DOCX /
    # text files so future turns see the content without re-upload. Claude
    # still gets the raw attachments as `document` blocks for THIS turn
    # (highest fidelity); the DB snapshot is the cross-conversation fallback.
    # Skip extraction only when this is a SERVER-initiated failover retry —
    # original turn already persisted them. A client-controlled is_regeneration
    # MUST still trigger extraction in case a doc was uploaded again.
    if documents and DB_AVAILABLE and not (is_regeneration and is_failover_retry):
        try:
            from .document_extractor import extract_and_persist

            db_inst = _get_db()
            saved_docs = await extract_and_persist(
                documents,
                db=db_inst,
                source_conversation_id=conversation_id,
            )
            if saved_docs:
                # Non-blocking UX feedback.
                try:
                    await ws.send_json(
                        {
                            "type": "document_saved",
                            "documents": saved_docs,
                            "conversation_id": conversation_id,
                        }
                    )
                except Exception:
                    pass
        except Exception:
            logger.exception("Document extraction/persistence failed (API backend)")

    # Build context with user identity, scoped to this
    # conversation so uploaded documents stay within their RP thread.
    user_context, unrestricted_mode = await build_user_context(
        user_name,
        unrestricted_mode_requested,
        conversation_id=conversation_id,
    )

    # Build conversation messages for Claude API format
    messages: list[MessageParam] = []
    _db_history_loaded = False
    if DB_AVAILABLE and conversation_id:
        try:
            db = _get_db()
            db_msgs = await db.get_dashboard_messages(conversation_id)
            # Drop the current turn's user message precisely (see dashboard_chat.py
            # for the rationale): exact saved row when the save succeeded, the
            # pre-existing last user row on regeneration/failover-retry, and
            # nothing when an attempted save failed (user_msg_id == 0) so a prior
            # turn isn't silently stripped from context.
            if user_msg_id:
                hist_msgs = (
                    db_msgs[:-1] if db_msgs and db_msgs[-1].get("id") == user_msg_id else db_msgs
                )
            elif is_regeneration and db_msgs and db_msgs[-1]["role"] == "user":
                hist_msgs = db_msgs[:-1]
            else:
                hist_msgs = db_msgs
            if len(hist_msgs) > max_history_messages:
                hist_msgs = hist_msgs[-max_history_messages:]
            for msg in hist_msgs:
                role: ClaudeMessageRole = "user" if msg["role"] == "user" else "assistant"
                text = msg.get("content") or ""
                if msg.get("created_at"):
                    text = f"[{normalize_timestamp_to_bangkok(msg['created_at'])}] {text}"
                if msg.get("images"):
                    # Deliberately do NOT include `msg['id']` here — the
                    # primary key is a server-side handle and surfacing it in
                    # the AI-visible prompt invites the model to be tricked
                    # into operating on arbitrary message ids via injection.
                    text += f"\n[User had attached {len(msg['images'])} image(s) in this message]"
                messages.append(build_claude_message(role, text))
            _db_history_loaded = True
        except Exception as e:
            logger.warning(
                "Failed to load DB history, falling back to frontend history: %s",
                e,
                exc_info=True,
            )

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
                # Defensive parse: a malformed ``data:`` URL like
                # ``data;base64,XXX`` (note ``;`` instead of ``:``)
                # would IndexError on ``[1]`` because the first segment
                # has no colon. The previous shape only checked for a
                # colon ANYWHERE in the header, not in the first
                # ``;``-delimited piece, so it crashed on this input.
                first_segment = header.split(";")[0]
                if ":" in first_segment:
                    mime_type = first_segment.split(":", 1)[1] or "image/png"
                else:
                    mime_type = "image/png"
            else:
                b64_data = img_data
                mime_type = "image/png"

            # Validate MIME type against allowlist. Claude's Anthropic API
            # only accepts JPEG/PNG/GIF/WebP — HEIC/HEIF would be silently
            # accepted by the Gemini path, so call out the difference so
            # the user knows to convert and retry rather than blame "the
            # AI doesn't see my photo".
            if mime_type not in _ALLOWED_IMAGE_MIMES:
                logger.warning("Rejected image with disallowed MIME type: %s", mime_type)
                if mime_type in ("image/heic", "image/heif"):
                    msg = (
                        f"Claude doesn't accept {mime_type} — please convert to "
                        "JPEG or PNG and retry."
                    )
                else:
                    msg = f"Unsupported image type: {mime_type}"
                await ws.send_json({"type": "error", "message": msg})
                continue

            # Validate base64 string length BEFORE decoding to prevent memory exhaustion
            estimated_size = len(b64_data) * 3 // 4
            if estimated_size > max_image_size_bytes:
                logger.warning(
                    "Rejected image: estimated %s bytes exceeds %s limit",
                    estimated_size,
                    max_image_size_bytes,
                )
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Image too large (max {max_image_size_bytes // 1024 // 1024}MB)",
                    }
                )
                continue

            image_bytes = base64.b64decode(b64_data, validate=True)
            if len(image_bytes) > max_image_size_bytes:
                logger.warning(
                    "Rejected image: %s bytes exceeds %s limit",
                    len(image_bytes),
                    max_image_size_bytes,
                )
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Image too large (max {max_image_size_bytes // 1024 // 1024}MB)",
                    }
                )
                continue

            # Compress if exceeding Claude's 5MB API limit. Raises
            # ValueError if even max compression+downscale can't fit;
            # surface that to the client so the user knows the image was
            # dropped instead of silently triggering a 400 retry storm.
            # PIL work is offloaded to a thread — a 10 MB image
            # compress+resize sequence is hundreds of ms of CPU and would
            # otherwise stall the event loop, blocking every other WS client.
            try:
                image_bytes, mime_type = await asyncio.to_thread(
                    _compress_image_for_claude, image_bytes, mime_type
                )
            except ValueError as e:
                logger.warning("Image rejected after compression: %s", e)
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "Image too large to send to Claude (over 5MB even after compression)",
                    }
                )
                continue
            b64_data = base64.b64encode(image_bytes).decode("ascii")

            image_block = build_claude_base64_image_block(b64_data, mime_type)
            if image_block is None:
                logger.warning("Rejected image with Claude-unsupported MIME type: %s", mime_type)
                await ws.send_json(
                    {"type": "error", "message": f"Unsupported image type: {mime_type}"}
                )
                continue
            current_content.append(image_block)
            logger.info("📷 Added image to Claude message (%s bytes)", len(image_bytes))
        except Exception as e:
            logger.warning("Failed to process image: %s", e)
            # Notify the client. An unexpected failure here (e.g. binascii.Error
            # from b64decode(validate=True) on corrupt data, which no inner
            # handler catches) would otherwise drop the image silently — every
            # other rejection branch in this loop emits an error frame, so match
            # that contract instead of leaving the user wondering where it went.
            try:
                await ws.send_json(
                    {"type": "error", "message": "Failed to process an attached image"}
                )
            except Exception:
                pass

    # Add documents — PDFs become native `document` blocks (Claude parses
    # text + embedded images itself); text files become `document` blocks
    # with a text source so Claude treats them as distinct reference docs
    # rather than chat content. Either way, filename travels along as the
    # block's ``title`` for logs/citations.
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_name = re.sub(r"[^A-Za-z0-9._\-\s]", "_", str(doc.get("name", "attachment"))).strip(
            ".\\/ "
        )[:200]
        doc_kind = doc.get("kind")
        doc_data = doc.get("data")
        if not isinstance(doc_data, str) or not doc_data:
            continue

        # Filename-based routing — the frontend's ``kind`` is advisory; a
        # malicious / buggy client could lie. Extension is the stronger
        # signal and also what the CLI backend uses.
        ext_match = re.search(r"\.[A-Za-z0-9]+$", doc_name)
        ext = ext_match.group(0).lower() if ext_match else ""

        if ext != ".pdf" and doc_kind == "binary":
            # Non-PDF binary (the frontend ships .docx this way): the
            # Anthropic document block only accepts application/pdf — sending
            # DOCX bytes labeled as PDF is a non-retryable 400 that failed
            # the WHOLE turn. Skip the raw block; the extracted text was
            # already persisted into document memory (extract_and_persist
            # ran above) and reaches the model via user_context.
            logger.info(
                "📎 %s: skipping raw binary block (non-PDF); using extracted text via context",
                doc_name,
            )
            continue
        if ext == ".pdf":
            # Binary payload arrives as a data URL; pull the base64 part.
            if "," not in doc_data or not doc_data.startswith("data:"):
                logger.warning("Rejected document %s: malformed data URL", doc_name)
                continue
            _header, _, b64_payload = doc_data.partition(",")
            # Size pre-check via base64 length (avoids decoding huge strings
            # just to discover they're too big).
            estimated_size = len(b64_payload) * 3 // 4
            if estimated_size > max_document_size_bytes:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Document too large (max {max_document_size_bytes // 1024 // 1024}MB)",
                    }
                )
                continue
            try:
                doc_block = build_claude_pdf_document_block(b64_payload, title=doc_name)
            except Exception as e:
                logger.warning("Failed to build PDF block for %s: %s", doc_name, e)
                continue
            current_content.append(doc_block)
            logger.info(
                "📎 Added PDF document to Claude message (%s, ~%d bytes)", doc_name, estimated_size
            )
        else:
            # Text/code file — pass through as text-source document.
            # Size check on byte length, not char count (UTF-8 multibyte).
            encoded_len = len(doc_data.encode("utf-8", errors="replace"))
            if encoded_len > max_document_size_bytes:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Document too large (max {max_document_size_bytes // 1024 // 1024}MB)",
                    }
                )
                continue
            try:
                doc_block = build_claude_text_document_block(doc_data, title=doc_name)
            except Exception as e:
                logger.warning("Failed to build text doc block for %s: %s", doc_name, e)
                continue
            current_content.append(doc_block)
            logger.info(
                "📄 Added text document to Claude message (%s, %d chars)", doc_name, len(doc_data)
            )

    # Add text content — prefix with send timestamp so Claude sees when the
    # newly arrived message was sent, matching the [timestamp] prefix on
    # historical messages above. ZoneInfo is imported at module scope.
    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")
    send_timestamp = bangkok_now_iso()
    stamped_content = f"[{send_timestamp}] {content}" if content else content
    if stamped_content:
        current_content.append(build_claude_text_block(stamped_content))

    if not current_content and not stamped_content:
        await ws.send_json(
            {
                "type": "error",
                "message": "Message contains no supported text or images",
            }
        )
        return

    messages.append(
        build_claude_message(
            "user",
            current_content if current_content else stamped_content,
        )
    )

    # Build unrestricted mode injection if enabled
    unrestricted_injection = ""
    # Parse identically to the CLI backend (.strip() + "on") so the same env
    # value enables unrestricted mode regardless of which backend is active.
    allow_unrestricted = os.getenv("DASHBOARD_ALLOW_UNRESTRICTED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if unrestricted_mode and allow_unrestricted:
        framing = (
            preset.get("unrestricted_framing")
            or GENERAL_UNRESTRICTED_FRAMING
            or ENI_ESCALATION_FRAMING
        )
        if framing:
            unrestricted_injection = f"\n\n[Session Mode]\n{framing}\n"
        logger.info("🔓 Unrestricted Mode: ENABLED")

    thinking_prompt_enhancement = ""
    if thinking_enabled:
        thinking_prompt_enhancement = "\n[REASONING DIRECTIVE]\nPlease provide a thorough internal thought process before each response. Analyze the user's intent, context, and potential responses step-by-step regardless of the query's complexity."

    # Split system prompt into stable + volatile blocks for prompt caching.
    # The stable block (persona + injections + user context + memories + the
    # standing reminders) is identical between turns within a 5-minute window,
    # so it gets a cache_control marker and rides on Anthropic's prompt cache.
    # Only the per-turn ``Current Time: ...`` line goes in the volatile block,
    # which means a turn-to-turn time change no longer invalidates the cached
    # ~99% of the system prompt.
    stable_system_prompt = f"""{preset["system_instruction"]}
{unrestricted_injection}
{thinking_prompt_enhancement}
[System Context]
{user_context}

IMPORTANT: If user asks you to remember something, respond with the information you'll remember. The system will automatically save important facts.
NOTE: User messages (both historical and the current one) may be prefixed with timestamps like [2026-03-25T14:30:22]. These are system-injected metadata indicating when each message was sent. Do NOT include such timestamp prefixes in your own responses. Use them only to understand the timing context of the conversation."""
    volatile_system_prompt = f"Current Time: {current_time_str} (ICT)"

    # Build mode info for display
    mode_info: list[str] = []

    # Format model id like `claude-opus-4-7` → `Claude Opus 4.7`. The naive
    # `replace("-", " ").title()` produces `Claude Opus 4 7` (two version
    # tokens look like separate words). Split out the numeric trailer and
    # rejoin it with a dot so the version reads correctly.
    _model_parts = CLAUDE_MODEL.replace("claude-", "").split("-")
    _model_numeric: list[str] = []
    _model_words: list[str] = []
    for _p in _model_parts:
        if _p.isdigit():
            _model_numeric.append(_p)
        else:
            _model_words.append(_p)
    _name_part = " ".join(w.title() for w in _model_words)
    _version_part = ".".join(_model_numeric) if _model_numeric else ""
    _model_display = (
        f"Claude {_name_part} {_version_part}".strip()
        if _version_part
        else f"Claude {_name_part}".strip()
    )
    mode_info.insert(0, f"🟣 {_model_display}")

    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    # Gate the badge on the SAME composite condition as the actual injection
    # above (``if unrestricted_mode and allow_unrestricted:``) so the UI
    # doesn't show "🔓 Unrestricted" when the env flag is unset and no
    # unrestricted framing was injected.
    if unrestricted_mode and allow_unrestricted:
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
        "system": build_split_cached_system_prompt(
            stable_system_prompt,
            volatile_system_prompt,
        ),
        "messages": messages,
    }

    # Opus 4.7 effort level (low/medium/high/xhigh/max). Must be nested under
    # `output_config` per Anthropic API (per /build-with-claude/effort docs).
    # Only forwarded when explicitly configured so older models are unaffected.
    if CLAUDE_EFFORT:
        api_kwargs["output_config"] = {"effort": CLAUDE_EFFORT}

    # Thinking config:
    # - Opus 4.7+ (incl. 4.8) REJECT `type: "enabled"` with budget_tokens. Use
    #   adaptive thinking instead; effort (above) controls thinking depth.
    # - Older models (Opus 4.5, Sonnet 4.5) still accept the enabled+budget_tokens
    #   form, kept for backward compatibility.
    if thinking_enabled:
        if _uses_adaptive_thinking(CLAUDE_MODEL):
            api_kwargs["thinking"] = {"type": "adaptive"}
        elif CLAUDE_MAX_TOKENS > 1024:
            # budget_tokens MUST be strictly < max_tokens (Anthropic 400s
            # otherwise). max(…, 1024) alone could push budget >= max_tokens
            # when an operator sets CLAUDE_MAX_TOKENS very low, so cap it below
            # max_tokens; and skip the thinking config entirely when
            # CLAUDE_MAX_TOKENS <= 1024 (the 1024 floor) where no valid budget
            # exists — a non-retryable 400 that would fail the whole turn.
            _think_budget = max(1024, min(32000, CLAUDE_MAX_TOKENS - 1024))
            _think_budget = min(_think_budget, CLAUDE_MAX_TOKENS - 1)
            api_kwargs["thinking"] = {"type": "enabled", "budget_tokens": _think_budget}

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
            nonlocal \
                full_response, \
                thinking_content, \
                chunks_count, \
                is_thinking, \
                input_tokens, \
                output_tokens
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
                                await ws.send_json(
                                    {
                                        "type": "thinking_start",
                                        "conversation_id": conversation_id,
                                    }
                                )

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        delta_type = getattr(delta, "type", "")

                        if delta_type == "thinking_delta":
                            thought_text = getattr(delta, "thinking", "")
                            if thought_text and thinking_enabled:
                                thinking_content += thought_text
                                await ws.send_json(
                                    {
                                        "type": "thinking_chunk",
                                        "content": thought_text,
                                        "conversation_id": conversation_id,
                                    }
                                )

                        elif delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                if is_thinking:
                                    is_thinking = False
                                    await ws.send_json(
                                        {
                                            "type": "thinking_end",
                                            "conversation_id": conversation_id,
                                            "full_thinking": thinking_content,
                                        }
                                    )
                                safe_text = ts_stripper.feed(text)
                                if safe_text:
                                    full_response += safe_text
                                    chunks_count += 1
                                    await ws.send_json(
                                        {
                                            "type": "chunk",
                                            "content": safe_text,
                                            "conversation_id": conversation_id,
                                        }
                                    )

                    elif event_type == "content_block_stop":
                        if is_thinking:
                            is_thinking = False
                            await ws.send_json(
                                {
                                    "type": "thinking_end",
                                    "conversation_id": conversation_id,
                                    "full_thinking": thinking_content,
                                }
                            )

                try:
                    final_msg = await stream.get_final_message()
                    if final_msg and hasattr(final_msg, "usage") and final_msg.usage:
                        input_tokens = getattr(final_msg.usage, "input_tokens", 0) or input_tokens
                        output_tokens = (
                            getattr(final_msg.usage, "output_tokens", 0) or output_tokens
                        )
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
            nonlocal \
                full_response, \
                thinking_content, \
                chunks_count, \
                is_thinking, \
                input_tokens, \
                output_tokens
            nonlocal cache_creation_tokens, cache_read_tokens
            attempt = 1
            # Save original messages to prevent accumulation on each retry
            original_messages = list(api_kwargs["messages"])

            # Pre-bind so the asyncio.sleep(delay) at loop bottom never
            # touches an unbound local. Both except branches reassign it
            # before the sleep is reached, but a future edit could add a
            # path that falls through unchanged. Pre-bind retry_notice for
            # the same reason — it's only assigned in the two known except
            # branches and a future non-retryable except path would otherwise
            # hit ws.send_json with UnboundLocalError.
            delay = 1.0
            retry_notice = ""
            # Track the last failure so genuine exhaustion can re-raise it and the
            # outer handler routes it correctly (timeout->timeout branch, 429->quota,
            # else record_failure+failover) instead of falling through to a
            # success-shaped stream_end + record_success().
            last_error: Exception | None = None
            while attempt <= _MAX_STREAM_RETRIES:
                try:
                    if stream_timeout > 0:
                        await asyncio.wait_for(_stream_once(), timeout=stream_timeout)
                    else:
                        await _stream_once()
                    return
                except _RETRYABLE_ERRORS as retry_err:
                    last_error = retry_err
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⚠️ Claude overloaded (attempt %d), retrying in %ds: %s",
                        attempt,
                        delay,
                        retry_err,
                    )
                    retry_notice = f"\n\n⏳ *Server busy, retrying (attempt {attempt})...*\n\n"
                except TimeoutError as timeout_err:
                    last_error = timeout_err
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⏱️ Claude stream timed out on attempt %d, retrying in %ds",
                        attempt,
                        delay,
                    )
                    retry_notice = (
                        f"\n\n⏳ *Request timed out, retrying (attempt {attempt})...*\n\n"
                    )

                # Send retry notice to frontend (appends to current streaming
                # bubble) — but only when another attempt actually remains, so the
                # final failure doesn't show a "retrying" message for a retry that
                # will never happen.
                if attempt < _MAX_STREAM_RETRIES:
                    await ws.send_json(
                        {
                            "type": "chunk",
                            "content": retry_notice,
                            "conversation_id": conversation_id,
                        }
                    )

                # Prefill: inject partial response so Claude continues from where it stopped
                partial = full_response
                # Cap accumulated response size to prevent unbounded memory growth
                if len(partial) > _MAX_RESPONSE_SIZE:
                    logger.warning(
                        "⚠️ Claude stream response exceeded %d chars, stopping retries",
                        _MAX_RESPONSE_SIZE,
                    )
                    # We already have a large (if truncated) response — deliver it
                    # via the normal stream_end path rather than erroring.
                    return
                # Reset only counters, keep full_response accumulating
                thinking_content = ""
                chunks_count = 0
                is_thinking = False
                input_tokens = 0
                output_tokens = 0
                # Reset the timestamp stripper too: a partial "[2026..." it
                # buffered on the failed attempt would otherwise be prepended
                # to this attempt's clean continuation when its buffer flushes.
                ts_stripper.reset()

                # Anthropic rejects a final assistant prefill whose content ends
                # in trailing whitespace (400 BadRequestError, which is NOT
                # retryable) — and the streamed partial can legitimately end in a
                # newline/space. Right-strip it; if nothing survives, skip the
                # prefill entirely and just retry from original_messages.
                partial_prefill = partial.rstrip() if partial else ""
                if partial_prefill:
                    # A last-assistant-turn prefill (request ending in an
                    # assistant message) is REJECTED with a 400 on Claude 4.x
                    # models (Opus 4.6/4.7/4.8, Sonnet 4.6) — and BadRequestError
                    # is NOT in _RETRYABLE_ERRORS, so it would propagate out and
                    # defeat this entire retry loop. Use the user-continuation
                    # form for ALL models (thinking and non-thinking alike):
                    # append the partial as an assistant turn followed by a user
                    # message asking Claude to continue, so the request ends in a
                    # user turn (always valid). Rebuild from original_messages to
                    # prevent accumulation across attempts.
                    api_kwargs["messages"] = [
                        *original_messages,
                        {"role": "assistant", "content": partial_prefill},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was interrupted mid-stream. "
                                "The text above is what you had written so far. "
                                "Continue writing from EXACTLY where you left off. "
                                "Do NOT repeat any of the text above — only output the continuation."
                            ),
                        },
                    ]
                    # Disable thinking for the continuation (no-op if absent) to
                    # avoid repetition overhead.
                    api_kwargs.pop("thinking", None)

                attempt += 1
                # On the last attempt the loop is about to exit and re-raise; don't
                # waste up to _RETRY_MAX_DELAY seconds sleeping before surfacing it.
                if attempt <= _MAX_STREAM_RETRIES:
                    await asyncio.sleep(delay)

            # All retries exhausted — every attempt failed. Surface the failure so
            # the outer except records it against failover health and sends the
            # client an error frame, instead of returning normally (which would
            # send a success-shaped stream_end and record_success()).
            logger.error(
                "💀 Claude dashboard stream retries exhausted after %d attempts", attempt - 1
            )
            if last_error is not None:
                raise last_error
            raise RuntimeError("Claude dashboard stream retries exhausted")

        await _consume_claude_stream()

        # If the stream ended while still inside a thinking block (retries
        # exhausted mid-reasoning, or an abort before content_block_stop),
        # close the thinking UI so the client spinner doesn't hang. Mirrors
        # the Gemini handler's end-of-stream flush.
        if is_thinking:
            is_thinking = False
            await ws.send_json(
                {
                    "type": "thinking_end",
                    "conversation_id": conversation_id,
                    "full_thinking": thinking_content,
                }
            )

        # Log prompt-caching effectiveness for this request. A healthy
        # cache_read_tokens value means Anthropic reused the cached prefix
        # (~90% cost reduction on those tokens).
        if cache_creation_tokens or cache_read_tokens:
            logger.info(
                "💾 Prompt cache: read=%s, created=%s, fresh_input=%s, output=%s",
                cache_read_tokens,
                cache_creation_tokens,
                input_tokens,
                output_tokens,
            )

        # Flush any residual buffered text from the leading-timestamp stripper.
        tail = ts_stripper.flush()
        if tail:
            full_response += tail
            chunks_count += 1
            await ws.send_json(
                {
                    "type": "chunk",
                    "content": tail,
                    "conversation_id": conversation_id,
                }
            )
        # Defense in depth: also strip if a prefix slipped through (e.g. after
        # a retry reset or split exactly at the probe boundary).
        full_response = strip_leading_timestamp(full_response)

        # Strip <think>...</think> from full_response (proxy may embed thinking in text)
        think_match = re.search(r"<think>(.*?)</think>", full_response, re.DOTALL)
        if think_match:
            if not thinking_content:
                thinking_content = think_match.group(1).strip()
            full_response = re.sub(
                r"<think>.*?</think>", "", full_response, flags=re.DOTALL
            ).strip()

        # Fallback: estimate tokens from content if API didn't return usage.
        # A full-cache-hit turn legitimately reports 0 fresh input tokens with
        # nonzero cache reads — that's real usage, not "missing", so it must
        # NOT be clobbered by the char-count estimate (the stream_end sum
        # below would then double count it).
        if not (input_tokens or cache_read_tokens or cache_creation_tokens):
            # Estimate input tokens from system prompt + conversation history.
            # The system prompt is now sent as two blocks (stable + volatile)
            # for prompt caching, so concat both back together for the estimate.
            input_text = stable_system_prompt + volatile_system_prompt
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
                        logger.info("📝 Set title from user message: %s", title)

            except Exception as e:
                logger.warning("Failed to save assistant message: %s", e)

        # Report context-window OCCUPANCY, matching the CLI backend: Anthropic
        # bills three flavors of input (fresh, cache-creation, cache-read) and
        # all three occupy the context, so the FE indicator must see their sum.
        # Raw fresh-only input_tokens made the bar collapse to ~the latest turn
        # on every cache-hit resumed turn (the norm with prompt caching on).
        # Frame-local sum only — the cache-effectiveness log above keeps
        # reporting the true fresh input, and the raw split stays in the
        # cache_* fields.
        reported_input = input_tokens + cache_creation_tokens + cache_read_tokens
        await ws.send_json(
            {
                "type": "stream_end",
                "conversation_id": conversation_id,
                "full_response": full_response,
                "chunks_count": chunks_count,
                "user_message_id": user_msg_id or None,
                "assistant_message_id": assistant_msg_id or None,
                "token_usage": {
                    "input_tokens": reported_input,
                    "output_tokens": output_tokens,
                    "total_tokens": reported_input + output_tokens,
                    "cache_creation_input_tokens": cache_creation_tokens,
                    "cache_read_input_tokens": cache_read_tokens,
                    "context_window": CLAUDE_CONTEXT_WINDOW,
                },
            }
        )

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
                    # Pass _failover_retry as an explicit kwarg, not via data,
                    # so a client cannot set it. Also force is_regeneration=True
                    # via a dict copy so the user message we already saved on
                    # the first attempt isn't duplicated.
                    retry_data = {**data, "is_regeneration": True}
                    new_client = _api_failover.get_client()
                    await handle_chat_message_claude(
                        ws,
                        retry_data,
                        new_client,
                        max_content_length=max_content_length,
                        max_history_messages=max_history_messages,
                        max_images=max_images,
                        max_image_size_bytes=max_image_size_bytes,
                        max_documents=max_documents,
                        max_document_size_bytes=max_document_size_bytes,
                        stream_timeout=stream_timeout,
                        _failover_retry=True,
                    )
                    return
                except Exception as retry_err:
                    logger.error("❌ Retry after failover also failed: %s", retry_err)
        elif _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(TimeoutError("stream timeout"))
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Response timed out. Please try again.",
                    "conversation_id": conversation_id,
                }
            )
        except Exception:
            logger.debug(
                "WebSocket send failed during timeout handling, client may have disconnected"
            )
    except Exception as e:
        error_str = str(e)
        logger.error("❌ Claude streaming error: %s", type(e).__name__, exc_info=True)

        # Detect quota/billing limit — no point retrying or failing over.
        # Substring check is fragile (Anthropic wording can change) but the
        # consequence of a miss is "we retry once more" which is acceptable.
        # Also detect HTTP 429 explicitly via the SDK exception type so a
        # rate-limit error is recognised even if the message wording shifts.
        _err_lower = error_str.lower()
        is_quota_error = (
            "usage limits" in _err_lower
            or "billing" in _err_lower
            or "quota" in _err_lower
            or "credit balance" in _err_lower
        )
        if not is_quota_error and (
            isinstance(e, anthropic.APIStatusError) and getattr(e, "status_code", 0) == 429
        ):
            is_quota_error = True
        if is_quota_error:
            try:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "Claude API quota reached — please switch to Gemini in the provider selector, or wait until your quota resets.",
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:
                pass
            return

        # A ConnectionResetError here means the CLIENT WebSocket dropped mid-
        # stream (aiohttp raises it from ws.send_json on a closing transport),
        # not an Anthropic-endpoint failure. Abort without recording it against
        # failover health — otherwise a disconnect flips the active endpoint
        # and re-runs a full generation for a client that is already gone.
        if isinstance(e, ConnectionResetError):
            logger.info("Dashboard client disconnected mid-stream; aborting (no failover).")
            return

        if _FAILOVER_AVAILABLE and not is_failover_retry:
            switched = await _api_failover.record_failure(e)
            if switched:
                logger.info("🔀 Retrying with new endpoint after failover...")
                try:
                    retry_data = {**data, "is_regeneration": True}
                    new_client = _api_failover.get_client()
                    await handle_chat_message_claude(
                        ws,
                        retry_data,
                        new_client,
                        max_content_length=max_content_length,
                        max_history_messages=max_history_messages,
                        max_images=max_images,
                        max_image_size_bytes=max_image_size_bytes,
                        max_documents=max_documents,
                        max_document_size_bytes=max_document_size_bytes,
                        stream_timeout=stream_timeout,
                        _failover_retry=True,
                    )
                    return
                except Exception as retry_err:
                    logger.error("❌ Retry after failover also failed: %s", retry_err)
        elif _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(e)
        # The SDK's client-side timeout (anthropic.APITimeoutError) is NOT a
        # subclass of builtin TimeoutError, so a timeout that exhausts the retry
        # loop and re-raises here never reaches the dedicated `except TimeoutError`
        # branch above — surface the same friendly timeout message rather than the
        # generic "internal error" one.
        if isinstance(e, anthropic.APITimeoutError):
            error_message = "Response timed out. Please try again."
        else:
            error_message = "An internal error occurred while processing your request."
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": error_message,
                    "conversation_id": conversation_id,
                }
            )
        except Exception:
            logger.debug(
                "WebSocket send failed during error handling, client may have disconnected"
            )


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
    # Coerce before .strip() — a non-string instruction (e.g. {"instruction": 123})
    # would otherwise raise AttributeError at this unguarded function head (the
    # try/except starts later), and since this runs as a background task the
    # error never reaches the client. Mirrors the Gemini twin (dashboard_chat.py).
    _raw_instruction = data.get("instruction", "")
    instruction = str(_raw_instruction).strip() if _raw_instruction is not None else ""
    role_preset = data.get("role_preset", "general")
    thinking_enabled = data.get("thinking_enabled", False)
    user_name = data.get("user_name", "User")

    if not conversation_id or not target_message_id or not instruction:
        await ws.send_json({"type": "error", "message": "Missing data for AI edit"})
        return

    # Parity with the Gemini handler — same conversation_id format
    # check and instruction-length cap. Without these, the Claude path
    # accepted malformed IDs and oversized instructions that the Gemini
    # twin already rejected at the door.
    if not isinstance(conversation_id, str) or not re.match(
        r"^[a-zA-Z0-9_\-]{1,128}\Z", conversation_id
    ):
        await ws.send_json({"type": "error", "message": "Invalid conversation ID format"})
        return

    max_instruction_length = 10_000
    if len(instruction) > max_instruction_length:
        await ws.send_json(
            {
                "type": "error",
                "message": f"Instruction too long (max {max_instruction_length} characters)",
            }
        )
        return
    if user_name and len(str(user_name)) > 200:
        user_name = str(user_name)[:200]

    if not claude_client:
        await ws.send_json({"type": "error", "message": "Claude AI not available"})
        return

    if not DB_AVAILABLE:
        await ws.send_json({"type": "error", "message": "Database unavailable"})
        return

    # Load target message from DB
    try:
        target_message_id_int = int(target_message_id)
    except (TypeError, ValueError):
        await ws.send_json({"type": "error", "message": "Invalid target message ID"})
        return
    try:
        db = _get_db()
        all_msgs = await db.get_dashboard_messages(conversation_id)
        target_msg = next((m for m in all_msgs if m.get("id") == target_message_id_int), None)
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

    # Build context — scoped to this conversation's document library.
    user_context, _ = await build_user_context(
        user_name,
        False,
        conversation_id=conversation_id,
    )

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
    target_idx = next(
        (i for i, m in enumerate(all_msgs) if m.get("id") == target_message_id_int), -1
    )
    if target_idx > 0:
        hist = all_msgs[:target_idx]
        if len(hist) > max_history_messages:
            hist = hist[-max_history_messages:]
        for msg in hist:
            role: ClaudeMessageRole = "user" if msg["role"] == "user" else "assistant"
            messages.append(build_claude_message(role, str(msg.get("content", ""))))

    messages.append(build_claude_message("user", edit_prompt))

    # Build system prompt — ZoneInfo imported at module scope.
    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

    # Same stable/volatile split as the main chat path — keeps the long
    # persona+context prefix in cache while only the per-turn time
    # line is uncached.
    stable_system_prompt = f"{preset['system_instruction']}\n[System Context]\n{user_context}"
    volatile_system_prompt = f"Current Time: {current_time_str} (ICT)"

    # Build mode info
    mode_info: list[str] = []
    # Format model id like `claude-opus-4-8` → `Claude Opus 4.8`. Mirrors the
    # main chat handler: the naive `replace("-", " ").title()` renders the
    # version as two separate word tokens ("Claude Opus 4 8").
    _model_parts = CLAUDE_MODEL.replace("claude-", "").split("-")
    _model_numeric = [p for p in _model_parts if p.isdigit()]
    _model_words = [p for p in _model_parts if not p.isdigit()]
    _name_part = " ".join(w.title() for w in _model_words)
    _version_part = ".".join(_model_numeric)
    _model_display = (
        f"Claude {_name_part} {_version_part}".strip()
        if _version_part
        else f"Claude {_name_part}".strip()
    )
    mode_info.append(f"🟣 {_model_display}")
    mode_info.append("✏️ AI Edit")
    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    mode_str = " • ".join(mode_info)

    # Build API kwargs (Hybrid prompt caching: explicit system + auto history).
    api_kwargs: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "system": build_split_cached_system_prompt(
            stable_system_prompt,
            volatile_system_prompt,
        ),
        "messages": messages,
    }

    if CLAUDE_EFFORT:
        api_kwargs["output_config"] = {"effort": CLAUDE_EFFORT}

    if thinking_enabled:
        if _uses_adaptive_thinking(CLAUDE_MODEL):
            api_kwargs["thinking"] = {"type": "adaptive"}
        elif CLAUDE_MAX_TOKENS > 1024:
            # budget_tokens MUST be strictly < max_tokens — see the matching
            # block in the primary chat handler above for the full rationale.
            _think_budget = max(1024, min(32000, CLAUDE_MAX_TOKENS - 1024))
            _think_budget = min(_think_budget, CLAUDE_MAX_TOKENS - 1)
            api_kwargs["thinking"] = {"type": "enabled", "budget_tokens": _think_budget}

    logger.info("📍 AI Edit via Claude model: %s", CLAUDE_MODEL)

    # Stream response
    try:
        await ws.send_json(
            {
                "type": "stream_start",
                "conversation_id": conversation_id,
                "mode": mode_str,
                "is_edit": True,
                "target_message_id": target_message_id_int,
            }
        )

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
                                await ws.send_json(
                                    {"type": "thinking_start", "conversation_id": conversation_id}
                                )

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        delta_type = getattr(delta, "type", "")

                        if delta_type == "thinking_delta":
                            thought_text = getattr(delta, "thinking", "")
                            if thought_text and thinking_enabled:
                                thinking_content += thought_text
                                await ws.send_json(
                                    {
                                        "type": "thinking_chunk",
                                        "content": thought_text,
                                        "conversation_id": conversation_id,
                                    }
                                )

                        elif delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                if is_thinking:
                                    is_thinking = False
                                    await ws.send_json(
                                        {
                                            "type": "thinking_end",
                                            "conversation_id": conversation_id,
                                            "full_thinking": thinking_content,
                                        }
                                    )
                                full_response += text
                                chunks_count += 1
                                await ws.send_json(
                                    {
                                        "type": "chunk",
                                        "content": text,
                                        "conversation_id": conversation_id,
                                    }
                                )

                    elif event_type == "content_block_stop":
                        if is_thinking:
                            is_thinking = False
                            await ws.send_json(
                                {
                                    "type": "thinking_end",
                                    "conversation_id": conversation_id,
                                    "full_thinking": thinking_content,
                                }
                            )

        _MAX_EDIT_RETRIES = 6

        async def _consume_claude_edit_stream():
            attempt = 1
            # Pre-bind so the asyncio.sleep(delay) at loop bottom can never
            # touch an unbound local. Mirror the chat-stream guard above.
            delay = 1.0
            # See chat-stream handler: capture the last failure so exhaustion can
            # re-raise it for correct outer routing instead of a false success.
            last_error: Exception | None = None

            while attempt <= _MAX_EDIT_RETRIES:
                try:
                    if stream_timeout > 0:
                        await asyncio.wait_for(_stream_once(), timeout=stream_timeout)
                    else:
                        await _stream_once()
                    return
                except _RETRYABLE_ERRORS as retry_err:
                    last_error = retry_err
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⚠️ Claude AI edit overloaded (attempt %d), retrying in %ds: %s",
                        attempt,
                        delay,
                        retry_err,
                    )
                    if attempt < _MAX_EDIT_RETRIES:
                        await ws.send_json(
                            {
                                "type": "chunk",
                                "content": f"\n\n⏳ *Server busy, retrying (attempt {attempt})...*\n\n",
                                "conversation_id": conversation_id,
                            }
                        )
                except TimeoutError as timeout_err:
                    last_error = timeout_err
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "⏱️ Claude AI edit stream timed out on attempt %d, retrying in %ds",
                        attempt,
                        delay,
                    )
                    if attempt < _MAX_EDIT_RETRIES:
                        await ws.send_json(
                            {
                                "type": "chunk",
                                "content": f"\n\n⏳ *Request timed out, retrying (attempt {attempt})...*\n\n",
                                "conversation_id": conversation_id,
                            }
                        )

                _reset_stream_state()
                attempt += 1
                if attempt <= _MAX_EDIT_RETRIES:
                    await asyncio.sleep(delay)

            # All retries exhausted — surface the failure to the outer handler
            # (record_failure + client error frame) instead of falling through to
            # a success-shaped stream_end + record_success().
            logger.error(
                "💀 Claude AI edit stream retries exhausted after %d attempts", attempt - 1
            )
            if last_error is not None:
                raise last_error
            raise RuntimeError("Claude AI edit stream retries exhausted")

        await _consume_claude_edit_stream()

        # Close a dangling thinking block if the edit stream ended mid-
        # reasoning (parity with the chat handler / Gemini path).
        if is_thinking:
            is_thinking = False
            await ws.send_json(
                {
                    "type": "thinking_end",
                    "conversation_id": conversation_id,
                    "full_thinking": thinking_content,
                }
            )

        # Apply search/replace patches if present, otherwise use full response
        final_content = (
            _apply_search_replace(original_content, full_response) if full_response else ""
        )

        # Update the message in DB. Pass conversation_id so the UPDATE only
        # matches when the row is in the conversation the AI was editing —
        # prevents an attacker (or a bug) from coercing this path into
        # rewriting messages in a different conversation. Also refuse to
        # write whitespace-only content (truthy but useless) so a bad AI
        # response can't blank the user's message.
        if final_content and final_content.strip():
            try:
                db = _get_db()
                await db.update_dashboard_message(
                    target_message_id_int,
                    final_content,
                    expected_conversation_id=conversation_id,
                )
            except Exception as e:
                logger.warning("Failed to update AI-edited message in DB: %s", e)
            else:
                # After rewriting a DB row the cached --resume session replays
                # the OLD content server-side; wipe it so a later CLI-backend
                # turn doesn't resume pre-edit state. Both sibling backends
                # (gemini dashboard_chat.py, CLI dashboard_chat_claude_cli.py)
                # already do this; the SDK path was the only one that didn't.
                try:
                    from .dashboard_chat_claude_cli import delete_session_file

                    await delete_session_file(conversation_id)
                except Exception:
                    logger.exception("Failed to reset CLI session after SDK AI edit")
        elif full_response:
            logger.warning(
                "AI edit produced empty/whitespace content; keeping original message %s",
                target_message_id_int,
            )
            # Keep the DB row intact AND echo the original back so the client
            # doesn't blank the bubble (it renders full_response unconditionally).
            final_content = original_content

        await ws.send_json(
            {
                "type": "stream_end",
                "conversation_id": conversation_id,
                "full_response": final_content,
                "chunks_count": chunks_count,
                "is_edit": True,
                "target_message_id": target_message_id_int,
            }
        )

        if _FAILOVER_AVAILABLE:
            await _api_failover.record_success()

    except TimeoutError:
        logger.error("❌ Claude AI edit streaming timeout")
        if _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(TimeoutError("edit stream timeout"))
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Edit timed out. Please try again.",
                    "conversation_id": conversation_id,
                }
            )
        except Exception:
            logger.debug("WebSocket send failed during Claude AI edit timeout handling")
    except Exception as e:
        logger.exception("❌ Claude AI edit streaming error")
        # Client WS disconnect (ConnectionResetError from ws.send_json) is not
        # an endpoint failure — abort without polluting failover health.
        if isinstance(e, ConnectionResetError):
            logger.info("Dashboard client disconnected during AI edit; aborting (no failover).")
            return
        if _FAILOVER_AVAILABLE:
            await _api_failover.record_failure(e)
        # anthropic.APITimeoutError is not a builtin TimeoutError subclass, so a
        # timeout re-raised after retry exhaustion lands here rather than in the
        # dedicated `except TimeoutError` branch above — surface the same friendly
        # timeout message instead of the generic "Failed to edit message."
        if isinstance(e, anthropic.APITimeoutError):
            edit_error_message = "Edit timed out. Please try again."
        else:
            edit_error_message = "Failed to edit message."
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": edit_error_message,
                    "conversation_id": conversation_id,
                }
            )
        except Exception:
            logger.debug("WebSocket send failed during Claude AI edit error handling")
