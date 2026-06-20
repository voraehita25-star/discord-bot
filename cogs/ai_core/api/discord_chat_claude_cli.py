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

Capabilities / limitations vs the SDK path:
    - Web tools: WebSearch + WebFetch are enabled (claude's built-ins) so the
      Discord AI can look up current info and read URLs. There's no Read tool
      on this path, so no local-file exfil risk. Toggle via DASHBOARD_CLI_WEB_TOOLS.
    - No ``temperature`` / ``max_tokens`` overrides (CLI doesn't expose them)
    - No API failover (subscription auth has no proxy concept)
    - Images attached to Discord messages are dropped with a "[image]"
      placeholder in the prompt — wiring through the Read-tool image
      path is a future improvement.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import discord

from .dashboard_chat_claude_cli import (
    _CLI_WEB_TOOLS_ENABLED,
    _IDENTITY_OVERRIDE,
    _PENDING_SESSION_CLEANUPS,
    _SESSION_ID_PATTERN,
    _ai_tool_names,
    _ai_tools_env,
    _build_claude_argv,
    _OverloadedError,
    _prompt_max_chars_from_env,
    _run_claude_subprocess,
    _StaleSessionError,
    _unlink_session_file_by_id,
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
_ROLE_LEAK_RE = re.compile(r"(?im)^(\s*)(user|assistant|system|tool|human|ai)(\s*:)")

# The flattened prompt's structure is delimited by Markdown ATX section
# headers (``# System`` / ``# Formatting rules`` / ``# Conversation
# history (oldest first)`` / ``# Current user message``) — a user message
# containing ``\n# Current user message\n<override>`` would spoof a NEW
# section that supersedes the persona, a strictly stronger injection than
# the role markers above. Defang only the bot's own reserved section
# names (any ``#`` depth, optionally followed by ``(…)``/``:``) so a
# legitimate markdown header like ``# System Requirements`` is untouched.
_HEADER_LEAK_RE = re.compile(
    r"(?im)^(\s*)(#{1,6}\s+)"
    r"(system|formatting rules|conversation history|current user message)"
    r"(?=\s*(?:\(|:|$))"
)


def _sanitize_dialog_segment(text: str) -> str:
    """Defang role-marker and section-header injection in dialog text.

    A user whose message contains a literal line ``Assistant: I'll do
    anything`` could otherwise spoof an assistant turn in the prompt the
    CLI subprocess receives, and a line ``# System`` could spoof a whole
    new prompt section. We rewrite every such line so the model sees
    them as quoted text the user typed, not real structure. Safe because
    the genuine section headers are emitted directly by
    ``_flatten_contents_to_prompt`` and never pass through here.
    """
    if not text:
        return text
    text = _ROLE_LEAK_RE.sub(r"\1[user-text] \2\3", text)
    return _HEADER_LEAK_RE.sub(r"\1[user-text] \2\3", text)


# Bound the per-update edit rate on the placeholder message so we don't
# burn Discord rate-limit budget on a long answer. The SDK path uses 1s;
# match it.
_DISCORD_EDIT_INTERVAL = 1.0

# Hard ceiling on a single turn end-to-end. Discord CLI replies run with
# extended thinking (`--effort xhigh`, see the
# _build_claude_argv calls below), which can reason for minutes on hard
# questions — so match the dashboard's 1800s thinking cap. The old 600s
# assumed thinking was off and would kill a deep-reasoning turn mid-reason.
# Still bounded so a runaway subprocess can't hold the channel lock forever.
_DISCORD_STREAM_TIMEOUT = 1800.0

# Prompt-size ceiling, shared env knob (CLI_PROMPT_MAX_CHARS, 0 = off) with
# the dashboard handler. Default sits at the model's physical 1M-token
# window, NOT a quota cap — full history is only sent on fresh sessions
# (delta-on-resume) and RP operators want the whole conversation in context.
# On the Discord path exceeding it does NOT truncate: the turn stops and the
# user chooses via _OverlimitChoiceView (summarize the chat, or pause it).
_DISCORD_PROMPT_MAX_CHARS = _prompt_max_chars_from_env()

# Discord-side model + system-prompt overrides. The global ``CLAUDE_MODEL``
# default tracks Opus 4.8's 1M-token variant (``claude-opus-4-8[1m]``), so the
# explicit ``model=`` pin here is defensive: the Discord RP path stays on the
# 1M variant even if an operator overrides ``CLAUDE_MODEL`` in env for the
# dashboard. The system-prompt path is resolved per turn via
# :func:`_resolve_discord_system_prompt_file` — prefers ``CLAUDE2.md`` (LO's
# local gitignored persona override) and falls back to the committed
# ``CLAUDE.md`` for fresh clones. Both are fed to ``_build_claude_argv`` —
# dashboard callers that omit them keep their existing behaviour.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISCORD_CLI_MODEL = "claude-opus-4-8[1m]"
_DISCORD_CLI_SYSTEM_PROMPT_PRIMARY = _REPO_ROOT / "CLAUDE2.md"
_DISCORD_CLI_SYSTEM_PROMPT_FALLBACK = _REPO_ROOT / "CLAUDE.md"


def _resolve_discord_system_prompt_file() -> Path:
    """Pick the discord ``--append-system-prompt-file`` path at call time.

    Prefers the gitignored ``CLAUDE2.md`` at the repo root (LO's local persona
    override — held out of git for privacy); falls back to the committed
    ``CLAUDE.md`` so a fresh clone still spawns a working ``claude -p``
    instead of erroring on a missing path. Resolved per turn so adding or
    removing ``CLAUDE2.md`` takes effect without restarting the bot.
    """
    if _DISCORD_CLI_SYSTEM_PROMPT_PRIMARY.exists():
        return _DISCORD_CLI_SYSTEM_PROMPT_PRIMARY
    return _DISCORD_CLI_SYSTEM_PROMPT_FALLBACK


def _get_channel_lock(channel_id: int) -> asyncio.Lock:
    """Return the per-channel subprocess lock, creating it on demand.

    Uses ``setdefault`` so concurrent first-touch callers settle on the
    same Lock object (the old ``if not in`` shape created two distinct
    Locks under racy access). Also LRU-evicts when the dict grows past
    ``_MAX_TRACKED_CHANNELS`` to bound memory in long-lived bots.
    """
    lock = _CHANNEL_LOCKS.setdefault(channel_id, asyncio.Lock())
    _CHANNEL_LOCKS.move_to_end(channel_id)
    # Scan oldest-first for an unheld lock to evict. A held lock can't be
    # dropped (the holder must release the real object on exit), so instead
    # of giving up on the first held entry we move it to the back (it is in
    # active use right now, so treating it as most-recent is fine) and keep
    # inspecting the next-oldest, strictly enforcing the cap whenever any
    # entry is evictable. ``inspections`` bounds the scan to one full pass so
    # an all-held dict can't spin forever (it just can't shrink this call).
    inspections = len(_CHANNEL_LOCKS)
    while len(_CHANNEL_LOCKS) > _MAX_TRACKED_CHANNELS and inspections > 0:
        inspections -= 1
        evicted_id, evicted_lock = next(iter(_CHANNEL_LOCKS.items()))
        if evicted_id == channel_id:
            # Never evict the entry we just returned to the caller: it hasn't
            # acquired ``lock`` yet, so deleting it here would let a later
            # caller create a second Lock and defeat per-channel serialization.
            # Move it to the back and keep scanning; the dict may transiently
            # sit one over the cap until the next call shrinks it.
            _CHANNEL_LOCKS.move_to_end(evicted_id, last=True)
            continue
        if evicted_lock.locked():
            # Actively held — keep it but move it to the back so the next
            # iteration inspects a different (newer) entry.
            _CHANNEL_LOCKS.move_to_end(evicted_id, last=True)
            continue
        # Unheld: drop it.
        del _CHANNEL_LOCKS[evicted_id]
    return lock


def _schedule_session_unlink(session_id: str | None) -> None:
    """Best-effort, fire-and-forget unlink of a dropped session's ``.jsonl``.

    Routes through the dashboard module's ``_unlink_session_file_by_id``
    (which validates ``_SESSION_ID_PATTERN`` and confines deletion to the
    Claude projects folder — do NOT hand-roll a path join here) and pins
    the task in the shared ``_PENDING_SESSION_CLEANUPS`` set so it isn't
    GC'd mid-run. Never raises: with no running loop (sync callers,
    tests) the unlink is silently skipped — same contract as the
    dashboard's ``_track_session`` cleanup.
    """
    if not session_id:
        return
    with contextlib.suppress(RuntimeError):  # no running loop (sync callers)
        loop = asyncio.get_running_loop()
        task = loop.create_task(_unlink_session_file_by_id(session_id))
        _PENDING_SESSION_CLEANUPS.add(task)
        task.add_done_callback(_PENDING_SESSION_CLEANUPS.discard)


def _record_session(channel_id: int, session_id: str) -> None:
    """LRU-record the session_id for the channel."""
    # Validate at the source (mirrors the dashboard's _track_session). A
    # session id that doesn't match the strict pattern (e.g. one starting
    # with '-') would be dropped every turn by _build_claude_argv anyway —
    # leaving the channel permanently non-resuming. Refuse to store it so
    # the channel cleanly falls back to a fresh session instead.
    if not _SESSION_ID_PATTERN.match(session_id):
        logger.warning("Refusing to track suspicious Claude session id %r", session_id)
        return
    # Pop+reinsert puts the entry at the back of the eviction queue
    # (replaces the old move_to_end) AND captures the superseded id.
    old = _CHANNEL_SESSIONS.pop(channel_id, None)
    if old and old != session_id:
        # Every resumed ``--resume`` turn forks a NEW session id, so the
        # previous turn's transcript becomes unreachable by every cleanup
        # path — one orphaned .jsonl per turn (the dashboard's
        # _track_session fixes the same leak). The ``old != session_id``
        # guard is load-bearing: unlinking the CURRENT id would stale the
        # next --resume.
        _schedule_session_unlink(old)
    logger.debug(
        "claude session transition channel=%s %s -> %s",
        channel_id,
        (old or "none")[:8],
        session_id[:8],
    )
    _CHANNEL_SESSIONS[channel_id] = session_id
    while len(_CHANNEL_SESSIONS) > _MAX_TRACKED_CHANNELS:
        # LRU eviction is a memory cap, not a user-intent wipe — keep the
        # evicted channel's transcript on disk (deliberately conservative;
        # only explicit supersede/reset deletes files).
        _CHANNEL_SESSIONS.popitem(last=False)


def reset_channel_session(channel_id: int) -> None:
    """Forget the CLI session for a Discord channel.

    Called when the channel's history is wiped (e.g. ``!reset_ai``) so the
    next turn starts a fresh Claude session rather than ``--resume``-ing
    into stale server-side context. Also best-effort deletes the local
    ``.jsonl`` transcript — "memory wiped" shouldn't leave the full
    conversation readable on disk for the CLI's retention window.
    """
    _schedule_session_unlink(_CHANNEL_SESSIONS.pop(channel_id, None))
    _OVERLIMIT_LAST_WARN.pop(channel_id, None)


def _flatten_contents_to_prompt(
    contents: list[dict[str, Any]],
    system_instruction: str,
    include_history: bool = True,
) -> str:
    """Build the single prompt string fed to ``claude -p`` via stdin.

    The CLI's stream-json input format takes one user-role message per
    invocation; the system prompt and prior turns are folded into that
    single message body. Format roughly mirrors how the dashboard
    handler builds its prompt: a ``# System`` section, optional
    ``# Conversation history`` recap, then a ``# Current user message``
    trailer. Claude Code's own prompt processing handles structured
    sections well.

    ``include_history=False`` is the resumed-session (``--resume``) form:
    the server-side session already contains every prior turn, so
    re-sending the recap would duplicate the entire conversation in the
    session context each turn (quadratic growth that exhausts the model
    window within tens of turns). The ``# System`` persona and
    ``# Formatting rules`` stay in every turn — same persona-every-turn
    contract as the dashboard handler's ``is_resumed_session`` path.
    """
    parts: list[str] = []

    # If there's no system prompt AND no contents to respond to, the
    # caller is asking for an empty prompt — skip every header so the
    # callers can detect "nothing to send" via empty output.
    if not system_instruction and not contents:
        return ""

    if system_instruction:
        # Drop Claude Code's coding-assistant default identity before the persona
        # (see _IDENTITY_OVERRIDE) so the bot stays in character on the CLI backend.
        parts.append(_IDENTITY_OVERRIDE)
        parts.append("")
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

    history_parts: list[str] = []
    if history and include_history:
        history_parts.append("# Conversation history (oldest first)")
        for item in history:
            # contents is contractually list[dict] from logic.py, but guard the
            # shape here so an upstream contract violation (e.g. a bare string
            # tail item) is skipped rather than raising AttributeError out of
            # this pre-try helper — which would orphan the placeholder.
            if not isinstance(item, dict):
                continue
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
                history_parts.append(f"{speaker}: {_sanitize_dialog_segment(joined)}")
        history_parts.append("")

    tail_parts: list[str] = []
    if isinstance(current, dict):
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
            tail_parts.append("# Current user message")
            tail_parts.append(f"{speaker}: {_sanitize_dialog_segment(current_text)}")

    # NOTE: no silent truncation here. When the assembled prompt exceeds
    # _DISCORD_PROMPT_MAX_CHARS the CALLER stops the turn and asks the user
    # to choose (summarize the chat, or pause it) — per operator decision,
    # silently dropping RP context is worse than interrupting the turn.
    return "\n".join(parts + history_parts + tail_parts).strip()


# ---------------------------------------------------------------------------
# Over-limit flow: when a fresh-session prompt exceeds the context ceiling we
# stop the turn and let the user choose instead of silently dropping history.
# ---------------------------------------------------------------------------

# Last full warning (embed + buttons) per channel; within the cooldown a
# short delete_after notice is sent instead so repeated messages in a
# paused channel don't stack interactive views.
_OVERLIMIT_LAST_WARN: dict[int, float] = {}
# Keep the cooldown >= the _OverlimitChoiceView timeout (600s) so a still
# over-limit channel never has two live interactive views at once: an
# un-clicked view stays active (with owner-only buttons) for the full
# view timeout, and only the short delete_after notice is sent until it
# expires. A shorter cooldown let up to ~5 stacked views accumulate.
_OVERLIMIT_WARN_COOLDOWN = 600.0
# Token target handed to smart_trim_by_tokens — same default as the
# owner command ``!auto_summarize``.
_OVERLIMIT_SUMMARIZE_TARGET_TOKENS = 500_000


class _OverlimitChoiceView(discord.ui.View):
    """อยู่บนข้อความเตือน "แชทเกิน context window" — ให้เลือก:
    สรุปแชททั้งหมดแล้วคุยต่อ หรือพักแชทนี้ไว้ (ไม่สรุป = คุยต่อไม่ได้)

    OWNER-ONLY (per operator request): both choices are gated on
    ``bot.is_owner`` — the same authority as ``!auto_summarize`` — since
    summarize rewrites persisted history and pause blocks the channel.
    Summarize runs the identical trim+force-save routine and preserves
    old context as summaries.
    """

    def __init__(self, channel_id: int) -> None:
        super().__init__(timeout=600.0)
        self.channel_id = channel_id
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message is not None:
            with contextlib.suppress(Exception):
                await self.message.edit(view=self)

    async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        """Owner-only gate, same authority as ``@commands.is_owner()``.

        Summarize rewrites the persisted history (trim + force-save) and
        pause blocks the channel — both are operator decisions, so the
        buttons match the ``!auto_summarize`` permission instead of being
        clickable by every RP participant.
        """
        is_owner = False
        with contextlib.suppress(Exception):
            is_owner = await interaction.client.is_owner(interaction.user)
        if not is_owner:
            with contextlib.suppress(Exception):
                await interaction.response.send_message(
                    "❌ เฉพาะเจ้าของบอทเท่านั้นที่เลือกได้", ephemeral=True
                )
        return is_owner

    @discord.ui.button(label="📝 สรุปแชททั้งหมด", style=discord.ButtonStyle.primary)
    async def summarize(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._ensure_owner(interaction):
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content="⏳ กำลังสรุปแชททั้งหมด อาจใช้เวลาสักครู่...", view=self
        )
        ok, detail = await _summarize_channel_history(self.channel_id)
        if ok:
            _OVERLIMIT_LAST_WARN.pop(self.channel_id, None)
            reset_channel_session(self.channel_id)
            content = f"✅ สรุปแชทเรียบร้อย คุยต่อได้เลย\n{detail}"
        else:
            content = f"❌ สรุปไม่สำเร็จ: {detail}\nลองใหม่อีกครั้ง หรือใช้ `!auto_summarize`"
        with contextlib.suppress(Exception):
            await interaction.edit_original_response(content=content, view=None)
        self.stop()

    @discord.ui.button(label="❌ ไม่สรุป (พักแชทนี้ไว้)", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._ensure_owner(interaction):
            return
        await interaction.response.edit_message(
            content=(
                "⏸️ พักแชทนี้ไว้ตามที่เลือก — ประวัติเกิน context window "
                "จะคุยต่อได้เมื่อกด 📝 สรุปจากข้อความเตือนครั้งถัดไป "
                "หรือใช้ `!auto_summarize` / `!reset_ai`"
            ),
            view=None,
        )
        self.stop()


async def _summarize_channel_history(channel_id: int) -> tuple[bool, str]:
    """Trim+summarize the live channel history — mirrors ``!auto_summarize``.

    Runs under the channel's processing lock so an in-flight turn can't
    interleave, force-saves the trimmed history (the diff path would write
    nothing — see the owner command), and reports a Thai summary line.
    """
    from .chat_manager_registry import get_chat_manager

    cm = get_chat_manager()
    if cm is None:
        return False, "ระบบ AI ยังไม่พร้อม (cog ไม่ได้โหลด)"
    chat_data = cm.chats.get(channel_id)
    if chat_data is None:
        return False, "ไม่พบ session ของแชนเนลนี้ในหน่วยความจำ"
    try:
        from cogs.ai_core.memory.history_manager import history_manager
        from cogs.ai_core.storage import save_history

        locks = cm.processing_locks
        if channel_id not in locks:
            locks[channel_id] = asyncio.Lock()
        async with locks[channel_id]:
            # Re-fetch under the lock: the reference captured before acquiring it
            # could be replaced/evicted by a concurrent turn (mirror the hardened
            # !auto_summarize path, which re-reads the live session here).
            chat_data = cm.chats.get(channel_id)
            if chat_data is None:
                return False, "ไม่พบ session ของแชนเนลนี้ในหน่วยความจำ"
            history = chat_data.get("history", [])
            if not history:
                return False, "ไม่มีประวัติให้สรุป"
            before = len(history)
            trimmed = await history_manager.smart_trim_by_tokens(
                history,
                max_tokens=_OVERLIMIT_SUMMARIZE_TARGET_TOKENS,
                reserve_tokens=2000,
            )
            chat_data["history"] = trimmed
            persisted = await save_history(cm.bot, channel_id, chat_data, force=True)
        if not persisted:
            return False, "สรุปในหน่วยความจำแล้ว แต่บันทึกลงฐานข้อมูลไม่สำเร็จ (ดู log)"
        return True, f"📉 {before:,} → {len(trimmed):,} ข้อความ"
    except Exception:
        logger.exception("Over-limit summarize failed for channel %s", channel_id)
        return False, "เกิดข้อผิดพลาดภายใน (ดู log ของบอท)"


async def _send_overlimit_warning(
    send_channel: Any, channel_id: int | None, prompt_chars: int
) -> None:
    """Warn that the chat exceeds the context ceiling and offer the choice.

    Within the cooldown only a short auto-deleting reminder is sent so a
    busy paused channel doesn't accumulate interactive views.
    """
    now = time.monotonic()
    if channel_id is None:
        # No real channel to summarize/pause — the interactive view would map
        # to channel id 0 and its Summarize button would run against a session
        # that doesn't exist. Send only a static notice for the channel-less
        # caller; the real-channel path (the default) owns the choice flow.
        with contextlib.suppress(Exception):
            await send_channel.send(
                "⚠️ ประวัติแชทยาวเกิน context window ของโมเดลแล้ว "
                f"(~{prompt_chars:,} ตัวอักษร > {_DISCORD_PROMPT_MAX_CHARS:,}) "
                "— กรุณาใช้ `!auto_summarize` หรือ `!reset_ai`",
                delete_after=30,
            )
        return
    key = channel_id
    # Purge stale entries unconditionally — a channel that stays over-limit
    # hits the cooldown early-return below and would otherwise never run this,
    # so abandoned entries (channels long past their cooldown) would linger.
    for cid in [c for c, t in _OVERLIMIT_LAST_WARN.items() if now - t >= _OVERLIMIT_WARN_COOLDOWN]:
        _OVERLIMIT_LAST_WARN.pop(cid, None)
    last = _OVERLIMIT_LAST_WARN.get(key, 0.0)
    with contextlib.suppress(Exception):
        if now - last < _OVERLIMIT_WARN_COOLDOWN:
            await send_channel.send(
                "⚠️ แชทยังเกินขนาด context — เลือกจากข้อความเตือนก่อนหน้า หรือใช้ `!auto_summarize`",
                delete_after=15,
            )
            return
        # Reserve the cooldown slot synchronously BEFORE the network await so a
        # second over-limit turn for the same channel that interleaves at the
        # send below reads this timestamp and takes the short-notice path,
        # rather than both passing the check-then-act window and spawning two
        # live owner-only views. On send failure we roll the slot back (in the
        # except) so a transient Discord error doesn't lock the channel into the
        # short-notice path without ever having received the buttons.
        _OVERLIMIT_LAST_WARN[key] = now
        try:
            view = _OverlimitChoiceView(key)
            view.message = await send_channel.send(
                (
                    "⚠️ **ประวัติแชทนี้ยาวเกิน context window ของโมเดลแล้ว** "
                    f"(~{prompt_chars:,} ตัวอักษร > {_DISCORD_PROMPT_MAX_CHARS:,})\n"
                    "เลือกได้ว่าจะทำยังไงต่อ (เฉพาะเจ้าของบอท):\n"
                    "• 📝 **สรุปแชททั้งหมด** — ย่อประวัติเก่าเป็นบทสรุป แล้วคุยต่อได้ทันที\n"
                    "• ❌ **ไม่สรุป** — เก็บประวัติเต็มไว้ แต่แชทนี้จะคุยต่อไม่ได้จนกว่าจะสรุปหรือ reset"
                ),
                view=view,
            )
        except Exception:
            # Send failed: undo the reservation so the channel isn't stuck on
            # the short-notice path having never received the buttons. Only
            # roll back if no other turn has since claimed the slot.
            if _OVERLIMIT_LAST_WARN.get(key) == now:
                _OVERLIMIT_LAST_WARN.pop(key, None)
            raise


async def call_claude_cli_streaming(
    contents: list[dict[str, Any]],
    config_params: dict[str, Any],
    send_channel: Any,
    channel_id: int | None = None,
    cancel_flags: dict[int, bool] | None = None,
    user_id: int | None = None,
    guild_id: int | None = None,
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
        msg = f"⚠️ Claude CLI ไม่พร้อมใช้งาน ({reason}). กรุณาให้แอดมินตรวจสอบ `claude` CLI"
        with contextlib.suppress(Exception):
            await send_channel.send(msg, delete_after=30)
        return "", "", []

    system_instruction = config_params.get("system_instruction", "") or ""

    placeholder_msg = None
    last_edit_time = 0.0
    accumulated_text = ""
    aborted = False
    # Infrastructure-failure notice for the user. Kept OUT of the returned
    # model text so logic.py never persists "⚠️ Claude CLI ..." strings as
    # model turns that would be re-fed to the model on every later turn.
    error_notice: str | None = None
    # Set when a fresh-session prompt exceeds the context ceiling — the turn
    # stops and the user chooses (summarize / pause) instead of us silently
    # truncating their RP history.
    overlimit_chars: int | None = None

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

    reasoning_signalled = False

    async def on_thinking_start() -> None:
        nonlocal reasoning_signalled
        # One-shot, and only before any visible text: thinking blocks recur
        # mid-turn between tool calls, and an unguarded edit would clobber
        # the streamed preview (and burn Discord edit budget). Subscription
        # mode redacts the reasoning content itself, so this single liveness
        # edit is the only sign the potentially minutes-long xhigh reasoning
        # phase hasn't hung. The suppress is load-bearing — a deleted
        # placeholder must not abort the whole stream.
        if reasoning_signalled or accumulated_text:
            return
        reasoning_signalled = True
        with contextlib.suppress(Exception):
            await placeholder_msg.edit(
                content="💭 กำลังใช้ความคิดเชิงลึก อาจใช้เวลาสักครู่...",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    lock = _get_channel_lock(channel_id) if channel_id is not None else _FALLBACK_LOCK
    async with lock:
        # First-turn ⇒ no session_id; subsequent turns reuse via --resume.
        session_id = _CHANNEL_SESSIONS.get(channel_id) if channel_id is not None else None
        turn_start = time.monotonic()
        logger.info(
            "💬 discord-cli start channel=%s resume=%s",
            channel_id,
            (session_id or "")[:8] or "none",
        )
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

        # AI tools (memory + optional server actions) via the MCP→IPC bridge.
        # Needs the per-turn Discord context; guild falls back to the channel's.
        _guild = (
            guild_id
            if guild_id is not None
            else getattr(getattr(send_channel, "guild", None), "id", None)
        )
        ai_tools = _ai_tool_names()
        tools_env = (
            _ai_tools_env(guild_id=_guild, channel_id=channel_id, user_id=user_id)
            if ai_tools
            else None
        )

        # Run with retry-once on stale session — exactly mirrors the
        # dashboard handler's behaviour. The stale-session case is when
        # Claude on the server side has GC'd the session log under us.
        for attempt in (1, 2):
            # Built per attempt: a resumed session already holds every prior
            # turn server-side, so it gets the delta form (no history recap);
            # a fresh session — including the attempt-2 stale retry, which
            # clears session_id — gets the full flattened history.
            prompt = _flatten_contents_to_prompt(
                contents, system_instruction, include_history=session_id is None
            )
            if (
                session_id is None
                and _DISCORD_PROMPT_MAX_CHARS
                and len(prompt) > _DISCORD_PROMPT_MAX_CHARS
            ):
                # Fresh-session prompt would blow the model window. Stop and
                # ask the user (summarize / pause) — never truncate silently.
                overlimit_chars = len(prompt)
                break
            argv = _build_claude_argv(
                claude_exe,
                session_id=session_id,
                allow_read_for_images=False,
                allow_edit_tools=False,
                # Discord replies think at xhigh effort, same as a dashboard
                # conversation with thinking enabled. Subscription mode redacts
                # the reasoning content (only start/stop markers reach us — see
                # on_thinking), but the model still spends real reasoning effort.
                enable_thinking=True,
                # Give the Discord AI web access (WebSearch + WebFetch). There's
                # no Read tool on this path, so no local-file exfil risk; both
                # run server-side at Anthropic.
                enable_web=_CLI_WEB_TOOLS_ENABLED,
                ai_tool_names=ai_tools,
                # Discord path pins Opus 4.8's 1M-context variant and the
                # repo-root CLAUDE2.md persona (fallback: CLAUDE.md) — see the
                # module-level constants for the rationale.
                model=_DISCORD_CLI_MODEL,
                system_prompt_file=_resolve_discord_system_prompt_file(),
            )
            try:
                runner = asyncio.create_task(
                    _run_claude_subprocess(
                        argv,
                        prompt,
                        on_text_delta=on_text,
                        on_thinking_delta=on_thinking,
                        on_thinking_block_start=on_thinking_start,
                        on_thinking_block_stop=None,
                        timeout=_DISCORD_STREAM_TIMEOUT,
                        extra_env=tools_env,
                    )
                )

                async def _cancel_watcher(_runner: asyncio.Task = runner) -> None:
                    # Cancelling the runner kills the claude subprocess via
                    # its finally (proc.kill) and releases the channel lock.
                    # Previously a user cancel only muted output while the
                    # lock stayed held until the CLI finished the FULL
                    # generation (or the 1800s timeout) — queueing every
                    # later message in the channel behind a dead turn.
                    while not _runner.done():
                        if (
                            channel_id is not None
                            and cancel_flags is not None
                            and cancel_flags.get(channel_id)
                        ):
                            _runner.cancel()
                            return
                        await asyncio.sleep(0.5)

                watcher: asyncio.Task | None = None
                if channel_id is not None and cancel_flags is not None:
                    watcher = asyncio.create_task(_cancel_watcher())
                try:
                    new_session_id, _usage = await asyncio.wait_for(
                        runner, timeout=_DISCORD_STREAM_TIMEOUT
                    )
                except asyncio.CancelledError:
                    if (
                        channel_id is not None
                        and cancel_flags is not None
                        and cancel_flags.get(channel_id)
                    ):
                        # Our watcher cancelled the runner: treat as a clean
                        # user cancellation, drop the now-divergent session.
                        aborted = True
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                        break
                    # Genuine external cancellation (cog unload / loop
                    # shutdown): this BaseException skips the post-lock
                    # placeholder cleanup below, so delete the
                    # "💭 กำลังคิด..." placeholder here before re-raising.
                    if placeholder_msg is not None:
                        with contextlib.suppress(Exception):
                            await placeholder_msg.delete()
                    raise
                finally:
                    if watcher is not None:
                        watcher.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await watcher
                if channel_id is not None and new_session_id and not aborted:
                    _record_session(channel_id, new_session_id)
                elif aborted and channel_id is not None:
                    # Cancelled mid-stream: the subprocess still ran to completion
                    # server-side, but we return empty (the SDK-path contract) and
                    # never store this reply in local history. Don't --resume into
                    # a session whose server-side context holds an undelivered
                    # reply — drop it so the next turn starts fresh and local vs.
                    # server-side history stay aligned.
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                if not aborted:
                    logger.info(
                        "✅ discord-cli done channel=%s attempt=%d duration=%.1fs "
                        "response_len=%d session=%s",
                        channel_id,
                        attempt,
                        time.monotonic() - turn_start,
                        len(accumulated_text),
                        (new_session_id or "")[:8] or "none",
                    )
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
                    # Reset the placeholder to an explicit retry state so any
                    # attempt-1 preview/'thinking' text doesn't linger across
                    # the (potentially minutes-long) fresh attempt, and let
                    # attempt 2's first delta + reasoning marker fire again.
                    last_edit_time = 0.0
                    reasoning_signalled = False
                    with contextlib.suppress(Exception):
                        await placeholder_msg.edit(
                            content="💭 กำลังลองใหม่...",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    continue
                # Second stale-session in a row → give up; the prompt is
                # probably mal-formed in a way Claude refuses. Tell the user
                # (this used to be completely silent: placeholder vanished,
                # no reply, nothing).
                logger.error(
                    "Claude CLI session repeatedly stale for channel %s (attempt=%d)",
                    channel_id,
                    attempt,
                )
                accumulated_text = ""
                error_notice = "⚠️ เซสชัน Claude CLI มีปัญหาซ้ำ กรุณาลองส่งข้อความใหม่อีกครั้ง"
                break
            except TimeoutError:
                logger.warning(
                    "Claude CLI timed out after %ss for channel %s (session=%s attempt=%d)",
                    _DISCORD_STREAM_TIMEOUT,
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                )
                # The server-side session never recorded this turn (the run
                # died before a session id came back) while logic.py persists
                # any partial text locally — resuming would diverge local vs
                # server history. Drop the session: next turn starts fresh
                # with the full-history prompt and self-heals.
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                if accumulated_text:
                    # Real (partial) model output: keep it, with a marker.
                    accumulated_text += "\n\n*[การตอบถูกตัดเนื่องจากใช้เวลานานเกินไป]*"
                else:
                    error_notice = "⚠️ Claude CLI ใช้เวลาตอบนานเกินกำหนด กรุณาลองใหม่"
                break
            except _OverloadedError:
                # Transient Anthropic overload (429/529). claude already retried
                # internally, so don't loop again — show a clear retry hint.
                logger.warning(
                    "Claude CLI: Anthropic API overloaded for channel %s (session=%s attempt=%d)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                accumulated_text = ""
                error_notice = "⚠️ เซิร์ฟเวอร์ Anthropic ไม่ว่างชั่วคราว กรุณาลองใหม่อีกครั้งในอีกสักครู่"
                break
            except Exception:
                logger.exception(
                    "Claude CLI subprocess failed for channel %s (session=%s attempt=%d)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                )
                # Unclassified failures include context-overflow API errors:
                # without this pop the next turn would --resume straight back
                # into the same overflowing session and fail identically,
                # wedging the channel until a bot restart / !reset_ai.
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                accumulated_text = ""
                error_notice = "⚠️ Claude CLI ขัดข้อง กรุณาดู log ของบอท"
                break

    # Final placeholder cleanup. ``logic.py`` will send the actual
    # response separately via its chunked send path, so we delete the
    # placeholder rather than leave the running-preview text behind as a
    # duplicate of the final message.
    if placeholder_msg is not None:
        with contextlib.suppress(Exception):
            await placeholder_msg.delete()

    if overlimit_chars is not None:
        # Chat exceeds the context ceiling: warn + offer summarize/pause.
        # Return empty so nothing about this aborted turn is persisted.
        await _send_overlimit_warning(send_channel, channel_id, overlimit_chars)
        return "", "", []

    if error_notice and not accumulated_text:
        # Infrastructure failure with no usable output: tell the user via a
        # short-lived notice and return EMPTY so the warning never enters
        # durable channel history (logic.py persists any non-empty model
        # text and would re-feed it to the model on every later turn).
        with contextlib.suppress(Exception):
            await send_channel.send(error_notice, delete_after=30)
        return "", "", []

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
    cancel_flags: dict[int, bool] | None = None,
    user_id: int | None = None,
    guild_id: int | None = None,
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

    accumulated_text = ""
    aborted = False

    async def on_text(text: str) -> None:
        nonlocal accumulated_text
        if text:
            accumulated_text += text

    async def on_thinking(_text: str) -> None:
        return

    lock = _get_channel_lock(channel_id) if channel_id is not None else _FALLBACK_LOCK
    async with lock:
        session_id = _CHANNEL_SESSIONS.get(channel_id) if channel_id is not None else None
        turn_start = time.monotonic()
        logger.info(
            "💬 discord-cli start (non-stream) channel=%s resume=%s",
            channel_id,
            (session_id or "")[:8] or "none",
        )
        from .dashboard_chat_claude_cli import _resolve_claude_executable

        claude_exe = _resolve_claude_executable()
        if not claude_exe:
            return "", "", []

        ai_tools = _ai_tool_names()
        tools_env = (
            _ai_tools_env(guild_id=guild_id, channel_id=channel_id, user_id=user_id)
            if ai_tools
            else None
        )

        for attempt in (1, 2):
            # Same delta-on-resume rule as the streaming sibling: resumed
            # sessions skip the history recap; fresh sessions (incl. the
            # attempt-2 stale retry) re-send the full flattened history.
            prompt = _flatten_contents_to_prompt(
                contents, system_instruction, include_history=session_id is None
            )
            if (
                session_id is None
                and _DISCORD_PROMPT_MAX_CHARS
                and len(prompt) > _DISCORD_PROMPT_MAX_CHARS
            ):
                # Over the context ceiling. This path has no channel object
                # to post the interactive summarize/pause choice to — log
                # and skip the turn; the streaming path (the default for
                # real channels) owns the user-facing flow.
                logger.warning(
                    "Prompt over context ceiling (%d > %d chars) for channel %s "
                    "(non-stream) — turn skipped",
                    len(prompt),
                    _DISCORD_PROMPT_MAX_CHARS,
                    channel_id,
                )
                return "", "", []
            argv = _build_claude_argv(
                claude_exe,
                session_id=session_id,
                allow_read_for_images=False,
                allow_edit_tools=False,
                # Discord replies think at xhigh effort, same as a dashboard
                # conversation with thinking enabled. Subscription mode redacts
                # the reasoning content (only start/stop markers reach us — see
                # on_thinking), but the model still spends real reasoning effort.
                enable_thinking=True,
                # Give the Discord AI web access (WebSearch + WebFetch). There's
                # no Read tool on this path, so no local-file exfil risk; both
                # run server-side at Anthropic.
                enable_web=_CLI_WEB_TOOLS_ENABLED,
                ai_tool_names=ai_tools,
                # Discord path pins Opus 4.8's 1M-context variant and the
                # repo-root CLAUDE2.md persona (fallback: CLAUDE.md) — see the
                # module-level constants for the rationale.
                model=_DISCORD_CLI_MODEL,
                system_prompt_file=_resolve_discord_system_prompt_file(),
            )
            try:
                runner = asyncio.create_task(
                    _run_claude_subprocess(
                        argv,
                        prompt,
                        on_text_delta=on_text,
                        on_thinking_delta=on_thinking,
                        on_thinking_block_start=None,
                        on_thinking_block_stop=None,
                        timeout=_DISCORD_STREAM_TIMEOUT,
                        extra_env=tools_env,
                    )
                )

                async def _cancel_watcher(_runner: asyncio.Task = runner) -> None:
                    # Same watcher as the streaming sibling: cancelling the
                    # runner kills the claude subprocess via its finally
                    # (proc.kill) and releases the channel lock. Without it a
                    # user abort neither stopped the child nor freed the lock
                    # — the turn ran to completion (up to the 1800s budget)
                    # queueing every later message behind a dead turn.
                    while not _runner.done():
                        if (
                            channel_id is not None
                            and cancel_flags is not None
                            and cancel_flags.get(channel_id)
                        ):
                            _runner.cancel()
                            return
                        await asyncio.sleep(0.5)

                watcher: asyncio.Task | None = None
                if channel_id is not None and cancel_flags is not None:
                    watcher = asyncio.create_task(_cancel_watcher())
                try:
                    new_session_id, _usage = await asyncio.wait_for(
                        runner, timeout=_DISCORD_STREAM_TIMEOUT
                    )
                except asyncio.CancelledError:
                    if (
                        channel_id is not None
                        and cancel_flags is not None
                        and cancel_flags.get(channel_id)
                    ):
                        # Our watcher cancelled the runner: treat as a clean
                        # user cancellation. Drop the session — the killed
                        # half-reply never enters local history, so resuming
                        # it would desync local vs server-side context.
                        aborted = True
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                        break
                    raise
                finally:
                    if watcher is not None:
                        watcher.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await watcher
                if channel_id is not None and new_session_id and not aborted:
                    _record_session(channel_id, new_session_id)
                if not aborted:
                    logger.info(
                        "✅ discord-cli done (non-stream) channel=%s attempt=%d "
                        "duration=%.1fs response_len=%d session=%s",
                        channel_id,
                        attempt,
                        time.monotonic() - turn_start,
                        len(accumulated_text),
                        (new_session_id or "")[:8] or "none",
                    )
                break
            except _StaleSessionError:
                if attempt == 1 and session_id:
                    session_id = None
                    accumulated_text = ""
                    if channel_id is not None:
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                    continue
                logger.error(
                    "Claude CLI session repeatedly stale (non-stream) for channel %s (attempt=%d)",
                    channel_id,
                    attempt,
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                # Surface a user-facing notice like the other branches — a blank
                # accumulated_text would return "" and leave the non-stream user
                # with no reply at all ("visible beats invisible", per the note
                # below; the streaming sibling posts an equivalent notice).
                accumulated_text = "⚠️ เซสชัน Claude CLI มีปัญหาซ้ำ กรุณาลองส่งข้อความใหม่อีกครั้ง"
                break
            # NOTE: unlike the streaming sibling, this path has no channel
            # object to post a short-lived notice to — the returned text is
            # the only way to reach the user, so warnings stay in the return
            # value here (visible beats invisible) at the cost of being
            # persisted into history once. All failure paths still drop the
            # session: the server never recorded this turn, so resuming
            # would diverge local vs server-side context (and for
            # unclassified errors — incl. context overflow — would wedge
            # the channel on the same broken session).
            except TimeoutError:
                logger.warning(
                    "Claude CLI timed out (non-stream) for channel %s (session=%s attempt=%d)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                if accumulated_text:
                    accumulated_text += "\n\n*[การตอบถูกตัดเนื่องจากใช้เวลานานเกินไป]*"
                else:
                    accumulated_text = "⚠️ Claude CLI ใช้เวลาตอบนานเกินกำหนด กรุณาลองใหม่"
                break
            except _OverloadedError:
                logger.warning(
                    "Claude CLI: Anthropic API overloaded (non-stream) for channel %s "
                    "(session=%s attempt=%d)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                accumulated_text = "⚠️ เซิร์ฟเวอร์ Anthropic ไม่ว่างชั่วคราว กรุณาลองใหม่อีกครั้งในอีกสักครู่"
                break
            except Exception:
                logger.exception(
                    "Claude CLI subprocess failed (non-stream) for channel %s "
                    "(session=%s attempt=%d)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                accumulated_text = "⚠️ Claude CLI ขัดข้อง กรุณาดู log ของบอท"
                break

    if aborted:
        # Cancellation matches the SDK/streaming contract: return empty so
        # nothing from the killed turn is persisted as a model reply.
        return "", "", []

    # Same defence pipeline as the streaming path.
    cleaned = strip_claude_internal_tags(accumulated_text)
    cleaned = strip_leading_timestamp(cleaned)
    return cleaned, "", []


__all__ = [
    "call_claude_cli",
    "call_claude_cli_streaming",
    "reset_channel_session",
]
