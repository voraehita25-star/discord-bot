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
      These — and the ``mcp__bottools__*`` custom tools — are DECLARED to the
      model in the prompt (see ``_discord_tools_note``); the personas here were
      written for the Gemini backend and would otherwise have the model deny
      having web access instead of calling the tool.
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
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, cast

import discord
from discord.ext import commands

from .dashboard_chat_claude_cli import (
    _CLI_EFFORT,
    _CLI_WEB_TOOLS_ENABLED,
    _IDENTITY_DEFERRAL,
    _IDENTITY_OVERRIDE,
    _PENDING_SESSION_CLEANUPS,
    _SESSION_ID_PATTERN,
    _ai_tool_names,
    _ai_tools_env,
    _build_claude_argv,
    _lower_effort,
    _OverloadedError,
    _persona_depth_replaces,
    _prompt_max_chars_from_env,
    _run_claude_subprocess,
    _SafeguardError,
    _StaleSessionError,
    _unlink_session_file_by_id,
    build_tools_declaration,
    effective_ai_tool_names,
    has_prompt_content,
    is_cli_backend_ready,
)
from .dashboard_common import (
    strip_claude_internal_tags,
    strip_leading_message_ids,
    strip_leading_timestamp,
)

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

# Per-channel reset generation counter. reset_channel_session() bumps this;
# a turn captures it at start and refuses to _record_session() its forked
# session id if the epoch moved while the subprocess was in flight.
# reset_channel_session() deliberately takes NO channel lock (its callers —
# !reset_ai, link_memory — must be able to wipe even while a long turn holds
# it), so a reset can land mid-turn. Without this guard the completing turn
# re-records a fork whose server-side context still holds the whole pre-wipe
# conversation, resurrecting the "forgotten" history AND re-creating the
# .jsonl on disk. Uncapped like _OVERLIMIT_LAST_WARN: it's one small int per
# channel-ever-reset (rare, user-initiated), and evicting it could false-drop
# an in-flight turn's legitimate recording.
_CHANNEL_RESET_EPOCH: dict[int, int] = {}

# NOTE: prompt-injection defang for the Discord flattened prompt was removed per
# operator request — user messages + history are flattened into the prompt
# VERBATIM (no ``[user-text]`` rewriting of ``Assistant:`` / ``# Current user
# message`` lines). This lowers the bar for a server member to jailbreak the bot
# via a crafted chat message; accepted by the operator.


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

# How often a RESUMED turn re-sends the guild lore block. Default 0: once per
# session, never again — the operator's call, made with the trade-off below on
# the table.
#
# Lore is part of the system instruction, and the persona-every-turn contract
# re-sends the whole instruction on every turn — so on the RP guild a resumed
# turn spent ~92% of its prompt repeating world data the server-side session
# already had (measured: 55,285 chars/turn, 4,560 without the lore, 7.8x less
# on average even at the periodic setting).
#
# The trade-off the default accepts: Claude Code compacts a long session on its
# own, and a lore block last seen hundreds of turns ago is what compaction
# summarises away first — after which nothing re-sends it. Raise the knob if a
# long-running channel ever starts forgetting world detail. Note the opposite
# extreme is not the safe one either: re-sending every turn fills the window
# ~12x faster, so it TRIGGERS the compaction it is trying to survive.
#
#   CLI_LORE_REFRESH_TURNS=0   fresh sessions only, never re-sent (default)
#   CLI_LORE_REFRESH_TURNS=N   fresh sessions + every Nth resumed turn
#   CLI_LORE_REFRESH_TURNS=1   every turn (the pre-change behaviour)
_LORE_REFRESH_ENV = "CLI_LORE_REFRESH_TURNS"


