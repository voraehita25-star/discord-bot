"""
Gemini API Handler Module for AI Core.
Handles API configuration, streaming and non-streaming calls, retry logic, and fallback strategies.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import time
from typing import Any, cast

from google import genai
from google.genai import types

from ..data.constants import THINKING_BUDGET_DEFAULT
from ..data import (
    ESCALATION_FRAMINGS,
    FAUST_DM_INSTRUCTION,
    FAUST_INSTRUCTION,
    ROLEPLAY_ASSISTANT_INSTRUCTION,
)

# Import circuit breaker for API protection
try:
    from utils.reliability.circuit_breaker import gemini_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    gemini_circuit = None

# Import performance tracker
try:
    from utils.monitoring.performance_tracker import perf_tracker

    PERF_TRACKER_AVAILABLE = True
except ImportError:
    PERF_TRACKER_AVAILABLE = False
    perf_tracker = None

# Import error recovery
try:
    from utils.reliability.error_recovery import service_monitor

    ERROR_RECOVERY_AVAILABLE = True
except ImportError:
    ERROR_RECOVERY_AVAILABLE = False
    service_monitor = None

# Import guardrails
try:
    from ..processing.guardrails import detect_refusal, is_silent_block

    GUARDRAILS_AVAILABLE = True
except ImportError:
    GUARDRAILS_AVAILABLE = False

    def detect_refusal(response: str) -> tuple[bool, str | None]:
        return False, None

    def is_silent_block(response: str, expected_min_length: int = 50) -> bool:
        return False


def build_api_config(
    chat_data: dict[str, Any],
    guild_id: int | None = None,
    use_search: bool = False,
) -> dict[str, Any]:
    """Build API configuration for Gemini.

    Args:
        chat_data: Chat configuration data containing system_instruction and thinking_enabled.
        guild_id: Optional guild ID.
        use_search: If True, enable Google Search (disables Thinking mode).

    Returns:
        Dict of configuration parameters for Gemini API.
    """
    system_instruction = chat_data.get("system_instruction", "")
    # Use 'in' instead of '==' because server lore is appended to instructions
    is_faust_mode = FAUST_INSTRUCTION in system_instruction
    is_faust_dm_mode = FAUST_DM_INSTRUCTION in system_instruction
    is_rp_mode = ROLEPLAY_ASSISTANT_INSTRUCTION in system_instruction
    thinking_enabled = chat_data.get("thinking_enabled", True)

    config_params = {
        "system_instruction": system_instruction,
        # NOTE: BLOCK_NONE is intentional — application-level guardrails
        # (OutputGuardrails, input validation) handle content filtering instead
        # of relying on API-level safety filters. Do not change.
        "safety_settings": [
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        ],
    }

    # Dynamic mode switching: Google Search OR Thinking (cannot use both)
    if use_search:
        # Use Google Search - for real-time web information
        config_params["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        logging.info("🔍 Google Search: ENABLED (search requested)")
    elif (is_faust_mode or is_faust_dm_mode or is_rp_mode) and thinking_enabled:
        # Use Thinking mode for deep reasoning
        config_params["thinking_config"] = types.ThinkingConfig(
            thinking_budget=THINKING_BUDGET_DEFAULT
        )
        logging.info("🧠 Thinking Mode: ENABLED (budget: %d)", THINKING_BUDGET_DEFAULT)
    else:
        # Default: Google Search for non-RP modes
        config_params["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        logging.info("🔍 Google Search: ENABLED (default)")

    return config_params


async def detect_search_intent(
    client: genai.Client,
    target_model: str,
    message: str,
) -> bool:
    """Use AI to detect if user's message requires web search.

    Args:
        client: Gemini API client.
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

        response = await client.aio.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=10, temperature=0.0),
        )

        result = response.text.strip().upper() if response.text else ""
        needs_search = "SEARCH" in result and "NO_SEARCH" not in result

        logging.info(
            "🔎 Search intent: %s -> %s",
            message[:40],
            "SEARCH" if needs_search else "NO_SEARCH",
        )

        return needs_search

    except Exception as e:
        logging.error("🔎 Search intent detection FAILED: %s", e)
        return False  # Default to no search on error


