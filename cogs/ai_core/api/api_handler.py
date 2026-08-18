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
import time
from typing import Any, TypedDict, cast

import anthropic
import discord
from anthropic.types.message_param import MessageParam

from ..claude_payloads import (
    ClaudeContentBlockParam,
    ClaudeMessageRole,
    build_claude_base64_image_block,
    build_claude_message,
    build_claude_text_block,
)
from ..data import (
    FAUST_DM_INSTRUCTION,
    FAUST_INSTRUCTION,
    ROLEPLAY_ASSISTANT_INSTRUCTION,
)
from ..data.constants import (
    CLAUDE_EFFORT,
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    STREAMING_TIMEOUT_CHUNK,
    STREAMING_TIMEOUT_INITIAL,
)
from ..data.model_caps import effort_with_thinking_off, thinking_off_config

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


# Guardrails removed — ``is_silent_block`` is a local no-op (never flags a
# response as silent). Kept only because tests import it; no production code
# path calls it anymore. NOTE: the same-named shim in imports.py has different
# semantics (returns True for empty strings) — don't conflate the two.
def is_silent_block(response: str) -> bool:
    return False


logger = logging.getLogger(__name__)

_CLAUDE_RETRY_BASE_DELAY = 1.0
_CLAUDE_RETRY_MAX_DELAY = 30.0
_CLAUDE_MAX_CONTENT_RETRIES = 5
_CLAUDE_MAX_API_RETRIES = 8  # Max retries for transient API errors (rate limit, server error)
_CLAUDE_MAX_STREAM_RETRIES = 6  # Max retries for streaming failures


class _ClaudeMessage(TypedDict):
    role: ClaudeMessageRole
    content: list[ClaudeContentBlockParam]


def _claude_retry_delay_seconds(attempt: int, *, minimum_delay: float = 1.0) -> float:
    # Exponential backoff: base * 2^(attempt-1), capped at max.
    # attempt=1 → base, attempt=2 → 2*base, attempt=3 → 4*base, … then plateau.
    exponent = max(0, attempt - 1)
    delay = min(_CLAUDE_RETRY_BASE_DELAY * (2**exponent), _CLAUDE_RETRY_MAX_DELAY)
    # float(): int ** int is typed Any in typeshed (negative exponents yield float),
    # which would otherwise make this an Any return.
    return float(max(delay, minimum_delay))


# Appended to the system prompt on the SDK Discord path. ``logic.py`` prefixes
# every historical turn with system metadata — an ISO timestamp on all of them,
# plus the ``(msg …)`` Discord message ids on the bot's own — and the model
# reproduces observed patterns unless told not to. The CLI path carries the
# equivalent under its "# Formatting rules" heading; without this the SDK path
# was the silent downgrade (it also had no output-side strip at all).
INJECTED_PREFIX_NOTE = """

FORMATTING RULES (system-injected metadata — never reproduce these in a reply):
- Messages may carry a leading timestamp like [2026-05-20T13:18:47+07:00]. It
  tells you when the turn was sent; it is not part of anyone's intent.
- Your own past turns may also carry '(msg 1401234567890123456)', or
  '(msgs narration=140…, Character=140…)' when the turn went out as several
  Discord messages. Those ids are what the edit_message tool takes, so you can
  correct an earlier message rather than only apologising for it. For anything
  older than the visible history, read_channel reports the id of every message
  it returns."""


def with_prefix_note(system_prompt: str) -> str:
    """Append :data:`INJECTED_PREFIX_NOTE` to a system prompt about to go out.

    Empty in, empty out: an empty instruction means "no persona", and shipping
    a lone rules block would turn that into a prompt.
    """
    return (system_prompt + INJECTED_PREFIX_NOTE) if system_prompt else system_prompt


def clean_model_text(text: str) -> str:
    """Strip system-injected prefixes the model echoed back into its reply.

    Defence-in-depth companion to :data:`INJECTED_PREFIX_NOTE`: the prompt asks
    the model not to reproduce them, this catches it when it does anyway. The
    CLI path has had this since the timestamp prefix was introduced; the SDK
    path had no output cleaning at all, so a mimicked prefix was posted to
    Discord verbatim. Order matches how the prefixes are assembled — timestamp
    first, then the message-id annotation.
    """
    if not text:
        return text
    from .dashboard_common import strip_leading_message_ids, strip_leading_timestamp

    return strip_leading_message_ids(strip_leading_timestamp(text))


