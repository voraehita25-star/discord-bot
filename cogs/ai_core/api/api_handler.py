"""
Claude API Handler Module for AI Core.
Handles API configuration, streaming and non-streaming calls, retry logic, and fallback strategies.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
logger = logging.getLogger(__name__)
import re
import time
from typing import Any, TypedDict

import anthropic
from anthropic.types.message_param import MessageParam

from ..claude_payloads import (
    ClaudeContentBlockParam,
    ClaudeMessageRole,
    build_claude_base64_image_block,
    build_claude_message,
    build_claude_text_block,
    build_single_user_text_messages,
)
from ..data import (
    FAUST_DM_INSTRUCTION,
    FAUST_INSTRUCTION,
    ROLEPLAY_ASSISTANT_INSTRUCTION,
)
from ..data.constants import CLAUDE_MAX_TOKENS

# Import circuit breaker for API protection
try:
    from utils.reliability.circuit_breaker import gemini_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    gemini_circuit = None  # type: ignore[assignment]

# Import performance tracker
try:
    from utils.monitoring.performance_tracker import perf_tracker

    PERF_TRACKER_AVAILABLE = True
except ImportError:
    PERF_TRACKER_AVAILABLE = False
    perf_tracker = None  # type: ignore[assignment]

# Import error recovery
try:
    from utils.reliability.error_recovery import service_monitor

    ERROR_RECOVERY_AVAILABLE = True
except ImportError:
    ERROR_RECOVERY_AVAILABLE = False
    service_monitor = None  # type: ignore[assignment]

# Import guardrails
try:
    from ..processing.guardrails import is_silent_block
except ImportError:

    def is_silent_block(response: str, expected_min_length: int = 50) -> bool:
        return False


_CLAUDE_RETRY_BASE_DELAY = 1.0
_CLAUDE_RETRY_MAX_DELAY = 30.0
_CLAUDE_MAX_CONTENT_RETRIES = 5
_CLAUDE_MAX_API_RETRIES = 8  # Max retries for transient API errors (rate limit, server error)
_CLAUDE_MAX_STREAM_RETRIES = 6  # Max retries for streaming failures


class _ClaudeMessage(TypedDict):
    role: ClaudeMessageRole
    content: list[ClaudeContentBlockParam]


def _claude_retry_delay_seconds(attempt: int, *, minimum_delay: float = 1.0) -> float:
    delay = _CLAUDE_RETRY_BASE_DELAY
    for _ in range(1, attempt):
        if delay >= _CLAUDE_RETRY_MAX_DELAY:
            break
        delay = min(delay * 2, _CLAUDE_RETRY_MAX_DELAY)
    return max(delay, minimum_delay)

def build_api_config(
    chat_data: dict[str, Any],
    guild_id: int | None = None,
    use_search: bool = False,
) -> dict[str, Any]:
    """Build API configuration for Claude.

    Args:
        chat_data: Chat configuration data containing system_instruction and thinking_enabled.
        guild_id: Optional guild ID.
        use_search: If True, indicates search was requested (logged only, Claude has no built-in search).

    Returns:
        Dict of configuration parameters for Claude API.
    """
    system_instruction = chat_data.get("system_instruction", "")
    # Use 'in' instead of '==' because server lore is appended to instructions
    is_faust_mode = FAUST_INSTRUCTION in system_instruction
    is_faust_dm_mode = FAUST_DM_INSTRUCTION in system_instruction
    is_rp_mode = ROLEPLAY_ASSISTANT_INSTRUCTION in system_instruction
    thinking_enabled = chat_data.get("thinking_enabled", True)

    config_params: dict[str, Any] = {
        "system_instruction": system_instruction,
        "max_tokens": CLAUDE_MAX_TOKENS,
    }

    # Enable adaptive thinking for RP/Faust modes when thinking is enabled
    # Claude Opus 4.6 uses adaptive thinking (type: "adaptive") instead of
    # manual budget_tokens which is deprecated on this model.
    if (is_faust_mode or is_faust_dm_mode or is_rp_mode) and thinking_enabled:
        config_params["thinking"] = {"type": "adaptive"}
        logger.info("🧠 Adaptive Thinking Mode: ENABLED")
    else:
        logger.info("💬 Standard Mode (no extended thinking)")

    if use_search:
        logger.info("🔍 Search was requested (content added via URL fetcher)")

    return config_params


# ==================== Search Intent Pre-Filter ====================
# Multi-layer heuristic that classifies messages as SEARCH / NO_SEARCH / UNCERTAIN
# to avoid an expensive AI API call for obvious cases.
#
# Layer 1: Regex patterns that strongly indicate search IS needed
# Layer 2: Regex patterns that strongly indicate search is NOT needed
# Layer 3: Scoring heuristic for borderline messages

# --- Layer 1: Patterns that indicate SEARCH ---

# Factual question patterns (Thai + English)
_FACTUAL_QUESTION_RE = re.compile(
    r"""(?:
        # English factual question starters
        \b(?:what|who|where|when|which|how\s+(?:much|many|long|old|far|tall|big))
            \s+(?:is|are|was|were|does|do|did|will|would|can|could|has|have)\b
        # "how to" / "how do I" — looking for instructions/procedures
        | \bhow\s+(?:to|do\s+(?:i|you|we))\b
        # Thai factual question particles (no space boundaries — Thai is unsegmented)
        | (?:อะไร|ใคร|ที่ไหน|เมื่อไหร่|กี่|เท่าไหร่|ยังไง|อย่างไร)
        | คือ(?:อะไร|ใคร)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Time-sensitive / current event patterns
_TIME_SENSITIVE_RE = re.compile(
    r"""(?:
        \b(?:latest|newest|recent|current|today|yesterday|this\s+(?:week|month|year)
            |breaking\s+news|update[sd]?|trending|patch\s+note|changelog|announce)
        \b
        | (?:ล่าสุด|ตอนนี้|วันนี้|เมื่อวาน|สัปดาห์นี้|เดือนนี้|ปีนี้
            |อัปเดต|แพทช์โน้ต|ข่าว)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Comparison / benchmark / lookup patterns
_LOOKUP_RE = re.compile(
    r"""(?:
        \b(?:compare|versus|vs\.?|benchmark|ranking|tier\s+list|top\s+\d+
            |best\s+(?:way|method|practice)|difference\s+between
            |recipe|ingredient|symptom|side\s+effect|dosage
            |weather|forecast|stock|crypto|exchange\s+rate|population)
        \b
        | (?:เปรียบเทียบ|อันดับ|เทียบ|สูตร|ส่วนผสม|อาการ|สภาพอากาศ|หุ้น)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Explicit search request
_EXPLICIT_SEARCH_RE = re.compile(
    r"""(?:
        \b(?:search|google|look\s+up|find\s+(?:me|out)|wiki(?:pedia)?|source|reference|cite|link)
        \b
        | (?:หา(?:ให้|มา)|ค้นหา|เสิร์ช|กูเกิล|วิกิ|อ้างอิง|ลิงก์|ลิ้งค์)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Technical lookup / definition patterns
_DEFINITION_RE = re.compile(
    r"""(?:
        \b(?:define|definition|meaning\s+of|explain\s+(?:what|the\s+concept)|what\s+does\s+\S+\s+mean)
        \b
        | (?:แปลว่า|หมายความว่า|นิยาม|ความหมาย)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

_SEARCH_PATTERNS: list[tuple[re.Pattern, int]] = [
    # (pattern, weight) — higher weight = stronger search signal
    (_FACTUAL_QUESTION_RE, 2),   # Direct factual questions are strong signals
    (_TIME_SENSITIVE_RE, 2),     # Time-sensitive queries almost always need search
    (_LOOKUP_RE, 2),             # Comparison/lookup patterns are clear search intent
    (_EXPLICIT_SEARCH_RE, 2),    # Explicit "search for X" is definitive
    (_DEFINITION_RE, 2),          # Definition questions need factual lookup
]

# --- Layer 2: Patterns that indicate NO_SEARCH ---

# Roleplay markers: *action*, character acting
_ROLEPLAY_RE = re.compile(
    r"""(?:
        ^\s*\*[^*]+\*           # *action text*
        | ^\s*\([^)]+\)         # (action text)
        | ^\s*>[^>]             # >greentext style
    )""",
    re.VERBOSE | re.MULTILINE,
)

# Greeting / social chat
_GREETING_RE = re.compile(
    r"""(?:
        ^(?:hi|hello|hey|yo|sup|good\s+(?:morning|afternoon|evening|night)
            |bye|goodbye|see\s+ya|thanks|thank\s+you|ty|gn|gm)
        [\s!.\U0001f600-\U0001f64f]*$
        | ^(?:สวัสดี|หวัดดี|ดีครับ|ดีค่ะ|ดีจ้า|บาย|ลาก่อน|ขอบคุณ|ไง|ว่าไง)
        [\s!.\U0001f600-\U0001f64f]*$
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Pure emotional / reaction expressions
_EMOTION_RE = re.compile(
    r"""(?:
        ^[\s]*(?:lol|lmao|rofl|haha[ha]*|555+|oof|bruh|omg|wow|wtf|xd+|:[\w]+:
            |pog|kek|sadge|copium|hopium|based|fr|No\s*way
            |5555+|ขำ|ฮ่าๆ|โอ้|ว้าว|เฮ้ย|โคตร|งง|อิอิ|อารมณ์ดี|เศร้า)
        [\s!?.\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f900-\U0001f9ff]*$
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Creative / generative requests (AI can handle without search)
_CREATIVE_RE = re.compile(
    r"""(?:
        \b(?:write\s+(?:me\s+)?(?:a|an|the)|compose|create|generate|make\s+(?:up|me)
            |tell\s+(?:me\s+)?a\s+(?:story|joke|poem)|imagine|pretend|roleplay|act\s+as
            |sing|rap|summarize\s+(?:this|the\s+above|our\s+chat))
        \b
        | (?:เขียน(?:ให้|มา)|แต่ง|สร้าง|เล่า(?:นิทาน|เรื่อง)|สมมติ|จินตนาการ
            |ร้องเพลง|แร็ป|สรุป)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Opinion / subjective questions (no factual lookup needed)
_OPINION_RE = re.compile(
    r"""(?:
        \b(?:do\s+you\s+(?:think|like|prefer|feel|believe)
            |what(?:'s|\s+is)\s+your\s+(?:opinion|thought|favorite|take)
            |should\s+i|would\s+you\s+rather|rate\s+(?:this|my)|review\s+(?:this|my)
            |(?:is|isn't|are|aren't)\s+(?:it|this|that)\s+(?:good|bad|cool|fun|worth))
        \b
        | (?:คิดว่า(?:ไง|ยังไง|อย่างไร)|ชอบ(?:ไหม|มั้ย)|ควร(?:ไหม|มั้ย)
            |รีวิว|ให้คะแนน|ดีไหม|สนุกไหม)
    )""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Short casual messages (< 5 words, no question mark) — likely chat
_SHORT_CASUAL_RE = re.compile(
    r'^[^?？]{1,30}$',  # noqa: RUF001 - fullwidth ？ is intentional (Thai/Japanese input)
    re.UNICODE,
)

_NO_SEARCH_PATTERNS: list[tuple[re.Pattern, int]] = [
    # (pattern, weight) — higher weight = stronger no-search signal
    (_ROLEPLAY_RE, 3),
    (_GREETING_RE, 3),
    (_EMOTION_RE, 3),
    (_CREATIVE_RE, 2),
    (_OPINION_RE, 2),
]


# --- Layer 3: Scoring ---

# Additional search signal keywords (each adds +1 to search score)
_SEARCH_SIGNAL_WORDS = frozenset({
    "price", "cost", "buy", "sell", "stock", "rate", "salary", "worth",
    "release", "date", "schedule", "event", "maintenance", "server",
    "download", "install", "version", "specs", "requirements",
    "error", "bug", "fix", "patch", "issue", "crash",
    "map", "location", "address", "route", "distance",
    "score", "result", "standing", "leaderboard", "rank",
    "ราคา", "ซื้อ", "ขาย", "เงิน", "กำหนดการ", "ดาวน์โหลด",
    "เวอร์ชัน", "แผนที่", "ที่อยู่", "คะแนน", "ผลลัพธ์",
})

# No-search signal keywords (each adds +1 to no-search score)
_NO_SEARCH_SIGNAL_WORDS = frozenset({
    "feel", "feelings", "love", "hate", "happy", "sad", "angry", "mood",
    "dream", "wish", "hope", "believe", "imagine", "pretend",
    "think", "prefer", "opinion",
    "story", "poem", "joke", "song", "chat", "talk",
    "cute", "cool", "awesome", "amazing", "boring", "funny",
    "รู้สึก", "รัก", "เกลียด", "ฝัน", "อยาก", "หวัง",
    "นิทาน", "บทกวี", "มุก", "เพลง", "คุย", "น่ารัก", "คิดว่า",
})


def classify_search_intent(message: str) -> bool | None:
    """Classify whether a message needs web search using heuristic pre-filter.

    Returns:
        True  — definitely needs search (skip AI call)
        False — definitely no search needed (skip AI call)
        None  — uncertain, should fall through to AI-based detection
    """
    if not message or not message.strip():
        return False

    msg = message.strip()
    msg_lower = msg.lower()
    word_count = len(msg.split())

    # --- Layer 1: Check search-indicating patterns ---
    search_pattern_score = sum(w for p, w in _SEARCH_PATTERNS if p.search(msg))
    if search_pattern_score >= 3:
        # Strong search signals → high confidence
        return True

    # --- Layer 2: Check no-search patterns ---
    no_search_pattern_score = sum(w for p, w in _NO_SEARCH_PATTERNS if p.search(msg))
    if no_search_pattern_score >= 3:
        return False

    # Short casual message with no question marks and no search pattern
    if word_count <= 4 and search_pattern_score == 0 and _SHORT_CASUAL_RE.match(msg):
        return False

    # --- Layer 3: Scoring for borderline cases ---
    words = set(re.findall(r'[a-zA-Z\u0E00-\u0E7F]+', msg_lower))

    search_score = search_pattern_score  # Start with weighted pattern hits
    search_score += len(words & _SEARCH_SIGNAL_WORDS)

    no_search_score = no_search_pattern_score  # Start with weighted pattern hits
    no_search_score += len(words & _NO_SEARCH_SIGNAL_WORDS)
    # Question marks are a mild search signal
    if '?' in msg or '？' in msg:  # noqa: RUF001 - fullwidth ？ intentional
        search_score += 1

    # If scoring is decisive (gap >= 2), return the verdict
    gap = search_score - no_search_score
    if gap >= 2:
        return True
    if gap <= -2:
        return False

    # Uncertain — fall through to AI detection
    return None


async def detect_search_intent(
    client: anthropic.AsyncAnthropic,
    target_model: str,
    message: str,
) -> bool:
    """Use AI to detect if user's message requires web search.

    Args:
        client: Anthropic async client.
        target_model: Model name to use.
        message: User message to analyze.

    Returns:
        True if web search is needed, False otherwise.
    """
    try:
        prompt = f"""You need to decide: should I search the web to answer this message?

Message: "{message}"

Reply ONLY "SEARCH" or "NO_SEARCH":
- SEARCH = Need up-to-date info from web, wiki, or external source
  Examples: game stats, Identity details, rarity info, news, wiki data
- NO_SEARCH = Can answer from general knowledge, roleplay, chat, opinions

IMPORTANT: For questions about Limbus Company, Project Moon, Identities,
E.G.O, character stats, rarity levels, skill info - reply "SEARCH".

Reply ONE word: SEARCH or NO_SEARCH"""

        response = await client.messages.create(
            model=target_model,
            max_tokens=10,
            messages=build_single_user_text_messages(prompt),
        )

        result = ""
        for block in response.content:
            if block.type == "text":
                result = block.text.strip().upper()
                break
        needs_search = "SEARCH" in result and "NO_SEARCH" not in result

        logger.info(
            "🔎 Search intent: %s -> %s",
            message[:40],
            "SEARCH" if needs_search else "NO_SEARCH",
        )

        return needs_search

    except (ValueError, TypeError, anthropic.APIError):
        logger.exception("🔎 Search intent detection FAILED")
        return False  # Default to no search on error


def convert_to_claude_messages(
    contents: list[dict[str, Any]],
) -> list[MessageParam]:
    """Convert Gemini-format contents to Claude messages format.

    Gemini format: [{"role": "user"/"model", "parts": [{"text": "..."}, {"inline_data": {...}}]}]
    Claude format: [{"role": "user"/"assistant", "content": [{"type": "text", "text": "..."}, ...]}]

    Args:
        contents: List of messages in Gemini internal format.

    Returns:
        List of messages in Claude API format.
    """
    messages: list[_ClaudeMessage] = []

    for item in contents:
        role = item.get("role", "user")
        claude_role: ClaudeMessageRole = "assistant" if role == "model" else "user"
        parts = item.get("parts", [])

        content_blocks: list[ClaudeContentBlockParam] = []
        for part in parts:
            if isinstance(part, dict):
                if "text" in part:
                    content_blocks.append(build_claude_text_block(part["text"]))
                elif "inline_data" in part and isinstance(part["inline_data"], dict):
                    data = part["inline_data"]
                    image_block = build_claude_base64_image_block(
                        data.get("data", ""),
                        data.get("mime_type", "image/png"),
                    )
                    if image_block is not None:
                        content_blocks.append(image_block)
                    else:
                        mime_type = data.get("mime_type", "unknown")
                        content_blocks.append(
                            build_claude_text_block(
                                f"[User attached unsupported media omitted: {mime_type}]"
                            )
                        )
            elif isinstance(part, str):
                content_blocks.append(build_claude_text_block(part))

        if not content_blocks:
            continue

        # Claude requires alternating user/assistant messages — merge consecutive same-role
        if messages and messages[-1]["role"] == claude_role:
            messages[-1]["content"].extend(content_blocks)
        else:
            messages.append({"role": claude_role, "content": content_blocks})

    # Claude requires messages to start with "user" role
    if messages and messages[0]["role"] == "assistant":
        messages.insert(
            0,
            {"role": "user", "content": [build_claude_text_block("[conversation continues]")]},
        )

    typed_messages: list[MessageParam] = []
    for message in messages:
        typed_messages.append(build_claude_message(message["role"], message["content"]))

    return typed_messages


async def call_claude_api_streaming(
    client: anthropic.AsyncAnthropic,
    target_model: str,
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    send_channel: Any,
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
    fallback_func: Any = None,
) -> tuple[str, str, list[Any]]:
    """Call Claude API with streaming for real-time response updates.

    Args:
        client: Anthropic async client.
        target_model: Model name to use.
        contents: Message contents in Gemini internal format (converted here).
        config_params: API configuration.
        send_channel: Discord channel to send streaming updates.
        channel_id: Channel ID for cancellation checks.
        cancel_flags: Dict of channel_id -> should_cancel flags.
        fallback_func: Async function to call on streaming failure.

    Returns:
        Tuple of (model_text, search_indicator, function_calls).
    """
    model_text = ""
    search_indicator = ""
    function_calls: list[Any] = []
    placeholder_msg = None
    update_interval = 1.0
    chunks_received = 0
    stream_attempt = 1

    try:
        # Check circuit breaker
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
            logger.warning("⚡ Circuit breaker OPEN - skipping streaming API call")
            return "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่", "", []

        # Send initial placeholder
        placeholder_msg = await send_channel.send("💭 กำลังคิด...")

        # Convert contents to Claude format
        messages = convert_to_claude_messages(contents)
        system_prompt = config_params.get("system_instruction", "")
        max_tokens = config_params.get("max_tokens", CLAUDE_MAX_TOKENS)

        # Streaming does not use extended thinking (remove if present)
        streaming_config = copy.deepcopy(config_params)
        if "thinking" in streaming_config:
            streaming_config.pop("thinking")
            logger.info("🌊 Streaming mode: Disabled thinking for real-time updates")
    except Exception as e:
        logger.warning("⚠️ Streaming setup failed, falling back to normal API: %s", e)
        if placeholder_msg:
            with contextlib.suppress(Exception):
                await placeholder_msg.delete()
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
            gemini_circuit.record_failure()
        if fallback_func:
            return await fallback_func(contents, config_params, channel_id)  # type: ignore[no-any-return]
        return "", "", []

    max_stall_time = 60.0
    while stream_attempt <= _CLAUDE_MAX_STREAM_RETRIES:
            current_model_text = ""
            current_chunks_received = 0
            last_update_time = 0.0
            stream_start_time = time.time()

            try:
                stream = client.messages.stream(
                    model=target_model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=messages,
                )

                async with stream as response_stream:
                    async for text in response_stream.text_stream:
                        current_chunks_received += 1

                        if channel_id and cancel_flags and cancel_flags.get(channel_id, False):
                            logger.info("⏹️ Streaming cancelled for channel %s", channel_id)
                            if placeholder_msg:
                                with contextlib.suppress(Exception):
                                    await placeholder_msg.delete()
                            return "", "", []

                        elapsed = time.time() - stream_start_time
                        if elapsed > max_stall_time and len(current_model_text) < 50:
                            raise TimeoutError(f"Claude stream stalled after {elapsed:.1f}s")

                        if text:
                            current_model_text += text

                            current_time = time.time()
                            if current_time - last_update_time >= update_interval:
                                last_update_time = current_time
                                display_text = current_model_text
                                if len(display_text) > 1900:
                                    display_text = display_text[:1900] + "..."
                                progress = f"✍️ ({current_chunks_received} chunks)"
                                display_text += f" {progress}"
                                try:
                                    await placeholder_msg.edit(content=display_text)
                                except Exception as edit_error:
                                    logger.debug("Failed to update streaming message: %s", edit_error)

                model_text = current_model_text
                chunks_received = current_chunks_received

                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_success()

                if placeholder_msg:
                    with contextlib.suppress(Exception):
                        await placeholder_msg.delete()

                stream_duration = time.time() - stream_start_time
                logger.info(
                    "🌊 Streaming complete: %d chars, %d chunks, %.1fs",
                    len(model_text),
                    chunks_received,
                    stream_duration,
                )
                return model_text, search_indicator, function_calls

            except TimeoutError as e:
                if len(current_model_text) > 100:
                    logger.info("🔄 Using partial streaming result (%d chars)", len(current_model_text))
                    if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                        gemini_circuit.record_success()
                    if placeholder_msg:
                        with contextlib.suppress(Exception):
                            await placeholder_msg.delete()
                    return current_model_text, search_indicator, function_calls

                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                delay = _claude_retry_delay_seconds(stream_attempt)
                logger.warning(
                    "⚠️ Claude streaming timeout on attempt %d after %d chunks: %s. Retrying in %.1fs",
                    stream_attempt,
                    current_chunks_received,
                    e,
                    delay,
                )

            except (
                anthropic.RateLimitError,
                anthropic.InternalServerError,
                anthropic.APIConnectionError,
                OSError,
            ) as e:
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                delay = _claude_retry_delay_seconds(
                    stream_attempt,
                    minimum_delay=5.0 if isinstance(e, anthropic.RateLimitError) else 1.0,
                )
                logger.warning(
                    "⚠️ Claude streaming transient failure on attempt %d after %d chunks: %s. Retrying in %.1fs",
                    stream_attempt,
                    current_chunks_received,
                    e,
                    delay,
                )

            except Exception as e:
                logger.warning("⚠️ Streaming failed, falling back to normal API: %s", e)
                if placeholder_msg:
                    with contextlib.suppress(Exception):
                        await placeholder_msg.delete()
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                if fallback_func:
                    return await fallback_func(contents, config_params, channel_id)  # type: ignore[no-any-return]
                return "", "", []

            model_text = ""
            chunks_received = 0
            if placeholder_msg:
                with contextlib.suppress(Exception):
                    await placeholder_msg.edit(
                        content=f"⏳ Claude server busy, retrying (attempt {stream_attempt})..."
                    )
            await asyncio.sleep(delay)
            stream_attempt += 1

    # All stream retries exhausted — fall back to non-streaming API
    logger.warning("⚠️ Streaming retries exhausted after %d attempts, falling back", stream_attempt - 1)
    if placeholder_msg:
        with contextlib.suppress(Exception):
            await placeholder_msg.delete()
    if fallback_func:
        return await fallback_func(contents, config_params, channel_id)  # type: ignore[no-any-return]
    return "", "", []


async def call_claude_api(
    client: anthropic.AsyncAnthropic,
    target_model: str,
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
) -> tuple[str, str, list[Any]]:
    """Call Claude API with retry logic, refusal detection, and multi-tiered fallback.

    Args:
        client: Anthropic async client.
        target_model: Model name to use.
        contents: Message contents in Gemini internal format (converted here).
        config_params: API configuration.
        channel_id: Channel ID for cancellation checks.
        cancel_flags: Dict of channel_id -> should_cancel flags.

    Returns:
        Tuple of (model_text, search_indicator, function_calls).

    Fallback Tiers:
        - Tier 1: Standard retry with Thinking Mode fallback
        - Tier 2: Content reduction (truncate large text)
        - Tier 3: Reframe as "continuation" for blocked content
        - Tier 4: Abstract literary analysis framing
    """
    model_text = ""
    search_indicator = ""
    function_calls: list[Any] = []
    content_retry_attempt = 0
    api_attempt = 1
    _api_start_time = time.time()

    # Deep copy contents and config to avoid mutating caller's data during retry/fallback
    contents = copy.deepcopy(contents)
    config_params = copy.deepcopy(config_params)

    while api_attempt <= _CLAUDE_MAX_API_RETRIES:
        # Check for cancellation
        if channel_id and cancel_flags and cancel_flags.get(channel_id, False):
            logger.info("⏹️ API call cancelled for channel %s", channel_id)
            return "", "", []

        try:
            # Check circuit breaker
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
                logger.warning("⚡ Circuit breaker OPEN - skipping Claude API call")
                return "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่", "", []

            # Convert contents to Claude format
            messages = convert_to_claude_messages(contents)
            system_prompt = config_params.get("system_instruction", "")
            max_tokens = config_params.get("max_tokens", CLAUDE_MAX_TOKENS)

            # Build Claude API kwargs
            api_kwargs: dict[str, Any] = {
                "model": target_model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
            }

            # Add extended thinking if configured
            thinking_config = config_params.get("thinking")
            if thinking_config:
                api_kwargs["thinking"] = thinking_config

            api_timeout = 120.0
            try:
                response = await asyncio.wait_for(
                    client.messages.create(**api_kwargs),
                    timeout=api_timeout,
                )
            except TimeoutError:
                delay = _claude_retry_delay_seconds(api_attempt)
                logger.error(
                    "⏱️ Claude API timeout after %.0fs (attempt %d). Retrying in %.1fs",
                    api_timeout,
                    api_attempt,
                    delay,
                    extra={"event": "api_timeout", "attempt": api_attempt, "timeout_s": api_timeout, "retry_delay_s": delay},
                )
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                if ERROR_RECOVERY_AVAILABLE and service_monitor:
                    service_monitor.record_failure("claude_api", "timeout")
                await asyncio.sleep(delay)
                api_attempt += 1
                continue

            # Record success
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_success()
            if ERROR_RECOVERY_AVAILABLE and service_monitor:
                service_monitor.record_success("claude_api")

            # Extract text from Claude response
            temp_text = ""
            for block in response.content:
                if block.type == "text":
                    temp_text += block.text

            # Empty/silent response detection
            if temp_text and temp_text.strip():
                model_text = temp_text
                break

            if is_silent_block(temp_text):
                logger.warning(
                    "⚠️ Silent block detected (attempt %s). AI response: %s",
                    content_retry_attempt + 1,
                    repr(temp_text) if temp_text else "(empty)",
                )

            content_retry_attempt += 1
            logger.warning(
                "Attempt %s/%s: Claude returned empty response",
                content_retry_attempt,
                _CLAUDE_MAX_CONTENT_RETRIES,
            )

            if content_retry_attempt >= _CLAUDE_MAX_CONTENT_RETRIES:
                logger.warning(
                    "⚠️ Claude content retries exhausted after %d attempts",
                    _CLAUDE_MAX_CONTENT_RETRIES,
                )
                break

        except anthropic.RateLimitError as e:
            delay = _claude_retry_delay_seconds(api_attempt, minimum_delay=5.0)
            logger.warning(
                "⚠️ Claude API rate limited on attempt %d: %s. Retrying in %.1fs",
                api_attempt,
                e,
                delay,
                extra={"event": "api_rate_limit", "attempt": api_attempt, "retry_delay_s": delay},
            )
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            if ERROR_RECOVERY_AVAILABLE and service_monitor:
                service_monitor.record_failure("claude_api", "rate_limit")
            await asyncio.sleep(delay)
            api_attempt += 1
            continue

        except (
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            OSError,
        ) as api_error:
            delay = _claude_retry_delay_seconds(api_attempt)
            logger.warning(
                "⚠️ Claude API transient failure on attempt %d: %s. Retrying in %.1fs",
                api_attempt,
                api_error,
                delay,
            )
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            if ERROR_RECOVERY_AVAILABLE and service_monitor:
                service_monitor.record_failure("claude_api", str(api_error)[:100])
            await asyncio.sleep(delay)
            api_attempt += 1
            continue

        except Exception as api_error:
            logger.warning("⚠️ Claude API non-retryable failure: %s", api_error)
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            if ERROR_RECOVERY_AVAILABLE and service_monitor:
                service_monitor.record_failure("claude_api", str(api_error)[:100])
            break

        # Fallback strategies for empty responses
        if "thinking" in config_params:
            logger.warning("⚠️ Fallback: Disabling 'Thinking Mode' for retry")
            config_params.pop("thinking", None)

        # Content reduction for large messages
        if content_retry_attempt >= 2 and contents:
            last_message = contents[-1] if contents else None
            if last_message and "parts" in last_message:
                for part in last_message["parts"]:
                    if isinstance(part, dict) and "text" in part:
                        text = part["text"]
                        if len(text) > 10000:
                            truncated = (
                                text[:5000] + "\n\n[... content truncated ...]\n\n" + text[-3000:]
                            )
                            part["text"] = truncated
                            logger.warning(
                                "⚠️ Fallback: Truncated large text (was %d chars)", len(text)
                            )

        await asyncio.sleep(_claude_retry_delay_seconds(content_retry_attempt))
    else:
        # while-loop exhausted without break — all API retries used
        logger.error("💀 Claude API retries exhausted after %d attempts", api_attempt - 1)

    # Record performance metrics
    if PERF_TRACKER_AVAILABLE and perf_tracker:
        perf_tracker.record("claude_api", _api_start_time)

    return model_text, search_indicator, function_calls
