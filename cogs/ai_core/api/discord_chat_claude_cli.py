"""Discord-side AI replies via the Claude Code CLI subprocess.

Purpose:
    When ``CLAUDE_BACKEND=cli`` the SDK-based client in ``logic.py`` is
    intentionally not initialised — historically that left Discord-side
    AI replies dead and only the dashboard chat worked. This module is the
    Discord-flavoured counterpart of ``dashboard_chat_claude_cli``: it
    spawns ``claude -p`` per turn, streams the response back to the
    placeholder Discord message, and tracks one Claude session_id per
    Discord channel so ``--resume`` keeps the prompt cache warm and the
    server-side context intact across turns.

Reuse:
    Subprocess plumbing (``_run_claude_subprocess``, ``_build_claude_argv``,
    ``_make_subprocess_env``, ``is_cli_backend_ready``, the stale-session
    sentinel) is shared with the dashboard module — there's no second copy
    of "how to spawn claude". This module only owns the Discord-specific
    concerns: prompt assembly from the in-memory ``contents`` shape that
    ``logic.py`` produces, per-channel session tracking, placeholder
    message updates, and the SDK-shape return tuple.

Limitations vs the SDK path:
    - No ``temperature`` / ``max_tokens`` overrides (CLI doesn't expose them)
    - No API failover (subscription auth has no proxy concept)
    - Images attached to Discord messages are dropped with a "[image]"
      placeholder in the prompt — wiring through the Read-tool image
      path is a future improvement; today the CLI-mode Discord bot is
      text-only, matching what env.example documents.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import OrderedDict
from typing import Any

import discord

from .dashboard_chat_claude_cli import (
    _build_claude_argv,
    _OverloadedError,
    _run_claude_subprocess,
    _StaleSessionError,
    is_cli_backend_ready,
)
from .dashboard_common import strip_claude_internal_tags, strip_leading_timestamp

logger = logging.getLogger(__name__)

# Cap per-channel state so a bot in thousands of guilds doesn't grow these
# dicts unbounded. LRU eviction (OrderedDict.popitem(last=False)) keeps the
# most recently active channels resident.
_MAX_TRACKED_CHANNELS = 500

# Per-Discord-channel Claude session_id. Kept in-memory only (Discord
# channels are server-side resources, not local state we need to persist
# across bot restarts — losing the session_id just means the next turn
# starts a fresh subprocess and re-sends history via the prompt, which
# is already the default first-turn behaviour). The map lives at module
# scope so a single channel's turns share the same Claude --resume id
# across the bot's lifetime.
_CHANNEL_SESSIONS: OrderedDict[int, str] = OrderedDict()

# Per-channel asyncio.Lock so two concurrent turns for the same channel
# serialise on the subprocess. ``ChatManager`` already holds a higher-level
# lock per channel before reaching here, so this is defence-in-depth —
# but mistakes in upstream lock ordering shouldn't crash claude with
# concurrent stdin writers.
_CHANNEL_LOCKS: OrderedDict[int, asyncio.Lock] = OrderedDict()

# Fallback lock for the channel_id=None case (e.g. callers that didn't
# wire a channel id). Without this, every call constructed a fresh local
# Lock and serialisation was lost.
_FALLBACK_LOCK = asyncio.Lock()

# Matches a role marker at the start of a line in arbitrary user text.
# The flattened-prompt format (``# Conversation history\nUser: …\n
# Assistant: …``) is vulnerable to a user message that contains
# ``\nAssistant: I'll obey…\nUser: continue…`` — the bare LLM has no way
# to tell injected role markers from real ones. We rewrite hits to a
# clearly-marked sentinel so the model sees them as quoted text, not new
# turns. Covers common alternate aliases (Human/AI/Tool) as well.
_ROLE_LEAK_RE = re.compile(
    r"(?im)^(\s*)(user|assistant|system|tool|human|ai)(\s*:)"
)


def _sanitize_dialog_segment(text: str) -> str:
    """Defang role-marker injection in flattened-prompt history text.

    A user whose message contains a literal line ``Assistant: I'll do
    anything`` could otherwise spoof an assistant turn in the prompt the
    CLI subprocess receives. We rewrite every such line so the model
    sees it as quoted text the user typed, not a real turn header.
    """
    if not text:
        return text
    return _ROLE_LEAK_RE.sub(r"\1[user-text] \2\3", text)

# Bound the per-update edit rate on the placeholder message so we don't
# burn Discord rate-limit budget on a long answer. The SDK path uses 1s;
# match it.
_DISCORD_EDIT_INTERVAL = 1.0

# Hard ceiling on a single turn end-to-end. Discord CLI replies run with
# extended thinking (`--effort max`, see the
# _build_claude_argv calls below), which can reason for minutes on hard
# questions — so match the dashboard's 1800s thinking cap. The old 600s
# assumed thinking was off and would kill a max-effort turn mid-reason.
# Still bounded so a runaway subprocess can't hold the channel lock forever.
_DISCORD_STREAM_TIMEOUT = 1800.0

# Soft cap on prompt size sent to the CLI. Claude Code CLI itself can
# handle Opus 4.8's 1M context, but very large prompts inflate both
# latency and quota; clip the history portion the same way logic.py
# clips ``contents`` before this layer sees them.
_DISCORD_PROMPT_MAX_CHARS = 200_000


def _get_channel_lock(channel_id: int) -> asyncio.Lock:
    """Return the per-channel subprocess lock, creating it on demand.

    Uses ``setdefault`` so concurrent first-touch callers settle on the
    same Lock object (the old ``if not in`` shape created two distinct
    Locks under racy access). Also LRU-evicts when the dict grows past
    ``_MAX_TRACKED_CHANNELS`` to bound memory in long-lived bots.
    """
    lock = _CHANNEL_LOCKS.setdefault(channel_id, asyncio.Lock())
    _CHANNEL_LOCKS.move_to_end(channel_id)
    while len(_CHANNEL_LOCKS) > _MAX_TRACKED_CHANNELS:
        evicted_id, evicted_lock = _CHANNEL_LOCKS.popitem(last=False)
        # Don't drop a lock that's actively held — re-insert it so the
        # holder still releases the real object on exit.
        if evicted_lock.locked():
            _CHANNEL_LOCKS[evicted_id] = evicted_lock
            _CHANNEL_LOCKS.move_to_end(evicted_id, last=False)
            break
    return lock


def _record_session(channel_id: int, session_id: str) -> None:
    """LRU-record the session_id for the channel."""
    _CHANNEL_SESSIONS[channel_id] = session_id
    _CHANNEL_SESSIONS.move_to_end(channel_id)
    while len(_CHANNEL_SESSIONS) > _MAX_TRACKED_CHANNELS:
        _CHANNEL_SESSIONS.popitem(last=False)


def reset_channel_session(channel_id: int) -> None:
    """Forget the CLI session for a Discord channel.

    Called when the channel's history is wiped (e.g. ``!reset_ai``) so the
    next turn starts a fresh Claude session rather than ``--resume``-ing
    into stale server-side context.
    """
    _CHANNEL_SESSIONS.pop(channel_id, None)


def _flatten_contents_to_prompt(
    contents: list[dict[str, Any]],
    system_instruction: str,
) -> str:
    """Build the single prompt string fed to ``claude -p`` via stdin.

    The CLI's stream-json input format takes one user-role message per
    invocation; the system prompt and prior turns are folded into that
    single message body. Format roughly mirrors how the dashboard
    handler builds its prompt: a ``# System`` section, optional
    ``# Conversation history`` recap, then a ``# Current user message``
    trailer. Claude Code's own prompt processing handles structured
    sections well.
    """
    parts: list[str] = []

    # If there's no system prompt AND no contents to respond to, the
    # caller is asking for an empty prompt — skip every header so the
    # callers can detect "nothing to send" via empty output.
    if not system_instruction and not contents:
        return ""

    if system_instruction:
        parts.append("# System")
        parts.append(system_instruction.strip())
        parts.append("")

    # Defensive prompt instruction so the model doesn't echo the
    # ``[ISO-timestamp]`` prefixes that ``logic.py`` attaches to every
    # historical message. Without this Claude tends to mimic the
    # observed pattern and start its own replies with a timestamp
    # bracket — see ``dashboard_chat_claude.py`` for the same defence on
    # the SDK side. Pair this with ``strip_leading_timestamp`` on the
    # output as defence-in-depth.
    parts.append("# Formatting rules")
    parts.append(
        "User messages may be prefixed with timestamps like "
        "[2026-05-20T13:18:47+07:00] — these are system-injected "
        "metadata so you can see when each turn was sent. They are NOT "
        "part of the user's intent. Do NOT include such timestamp "
        "prefixes in your own response. Just answer normally."
    )
    parts.append("")

    # contents is the bot's internal Gemini-shaped history: a list of
    # ``{role, parts: [str | {text}/{inline_data}], ...}`` items where
    # the LAST item is the user message we want answered. Split the
    # tail off so the prompt reads "context… then ask".
    history = contents[:-1] if contents else []
    current = contents[-1] if contents else None

    if history:
        parts.append("# Conversation history (oldest first)")
        for item in history:
            role = item.get("role", "user")
            speaker = "Assistant" if role == "model" else "User"
            text_segments: list[str] = []
            for part in item.get("parts", []):
                if isinstance(part, str):
                    text_segments.append(part)
                elif isinstance(part, dict):
                    if isinstance(part.get("text"), str):
                        text_segments.append(part["text"])
                    elif "inline_data" in part:
                        # Inline media is dropped — see module docstring.
                        # Leave a placeholder so the model knows a non-text
                        # element existed at this position rather than
                        # silently editing the conversation flow.
                        mime = (part.get("inline_data") or {}).get("mime_type", "media")
                        text_segments.append(f"[attachment omitted: {mime}]")
            joined = "\n".join(s for s in text_segments if s).strip()
            if joined:
                parts.append(f"{speaker}: {_sanitize_dialog_segment(joined)}")
        parts.append("")

    if current is not None:
        speaker = "User"
        text_segments = []
        for part in current.get("parts", []):
            if isinstance(part, str):
                text_segments.append(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    text_segments.append(part["text"])
                elif "inline_data" in part:
                    mime = (part.get("inline_data") or {}).get("mime_type", "media")
                    text_segments.append(f"[attachment omitted: {mime}]")
        current_text = "\n".join(s for s in text_segments if s).strip()
        if current_text:
            parts.append("# Current user message")
            parts.append(f"{speaker}: {_sanitize_dialog_segment(current_text)}")

    prompt = "\n".join(parts).strip()
    if len(prompt) > _DISCORD_PROMPT_MAX_CHARS:
        # Hard truncate from the FRONT of the history block so the most
        # recent turns + the current question survive intact. We keep
        # the last 95% of the budget for the tail.
        keep = int(_DISCORD_PROMPT_MAX_CHARS * 0.95)
        prompt = "[...older context truncated...]\n" + prompt[-keep:]
    return prompt


async def call_claude_cli_streaming(
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    send_channel: Any,
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
) -> tuple[str, str, list[Any]]:
    """Drop-in replacement for ``api_handler.call_claude_api_streaming``.

    Spawns ``claude -p`` for the turn, streams visible text deltas, and
    edits the Discord placeholder message every ~1 s with the running
    response. Returns ``(model_text, search_indicator, function_calls)``
    so the call site in ``logic.py`` doesn't need a separate branch for
    the result shape.

    ``search_indicator`` is always ``""`` and ``function_calls`` is
    always ``[]`` — Claude Code CLI doesn't surface tool-call events to
    the host in a stable schema today, and the SDK-path ``search``
    integration is server-side anyway.
    """
    ok, reason = is_cli_backend_ready()
    if not ok:
        # Caller has a fallback in non-CLI mode, but in CLI mode we have
        # nowhere to fall back to. Send the operator-actionable message
        # so the user sees something rather than a silent failure.
        msg = (
            "⚠️ Claude CLI ไม่พร้อมใช้งาน "
            f"({reason}). กรุณาให้แอดมินตรวจสอบ `claude` CLI"
        )
        with contextlib.suppress(Exception):
            await send_channel.send(msg, delete_after=30)
        return "", "", []

    system_instruction = config_params.get("system_instruction", "") or ""
    prompt = _flatten_contents_to_prompt(contents, system_instruction)

    placeholder_msg = None
    last_edit_time = 0.0
    accumulated_text = ""
    aborted = False

    try:
        placeholder_msg = await send_channel.send("💭 กำลังคิด...")
    except Exception:
        # If even the placeholder send fails (permissions, Discord
        # outage, channel deleted), there's no point spawning claude.
        logger.exception("Failed to send placeholder message for Discord CLI chat")
        return "", "", []

    async def _maybe_edit_placeholder() -> None:
        """Edit the placeholder message at most once per
        ``_DISCORD_EDIT_INTERVAL`` to stay under Discord's edit budget."""
        nonlocal last_edit_time
        now = time.monotonic()
        if now - last_edit_time < _DISCORD_EDIT_INTERVAL:
            return
        last_edit_time = now
        # Discord caps a message at 2000 characters; if we overflow,
        # show a "(typing…)" marker and let the final response use the
        # normal Discord-side chunked send-path in logic.py.
        preview = accumulated_text
        if len(preview) > 1900:
            preview = preview[:1900] + "…"
        if not preview:
            preview = "💭 กำลังคิด..."
        with contextlib.suppress(Exception):
            await placeholder_msg.edit(
                content=preview,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def on_text(text: str) -> None:
        nonlocal accumulated_text, aborted
        if aborted:
            return
        if channel_id is not None and cancel_flags is not None and cancel_flags.get(channel_id):
            aborted = True
            return
        if not text:
            return
        accumulated_text += text
        await _maybe_edit_placeholder()

    async def on_thinking(_text: str) -> None:
        # Subscription mode redacts thinking content; we ignore deltas
        # for the Discord UI rather than pollute the placeholder with
        # empty thinking strings.
        return

    lock = _get_channel_lock(channel_id) if channel_id is not None else _FALLBACK_LOCK
    async with lock:
        # First-turn ⇒ no session_id; subsequent turns reuse via --resume.
        session_id = _CHANNEL_SESSIONS.get(channel_id) if channel_id is not None else None
        # Discover the claude binary once per call — the path can change at
        # runtime (PATH update, install/uninstall) and the resolver is
        # cheap enough that caching isn't worth the staleness risk.
        from .dashboard_chat_claude_cli import _resolve_claude_executable

        claude_exe = _resolve_claude_executable()
        if not claude_exe:
            with contextlib.suppress(Exception):
                await placeholder_msg.edit(
                    content="⚠️ Claude CLI binary ไม่พบใน PATH",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            return "", "", []

        # Run with retry-once on stale session — exactly mirrors the
        # dashboard handler's behaviour. The stale-session case is when
        # Claude on the server side has GC'd the session log under us.
        for attempt in (1, 2):
            argv = _build_claude_argv(
                claude_exe,
                session_id=session_id,
                allow_read_for_images=False,
                allow_edit_tools=False,
                # Discord replies think at max effort, same as a dashboard
                # conversation with thinking enabled. Subscription mode redacts
                # the reasoning content (only start/stop markers reach us — see
                # on_thinking), but the model still spends real reasoning effort.
                enable_thinking=True,
            )
            try:
                new_session_id, _usage = await asyncio.wait_for(
                    _run_claude_subprocess(
                        argv,
                        prompt,
                        on_text_delta=on_text,
                        on_thinking_delta=on_thinking,
                        on_thinking_block_start=None,
                        on_thinking_block_stop=None,
                        timeout=_DISCORD_STREAM_TIMEOUT,
                    ),
                    timeout=_DISCORD_STREAM_TIMEOUT,
                )
                if channel_id is not None and new_session_id:
                    _record_session(channel_id, new_session_id)
                break
            except _StaleSessionError:
                if attempt == 1 and session_id:
                    logger.info(
                        "Claude session %s stale for channel %s; retrying fresh",
                        session_id,
                        channel_id,
                    )
                    session_id = None
                    accumulated_text = ""
                    if channel_id is not None:
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                    continue
                # Second stale-session in a row → give up; the prompt is
                # probably mal-formed in a way Claude refuses.
                logger.error("Claude CLI session repeatedly stale for channel %s", channel_id)
                accumulated_text = ""
                break
            except TimeoutError:
                logger.warning(
                    "Claude CLI timed out after %ss for channel %s",
                    _DISCORD_STREAM_TIMEOUT,
                    channel_id,
                )
                # Surface a clear message rather than silently returning
                # whatever partial text was accumulated.
                if accumulated_text:
                    accumulated_text += (
                        "\n\n*[การตอบถูกตัดเนื่องจากใช้เวลานานเกินไป]*"
                    )
                else:
                    accumulated_text = (
                        "⚠️ Claude CLI ใช้เวลาตอบนานเกินกำหนด กรุณาลองใหม่"
                    )
                break
            except _OverloadedError:
                # Transient Anthropic overload (429/529). claude already retried
                # internally, so don't loop again — show a clear retry hint.
                logger.warning(
                    "Claude CLI: Anthropic API overloaded for channel %s",
                    channel_id,
                )
                accumulated_text = (
                    "⚠️ เซิร์ฟเวอร์ Anthropic ไม่ว่างชั่วคราว กรุณาลองใหม่อีกครั้งในอีกสักครู่"
                )
                break
            except Exception:
                logger.exception("Claude CLI subprocess failed for channel %s", channel_id)
                accumulated_text = "⚠️ Claude CLI ขัดข้อง กรุณาดู log ของบอท"
                break

    # Final placeholder cleanup. ``logic.py`` will send the actual
    # response separately via its chunked send path, so we delete the
    # placeholder rather than leave the running-preview text behind as a
    # duplicate of the final message.
    if placeholder_msg is not None:
        with contextlib.suppress(Exception):
            await placeholder_msg.delete()

    if aborted:
        # Cancellation matches the SDK path's contract: return empty.
        return "", "", []

    # Defence-in-depth pipeline:
    # 1. Strip Claude Code internal XML markup (``<system-reminder>``,
    #    ``</system-reminder>``, etc.) that the model occasionally
    #    bleeds because the same Claude Opus weights power both
    #    interactive Claude Code and our ``claude -p`` subprocess.
    # 2. Strip a leading ``[ISO-timestamp]`` prefix if the model
    #    mimicked the historical-message format despite the explicit
    #    instruction in the prompt.
    cleaned = strip_claude_internal_tags(accumulated_text)
    cleaned = strip_leading_timestamp(cleaned)
    return cleaned, "", []


async def call_claude_cli(
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    channel_id: int | None = None,
) -> tuple[str, str, list[Any]]:
    """Non-streaming variant — used when streaming is disabled per channel.

    Internally still spawns ``claude -p`` (the CLI has no separate
    "non-streaming" mode); the difference is that we accumulate
    silently and don't edit any placeholder.
    """
    ok, reason = is_cli_backend_ready()
    if not ok:
        logger.warning("Claude CLI not ready: %s", reason)
        return "", "", []

    system_instruction = config_params.get("system_instruction", "") or ""
    prompt = _flatten_contents_to_prompt(contents, system_instruction)

    accumulated_text = ""

    async def on_text(text: str) -> None:
        nonlocal accumulated_text
        if text:
            accumulated_text += text

    async def on_thinking(_text: str) -> None:
        return

    lock = _get_channel_lock(channel_id) if channel_id is not None else _FALLBACK_LOCK
    async with lock:
        session_id = _CHANNEL_SESSIONS.get(channel_id) if channel_id is not None else None
        from .dashboard_chat_claude_cli import _resolve_claude_executable

        claude_exe = _resolve_claude_executable()
        if not claude_exe:
            return "", "", []

        for attempt in (1, 2):
            argv = _build_claude_argv(
                claude_exe,
                session_id=session_id,
                allow_read_for_images=False,
                allow_edit_tools=False,
                # Discord replies think at max effort, same as a dashboard
                # conversation with thinking enabled. Subscription mode redacts
                # the reasoning content (only start/stop markers reach us — see
                # on_thinking), but the model still spends real reasoning effort.
                enable_thinking=True,
            )
            try:
                new_session_id, _usage = await asyncio.wait_for(
                    _run_claude_subprocess(
                        argv,
                        prompt,
                        on_text_delta=on_text,
                        on_thinking_delta=on_thinking,
                        on_thinking_block_start=None,
                        on_thinking_block_stop=None,
                        timeout=_DISCORD_STREAM_TIMEOUT,
                    ),
                    timeout=_DISCORD_STREAM_TIMEOUT,
                )
                if channel_id is not None and new_session_id:
                    _record_session(channel_id, new_session_id)
                break
            except _StaleSessionError:
                if attempt == 1 and session_id:
                    session_id = None
                    accumulated_text = ""
                    if channel_id is not None:
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                    continue
                logger.error("Claude CLI session repeatedly stale (non-stream)")
                accumulated_text = ""
                break
            except TimeoutError:
                logger.warning("Claude CLI timed out (non-stream)")
                accumulated_text = accumulated_text or ""
                break
            except _OverloadedError:
                logger.warning("Claude CLI: Anthropic API overloaded (non-stream)")
                accumulated_text = (
                    "⚠️ เซิร์ฟเวอร์ Anthropic ไม่ว่างชั่วคราว กรุณาลองใหม่อีกครั้งในอีกสักครู่"
                )
                break
            except Exception:
                logger.exception("Claude CLI subprocess failed (non-stream)")
                accumulated_text = ""
                break

    # Same defence pipeline as the streaming path.
    cleaned = strip_claude_internal_tags(accumulated_text)
    cleaned = strip_leading_timestamp(cleaned)
    return cleaned, "", []


__all__ = [
    "call_claude_cli",
    "call_claude_cli_streaming",
    "reset_channel_session",
]