def build_api_config(
    chat_data: dict[str, Any],
    guild_id: int | None = None,
) -> dict[str, Any]:
    """Build API configuration for Claude.

    Args:
        chat_data: Chat configuration data containing system_instruction and thinking_enabled.
        guild_id: Optional guild ID.

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
        # Passed through verbatim — the formatting-rules note is appended where
        # the wire request is assembled (``with_prefix_note``), mirroring the
        # CLI path where it lives in the prompt builder, not the config.
        "system_instruction": system_instruction,
        # The lore block inside system_instruction, verbatim. Only the Discord
        # CLI path reads it (to drop the block from resumed turns); the SDK
        # path ignores the key, and nothing splats config_params into an API
        # request, so carrying it here is inert for every other consumer.
        "server_lore": chat_data.get("server_lore", "") or "",
        "max_tokens": CLAUDE_MAX_TOKENS,
    }

    # Enable adaptive thinking for RP/Faust modes when thinking is enabled.
    # Opus 4.x+ adaptive-thinking models use thinking type:"adaptive" instead
    # of a manual budget_tokens (removed on these models — sending it 400s).
    if (is_faust_mode or is_faust_dm_mode or is_rp_mode) and thinking_enabled:
        config_params["thinking"] = {"type": "adaptive"}
        logger.info("🧠 Adaptive Thinking Mode: ENABLED")
    else:
        # Standard mode is NOT the same as omitting the field on Opus 5 /
        # Sonnet 5: those think by default, so leaving `thinking` unset would
        # quietly spend reasoning tokens on every non-RP turn. Send the explicit
        # "disabled" where the generation needs it (call_claude_api clamps
        # effort to `high` alongside it — Opus 5 400s on disabled + xhigh/max).
        thinking_off = thinking_off_config(CLAUDE_MODEL)
        if thinking_off is not None:
            config_params["thinking"] = thinking_off
        logger.info("💬 Standard Mode (no extended thinking)")

    return config_params


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


async def _record_token_usage(
    usage_obj: Any,
    *,
    user_id: int | None,
    channel_id: int | None,
    guild_id: int | None,
    model: str,
) -> None:
    """Best-effort token-usage recording — never raises into the response path.

    Thin wrapper over the shared ``record_usage_snapshot`` so the SDK path and
    the two CLI paths feed the DB-backed ``TokenTracker`` through ONE recorder
    (they used to disagree: only this path recorded anything, leaving the
    tracker with no producer on the default ``cli`` backend).
    """
    try:
        from cogs.ai_core.cache.token_tracker import record_usage_snapshot

        await record_usage_snapshot(
            usage_obj,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            model=model,
        )
    except Exception:
        logger.debug("token usage recording failed (non-fatal)", exc_info=True)


# ---------------------------------------------------------------------------
# Failover wiring for the Discord SDK path.
#
# Previously only the dashboard handlers drove the APIFailoverManager state
# machine, so a dead Direct endpoint kept failing every Discord request
# forever — the manager never saw those failures and never switched to Proxy.
# These best-effort helpers let the Discord ``call_claude_api*`` paths feed the
# same state machine and pick up an endpoint switch on retry.
#
# All three lazy-import the singleton (no module-level import → no cycle) and
# no-op when failover isn't initialised — which is exactly the case under
# CLAUDE_BACKEND=cli (the default), so this is inert there.
# ---------------------------------------------------------------------------
async def _failover_record_success() -> None:
    """Tell the failover manager the active endpoint just succeeded (best-effort)."""
    try:
        from .api_failover import api_failover

        if api_failover._initialized and api_failover.active_config:
            await api_failover.record_success()
    except Exception:
        logger.debug("failover record_success skipped", exc_info=True)


async def _failover_record_failure(error: BaseException) -> bool:
    """Report a failure to the failover manager; return True if it switched endpoints."""
    try:
        from .api_failover import api_failover

        if api_failover._initialized and api_failover.active_config:
            # record_failure is typed for Exception; in practice this path only
            # ever receives Exception subclasses, so cast rather than narrow.
            return bool(await api_failover.record_failure(cast(Exception, error)))
    except Exception:
        logger.debug("failover record_failure skipped", exc_info=True)
    return False


def _failover_current_client(default: anthropic.AsyncAnthropic) -> anthropic.AsyncAnthropic:
    """Return the failover manager's current active client, or ``default`` if unavailable.

    Used to pick up an endpoint switch mid-retry: the manager builds a fresh
    client for the new endpoint, but the ``client`` arg these functions were
    called with is the pre-switch one.
    """
    try:
        from .api_failover import api_failover

        if api_failover._initialized and api_failover.active_config:
            current = api_failover.get_client()
            if current is not None:
                return current
    except Exception:
        logger.debug("failover get_client skipped", exc_info=True)
    return default


def _empty_response_error(message: str) -> Exception:
    """Build the failover-worthy sentinel for a 200-but-empty response.

    Lazy import mirrors the other failover helpers (no module-level import
    → no cycle); falls back to RuntimeError when failover is unavailable,
    which _should_failover ignores — same net behavior as before.
    """
    try:
        from .api_failover import EmptyResponseError

        return EmptyResponseError(message)
    except Exception:
        return RuntimeError(message)


async def call_claude_api_streaming(
    client: anthropic.AsyncAnthropic,
    target_model: str,
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    send_channel: Any,
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
    fallback_func: Any = None,
    user_id: int | None = None,
    guild_id: int | None = None,
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

        # The placeholder send is a Discord REST call, NOT an Anthropic call.
        # A discord.Forbidden / Discord 5xx here must NOT be recorded on
        # gemini_circuit (the breaker that gates EVERY Claude call) — a burst
        # of Discord send failures could otherwise trip it OPEN bot-wide while
        # Anthropic is perfectly healthy. Handle it separately: fall back to
        # the non-streaming path without touching the breaker.
        try:
            placeholder_msg = await send_channel.send("💭 กำลังคิด...")
        except Exception as send_error:
            logger.warning(
                "⚠️ Streaming placeholder send failed (Discord), falling back to normal API: %s",
                send_error,
            )
            if fallback_func:
                return await fallback_func(  # type: ignore[no-any-return]
                    contents, config_params, channel_id, user_id, guild_id
                )
            return "", "", []

        # Convert contents to Claude format
        messages = convert_to_claude_messages(contents)
        system_prompt = with_prefix_note(config_params.get("system_instruction", ""))
        max_tokens = config_params.get("max_tokens", CLAUDE_MAX_TOKENS)

        # Streaming forwards EFFORT (xhigh by default) for reasoning depth, but
        # suppresses extended THINKING: thinking blocks delay the first visible
        # chunk, which defeats real-time streaming. The non-streaming path
        # (call_claude_api) additionally applies thinking.
        #
        # "Suppress" used to mean "omit the field", which stopped being enough on
        # Opus 5 / Sonnet 5 — they think by default — so the disable is now sent
        # explicitly for those generations. Opus 5 rejects disabled thinking above
        # `high`, so effort is clamped to match; on Opus 4.8 and earlier nothing
        # is sent and the configured effort is forwarded untouched.
        #
        # Resolved ONCE here rather than per attempt: both depend only on
        # ``target_model``, and computing them up front lets the log below
        # report the effort that actually goes on the wire. It previously
        # printed the raw ``CLAUDE_EFFORT`` (xhigh) while the request carried
        # the clamped ``high`` on Opus 5 — an operator debugging a shallow
        # stream read a value that was never sent.
        stream_thinking_off = thinking_off_config(target_model)
        stream_effort = CLAUDE_EFFORT
        if stream_thinking_off is not None:
            stream_effort = effort_with_thinking_off(stream_effort)
        if "thinking" in config_params:
            logger.info(
                "🌊 Streaming mode: forwarding effort=%s (configured=%s); thinking %s "
                "for real-time first-token latency",
                stream_effort,
                CLAUDE_EFFORT,
                "explicitly disabled" if stream_thinking_off is not None else "omitted",
            )
    except Exception as e:
        logger.warning("⚠️ Streaming setup failed, falling back to normal API: %s", e)
        if placeholder_msg:
            with contextlib.suppress(Exception):
                await placeholder_msg.delete()
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
            gemini_circuit.record_failure()
        if fallback_func:
            return await fallback_func(  # type: ignore[no-any-return]
                contents, config_params, channel_id, user_id, guild_id
            )
        return "", "", []

    while stream_attempt <= _CLAUDE_MAX_STREAM_RETRIES:
        # Re-check the circuit breaker on EVERY attempt, mirroring the
        # non-streaming sibling (call_claude_api). _CLAUDE_MAX_STREAM_RETRIES
        # (6) exceeds the breaker's failure_threshold (5) and each failed
        # attempt records a failure, so without this a single request's own
        # retry sequence can trip the breaker OPEN at attempt 5 yet still fire
        # attempt 6 at the sick endpoint — and concurrently-looping requests
        # keep hammering a now-open breaker. Short-circuit here instead.
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
            logger.warning("⚡ Circuit breaker OPEN - skipping streaming API call")
            if placeholder_msg:
                with contextlib.suppress(Exception):
                    await placeholder_msg.delete()
            return "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่", "", []

        # Re-resolve the active client on EVERY attempt, not only after a
        # switch recorded inside this call: another request, a health probe,
        # or a manual dashboard switch may have popped (and, 130s later,
        # CLOSED) the caller's cached client while it sat in
        # ChatManager.self.client — retrying on that object mis-charges the
        # new endpoint's health and can never succeed.
        client = _failover_current_client(client)
        current_model_text = ""
        current_chunks_received = 0
        last_update_time = 0.0
        stream_start_time = time.time()
        # Initialise so the asyncio.sleep(delay) at loop bottom never sees
        # an unbound local — historically only the TimeoutError / retryable
        # paths assigned this, leaving an empty-string-on-success path that
        # could fall through unguarded.
        delay = 1.0

        try:
            stream_kwargs = {
                "model": target_model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
            }
            # Forward effort for depth (xhigh by default). Adaptive-thinking
            # models read this from output_config; suppressed thinking keeps the
            # first token fast — see the note above for why the disable has to be
            # explicit (and the effort clamped) on Opus 5 / Sonnet 5. Both values
            # were resolved in the setup block above (they are model-derived and
            # loop-invariant), so the logged effort and the sent effort agree.
            if stream_thinking_off is not None:
                stream_kwargs["thinking"] = stream_thinking_off
            if stream_effort:
                stream_kwargs["output_config"] = {"effort": stream_effort}
            stream = client.messages.stream(**stream_kwargs)

            _stream_final_message = None
            async with stream as response_stream:
                # Per-chunk timeouts (STREAMING_TIMEOUT_INITIAL/_CHUNK were
                # defined for exactly this). The old in-loop stall check only
                # ran when a NEW chunk arrived, so a stream that hung entirely
                # blocked in the async-for until the SDK's 10-minute read
                # timeout — and it measured time since stream START, killing
                # legitimately slow short replies (<50 chars after 60s).
                text_iter = response_stream.text_stream.__aiter__()
                while True:
                    chunk_timeout = (
                        STREAMING_TIMEOUT_INITIAL
                        if current_chunks_received == 0
                        else STREAMING_TIMEOUT_CHUNK
                    )
                    try:
                        text = await asyncio.wait_for(text_iter.__anext__(), chunk_timeout)
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        elapsed = time.time() - stream_start_time
                        raise TimeoutError(
                            f"Claude stream stalled: no chunk for {chunk_timeout:.0f}s "
                            f"({current_chunks_received} chunks in {elapsed:.1f}s)"
                        ) from None
                    current_chunks_received += 1

                    if channel_id and cancel_flags and cancel_flags.get(channel_id, False):
                        logger.info("⏹️ Streaming cancelled for channel %s", channel_id)
                        if placeholder_msg:
                            with contextlib.suppress(Exception):
                                await placeholder_msg.delete()
                        return "", "", []

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
                                await placeholder_msg.edit(
                                    content=display_text,
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )
                            except Exception as edit_error:
                                logger.debug("Failed to update streaming message: %s", edit_error)

                # Capture the final message WHILE the stream context is still
                # open. get_final_message() reads the stream's accumulated
                # state, which isn't contractually available after the
                # ``async with`` exits (works today only via SDK caching).
                with contextlib.suppress(Exception):
                    _stream_final_message = await response_stream.get_final_message()

            model_text = current_model_text
            chunks_received = current_chunks_received

            # A 200-but-EMPTY stream must NOT be recorded healthy (mirror the
            # non-streaming content-retry handling): record a failure so a
            # persistently-empty endpoint trips the circuit / drives failover,
            # then fall through to the retry tail below (and ultimately the
            # non-streaming fallback) instead of returning an empty reply and
            # reporting the endpoint healthy.
            if not model_text.strip():
                logger.warning(
                    "⚠️ Claude streaming returned empty content on attempt %d", stream_attempt
                )
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                if await _failover_record_failure(
                    _empty_response_error("Claude streaming returned empty content")
                ):
                    client = _failover_current_client(client)
                # Keep placeholder_msg alive: this branch falls through to the
                # retry tail (which edits it) and re-loops (progress edits at
                # ~835 also target it). Deleting here left those later edits
                # hitting a dead message. Cleanup is deferred to whichever exit
                # path terminates the loop — the success/error returns each
                # delete it once, and the post-loop fallback deletes it once
                # when retries are exhausted.
                delay = _claude_retry_delay_seconds(stream_attempt)
                # No return: control falls through to the retry tail (reset +
                # sleep(delay) + stream_attempt += 1), then re-loops or hits the
                # post-loop non-streaming fallback once retries are exhausted.
            else:
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_success()
                await _failover_record_success()

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
                # H27: record token usage (best-effort). Accumulated usage lives
                # on the stream's final message; guarded so it never breaks the reply.
                try:
                    await _record_token_usage(
                        getattr(_stream_final_message, "usage", None),
                        user_id=user_id,
                        channel_id=channel_id,
                        guild_id=guild_id,
                        model=target_model,
                    )
                except Exception:
                    logger.debug("streaming token usage record skipped", exc_info=True)
                return clean_model_text(model_text), search_indicator, function_calls

        except TimeoutError as e:
            if len(current_model_text) > 100:
                # Append a marker so the user can see this turn was cut
                # off mid-stream. Without it the partial reply looks
                # complete but isn't, leading to confused follow-ups.
                truncated_marker = "\n\n*[…response cut off due to a stream timeout]*"
                partial_with_marker = current_model_text + truncated_marker
                logger.info(
                    "🔄 Using partial streaming result (%d chars)",
                    len(current_model_text),
                )
                # A timeout — even when we recovered partial content — is
                # still a degraded outcome from the circuit breaker's
                # perspective: the SDK didn't deliver the full response
                # within budget. Recording success here masked
                # systematically slow streaming endpoints from the
                # breaker, leaving them open to keep timing out. Record
                # FAILURE on partial-recovery; the user still gets the
                # partial content (we return it), but the breaker
                # learns the endpoint is sick.
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                await _failover_record_failure(e)
                if placeholder_msg:
                    with contextlib.suppress(Exception):
                        await placeholder_msg.delete()
                # No token usage recorded here on purpose: asyncio.wait_for
                # cancelled the stream mid-flight, so the SDK never produced a
                # final message and there is no accumulated usage object to read.
                # Partial-timeout turns are intentionally left unaccounted rather
                # than fabricating an estimate.
                return clean_model_text(partial_with_marker), search_indicator, function_calls

            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            if await _failover_record_failure(e):
                client = _failover_current_client(client)
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
            if await _failover_record_failure(e):
                client = _failover_current_client(client)
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

        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.BadRequestError,
            anthropic.NotFoundError,
        ) as e:
            # Non-transient client errors: don't burn the retry budget or
            # silently fall back to Gemini, which masks the real problem
            # (wrong key, wrong model id, wrong tool schema). Surface and
            # exit the streaming retry loop.
            logger.error("❌ Claude rejected request (%s): %s", type(e).__name__, e)
            if placeholder_msg:
                with contextlib.suppress(Exception):
                    await placeholder_msg.delete()
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            await _failover_record_failure(e)
            return "", "", []
        except Exception as e:
            logger.warning("⚠️ Streaming failed, falling back to normal API: %s", e)
            if placeholder_msg:
                with contextlib.suppress(Exception):
                    await placeholder_msg.delete()
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            await _failover_record_failure(e)
            if fallback_func:
                return await fallback_func(  # type: ignore[no-any-return]
                    contents, config_params, channel_id, user_id, guild_id
                )
            return "", "", []

        model_text = ""
        chunks_received = 0
        if placeholder_msg:
            with contextlib.suppress(Exception):
                await placeholder_msg.edit(
                    content=f"⏳ Claude server busy, retrying (attempt {stream_attempt + 1})..."
                )
        await asyncio.sleep(delay)
        stream_attempt += 1

    # All stream retries exhausted — fall back to non-streaming API
    logger.warning(
        "⚠️ Streaming retries exhausted after %d attempts, falling back", stream_attempt - 1
    )
    if placeholder_msg:
        with contextlib.suppress(Exception):
            await placeholder_msg.delete()
    if fallback_func:
        return await fallback_func(  # type: ignore[no-any-return]
            contents, config_params, channel_id, user_id, guild_id
        )
    return "", "", []


async def call_claude_api(
    client: anthropic.AsyncAnthropic,
    target_model: str,
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
    user_id: int | None = None,
    guild_id: int | None = None,
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
    # perf_tracker.record() computes (perf_counter() - start), so the start must
    # come from the SAME monotonic clock. Using time.time() (wall-clock epoch)
    # here produced a ~ -1.7e9s duration that poisoned the claude_api stats.
    _api_start_time = time.perf_counter()

    # Deep copy contents and config to avoid mutating caller's data during retry/fallback
    contents = copy.deepcopy(contents)
    config_params = copy.deepcopy(config_params)

    while api_attempt <= _CLAUDE_MAX_API_RETRIES:
        # Check for cancellation
        if channel_id and cancel_flags and cancel_flags.get(channel_id, False):
            logger.info("⏹️ API call cancelled for channel %s", channel_id)
            return "", "", []

        # Re-resolve the active client on EVERY attempt (see the streaming
        # loop for the full rationale): the caller's cached client may have
        # been popped and closed by an endpoint switch outside this call.
        client = _failover_current_client(client)

        try:
            # Check circuit breaker
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
                logger.warning("⚡ Circuit breaker OPEN - skipping Claude API call")
                return "⚠️ ระบบ AI กำลังพักฟื้น กรุณาลองใหม่ในอีกสักครู่", "", []

            # Convert contents to Claude format
            messages = convert_to_claude_messages(contents)
            system_prompt = with_prefix_note(config_params.get("system_instruction", ""))
            max_tokens = config_params.get("max_tokens", CLAUDE_MAX_TOKENS)

            # Build Claude API kwargs
            api_kwargs: dict[str, Any] = {
                "model": target_model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
            }

            # Add extended thinking if configured (may be the explicit
            # {"type": "disabled"} that build_api_config sets for generations
            # which would otherwise think by default).
            thinking_config = config_params.get("thinking")
            if thinking_config:
                api_kwargs["thinking"] = thinking_config

            # Forward effort (Opus-tier reasoning depth, defaults to "xhigh"). On
            # adaptive-thinking models (Opus 4.7+, incl. Opus 5) effort governs how
            # deeply the model reasons; only sent when configured to a valid tier.
            # Opus 5 rejects disabled thinking above "high", so clamp when the
            # turn explicitly disabled it.
            effort = CLAUDE_EFFORT
            if thinking_config and thinking_config.get("type") == "disabled":
                effort = effort_with_thinking_off(effort)
            if effort:
                api_kwargs["output_config"] = {"effort": effort}

            api_timeout = 120.0
            try:
                # The explicit ``timeout=`` is load-bearing: without it the
                # anthropic SDK estimates non-streaming duration from
                # max_tokens (128000 default → ~3600s > 10min) and raises
                # ValueError("Streaming is required...") before any request
                # is sent — every non-streaming call returned a blank reply.
                response = await asyncio.wait_for(
                    client.messages.create(**api_kwargs, timeout=api_timeout),
                    timeout=api_timeout,
                )
            # ``anthropic.APITimeoutError`` subclasses ``APIConnectionError`` (NOT
            # builtin ``TimeoutError``), so an SDK-internal deadline would
            # otherwise skip this branch and be mis-recorded as a generic
            # connection failure below. Catch it here so both the outer
            # ``asyncio.wait_for`` deadline and the SDK timeout share the
            # dedicated "timeout" metric/retry path.
            except (TimeoutError, anthropic.APITimeoutError):
                delay = _claude_retry_delay_seconds(api_attempt)
                logger.error(
                    "⏱️ Claude API timeout after %.0fs (attempt %d). Retrying in %.1fs",
                    api_timeout,
                    api_attempt,
                    delay,
                    extra={
                        "event": "api_timeout",
                        "attempt": api_attempt,
                        "timeout_s": api_timeout,
                        "retry_delay_s": delay,
                    },
                )
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                if ERROR_RECOVERY_AVAILABLE and service_monitor:
                    service_monitor.record_failure("claude_api", "timeout")
                if await _failover_record_failure(TimeoutError("Claude API timeout")):
                    client = _failover_current_client(client)
                await asyncio.sleep(delay)
                api_attempt += 1
                continue

            # H27: record token usage from this successful response (best-effort).
            await _record_token_usage(
                getattr(response, "usage", None),
                user_id=user_id,
                channel_id=channel_id,
                guild_id=guild_id,
                model=target_model,
            )

            # Extract text from Claude response
            temp_text = ""
            for block in response.content:
                if block.type == "text":
                    temp_text += block.text

            # Empty/silent response detection
            if temp_text and temp_text.strip():
                # Record success only after confirming non-empty content — a
                # 200-but-empty endpoint must NOT be recorded healthy, or the
                # circuit never trips and failover never kicks in.
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_success()
                if ERROR_RECOVERY_AVAILABLE and service_monitor:
                    service_monitor.record_success("claude_api")
                await _failover_record_success()
                model_text = temp_text
                break

            # (Silent-block branch removed — is_silent_block is a constant-
            # False shim post-guardrails, so the warning could never fire.)
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
                # Exhausted with empty content: do NOT record success. Record a
                # soft failure so a persistently-empty endpoint can trip the
                # circuit / drive failover instead of looking healthy.
                if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                    gemini_circuit.record_failure()
                if ERROR_RECOVERY_AVAILABLE and service_monitor:
                    service_monitor.record_failure("claude_api", "empty_response")
                # Also feed the failover manager (the circuit/service monitor
                # alone never switch endpoints) with the dedicated sentinel so
                # a persistently-empty endpoint actually drives a switch.
                await _failover_record_failure(
                    _empty_response_error("Claude content retries exhausted (empty response)")
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
            if await _failover_record_failure(e):
                client = _failover_current_client(client)
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
            if await _failover_record_failure(api_error):
                client = _failover_current_client(client)
            await asyncio.sleep(delay)
            api_attempt += 1
            continue

        except Exception as api_error:
            # Distinguish "API call raised" from "API returned empty" — the
            # former needs to surface to the caller (auth error, schema
            # error, etc.) instead of being indistinguishable from a
            # genuinely empty response. ``logger.warning`` previously
            # buried the error and returned ``("", "", [])``, leaving the
            # user with a blank reply and no upstream signal.
            logger.exception(
                "⚠️ Claude API non-retryable failure (returning empty result): %s",
                api_error,
            )
            if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit:
                gemini_circuit.record_failure()
            if ERROR_RECOVERY_AVAILABLE and service_monitor:
                service_monitor.record_failure("claude_api", str(api_error)[:100])
            await _failover_record_failure(api_error)
            break

        # Fallback strategies for empty responses.
        #
        # "Disable thinking" is NOT the same as dropping the field. On the
        # generations that think by DEFAULT (Opus 5 / Sonnet 5 — see
        # data/model_caps.py) an absent ``thinking`` key means adaptive
        # thinking, so the old ``pop`` did the exact inverse of what this
        # fallback claims: a turn that build_api_config had explicitly
        # disabled came back with thinking ON, and `effort` un-clamped from
        # ``high`` back to ``xhigh`` on the next attempt — a more expensive
        # retry, not the de-escalation the log promises. Send the model's
        # explicit off-payload instead; only drop the key on generations
        # where omission genuinely means "off" (Opus 4.8 and earlier) or
        # that reject an explicit disable outright (Fable/Mythos).
        _thinking_now = config_params.get("thinking")
        if isinstance(_thinking_now, dict) and _thinking_now.get("type") != "disabled":
            logger.warning("⚠️ Fallback: Disabling 'Thinking Mode' for retry")
            _thinking_off = thinking_off_config(target_model)
            if _thinking_off is not None:
                config_params["thinking"] = _thinking_off
            else:
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

    return clean_model_text(model_text), search_indicator, function_calls