async def call_gemini_api_streaming(
    client: genai.Client,
    target_model: str,
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    send_channel: Any,
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
    fallback_func: Any = None,
) -> tuple[str, str, list[Any]]:
    """Call Gemini API with streaming for real-time response updates.

    Args:
        client: Gemini API client.
        target_model: Model name to use.
        contents: Message contents for API.
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
    function_calls = []
    placeholder_msg = None
    last_update_time = 0
    update_interval = 1.0
    stream_start_time = 0.0  # Track start time for performance
    chunks_received = 0  # Initialize outside try block for exception handler access

    try:
        # Check circuit breaker
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
            logging.warning("⚡ Circuit breaker OPEN - skipping streaming API call")
            return "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่", "", []

        # Send initial placeholder
        placeholder_msg = await send_channel.send("💭 กำลังคิด...")

        # Remove thinking_config for streaming (deep copy to avoid mutating nested objects)
        streaming_config = copy.deepcopy(config_params)
        if "thinking_config" in streaming_config:
            streaming_config.pop("thinking_config")
            logging.info("🌊 Streaming mode: Disabled thinking for real-time updates")

        # Progressive timeout configuration
        initial_chunk_timeout = 30.0
        chunk_timeout = 10.0
        max_stall_time = 60.0
        stream_start_time = time.time()

        # Use streaming API with timeout wrapper
        try:
            stream = await asyncio.wait_for(
                client.aio.models.generate_content_stream(
                    model=target_model,
                    contents=cast(Any, contents),
                    config=types.GenerateContentConfig(**streaming_config),
                ),
                timeout=initial_chunk_timeout,
            )
        except asyncio.TimeoutError:
            logging.warning("⚠️ Streaming init timeout, falling back")
            if placeholder_msg:
                await placeholder_msg.delete()
            if fallback_func:
                return await fallback_func(contents, config_params, channel_id)
            return "", "", []

        async for chunk in stream:
            chunks_received += 1

            # Adaptive timeout
            if chunks_received > 3:
                chunk_timeout = min(20.0, chunk_timeout + 2.0)

            # Check for cancellation
            if channel_id and cancel_flags and cancel_flags.get(channel_id, False):
                logging.info("⏹️ Streaming cancelled for channel %s", channel_id)
                if placeholder_msg:
                    await placeholder_msg.delete()
                return "", "", []

            # Check for stalled stream
            elapsed = time.time() - stream_start_time
            if elapsed > max_stall_time and len(model_text) < 50:
                logging.warning("⚠️ Stream stalled after %.1fs, falling back", elapsed)
                if placeholder_msg:
                    await placeholder_msg.delete()
                if fallback_func:
                    return await fallback_func(contents, config_params, channel_id)
                return "", "", []

            # Extract text from chunk
            chunk_text = ""
            try:
                if hasattr(chunk, "text") and chunk.text:
                    chunk_text = chunk.text
                elif (
                    hasattr(chunk, "candidates") and chunk.candidates and len(chunk.candidates) > 0
                ):
                    candidate = chunk.candidates[0]
                    has_content = (
                        hasattr(candidate, "content")
                        and candidate.content
                        and hasattr(candidate.content, "parts")
                        and candidate.content.parts
                    )
                    if has_content and candidate.content is not None:
                        for part in list(candidate.content.parts or []):
                            if hasattr(part, "text") and part.text:
                                chunk_text += part.text
                            if hasattr(part, "function_call") and part.function_call:
                                function_calls.append(part.function_call)
            except (AttributeError, IndexError, TypeError) as e:
                logging.debug("Failed to parse streaming chunk: %s", e)

            if chunk_text:
                model_text += chunk_text

                # Update placeholder periodically
                current_time = time.time()
                if current_time - last_update_time >= update_interval:
                    last_update_time = current_time
                    display_text = model_text
                    if len(display_text) > 1900:
                        display_text = display_text[:1900] + "..."
                    progress = f"✍️ ({chunks_received} chunks)"
                    display_text += f" {progress}"
                    try:
                        await placeholder_msg.edit(content=display_text)
                    except Exception as edit_error:
                        logging.debug("Failed to update streaming message: %s", edit_error)

        # Record success
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
            gemini_circuit.record_success()

        # Delete placeholder
        if placeholder_msg:
            with contextlib.suppress(Exception):
                await placeholder_msg.delete()

        stream_duration = time.time() - stream_start_time
        logging.info(
            "🌊 Streaming complete: %d chars, %d chunks, %.1fs",
            len(model_text),
            chunks_received,
            stream_duration,
        )
        return model_text, search_indicator, function_calls

    except asyncio.TimeoutError as e:
        # chunks_received is always defined at this point (line 220)
        logging.warning("⚠️ Streaming timeout after %d chunks: %s", chunks_received, e)
        if placeholder_msg:
            with contextlib.suppress(Exception):
                await placeholder_msg.delete()
        if len(model_text) > 100:
            logging.info("🔄 Using partial streaming result (%d chars)", len(model_text))
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_success()
            return model_text, search_indicator, function_calls
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
            gemini_circuit.record_failure()
        if fallback_func:
            return await fallback_func(contents, config_params, channel_id)
        return "", "", []

    except Exception as e:
        logging.warning("⚠️ Streaming failed, falling back to normal API: %s", e)
        if placeholder_msg:
            with contextlib.suppress(Exception):
                await placeholder_msg.delete()
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
            gemini_circuit.record_failure()
        if fallback_func:
            return await fallback_func(contents, config_params, channel_id)
        return "", "", []


async def call_gemini_api(
    client: genai.Client,
    target_model: str,
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
) -> tuple[str, str, list[Any]]:
    """Call Gemini API with retry logic, refusal detection, and multi-tiered fallback.

    Args:
        client: Gemini API client.
        target_model: Model name to use.
        contents: Message contents for API.
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
    max_retries = 5
    retry_delay = 1
    model_text = ""
    search_indicator = ""
    function_calls = []
    refusal_count = 0
    _api_start_time = time.time()

    # Deep copy contents and config to avoid mutating caller's data during retry/fallback
    # This is critical because fallback strategies modify these dicts (truncation, framing)
    contents = copy.deepcopy(contents)
    config_params = copy.deepcopy(config_params)

    for attempt in range(max_retries):
        # Check for cancellation
        if channel_id and cancel_flags and cancel_flags.get(channel_id, False):
            logging.info("⏹️ API call cancelled for channel %s", channel_id)
            return "", "", []

        try:
            # Check circuit breaker
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
                logging.warning("⚡ Circuit breaker OPEN - skipping Gemini API call")
                return "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่", "", []

            api_timeout = 120.0
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=target_model,
                        contents=cast(Any, contents),
                        config=types.GenerateContentConfig(**config_params),
                    ),
                    timeout=api_timeout,
                )
            except asyncio.TimeoutError:
                logging.error(
                    "⏱️ Gemini API timeout after %.0fs (attempt %d)", api_timeout, attempt + 1
                )
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                if ERROR_RECOVERY_AVAILABLE and service_monitor:
                    service_monitor.record_failure("gemini_api", "timeout")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10)
                    continue
                return "⚠️ API หมดเวลา กรุณาลองใหม่อีกครั้ง", "", []

            # Record success
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_success()
            if ERROR_RECOVERY_AVAILABLE and service_monitor:
                service_monitor.record_success("gemini_api")

            # Extract text
            temp_text = ""
            with contextlib.suppress(ValueError, AttributeError):
                temp_text = response.text or ""

            # Fallback: Get text from candidates/parts
            has_candidates = (
                hasattr(response, "candidates")
                and response.candidates
                and len(response.candidates) > 0
            )
            if has_candidates and response.candidates:
                candidate0 = response.candidates[0]

                # Extract search metadata
                if hasattr(candidate0, "grounding_metadata") and candidate0.grounding_metadata:
                    grounding = candidate0.grounding_metadata
                    if hasattr(grounding, "web_search_queries") and grounding.web_search_queries:
                        queries = grounding.web_search_queries
                        q_str = ", ".join(queries[:3])
                        search_indicator = f"🔍 *ค้นหา: {q_str}*\n\n"
                        logging.info("🔍 AI used Google Search: %s", queries)
                    elif hasattr(grounding, "grounding_chunks") and grounding.grounding_chunks:
                        src_count = len(grounding.grounding_chunks)
                        search_indicator = f"🔍 *ค้นหาข้อมูลจาก {src_count} แหล่ง*\n\n"
                        logging.info("🔍 AI grounded response with %s sources", src_count)

                if (
                    hasattr(candidate0, "content")
                    and candidate0.content
                    and hasattr(candidate0.content, "parts")
                    and candidate0.content.parts
                ):
                    parts_text = []
                    for part in candidate0.content.parts:
                        if hasattr(part, "text") and part.text:
                            parts_text.append(part.text)
                        if hasattr(part, "function_call") and part.function_call:
                            function_calls.append(part.function_call)

                    if not temp_text and parts_text:
                        temp_text = "\n".join(parts_text)

            # Refusal & Silent Block Detection
            if temp_text and temp_text.strip():
                is_refusal, refusal_type = detect_refusal(temp_text)
                if is_refusal and GUARDRAILS_AVAILABLE:
                    refusal_count += 1
                    logging.warning(
                        "🚫 Refusal detected (attempt %s, type: %s): %s",
                        attempt + 1,
                        refusal_type,
                        temp_text[:200] + "..." if len(temp_text) > 200 else temp_text,
                    )
                    temp_text = ""
                else:
                    model_text = temp_text
                    break

            if not refusal_count and is_silent_block(temp_text):
                logging.warning(
                    "⚠️ Silent block detected (attempt %s). AI response: %s",
                    attempt + 1,
                    repr(temp_text) if temp_text else "(empty)",
                )

            if function_calls and not temp_text:
                break

            logging.warning(
                "Attempt %s/%s: Gemini returned empty/refused (refusals: %s)",
                attempt + 1,
                max_retries,
                refusal_count,
            )

        except (ValueError, TypeError, OSError, asyncio.TimeoutError) as api_error:
            error_str = str(api_error).lower()
            logging.warning("⚠️ Attempt %s/%s Failed: %s", attempt + 1, max_retries, api_error)
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            if "429" in error_str or "resource exhausted" in error_str:
                retry_delay = 5

        # Multi-tiered fallback strategies
        if "thinking_config" in config_params:
            logging.warning("⚠️ Fallback Tier 1: Disabling 'Thinking Mode' for retry")
            config_params.pop("thinking_config", None)

        # Tier 2: Smart Content Reduction
        if attempt >= 1 and contents:
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
                            logging.warning(
                                "⚠️ Fallback Tier 2: Truncated large text (was %d chars)", len(text)
                            )

        # Tier 1-4: Escalation framing for refusal cases
        if attempt >= 1 and refusal_count > 0 and contents:
            tier_index = min(attempt, len(ESCALATION_FRAMINGS) - 1)
            framing = (
                ESCALATION_FRAMINGS[tier_index] if tier_index < len(ESCALATION_FRAMINGS) else None
            )
            tier_names = ["None", "Soft", "Literary", "Meta-Author", "Nuclear"]
            tier_name = (
                tier_names[tier_index] if tier_index < len(tier_names) else f"Tier{tier_index}"
            )

            if framing:
                last_message = contents[-1] if contents else None
                if last_message and "parts" in last_message:
                    parts_list = last_message.get("parts", [])
                    for part in parts_list if parts_list else []:
                        if isinstance(part, dict) and "text" in part:
                            # Remove any previous escalation framings before adding new one
                            # to prevent accumulation across retries
                            for prev_framing in ESCALATION_FRAMINGS:
                                if prev_framing and prev_framing in part["text"]:
                                    part["text"] = part["text"].replace(prev_framing, "")
                            part["text"] = part["text"] + framing
                            logging.warning(
                                "🔓 Escalation Tier %d (%s): Injecting stronger framing",
                                tier_index,
                                tier_name,
                            )
                            break

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, 10)

    # Record performance metrics
    if PERF_TRACKER_AVAILABLE and perf_tracker:
        perf_tracker.record("gemini_api", _api_start_time)

    return model_text, search_indicator, function_calls