def _lore_refresh_turns() -> int:
    """Resolve ``CLI_LORE_REFRESH_TURNS``; see the block comment above.

    Read per call so flipping it takes effect without a bot restart. A negative
    or unparseable value falls back to the default (0), so a typo lands on the
    shipped behaviour rather than on a re-send cadence nobody chose.
    """
    raw = (os.environ.get(_LORE_REFRESH_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid %s=%r; using default", _LORE_REFRESH_ENV, raw)
        else:
            if value >= 0:
                return value
            logger.warning("Negative %s=%r; using default", _LORE_REFRESH_ENV, raw)
    return 0


# Turns since this channel's prompt last carried the lore block. Same 500-entry
# LRU cap as _CHANNEL_SESSIONS. Eviction is not free: a channel sitting at
# seen=19 with every=20 restarts at 1, so the refresh arrives 19 turns LATE — a
# MISSED re-send, not a spare one. Hence move_to_end on every touch, so the
# channels that are actually talking are the ones that survive.
_TURNS_SINCE_LORE: OrderedDict[int, int] = OrderedDict()


def _lore_due_this_turn(channel_id: int | None, session_id: str | None) -> bool:
    """Whether THIS turn's prompt should carry the lore block, and tick the counter.

    Call exactly once per user turn, before the attempt loop — the loop rebuilds
    the prompt per attempt and must not advance the counter twice. The stale-
    session retry clears ``session_id``, and a fresh session always carries the
    lore, so a retry is covered regardless of what this returned.

    A ``None`` channel has no session to resume and nothing to count against,
    so it always carries the lore rather than seeding a ``None`` key.
    """
    if channel_id is None:
        return True
    every = _lore_refresh_turns()
    if every == 0:
        # Shipped default: carried when the session is created, never again.
        # Checked BEFORE the fresh-session branch so the map stays empty — at
        # this setting nothing ever reads it, and seeding a row per channel
        # (including every DM and non-RP guild) would be pure bookkeeping.
        return session_id is None
    if session_id is None or every == 1:
        _touch_lore_counter(channel_id, 0)
        return True
    seen = _TURNS_SINCE_LORE.get(channel_id, 0) + 1
    if seen >= every:
        _touch_lore_counter(channel_id, 0)
        return True
    _touch_lore_counter(channel_id, seen)
    return False


def _touch_lore_counter(channel_id: int, value: int) -> None:
    """Write a counter and mark the channel most-recently-used, then evict.

    ``OrderedDict[k] = v`` on an EXISTING key does not reorder, so a plain
    assignment would leave eviction ordered by FIRST touch — popping the busiest
    channel while a long-idle one survives. move_to_end makes it a real LRU,
    matching what ``_record_session`` and ``_get_channel_lock`` already do.
    """
    _TURNS_SINCE_LORE[channel_id] = value
    _TURNS_SINCE_LORE.move_to_end(channel_id)
    while len(_TURNS_SINCE_LORE) > _MAX_TRACKED_CHANNELS:
        _TURNS_SINCE_LORE.popitem(last=False)


def _without_server_lore(system_instruction: str, server_lore: str) -> str:
    """Strip the guild-lore block from a system instruction for a resumed turn.

    ``session_mixin`` appends the lore after the persona separated by a
    blank line, and stores the same text under ``server_lore``, so the block
    comes out by exact match. When it is NOT found — an operator edited the
    lore file mid-session, so the stored text no longer matches what was
    appended — the instruction goes out whole rather than being guessed at.
    """
    if not server_lore:
        return system_instruction
    block = "\n\n" + server_lore
    if system_instruction.endswith(block):
        return system_instruction[: -len(block)]
    occurrences = system_instruction.count(block)
    if occurrences == 1:
        # Not at the tail but unambiguous — the RP cache-fixup path can append
        # a roleplay-format addendum after the lore.
        return system_instruction.replace(block, "", 1)
    if occurrences > 1:
        # Two or more copies and none at the tail: the persona itself embeds
        # the lore text (e.g. ROLEPLAY_PROMPT interpolating WORLD_LORE). A
        # blind replace() would delete the PERSONA's copy and leave the
        # appended one, silently running the whole optimisation inert.
        logger.warning(
            "Server lore appears %d times in the system instruction and not at "
            "its tail — sending the instruction whole rather than stripping the "
            "wrong copy",
            occurrences,
        )
    return system_instruction


# Discord-side model + system-prompt overrides. The pin here is deliberate and
# is NOT the global ``CLAUDE_MODEL`` (which the dashboard keeps on Opus 5): the
# Discord path runs Opus 4.7 at the operator's request, after Opus 5 answered a
# normal RP turn with an AUP-safeguard refusal at the ``[reasoning_extraction]``
# stage (see ``_SafeguardError``). Keeping the two apart is the whole reason
# this constant exists — the dashboard's model is free to move without dragging
# Discord with it, and vice versa.
#
# ``[1m]`` is load-bearing, not decoration. Claude Code assumes a 200K window
# for a bare model id and auto-compacts to fit it; the suffix is how the CLI is
# told the model's real 1M window (it says so itself when it meets an id it
# cannot map). A fresh session on the RP guild measured 259,934 prompt tokens —
# lore, persona, and the channel's history — so the bare id would silently
# compact away most of a turn's context.
#
# The system-prompt path is resolved per turn via
# :func:`_resolve_discord_system_prompt_file` — prefers ``CLAUDE2.md`` (LO's
# local gitignored persona override) and falls back to the committed
# ``CLAUDE.md`` for fresh clones. With ``DISCORD_CLI_UNRESTRICTED_MODE=gated``
# the overlay is applied only to ``!unrestricted`` channels (the default
# ``always`` applies it to every channel). Both are fed to ``_build_claude_argv``
# — dashboard callers that omit them keep their existing behaviour.
#
# The file is passed with ``replace_system_prompt=True``, i.e. as
# ``--system-prompt-file``: it BECOMES the system prompt instead of trailing
# Claude Code's built-in one. "Overlay" below is therefore historical wording —
# nothing precedes the override at system level any more.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISCORD_CLI_MODEL = "claude-opus-4-7[1m]"
_DISCORD_CLI_SYSTEM_PROMPT_PRIMARY = _REPO_ROOT / "CLAUDE2.md"
_DISCORD_CLI_SYSTEM_PROMPT_FALLBACK = _REPO_ROOT / "CLAUDE.md"


def _discord_cli_unrestricted_gated() -> bool:
    """True when the CLI Discord path should GATE the CLAUDE2.md overlay on the
    per-channel ``!unrestricted`` toggle.

    Controlled by ``DISCORD_CLI_UNRESTRICTED_MODE``:
      * ``always`` (default) — every channel always gets the CLAUDE2.md overlay,
        regardless of ``!unrestricted`` (historical behaviour: no command needed,
        unrestricted always on).
      * ``gated`` — the overlay is applied ONLY to channels with ``!unrestricted``
        enabled; others run on their normal persona, so the command controls the
        CLI path too.

    Read per call so flipping the env takes effect without a bot restart.
    """
    return os.getenv("DISCORD_CLI_UNRESTRICTED_MODE", "always").strip().lower() == "gated"


def _resolve_discord_system_prompt_file(channel_id: int | None = None) -> Path | None:
    """Pick the discord ``--append-system-prompt-file`` path at call time.

    Prefers the gitignored ``CLAUDE2.md`` at the repo root (LO's local persona
    override — held out of git for privacy); falls back to the committed
    ``CLAUDE.md`` so a fresh clone still spawns a working ``claude -p`` instead
    of erroring on a missing path. Resolved per turn so adding or removing
    ``CLAUDE2.md`` takes effect without restarting the bot.

    In ``gated`` mode (``DISCORD_CLI_UNRESTRICTED_MODE=gated``) the overlay is
    withheld (returns ``None``) for channels that do NOT have ``!unrestricted``
    enabled — those run on the normal persona already carried in the prompt
    body. In the default ``always`` mode the overlay is applied unconditionally.

    An empty (or whitespace-only) file does not count as present. The override
    is passed at replace depth, so pointing the CLI at a blank file would hand
    the model NO system prompt at all — worse than the built-in default it was
    meant to displace. Returning ``None`` here keeps that turn on the default
    instead. See :func:`has_prompt_content`.
    """
    if _discord_cli_unrestricted_gated():
        # Lazy import: keeps this module importable even if the unrestricted
        # registry is unavailable (is_unrestricted then stubs to False).
        from ..imports import is_unrestricted

        if channel_id is None or not is_unrestricted(channel_id):
            return None
    if has_prompt_content(_DISCORD_CLI_SYSTEM_PROMPT_PRIMARY):
        return _DISCORD_CLI_SYSTEM_PROMPT_PRIMARY
    if has_prompt_content(_DISCORD_CLI_SYSTEM_PROMPT_FALLBACK):
        return _DISCORD_CLI_SYSTEM_PROMPT_FALLBACK
    return None


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
    # Bump the reset epoch so any turn already in flight for this channel
    # skips re-recording its (now forked-off) session id when it completes.
    _CHANNEL_RESET_EPOCH[channel_id] = _CHANNEL_RESET_EPOCH.get(channel_id, 0) + 1


# MCP tool names (unprefixed) served by ``ai_tools_ipc`` that belong to the
# MEMORY group; everything else ``_ai_tool_names()`` returns is a Discord
# server-action tool. Kept here rather than re-imported from ai_tools_ipc so this
# module doesn't pull the aiohttp-dependent IPC module at import time.
_MEMORY_TOOL_BASENAMES = frozenset({"remember", "recall_memory"})

# The two tools that make the ``(msg …)`` annotations ACTIONABLE: ``edit_message``
# takes an id, ``read_channel`` reports ids for messages older than the shown
# history. Both are server tools, so a deployment with
# ``DASHBOARD_CLI_SERVER_ACTIONS`` off has neither — and since ``--tools`` drops
# every MCP tool with no way to name one back, so does EVERY deployment at the
# default ``CLI_TOOL_SCOPE=minimal`` (see ``effective_ai_tool_names``).
_EDIT_MESSAGE_TOOL = "edit_message"
_READ_CHANNEL_TOOL = "read_channel"


def _message_id_tools(ai_tool_names: list[str] | None) -> tuple[bool, bool]:
    """``(can_edit_messages, can_read_channel)`` for THIS turn's resolved toolset.

    Callers pass the SAME list they hand to ``_build_claude_argv`` — i.e. the
    output of ``effective_ai_tool_names`` — so the prompt's claims about the
    message-id annotations track what the argv actually enables. Without this the
    "# Formatting rules" block promised ``edit_message`` on every turn while the
    shipped argv exposes only WebSearch/WebFetch: the model would offer to
    correct an earlier message and then have no tool to do it with, which is the
    exact confident-call-to-a-missing-tool failure ``_discord_tools_note`` and
    ``effective_ai_tool_names`` exist to prevent.
    """
    basenames = {name.rsplit("__", 1)[-1] for name in (ai_tool_names or [])}
    return _EDIT_MESSAGE_TOOL in basenames, _READ_CHANNEL_TOOL in basenames


def _discord_tools_note(ai_tool_names: list[str] | None) -> str:
    """The ``# Available tools`` block for THIS turn's resolved Discord toolset.

    The Discord CLI path enables real tools — WebSearch/WebFetch (``enable_web``)
    and the ``mcp__bottools__*`` custom tools — but the flattened prompt used to
    describe none of them, so the model fell back on its persona text (written
    for the old Gemini backend) and told users it had no web access instead of
    just searching. The dashboard sibling solved this with the same block; share
    it so the two backends can't describe the same toolset differently.

    Derived from the SAME inputs ``_build_claude_argv`` is called with below, so
    the declaration cannot advertise a tool the argv withholds:
      * web: ``_CLI_WEB_TOOLS_ENABLED``. WebFetch is listed too because this path
        passes ``allow_read_for_images=False``, and the argv only withholds
        WebFetch on Read-enabled turns (exfil-safety) — there are none here.
      * custom tools: split by ``_MEMORY_TOOL_BASENAMES`` so a deployment with
        ``DASHBOARD_CLI_SERVER_ACTIONS`` off (the default) isn't told it can
        create channels.
    """
    basenames = {name.rsplit("__", 1)[-1] for name in (ai_tool_names or [])}
    return build_tools_declaration(
        web_enabled=_CLI_WEB_TOOLS_ENABLED,
        webfetch_enabled=_CLI_WEB_TOOLS_ENABLED,
        memory_tools_enabled=bool(basenames & _MEMORY_TOOL_BASENAMES),
        server_tools_enabled=bool(basenames - _MEMORY_TOOL_BASENAMES),
    )


# The ``(msg …)`` / ``(msgs name=…)`` annotation logic.py prefixes onto the
# bot's own stored turns. Matched here (rather than re-derived) so the resumed
# recap and the prompt history can never disagree about a message id.
_MESSAGE_ID_ANNOTATION_RE = re.compile(r"^\s*(\(msgs?\s+[^()\n]{0,400}?\))\s*(.*)", re.DOTALL)

# How many recent assistant turns the resumed-session recap names, and how much
# of each turn's text it quotes. Both are deliberately small: the recap exists
# to make ids addressable, not to restore the conversation.
_RESUMED_ID_RECAP_TURNS = 5
_RESUMED_ID_RECAP_SNIPPET = 80


def _recent_message_id_lines(history: list[dict[str, Any]]) -> list[str]:
    """Id-only recap of the most recent assistant turns, oldest first.

    Each line pairs the annotation with just enough text to tell the turns
    apart. Turns with no annotation (rows written before the ids were tracked)
    are skipped: naming a turn without giving its id would only invite a guess.
    """
    lines: list[str] = []
    for item in reversed(history):
        if len(lines) >= _RESUMED_ID_RECAP_TURNS:
            break
        if not isinstance(item, dict) or item.get("role") != "model":
            continue
        first_text = next(
            (
                part if isinstance(part, str) else part.get("text")
                for part in item.get("parts", [])
                if isinstance(part, str) or (isinstance(part, dict) and part.get("text"))
            ),
            None,
        )
        if not isinstance(first_text, str):
            continue
        # logic.py assembles the prefix as ``[timestamp] (msg …) text``.
        match = _MESSAGE_ID_ANNOTATION_RE.match(strip_leading_timestamp(first_text))
        if not match:
            continue
        annotation, body = match.group(1), match.group(2).strip().replace("\n", " ")
        snippet = body[:_RESUMED_ID_RECAP_SNIPPET]
        if len(body) > _RESUMED_ID_RECAP_SNIPPET:
            snippet += "…"
        lines.append(f"{annotation} {snippet}".rstrip())
    lines.reverse()
    return lines


def _flatten_contents_to_prompt(
    contents: list[dict[str, Any]],
    system_instruction: str,
    include_history: bool = True,
    tools_note: str = "",
    persona_in_system_prompt: bool = False,
    can_edit_messages: bool = False,
    can_read_channel: bool = False,
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
    window within tens of turns). The ``# System`` block and
    ``# Formatting rules`` stay in every turn — same persona-every-turn
    contract as the dashboard handler's ``is_resumed_session`` path.

    ONE exception, applied by the callers rather than here: the guild-lore
    slice of ``system_instruction`` is stripped before it reaches this
    function on a resumed turn (see ``_without_server_lore`` and
    ``_lore_due_this_turn``). It is static world data, unlike the persona and
    profile the every-turn rule was written for, and on the RP guild it was
    ~92% of the prompt. What arrives here is still just "the system
    instruction" — this function has no opinion about what is in it.

    ``tools_note`` is the ``# Available tools (this session)`` block from
    :func:`_discord_tools_note`. It goes AFTER the persona so it supersedes
    stale persona claims (the Gemini-era "Google Search is automatically
    enabled"), and — like the persona — is re-sent on resumed turns so the
    model never loses track of what it can call mid-conversation.

    ``persona_in_system_prompt`` says whether THIS turn's argv installs a
    persona file with ``--system-prompt-file`` (see
    :func:`_resolve_discord_system_prompt_file` and ``_persona_depth_replaces``).
    It picks which directive opens the body: ``_IDENTITY_OVERRIDE``, which
    claims the body as the model's only identity source, or
    ``_IDENTITY_DEFERRAL``, which hands identity to the system prompt and
    demotes ``system_instruction`` to context and format rules. Getting this
    wrong is not cosmetic — the body directive beats the system prompt in
    practice, so the override wording silently discards the persona file the
    argv just installed. Callers must derive it from the same resolved path they
    hand to :func:`_build_claude_argv`, never re-resolve it here.

    ``can_edit_messages`` / ``can_read_channel`` say whether THIS turn's argv
    really carries those tools — see :func:`_message_id_tools`, which callers
    must derive from the same resolved tool list they pass to
    :func:`_build_claude_argv`. They gate every sentence that tells the model to
    ACT on a ``(msg …)`` annotation, and the resumed-session id recap (whose
    only purpose is feeding ``edit_message``). Both default to False so a caller
    that forgets to resolve them fails closed — silence about a tool is
    recoverable, a promise of one that isn't there is not.
    """
    parts: list[str] = []

    # If there's no system prompt AND no contents to respond to, the
    # caller is asking for an empty prompt — skip every header so the
    # callers can detect "nothing to send" via empty output.
    if not system_instruction and not contents:
        return ""

    if system_instruction:
        if persona_in_system_prompt:
            # A persona file IS the system prompt this turn. Identity belongs to
            # it; what follows here is the guild's world data and output-format
            # rules, so the header says so explicitly — a bare "# System" over a
            # character sheet reads as a competing persona and wins.
            parts.append(_IDENTITY_DEFERRAL)
            parts.append("")
            parts.append("# Context & format rules (NOT your identity)")
        else:
            # Append depth (or no persona file): Claude Code's coding-assistant
            # default still leads the system prompt, so drop it before the
            # persona (see _IDENTITY_OVERRIDE) to stay in character.
            parts.append(_IDENTITY_OVERRIDE)
            parts.append("")
            parts.append("# System")
        parts.append(system_instruction.strip())
        parts.append("")

    # AFTER the persona so it overrides stale persona claims about tooling
    # (see _discord_tools_note). Emitted even on the no-system-instruction
    # path — the tools are enabled in argv either way.
    if tools_note:
        parts.append(tools_note)
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
    # What to SAY about the ``(msg …)`` annotation depends on whether this turn
    # can act on the ids. The "never reproduce one" rule holds either way — it is
    # what stops the model mimicking the prefix into its own reply — but the
    # edit_message / read_channel sentences are claims about the toolset and only
    # go out when the argv really carries those tools.
    id_note = (
        "Your own past turns may additionally carry a message-id annotation — "
        "'(msg 1401234567890123456)' for a turn sent as one Discord message, or "
        "'(msgs narration=140…, Character=140…)' when the turn went out as "
        "several (one per {{Name}} block, or split across chunks). "
    )
    if can_edit_messages:
        id_note += (
            "These ids are what the edit_message tool takes, so you can correct an "
            "earlier message instead of only apologising for it. "
        )
    if can_read_channel:
        id_note += (
            "For messages older than the shown history, call read_channel — it "
            "reports the id of every message it returns. "
        )
    id_note += (
        "Like timestamps, these annotations are system-injected: never reproduce "
        "one in your own reply."
    )
    parts.append(id_note)
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
                history_parts.append(f"{speaker}: {joined}")
        history_parts.append("")
    elif history and can_edit_messages:
        # Resumed session: the full recap is deliberately not re-sent (see the
        # docstring), which would also withhold every ``(msg …)`` annotation —
        # leaving the model unable to correct its own recent messages without a
        # read_channel round trip on the default backend. Re-send just the ids
        # of the last few assistant turns: bounded, id-only, and short enough
        # that repeating it per turn cannot grow the session context the way a
        # full recap would. Skipped without ``edit_message``: the block's ONLY
        # purpose is feeding that tool, so without it the ids are prompt weight
        # that reads as an invitation to call something that isn't there.
        recap = _recent_message_id_lines(history)
        if recap:
            history_parts.append("# Your recent messages (ids for edit_message)")
            history_parts.extend(recap)
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
            tail_parts.append(f"{speaker}: {current_text}")

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
    ย่อประวัติแล้วคุยต่อ หรือพักแชทนี้ไว้ (ไม่ย่อ = คุยต่อไม่ได้)

    OWNER-ONLY (per operator request): both choices are gated on
    ``bot.is_owner`` — the same authority as ``!auto_summarize`` — since the
    condense path rewrites persisted history and pause blocks the channel.

    The wording deliberately says "ย่อ" (condense), not "สรุป" (summarise). The
    routine trims by importance and force-saves, which DELETES the dropped rows;
    a summary row replaces them only when the summarizer is operational, which
    it is not on the default CLI backend. The old copy promised a summary
    unconditionally, so the owner was choosing "summarise" and getting
    "permanently delete".
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
            is_owner = await cast(commands.Bot, interaction.client).is_owner(interaction.user)
        if not is_owner:
            with contextlib.suppress(Exception):
                await interaction.response.send_message(
                    "❌ เฉพาะเจ้าของบอทเท่านั้นที่เลือกได้", ephemeral=True
                )
        return is_owner

    @discord.ui.button(label="📝 ย่อประวัติแชท", style=discord.ButtonStyle.primary)
    async def summarize(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._ensure_owner(interaction):
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content="⏳ กำลังย่อประวัติแชท อาจใช้เวลาสักครู่...", view=self
        )
        ok, detail = await _summarize_channel_history(self.channel_id)
        if ok:
            _OVERLIMIT_LAST_WARN.pop(self.channel_id, None)
            reset_channel_session(self.channel_id)
            content = f"✅ ย่อประวัติเรียบร้อย คุยต่อได้เลย\n{detail}"
        else:
            content = f"❌ ย่อไม่สำเร็จ: {detail}\nลองใหม่อีกครั้ง หรือใช้ `!auto_summarize`"
        with contextlib.suppress(Exception):
            await interaction.edit_original_response(content=content, view=None)
        self.stop()

    @discord.ui.button(label="❌ ไม่ย่อ (พักแชทนี้ไว้)", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._ensure_owner(interaction):
            return
        await interaction.response.edit_message(
            content=(
                "⏸️ พักแชทนี้ไว้ตามที่เลือก — ประวัติเกิน context window "
                "จะคุยต่อได้เมื่อกด 📝 ย่อประวัติจากข้อความเตือนครั้งถัดไป "
                "หรือใช้ `!auto_summarize` / `!reset_ai`"
            ),
            view=None,
        )
        self.stop()


async def _summarize_channel_history(channel_id: int) -> tuple[bool, str]:
    """Trim (and, when possible, summarize) the live history — as ``!auto_summarize``.

    Runs under the channel's processing lock so an in-flight turn can't
    interleave, force-saves the trimmed history (the diff path would write
    nothing — see the owner command), and reports a Thai status line.

    The force-save is a delete-and-reinsert, so whatever the trim drops is gone
    from storage for good. The reported line therefore states which of the two
    things actually happened — summarised, or discarded — instead of the old
    unconditional "summarised" claim, which was wrong whenever the summarizer
    had no SDK client (i.e. on the default CLI backend, always).
    """
    from .chat_manager_registry import get_chat_manager

    cm = get_chat_manager()
    if cm is None:
        return False, "ระบบ AI ยังไม่พร้อม (cog ไม่ได้โหลด)"
    chat_data = cm.chats.get(channel_id)
    if chat_data is None:
        return False, "ไม่พบ session ของแชนเนลนี้ในหน่วยความจำ"
    try:
        from cogs.ai_core.memory.history_manager import history_manager, is_summary_entry
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
                summarize=True,
            )
            chat_data["history"] = trimmed
            persisted = await save_history(cm.bot, channel_id, chat_data, force=True)
        if not persisted:
            return False, "ย่อในหน่วยความจำแล้ว แต่บันทึกลงฐานข้อมูลไม่สำเร็จ (ดู log)"
        detail = f"📉 {before:,} → {len(trimmed):,} ข้อความ"
        if trimmed and is_summary_entry(trimmed[0]):
            return True, f"{detail} (ย่อของเก่าเป็นบทสรุปไว้ให้แล้ว)"
        return (
            True,
            f"{detail} — ข้อความเก่า {before - len(trimmed):,} ข้อความถูกลบถาวร (สร้างบทสรุปไม่ได้)",
        )
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
    last = _OVERLIMIT_LAST_WARN.get(key)
    with contextlib.suppress(Exception):
        # time.monotonic() is uptime-based, so a 0.0 default made
        # `now - 0.0 < cooldown` true within ~10 min of a reboot, misrouting a
        # never-warned channel's first over-limit turn to the short notice.
        if last is not None and now - last < _OVERLIMIT_WARN_COOLDOWN:
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
                    "• 📝 **ย่อประวัติแชท** — ตัดข้อความเก่าออกให้พอดี context แล้วคุยต่อได้ทันที\n"
                    "  ⚠️ ข้อความที่ถูกตัดจะถูก**ลบถาวร** (จะแทนด้วยบทสรุปให้ก็ต่อเมื่อ summarizer ใช้งานได้)\n"
                    "• ❌ **ไม่ย่อ** — เก็บประวัติเต็มไว้ แต่แชทนี้จะคุยต่อไม่ได้จนกว่าจะย่อหรือ reset"
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


async def _record_cli_usage(
    usage: dict[str, Any] | None,
    *,
    channel_id: int | None,
    user_id: int | None,
    guild_id: int | None,
) -> None:
    """Feed the turn's exact token usage to the DB-backed tracker.

    ``claude -p`` reports real input/output/cache counts in its terminal
    ``result`` event and ``_run_claude_subprocess`` hands them back — but both
    Discord entry points used to bind that to ``_usage`` and drop it. Since
    ``cli`` is the DEFAULT backend, the tracker therefore had NO producer:
    ``!ai_tokens`` reported zeros indefinitely even though ``!ai_trace`` tells
    the operator to look there. Best-effort and non-fatal; the model is pinned
    to ``_DISCORD_CLI_MODEL``, which is what the argv actually requests.
    """
    if not usage:
        return
    try:
        from cogs.ai_core.cache.token_tracker import record_usage_snapshot

        await record_usage_snapshot(
            usage,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            model=_DISCORD_CLI_MODEL,
        )
    except Exception:
        logger.debug("discord-cli token usage recording skipped", exc_info=True)


def _safeguard_notice(err: _SafeguardError) -> str:
    """User-facing Thai notice for an AUP-safeguard refusal.

    Two texts because the two stages need different advice: a reasoning-stage
    flag has nothing to do with what the member typed (asking them to rephrase
    would be misleading), while a content-stage one is exactly that.
    """
    if err.is_reasoning_stage:
        return (
            "⚠️ ตัวกรองความปลอดภัยของ Anthropic บล็อกเทิร์นนี้ "
            "(เกิดที่ขั้นตอนคิดของโมเดล ไม่ได้เกิดจากข้อความของคุณ) กรุณาลองส่งใหม่อีกครั้ง"
        )
    return "⚠️ ตัวกรองความปลอดภัยของ Anthropic ไม่อนุญาตให้ตอบข้อความนี้ กรุณาลองเรียบเรียงใหม่"


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
    # Dropped from resumed turns — see _lore_due_this_turn.
    server_lore = config_params.get("server_lore", "") or ""

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
    # Exact usage from the subprocess's terminal ``result`` event. Recorded
    # after the lock is released (see the tail below) — this used to be dropped
    # on the floor, which left the token tracker with no producer at all on the
    # default backend.
    turn_usage: dict[str, Any] | None = None

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
        # Capture the reset epoch NOW — synchronous and adjacent to the
        # session_id read (no await between, so a concurrent reset lands wholly
        # before or after both). Compared again before _record_session so a
        # reset that fires while this turn is in flight isn't silently undone.
        reset_epoch = _CHANNEL_RESET_EPOCH.get(channel_id, 0) if channel_id is not None else 0
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
        # Minimal tool scope cannot carry MCP tools (see effective_ai_tool_names),
        # so resolve them ONCE here: the same list feeds the argv and the tools
        # note, which is what stops the prompt from advertising a tool the argv
        # withheld.
        ai_tools = effective_ai_tool_names(_ai_tool_names())
        tools_env = (
            _ai_tools_env(guild_id=_guild, channel_id=channel_id, user_id=user_id)
            if ai_tools
            else None
        )
        # Declare the resolved toolset in the prompt — the argv below enables
        # web + custom tools that the persona (Gemini-era) doesn't know about.
        tools_note = _discord_tools_note(ai_tools)
        # Same list, so the prompt's claims about the ``(msg …)`` annotations
        # can't outrun the argv either (see _message_id_tools).
        can_edit_messages, can_read_channel = _message_id_tools(ai_tools)

        # Once per turn, NOT per attempt: the loop below rebuilds the prompt on
        # the stale-session retry and must not advance the refresh counter twice.
        lore_due = _lore_due_this_turn(channel_id, session_id)

        # Reasoning depth for the attempt. Normally None (= the operator's
        # pinned _CLI_EFFORT); the `[reasoning_extraction]` safeguard retry
        # below drops it one rung.
        effort_override: str | None = None

        # Run with retry-once on stale session — exactly mirrors the
        # dashboard handler's behaviour. The stale-session case is when
        # Claude on the server side has GC'd the session log under us.
        for attempt in (1, 2):
            # Built per attempt: a resumed session already holds every prior
            # turn server-side, so it gets the delta form (no history recap);
            # a fresh session — including the attempt-2 stale retry, which
            # clears session_id — gets the full flattened history. The lore
            # block follows the same rule on a slower clock (_lore_due_this_turn).
            send_lore = lore_due or session_id is None
            # Resolved ONCE per attempt and handed to BOTH the prompt body and
            # the argv below. The file is re-resolved every turn (it can be
            # edited or removed while the bot runs), so two independent calls
            # could disagree mid-turn — and a body that opens with the wrong
            # identity directive silently discards the persona the argv just
            # installed, which is the exact failure this pairing prevents.
            system_prompt_file = _resolve_discord_system_prompt_file(channel_id)
            prompt = _flatten_contents_to_prompt(
                contents,
                # Stripped lazily: on a lore-carrying turn (every fresh session,
                # and every turn at the CLI_LORE_REFRESH_TURNS=1 rollback) the
                # stripped copy would be built and thrown away — two scans of a
                # ~55 KB string against a ~50 KB needle, for nothing.
                system_instruction
                if send_lore
                else _without_server_lore(system_instruction, server_lore),
                include_history=session_id is None,
                tools_note=tools_note,
                # True whenever the argv installs the persona file AS the system
                # prompt (--system-prompt-file). Then identity is the file's and
                # system_instruction is demoted to context/format rules; at
                # append depth (CLI_PERSONA_DEPTH=append) or with no file at all
                # the body keeps its own identity directive.
                persona_in_system_prompt=(
                    system_prompt_file is not None and _persona_depth_replaces()
                ),
                # Resolved from the SAME tool list the argv below is built with,
                # so the body never offers a message-id tool the argv withholds.
                can_edit_messages=can_edit_messages,
                can_read_channel=can_read_channel,
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
                # Reasoning depth is pinned by `_CLI_EFFORT` (CLAUDE_EFFORT,
                # default xhigh) — the CLI has no thinking switch, so there is
                # no per-turn thinking flag. Subscription mode redacts the
                # reasoning content (only start/stop markers reach us — see
                # on_thinking), but the effort is real. `effort_override` is
                # None except on the safeguard retry below, which steps one
                # rung down; it is never a caller-supplied value.
                effort=effort_override,
                # Give the Discord AI web access (WebSearch + WebFetch). There's
                # no Read tool on this path, so no local-file exfil risk; both
                # run server-side at Anthropic.
                enable_web=_CLI_WEB_TOOLS_ENABLED,
                ai_tool_names=ai_tools,
                # Discord path pins its OWN model + persona, deliberately
                # apart from the dashboard's: _DISCORD_CLI_MODEL (Opus 4.7's
                # 1M-context variant, not the global CLAUDE_MODEL) and the
                # repo-root CLAUDE2.md (fallback: CLAUDE.md) — see the
                # module-level constants for the rationale.
                model=_DISCORD_CLI_MODEL,
                system_prompt_file=system_prompt_file,
                # The override REPLACES Claude Code's built-in system prompt
                # rather than trailing it (see _system_prompt_flag). Appending
                # left the built-in identity in front, and it won: the model
                # introduced itself as a coding assistant no matter what the
                # override said. Safe here because everything this path needs
                # besides identity — the guild's world data, the tools
                # declaration, the timestamp convention — travels in the prompt
                # body, not in the system prompt being replaced. Identity is the
                # replaced prompt's alone, and the body says so: at this depth it
                # opens with _IDENTITY_DEFERRAL instead of _IDENTITY_OVERRIDE.
                replace_system_prompt=True,
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
                    new_session_id, turn_usage = await asyncio.wait_for(
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
                    if _CHANNEL_RESET_EPOCH.get(channel_id, 0) != reset_epoch:
                        # A reset_channel_session() landed while this turn was
                        # in flight. Recording the fork would resurrect the
                        # wiped context (its server-side session still holds
                        # every pre-wipe turn) and re-create the transcript on
                        # disk. Drop it: unlink the fork and leave the channel
                        # session-less so the next turn starts fresh.
                        logger.info(
                            "discord-cli reset during turn channel=%s; dropping forked session %s",
                            channel_id,
                            (new_session_id or "")[:8] or "none",
                        )
                        _schedule_session_unlink(new_session_id)
                    else:
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
            except _SafeguardError as err:
                # Anthropic's AUP classifier refused the turn. A
                # `[reasoning_extraction]` flag fired on the model's own
                # reasoning trace — not on anything the member typed — and
                # Anthropic's own wording ("This sometimes happens with safe,
                # normal conversations") makes it non-deterministic, so it is
                # worth exactly one retry. Both levers the CLI itself suggests
                # are pulled: a fresh session, and one rung less --effort
                # (a shallower trace is what tripped the classifier, and the
                # retry finishes minutes sooner than a same-depth re-run).
                # A content-stage flag gets no retry: re-sending identical text
                # would burn another full turn to fail the same way.
                retry_effort = _lower_effort(effort_override or _CLI_EFFORT)
                if attempt == 1 and err.is_reasoning_stage and retry_effort:
                    logger.warning(
                        "Claude CLI safeguard flag on reasoning for channel %s "
                        "(session=%s); retrying fresh at --effort %s",
                        channel_id,
                        (session_id or "")[:8] or "none",
                        retry_effort,
                    )
                    effort_override = retry_effort
                    session_id = None
                    accumulated_text = ""
                    if channel_id is not None:
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                    # Same placeholder reset as the stale-session retry so
                    # attempt-1 preview text doesn't linger and attempt 2's
                    # first delta + reasoning marker fire again.
                    last_edit_time = 0.0
                    reasoning_signalled = False
                    with contextlib.suppress(Exception):
                        await placeholder_msg.edit(
                            content="💭 กำลังลองใหม่...",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    continue
                logger.warning(
                    "Claude CLI refused by the AUP safeguard classifier for channel %s "
                    "(session=%s attempt=%d stage=%s)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                    err.stage or "<unknown>",
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                accumulated_text = ""
                error_notice = _safeguard_notice(err)
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

    # Record the turn's tokens (best-effort, outside the channel lock). Also
    # done on a user-cancelled turn: the subprocess still ran to completion
    # server-side, so those tokens were genuinely spent.
    await _record_cli_usage(turn_usage, channel_id=channel_id, user_id=user_id, guild_id=guild_id)

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
    # 3. Same for the ``(msg …)`` message-id annotation carried by past
    #    assistant turns — stripped after the timestamp because that is
    #    the order the prefixes are assembled in.
    cleaned = strip_claude_internal_tags(accumulated_text)
    cleaned = strip_leading_timestamp(cleaned)
    cleaned = strip_leading_message_ids(cleaned)
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
    # Dropped from resumed turns — see _lore_due_this_turn.
    server_lore = config_params.get("server_lore", "") or ""

    accumulated_text = ""
    aborted = False
    # See the streaming sibling: the subprocess's exact usage was discarded here
    # too, leaving the token tracker without a producer on the default backend.
    turn_usage: dict[str, Any] | None = None

    async def on_text(text: str) -> None:
        nonlocal accumulated_text
        if text:
            accumulated_text += text

    async def on_thinking(_text: str) -> None:
        return

    lock = _get_channel_lock(channel_id) if channel_id is not None else _FALLBACK_LOCK
    async with lock:
        session_id = _CHANNEL_SESSIONS.get(channel_id) if channel_id is not None else None
        # Capture the reset epoch NOW (see the streaming sibling for the full
        # rationale): compared before _record_session so a reset landing
        # mid-turn isn't silently undone by re-recording the forked session.
        reset_epoch = _CHANNEL_RESET_EPOCH.get(channel_id, 0) if channel_id is not None else 0
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

        # Minimal tool scope cannot carry MCP tools (see effective_ai_tool_names),
        # so resolve them ONCE here: the same list feeds the argv and the tools
        # note, which is what stops the prompt from advertising a tool the argv
        # withheld.
        ai_tools = effective_ai_tool_names(_ai_tool_names())
        tools_env = (
            _ai_tools_env(guild_id=guild_id, channel_id=channel_id, user_id=user_id)
            if ai_tools
            else None
        )
        # Same toolset declaration as the streaming sibling — the argv below
        # enables the identical web + custom tools.
        tools_note = _discord_tools_note(ai_tools)
        # …and the same message-id capability resolution, so this path can't
        # promise edit_message where the streaming sibling stays silent.
        can_edit_messages, can_read_channel = _message_id_tools(ai_tools)

        # Once per turn, not per attempt — see the streaming sibling.
        lore_due = _lore_due_this_turn(channel_id, session_id)

        # Lowered only by the safeguard retry — see the streaming sibling.
        effort_override: str | None = None

        for attempt in (1, 2):
            # Same delta-on-resume rule as the streaming sibling: resumed
            # sessions skip the history recap; fresh sessions (incl. the
            # attempt-2 stale retry) re-send the full flattened history, and
            # the lore block follows on its own slower clock.
            send_lore = lore_due or session_id is None
            # Resolved ONCE per attempt and handed to BOTH the prompt body and
            # the argv below. The file is re-resolved every turn (it can be
            # edited or removed while the bot runs), so two independent calls
            # could disagree mid-turn — and a body that opens with the wrong
            # identity directive silently discards the persona the argv just
            # installed, which is the exact failure this pairing prevents.
            system_prompt_file = _resolve_discord_system_prompt_file(channel_id)
            prompt = _flatten_contents_to_prompt(
                contents,
                # Stripped lazily: on a lore-carrying turn (every fresh session,
                # and every turn at the CLI_LORE_REFRESH_TURNS=1 rollback) the
                # stripped copy would be built and thrown away — two scans of a
                # ~55 KB string against a ~50 KB needle, for nothing.
                system_instruction
                if send_lore
                else _without_server_lore(system_instruction, server_lore),
                include_history=session_id is None,
                tools_note=tools_note,
                # True whenever the argv installs the persona file AS the system
                # prompt (--system-prompt-file). Then identity is the file's and
                # system_instruction is demoted to context/format rules; at
                # append depth (CLI_PERSONA_DEPTH=append) or with no file at all
                # the body keeps its own identity directive.
                persona_in_system_prompt=(
                    system_prompt_file is not None and _persona_depth_replaces()
                ),
                # Resolved from the SAME tool list the argv below is built with,
                # so the body never offers a message-id tool the argv withholds.
                can_edit_messages=can_edit_messages,
                can_read_channel=can_read_channel,
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
                # Reasoning depth is pinned by `_CLI_EFFORT` (CLAUDE_EFFORT,
                # default xhigh) — the CLI has no thinking switch, so there is
                # no per-turn thinking flag. Subscription mode redacts the
                # reasoning content (only start/stop markers reach us — see
                # on_thinking), but the effort is real. `effort_override` is
                # None except on the safeguard retry below, which steps one
                # rung down; it is never a caller-supplied value.
                effort=effort_override,
                # Give the Discord AI web access (WebSearch + WebFetch). There's
                # no Read tool on this path, so no local-file exfil risk; both
                # run server-side at Anthropic.
                enable_web=_CLI_WEB_TOOLS_ENABLED,
                ai_tool_names=ai_tools,
                # Discord path pins its OWN model + persona, deliberately
                # apart from the dashboard's: _DISCORD_CLI_MODEL (Opus 4.7's
                # 1M-context variant, not the global CLAUDE_MODEL) and the
                # repo-root CLAUDE2.md (fallback: CLAUDE.md) — see the
                # module-level constants for the rationale.
                model=_DISCORD_CLI_MODEL,
                system_prompt_file=system_prompt_file,
                # The override REPLACES Claude Code's built-in system prompt
                # rather than trailing it (see _system_prompt_flag). Appending
                # left the built-in identity in front, and it won: the model
                # introduced itself as a coding assistant no matter what the
                # override said. Safe here because everything this path needs
                # besides identity — the guild's world data, the tools
                # declaration, the timestamp convention — travels in the prompt
                # body, not in the system prompt being replaced. Identity is the
                # replaced prompt's alone, and the body says so: at this depth it
                # opens with _IDENTITY_DEFERRAL instead of _IDENTITY_OVERRIDE.
                replace_system_prompt=True,
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
                    new_session_id, turn_usage = await asyncio.wait_for(
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
                    if _CHANNEL_RESET_EPOCH.get(channel_id, 0) != reset_epoch:
                        # A reset landed mid-turn (see the streaming sibling):
                        # drop the fork instead of resurrecting the wiped
                        # context and re-creating the transcript on disk.
                        logger.info(
                            "discord-cli reset during turn (non-stream) channel=%s; "
                            "dropping forked session %s",
                            channel_id,
                            (new_session_id or "")[:8] or "none",
                        )
                        _schedule_session_unlink(new_session_id)
                    else:
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
            except _SafeguardError as err:
                # Same one-shot recovery as the streaming sibling: a
                # reasoning-stage flag is retried once on a fresh session at
                # one rung less --effort; a content-stage flag is reported.
                retry_effort = _lower_effort(effort_override or _CLI_EFFORT)
                if attempt == 1 and err.is_reasoning_stage and retry_effort:
                    logger.warning(
                        "Claude CLI safeguard flag on reasoning (non-stream) for channel %s "
                        "(session=%s); retrying fresh at --effort %s",
                        channel_id,
                        (session_id or "")[:8] or "none",
                        retry_effort,
                    )
                    effort_override = retry_effort
                    session_id = None
                    accumulated_text = ""
                    if channel_id is not None:
                        _CHANNEL_SESSIONS.pop(channel_id, None)
                    continue
                logger.warning(
                    "Claude CLI refused by the AUP safeguard classifier (non-stream) "
                    "for channel %s (session=%s attempt=%d stage=%s)",
                    channel_id,
                    (session_id or "")[:8] or "none",
                    attempt,
                    err.stage or "<unknown>",
                )
                if channel_id is not None:
                    _CHANNEL_SESSIONS.pop(channel_id, None)
                accumulated_text = _safeguard_notice(err)
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

    # Record the turn's tokens before any early return (see the streaming
    # sibling): a cancelled turn still spent them server-side.
    await _record_cli_usage(turn_usage, channel_id=channel_id, user_id=user_id, guild_id=guild_id)

    if aborted:
        # Cancellation matches the SDK/streaming contract: return empty so
        # nothing from the killed turn is persisted as a model reply.
        return "", "", []

    # Same defence pipeline as the streaming path.
    cleaned = strip_claude_internal_tags(accumulated_text)
    cleaned = strip_leading_timestamp(cleaned)
    cleaned = strip_leading_message_ids(cleaned)
    return cleaned, "", []


__all__ = [
    "call_claude_cli",
    "call_claude_cli_streaming",
    "reset_channel_session",
]
