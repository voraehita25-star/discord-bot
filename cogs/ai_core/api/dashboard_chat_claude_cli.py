"""Dashboard chat backend that delegates to the Claude Code CLI subprocess.

Why this exists:
  Using the `anthropic` SDK + ANTHROPIC_API_KEY bills per-token. If the user
  already pays for a Claude Code Max subscription, this backend lets the
  dashboard reuse that subscription quota instead of double-billing on tokens.

Architecture:
  - Spawns ``claude -p --output-format stream-json --input-format stream-json``
  - Sends prompt via stdin (sidesteps the argv length limit so long histories
    fit) and reads NDJSON events from stdout.
  - Per-conversation Claude `session_id` is tracked in-memory: the first
    message in a conversation starts a fresh session, subsequent messages
    use ``--resume <session_id>`` so Claude carries the context server-side
    (no need to re-send the entire history each turn → faster + prompt cache
    stays warm).
  - Auth: the spawned `claude` picks up OAuth credentials saved by an
    interactive `claude` login (~/.claude/.credentials.json). Setting
    CLAUDE_CODE_OAUTH_TOKEN explicitly is optional. ANTHROPIC_API_KEY is
    stripped from the subprocess env so per-token billing never silently
    wins over the subscription.

Feature parity vs the SDK backend (`dashboard_chat_claude.py`):
  ✓ Streaming text
  ✓ Extended thinking (forwarded as `thinking_chunk` events)
  ✓ Exact token usage from CLI's final result event
  ✓ Image attachments (decoded to a per-conversation temp dir, Claude reads
    them via the Read tool)
  ✓ Session continuity via `--resume`
  ✓ `/edit` AI rewrite (uses the same SEARCH/REPLACE patch protocol)
  ✓ Persona delivered as a cacheable system prefix (--append-system-prompt-file)
    instead of re-sent in every user turn; the next turn's process is
    pre-warmed to hide the `claude -p` cold start (DASHBOARD_CLI_PREWARM=0 to
    disable)
  ✓ Prompt-cache stats: the CLI result usage carries
    cache_read_input_tokens / cache_creation_input_tokens (CLI ≥ 2.1.x), logged
    per turn so cache effectiveness on resumed turns is observable
  ✗ `--temperature` / `--max-tokens` — Claude Code CLI does not expose these
  ✗ API failover (`direct ↔ proxy`) — N/A for subscription auth

Toggle: set ``CLAUDE_BACKEND=cli`` in .env to use this module; anything else
(or unset) keeps the original SDK-based path.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

from .dashboard_common import (
    bangkok_now_iso,
    build_user_context,
    get_db,
    normalize_timestamp_to_bangkok,
    strip_claude_internal_tags,
    strip_leading_timestamp,
)
from .dashboard_config import (
    CLAUDE_CONTEXT_WINDOW,
    CLAUDE_MODEL,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Parse an int env var, falling back to ``default`` (with a warning) on a
    missing/blank/non-numeric value — so a malformed operator override can't
    raise ValueError at import and abort loading the default Claude backend."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Float counterpart of :func:`_env_int` — lenient, never raises at import."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to %g", name, raw, default)
        return default


# Per-conversation Claude session id. Loaded from _SESSIONS_FILE at import
# time and re-saved on every change — persistence lets us find and delete the
# right .jsonl when the user deletes a Dashboard conversation after a restart.
_CONVERSATION_SESSIONS: dict[str, str] = {}

# Background tasks for session-file cleanup (LRU eviction unlinks the
# evicted .jsonl). Pinned in a module-level set so they aren't GC'd
# before completing — the asyncio runtime only holds a weak reference
# to a task once you stop awaiting it.
_PENDING_SESSION_CLEANUPS: set[asyncio.Task[bool]] = set()


class _StaleSessionError(RuntimeError):
    """``claude -p --resume <id>`` failed because the session is stale.

    Subclass of ``RuntimeError`` so existing ``except RuntimeError`` paths
    keep working. Replaces the previous attribute-injection trick
    (``err.is_stale_session = True``) which bypassed type discipline and
    confused static analysers. Callers should ``except _StaleSessionError``
    explicitly when they want to drop the session id and retry.
    """


class _OverloadedError(RuntimeError):
    """``claude -p`` failed with a transient Anthropic-side overload/rate-limit
    (HTTP 429 or 529).

    Subclass of ``RuntimeError`` so existing ``except RuntimeError`` paths keep
    working. Callers that want to surface an actionable "servers busy, try
    again" message instead of a generic failure should ``except
    _OverloadedError`` first. We deliberately do NOT auto-retry: ``claude``
    already retries 429/529 with backoff internally before exiting non-zero, so
    an immediate re-spawn would just hit the same overloaded servers (or wait
    another long backoff).
    """


# Bound the conversation→session map so a long-running bot doesn't accumulate
# entries forever. We evict oldest insertion order on overflow.
_MAX_TRACKED_SESSIONS = 500

# Stream timeout used when ``thinking_enabled`` is set on the request. Opus
# 4.8 with ``--effort xhigh`` legitimately spends
# minutes reasoning on the Anthropic side before emitting any stdout, so the
# non-thinking 300s default fires while the API call is still in flight and
# surfaces as a spurious "Claude CLI timed out" toast. 1800s (30 min) covers
# the long tail of hard reasoning prompts; override via env if needed.
_THINKING_STREAM_TIMEOUT = max(300, _env_int("DASHBOARD_STREAM_TIMEOUT_THINKING", 1800))

# Strong refs to in-flight sidecar-persistence tasks. Without this set the
# tasks scheduled by ``_save_persisted_sessions`` are only weakly referenced
# by the event loop and can be garbage-collected mid-write — losing the
# session map on disk and orphaning the .jsonl file the user just touched.
_PERSIST_TASKS: set[asyncio.Task[None]] = set()

# The bot's own repo tree. Derived once so the default write-roots resolution
# can subtract it — the documented "repo and .env excluded" write-mode
# guarantee must hold even when the repo is cloned under Documents/Desktop/
# Downloads (where it would otherwise sit inside a default --add-dir root).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Dedicated working directory for every `claude -p` invocation. Claude Code
# logs each session as a .jsonl under `~/.claude/projects/<encoded-cwd>/`, so
# spawning from a bot-specific directory isolates Dashboard-spawned sessions
# from the user's own Claude Code session list (which uses the bot's repo
# root as CWD). Created lazily on first spawn.
_CLAUDE_CLI_WORKDIR = Path(__file__).resolve().parents[3] / "data" / "claude_cli_workdir"

# Sidecar JSON persisting {conversation_id: session_id}. Kept next to the
# workdir (not inside it — Claude Code would pick up random .jsonl-adjacent
# files in the workdir as project state).
_SESSIONS_FILE = Path(__file__).resolve().parents[3] / "data" / "claude_cli_sessions.json"

# Empty MCP config used with `--strict-mcp-config` to suppress every
# globally-enabled MCP server / plugin-bundled MCP for dashboard chats.
# Without this, the user's `~/.claude/settings.json` enabledPlugins
# (serena, playwright, chrome-devtools-mcp, …) all spawn alongside every
# turn — Serena in particular pops a web dashboard window each time,
# which is unwanted noise in the dashboard's chat-with-AI use case.
# We materialise the file lazily on first spawn so it lands next to the
# rest of the CLI sidecar state.
_EMPTY_MCP_CONFIG_FILE = Path(__file__).resolve().parents[3] / "data" / "claude_cli_empty_mcp.json"

# Write-mode guard. The PreToolUse hook script (committed next to this module)
# is registered via a generated settings file passed with --settings. Both live
# OUTSIDE every write root and outside the spawn cwd subtree, so the model can't
# overwrite the guard itself. See cli_write_guard.py for the enforcement logic.
_WRITE_GUARD_HOOK_SCRIPT = Path(__file__).resolve().parent / "cli_write_guard.py"
_WRITE_GUARD_SETTINGS_FILE = (
    Path(__file__).resolve().parents[3] / "data" / "claude_cli_write_guard_settings.json"
)

# The stable "how to read [timestamp] prefixes" instruction. Extracted to a
# constant so it can live in EITHER the prompt body (legacy) or the cacheable
# system prompt (see _build_system_prompt) without the two drifting apart.
_TIMESTAMP_CONVENTION = (
    "User messages (both historical and the current one) are prefixed "
    "with timestamps like `[2026-04-27T05:27:13+07:00]`. These are "
    "system-injected metadata indicating when each message was sent. "
    "Use them to understand elapsed time between turns — a multi-hour "
    "or multi-day gap should shape how you respond (e.g. acknowledge "
    "the user has been away). Do NOT include such timestamp prefixes "
    "in your own responses."
)

# Content-addressed system-prompt files for --append-system-prompt-file. The
# persona is stable per (preset, unrestricted), so hashing the content means a
# given persona reuses one file and the CLI sees an identical
# --append-system-prompt-file every turn — keeping Claude Code's prompt cache
# warm on the system prefix instead of re-sending the persona in the user body.
_SYSTEM_PROMPT_DIR = Path(__file__).resolve().parents[3] / "data" / "claude_cli_system_prompts"

# --- Pre-warm (speculative next-turn process) -----------------------------
# The dominant per-turn latency is the `claude -p` cold start (Node boot + CLI
# init + session load) paid BEFORE the first token. We hide it by spawning the
# *next* turn's process right after a turn finishes, booted and blocked on stdin;
# when the next turn arrives with a matching argv we just write the prompt to the
# already-booted process. Pure latency optimisation — model, prompt, and output
# are byte-identical to a cold spawn. Disable with DASHBOARD_CLI_PREWARM=0.
_PREWARM_ENABLED = os.getenv("DASHBOARD_CLI_PREWARM", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
# How long a warm process stays reusable. Kept under typical server-side session
# idle windows; a stale warm proc is killed and the turn spawns fresh.
_PREWARM_TTL = _env_float("DASHBOARD_CLI_PREWARM_TTL", 120.0)
# Cap concurrent warm processes (each ~150 MB RAM) regardless of conversation
# count — a single-user dashboard normally has 1 active conversation.
_PREWARM_MAX = max(1, _env_int("DASHBOARD_CLI_PREWARM_MAX", 3))
# conversation_id -> {"proc": Process, "argv": list[str], "created": float}
_warm_procs: dict[str, dict[str, Any]] = {}
# Strong refs to in-flight warm-spawn tasks so they aren't GC'd mid-spawn.
_PREWARM_TASKS: set[asyncio.Task[None]] = set()
# Set by shutdown_prewarm(): blocks new warm spawns and makes in-flight
# spawn tasks kill their child instead of registering it post-shutdown.
_PREWARM_SHUTDOWN = False


def _build_system_prompt(
    persona: str, *, web_enabled: bool = False, ai_tools_enabled: bool = False
) -> str:
    """The cacheable system block sent via --append-system-prompt-file.

    Persona (+ the timestamp convention) is appended to Claude Code's default
    system prompt. Putting it here instead of the per-turn user body means it
    forms a stable, prompt-cacheable prefix and gets system-level adherence
    (matching the SDK backend, which passes persona as ``system=``).

    When tools are enabled we ALSO declare them authoritatively here. Personas
    written for the old Gemini backend say things like "Google Search is
    automatically enabled" — on this Claude CLI backend that's WebSearch, and
    the model would otherwise wrongly tell users "the host hasn't enabled web
    search". This note comes AFTER the persona so it supersedes stale claims.
    """
    parts: list[str] = []
    if persona:
        parts.append(f"# Persona\n{persona}")
    parts.append(f"# Timestamp convention\n{_TIMESTAMP_CONVENTION}")

    tool_lines: list[str] = []
    if web_enabled:
        tool_lines.append(
            "- WebSearch: search the web for current, real-time, or post-training "
            "information. Use it whenever the answer depends on recent events or "
            "facts you're unsure of — do NOT claim you lack web access."
        )
        tool_lines.append("- WebFetch: fetch and read the contents of a specific URL.")
    if ai_tools_enabled:
        tool_lines.append(
            "- remember / recall_memory: save and look up long-term facts about the user."
        )
        tool_lines.append(
            "- Discord server tools (create/list channels & roles, permissions, read "
            "channels, user info): use them to act on the server when asked."
        )
    if tool_lines:
        parts.append(
            "# Available tools (this session)\n"
            "You have these tools available right now — call them directly; never say a "
            'tool is "not enabled" or that the host hasn\'t enabled it. Any persona text '
            'mentioning "Google Search" refers to WebSearch below.\n' + "\n".join(tool_lines)
        )
    return "\n\n".join(parts)


def _ensure_system_prompt_file(content: str) -> Path:
    """Write ``content`` to a content-hashed file (idempotent), return its path."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    path = _SYSTEM_PROMPT_DIR / f"sp_{digest}.txt"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically so a concurrent reader (a spawning claude) never sees
        # a half-written file.
        tmp = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
        tmp.write_text(content, encoding="utf-8")
        try:
            tmp.replace(path)
        except OSError:
            # The atomic replace failed (transient lock / AV). Clean up tmp,
            # then: if a concurrent writer already produced the content-hashed
            # destination, use it; otherwise surface the failure so the caller's
            # `except OSError` falls back to persona-in-body instead of getting
            # a path that does not exist (which would silently drop the persona).
            with contextlib.suppress(OSError):
                tmp.unlink()
            if not path.exists():
                raise
    return path


def _ensure_empty_mcp_config() -> Path:
    """Write the empty MCP config if it doesn't exist yet, return its path."""
    if not _EMPTY_MCP_CONFIG_FILE.exists():
        _EMPTY_MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _EMPTY_MCP_CONFIG_FILE.write_text('{"mcpServers": {}}', encoding="utf-8")
    return _EMPTY_MCP_CONFIG_FILE


# Our AI-tools MCP server (stdio). Spawned by claude as `bottools`; it proxies
# tool calls to the bot IPC. Stdlib-only so its stdout stays clean JSON-RPC.
_AI_TOOLS_MCP_SERVER = Path(__file__).resolve().parent / "mcp_tools_server.py"
_AI_TOOLS_MCP_CONFIG_FILE = (
    Path(__file__).resolve().parents[3] / "data" / "claude_cli_ai_tools_mcp.json"
)


def _ensure_ai_tools_mcp_config() -> Path:
    """Write (idempotently) the MCP config that registers our bottools server."""
    content = json.dumps(
        {
            "mcpServers": {
                "bottools": {
                    "command": sys.executable,
                    "args": [str(_AI_TOOLS_MCP_SERVER)],
                }
            }
        },
        ensure_ascii=False,
    )
    try:
        current = _AI_TOOLS_MCP_CONFIG_FILE.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current != content:
        _AI_TOOLS_MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _AI_TOOLS_MCP_CONFIG_FILE.write_text(content, encoding="utf-8")
    return _AI_TOOLS_MCP_CONFIG_FILE


def _ai_tool_names() -> list[str]:
    """MCP-prefixed names of the AI tools currently enabled, or [] when the
    bot IPC endpoint isn't running (so callers fall back to no custom tools)."""
    try:
        from .ai_tools_ipc import ai_tools_ipc, list_tool_schemas
    except Exception:
        return []
    if not ai_tools_ipc.ready:
        return []
    return [f"mcp__bottools__{t['name']}" for t in list_tool_schemas()]


def _ai_tools_env(
    *, guild_id: int | None = None, channel_id: int | None = None, user_id: int | None = None
) -> dict[str, str]:
    """IPC URL/token + per-turn Discord context for the spawned claude's MCP
    child. Empty when the IPC endpoint isn't ready."""
    try:
        from .ai_tools_ipc import ai_tools_ipc
    except Exception:
        return {}
    env = dict(ai_tools_ipc.env())
    if not env:
        return {}
    if guild_id is not None:
        env["BOT_AI_TOOLS_GUILD_ID"] = str(guild_id)
    if channel_id is not None:
        env["BOT_AI_TOOLS_CHANNEL_ID"] = str(channel_id)
    if user_id is not None:
        env["BOT_AI_TOOLS_USER_ID"] = str(user_id)
    return env


def _ensure_write_guard_settings() -> Path:
    """Materialise the --settings file registering the PreToolUse write guard.

    The hook command invokes the current interpreter on the committed
    ``cli_write_guard.py``. Rewritten only when the desired content changes (the
    interpreter path can move between installs), mirroring the lazy pattern of
    :func:`_ensure_empty_mcp_config`.
    """
    command = f'"{sys.executable}" "{_WRITE_GUARD_HOOK_SCRIPT}"'
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": command}],
                }
            ]
        }
    }
    content = json.dumps(settings, ensure_ascii=False, indent=2)
    try:
        current = _WRITE_GUARD_SETTINGS_FILE.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current != content:
        _WRITE_GUARD_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WRITE_GUARD_SETTINGS_FILE.write_text(content, encoding="utf-8")
    return _WRITE_GUARD_SETTINGS_FILE


def _encode_claude_project_dirname(path: Path) -> str:
    """Replicate Claude Code's path encoding for its session-log folder.

    Claude Code stores `~/.claude/projects/<encoded>/<session-id>.jsonl`
    where `<encoded>` replaces `:`, `\\`, `/`, space, and `_` with `-`:
        `c:\\Users\\ME\\BOT Discord\\data\\claude_cli_workdir`
            →  `c--Users-ME-BOT-Discord-data-claude-cli-workdir`
    We need the same encoding to locate the session file to delete —
    missing the `_` substitution silently breaks `delete_session_file()`
    so deleted dashboard conversations leave orphan .jsonl behind.
    """
    s = str(path)
    for ch in (":", "\\", "/", " ", "_"):
        s = s.replace(ch, "-")
    return s


def _claude_config_dir() -> Path:
    """The config dir the ``claude -p`` subprocess ACTUALLY uses.

    Mirrors _make_subprocess_env's decision order: an operator-set
    CLAUDE_CONFIG_DIR wins; otherwise the dedicated clean dir that the
    OAuth-token fast path redirects to; otherwise ~/.claude. Hardcoding
    ~/.claude here made every session-file cleanup a silent no-op whenever
    the env redirect was active (transcripts live under <config>/projects).

    Blank/whitespace-only CLAUDE_CONFIG_DIR is treated as unset (repo
    convention — see ai_tools_ipc._flag), matching the drop that
    _make_subprocess_env applies before its redirect gate. And the OAuth
    redirect is reported only when claude_home actually exists: if the
    spawn-time mkdir failed, the child fell back to ~/.claude, so cleanup
    must look there too.
    """
    operator_dir = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if operator_dir:
        return Path(operator_dir)
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        clean_cfg = _CLAUDE_CLI_WORKDIR / "claude_home"
        if clean_cfg.is_dir():
            return clean_cfg
    return Path.home() / ".claude"


def _claude_projects_folder() -> Path:
    """Folder where Claude Code writes .jsonl logs for our dedicated CWD."""
    return _claude_config_dir() / "projects" / _encode_claude_project_dirname(_CLAUDE_CLI_WORKDIR)


def _load_persisted_sessions() -> None:
    """Populate _CONVERSATION_SESSIONS from the sidecar JSON on import.

    Silently ignores missing/corrupt files — worst case we fail to delete
    old .jsonl files when conversations are deleted (cosmetic only).
    """
    try:
        if not _SESSIONS_FILE.exists():
            return
        raw = _SESSIONS_FILE.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Persisted Claude CLI session map is corrupt JSON; "
                "ignoring and starting with empty map (%s)",
                _SESSIONS_FILE,
            )
            return
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                _CONVERSATION_SESSIONS[k] = v
    except Exception:
        logger.exception("Failed to load persisted Claude CLI session map")


def _save_persisted_sessions_sync() -> None:
    """Atomically rewrite the sidecar JSON (blocking)."""
    try:
        _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Per-call unique temp filename — on Windows two writers racing on
        # the same `.tmp` path collide because the loser's open handle
        # blocks the winner's `replace()`. uuid4 keeps each writer's
        # temp file distinct.
        tmp = _SESSIONS_FILE.with_suffix(f".json.tmp.{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(_CONVERSATION_SESSIONS, indent=2), encoding="utf-8")
        tmp.replace(_SESSIONS_FILE)
    except Exception:
        logger.exception("Failed to save Claude CLI session map")


def _save_persisted_sessions() -> None:
    """Persist the sidecar JSON.

    When we have a running event loop (the common case — _track_session is
    invoked from the chat handler on the bot loop), dispatch the disk I/O
    to a worker thread so an mkdir + write_text + replace doesn't stall the
    event loop on Windows where file-lock contention is stricter. If no
    loop is running (CLI invocation, tests, shutdown path), fall back to
    a direct synchronous write.

    Failure is non-fatal — persistence is a nice-to-have, not critical.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _save_persisted_sessions_sync()
        return
    # Snapshot the dict under no-await window so the worker writes a stable
    # copy even if more updates land while it's running.
    snapshot = dict(_CONVERSATION_SESSIONS)

    def _write_snapshot(payload: dict[str, str]) -> None:
        try:
            _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Per-call unique temp filename so concurrent persist tasks
            # (track + delete in quick succession) don't collide on the
            # same .tmp path under Windows file-locking.
            tmp = _SESSIONS_FILE.with_suffix(f".json.tmp.{uuid.uuid4().hex}")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(_SESSIONS_FILE)
        except Exception:
            logger.exception("Failed to save Claude CLI session map")

    task = loop.create_task(asyncio.to_thread(_write_snapshot, snapshot))
    _PERSIST_TASKS.add(task)
    task.add_done_callback(_PERSIST_TASKS.discard)


# Must start with an alphanumeric: a session id beginning with '-' would be
# parsed as a CLI flag by ``claude --resume <id>`` (argv injection). The rest
# of the id is the usual UUID/hex+hyphen alphabet. Also blocks path-traversal
# chars on the delete path (no '/', '\', '.').
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


async def _unlink_session_file_by_id(session_id: str | None) -> bool:
    """Validate + unlink a Claude CLI session ``.jsonl`` by its session id.

    Shared by delete_session_file (which looks the id up from the conversation
    map first) and the LRU-eviction path (which already popped the map entry and
    holds the id, so it must NOT rely on a second lookup — that re-pop returning
    None was the bug that orphaned evicted session files).
    """
    if not session_id:
        return False
    # Defense-in-depth: refuse anything that doesn't look like the UUID/hex
    # session id we stored. Prevents path traversal if persisted JSON is ever
    # tampered with (e.g. session_id == "../../../something").
    if not _SESSION_ID_PATTERN.match(session_id):
        logger.warning("Refusing to delete session file with suspicious id %r", session_id)
        return False
    try:
        target = _claude_projects_folder() / f"{session_id}.jsonl"
        if target.exists():
            await asyncio.to_thread(target.unlink, missing_ok=True)
            return True
    except Exception:
        logger.exception("Failed to delete session file with id %s", session_id)
    return False


async def delete_session_file(conversation_id: str) -> bool:
    """Remove the Claude Code .jsonl for a dashboard conversation.

    Called from the delete-conversation handler so the CLI session log
    doesn't linger after the user deletes the chat in the dashboard.
    Returns True if a file was actually deleted.
    """
    # Wait for any in-flight track-saves so this delete's save is the
    # last write to land — otherwise an older snapshot containing this
    # conv would overwrite our deletion.
    if _PERSIST_TASKS:
        await asyncio.gather(*_PERSIST_TASKS, return_exceptions=True)
    session_id = _CONVERSATION_SESSIONS.pop(conversation_id, None)
    _save_persisted_sessions()
    # Wait for our own save to land before returning so the test (and any
    # caller relying on disk state) sees the deletion reflected.
    if _PERSIST_TASKS:
        await asyncio.gather(*_PERSIST_TASKS, return_exceptions=True)
    deleted = await _unlink_session_file_by_id(session_id)
    if deleted:
        logger.info("Deleted Claude CLI session file for conv %s", conversation_id)
    return deleted


# Load persisted state once at import so sync-delete works across restarts.
_load_persisted_sessions()

# Per-conversation lock: serializes outbound CLI calls so two messages in the
# SAME conversation can't spawn parallel `claude -p` processes that both try
# to --resume the same session id (which would either race on the server side
# or corrupt the session ordering). Different conversations remain parallel
# — the lock is keyed by conversation_id, not global. Cleaned up alongside
# session ids when a conversation is reset/deleted.
_CONVERSATION_LOCKS: dict[str, asyncio.Lock] = {}
_MAX_TRACKED_LOCKS = 500  # cap parallel to _MAX_TRACKED_SESSIONS


def _get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    """Return (creating if needed) the per-conversation send lock.

    Bound the dict size on insert: a long-running bot that sees thousands of
    distinct conversation ids would otherwise leak Lock objects forever — the
    sessions dict has the same cap (_MAX_TRACKED_SESSIONS), which is a
    natural reference point. Eviction picks the oldest unheld lock so we
    never yank one out from under an in-flight subprocess.
    """
    lock = _CONVERSATION_LOCKS.get(conversation_id)
    if lock is not None:
        return lock
    if len(_CONVERSATION_LOCKS) >= _MAX_TRACKED_LOCKS:
        # Pop a candidate, re-check while holding the outer dict access; if a
        # racing coroutine acquired it between checks, put it back and try
        # the next candidate. Bound iterations so we never spin.
        attempts = 0
        for old_id, old_lock in list(_CONVERSATION_LOCKS.items()):
            if attempts >= 10:
                break
            attempts += 1
            # ``locked()`` alone is NOT enough: right after release() wakes a
            # waiter, locked() reads False while the waiter is still pending
            # resume — evicting then hands the next caller a brand-new Lock
            # and two `claude -p --resume` runs race on the same session
            # (exactly what this lock exists to prevent). Treat a lock with
            # queued waiters as held.
            if old_lock.locked() or getattr(old_lock, "_waiters", None):
                continue
            # asyncio is single-threaded and no await happens between the
            # items() snapshot and pop(), so pop() always succeeds here.
            popped = _CONVERSATION_LOCKS.pop(old_id)
            if popped.locked() or getattr(popped, "_waiters", None):
                # Defensive: lock state could change if a coroutine
                # acquired it during dict iteration in the same step.
                # Put it back and try another.
                _CONVERSATION_LOCKS[old_id] = popped
                continue
            break
    lock = asyncio.Lock()
    _CONVERSATION_LOCKS[conversation_id] = lock
    return lock


# Where to drop temp image files Claude reads via the Read tool.
_TEMP_IMAGE_ROOT = Path(__file__).resolve().parents[3] / "data" / "tmp" / "dashboard_cli_images"

# Where to drop non-image attachments (PDFs, text, code) — Claude Code reads
# them via its Read tool the same way it reads images. Kept separate from
# _TEMP_IMAGE_ROOT for easier cleanup + debugging, but both directories are
# safe to nuke at any time (files are regenerated on the next turn if needed).
_TEMP_DOCS_ROOT = Path(__file__).resolve().parents[3] / "data" / "tmp" / "dashboard_cli_docs"

# Allowed image MIME types — must match what the SDK backend accepts so users
# don't get inconsistent behavior across the toggle.
_SUPPORTED_IMAGE_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# Safe extensions for document attachments. Binary (.pdf/.docx) is written
# from base64; everything else is treated as UTF-8 text. Frontend whitelist
# in document-attach.ts should stay synchronised.
_SUPPORTED_DOC_BINARY_EXT = {".pdf", ".docx"}
_SUPPORTED_DOC_TEXT_EXT = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    # NOTE: .env intentionally excluded — uploading .env files combined with
    # the CLI's Read-tool capability lets a malicious frontend exfiltrate
    # secrets via the AI response.
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".conf",
    ".cfg",
    ".csv",
    ".tsv",
    ".xml",
    ".log",
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".scala",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".hxx",
    ".cs",
    ".rb",
    ".php",
    ".pl",
    ".r",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".vue",
    ".svelte",
    ".sql",
    ".graphql",
    ".gql",
}


def _resolve_claude_executable() -> str | None:
    """Return absolute path to the `claude` CLI, or None if not on PATH."""
    return shutil.which("claude")


def is_cli_backend_ready() -> tuple[bool, str]:
    """Pre-flight check used by the WS server to decide if CLI mode is usable.

    Returns ``(ok, reason)``. The CLI subprocess picks up OAuth credentials
    saved by an interactive `claude` login automatically, so we don't require
    CLAUDE_CODE_OAUTH_TOKEN here — only the binary's presence on PATH.
    If auth turns out to be missing at runtime, the subprocess emits an auth
    error which we forward to the user.
    """
    if not _resolve_claude_executable():
        return False, "`claude` CLI not found on PATH. Install Claude Code first."
    return True, ""


def _track_session(conversation_id: str, session_id: str) -> None:
    """Remember the Claude session so subsequent turns can ``--resume`` it.

    Also moves the conversation to the back of the eviction queue so an
    actively-chatted conversation isn't evicted just because it was started
    long ago — fixes a stale-LRU bug where re-assigning the same key kept its
    original insertion position.
    """
    if not conversation_id or not session_id:
        return
    # Validate at the source. A session id that doesn't match the strict
    # pattern (e.g. one starting with '-') would be parsed as a flag when we
    # later run ``claude --resume <id>`` (argv injection), or could escape the
    # projects folder on the delete path. Refuse to track it.
    if not _SESSION_ID_PATTERN.match(session_id):
        logger.warning("Refusing to track Claude session with suspicious id %r", session_id)
        return
    # Pop first (if present) so the re-insert below puts the entry at the
    # end of insertion order. Without this, dict[key] = value keeps the
    # original position and a long-active conversation would be evicted
    # ahead of recently-touched ones.
    old_session = _CONVERSATION_SESSIONS.pop(conversation_id, None)
    # Breadcrumb for resumed-session debugging: every turn advances the id,
    # so without this the old→new chain is unreconstructable from bot.log.
    logger.debug(
        "claude session transition conv=%s %s -> %s",
        conversation_id,
        (old_session or "none")[:8],
        session_id[:8],
    )
    if old_session and old_session != session_id:
        # Every resumed turn yields a NEW session id, so the PREVIOUS turn's
        # .jsonl becomes unreachable by every cleanup path (they only know
        # the latest id) — one orphaned transcript per turn. Unlink it the
        # same pinned-background-task way the LRU eviction below does.
        with contextlib.suppress(RuntimeError):
            loop = asyncio.get_running_loop()
            stale_task = loop.create_task(_unlink_session_file_by_id(old_session))
            _PENDING_SESSION_CLEANUPS.add(stale_task)
            stale_task.add_done_callback(_PENDING_SESSION_CLEANUPS.discard)
    if len(_CONVERSATION_SESSIONS) >= _MAX_TRACKED_SESSIONS:
        oldest_conv = next(iter(_CONVERSATION_SESSIONS))
        oldest_session = _CONVERSATION_SESSIONS.pop(oldest_conv, None)
        # Also unlink the on-disk ``.jsonl`` for the evicted session, BY ITS
        # already-captured session id. We must not route through
        # delete_session_file here: it re-pops the conversation map, but we
        # already popped this entry above, so the re-pop returns None and the
        # file would never be deleted (the disk leak). Schedule the unlink as a
        # background task pinned to a module-level set so it isn't GC'd before
        # completing.
        if oldest_session:
            with contextlib.suppress(RuntimeError):
                # ``get_event_loop_policy().get_event_loop()`` is deprecated in
                # 3.12+ and slated for removal in 3.14. ``get_running_loop`` is
                # the right call here because the LRU-eviction path is reached
                # only from inside the running async session-tracker.
                loop = asyncio.get_running_loop()
                cleanup_task = loop.create_task(_unlink_session_file_by_id(oldest_session))
                _PENDING_SESSION_CLEANUPS.add(cleanup_task)
                cleanup_task.add_done_callback(_PENDING_SESSION_CLEANUPS.discard)
    _CONVERSATION_SESSIONS[conversation_id] = session_id
    _save_persisted_sessions()


def reset_session(conversation_id: str) -> None:
    """Forget the Claude session for a conversation (e.g. after a reload).

    Exposed so the WS server can call this when the user loads a conversation
    fresh from the database — the in-memory session would be stale relative
    to the DB-loaded message list. Also drops the per-conversation send lock
    so it doesn't accumulate forever in a long-running bot.
    """
    popped = _CONVERSATION_SESSIONS.pop(conversation_id, None)
    if popped is not None:
        _save_persisted_sessions()
        # The forgotten session's .jsonl is now unreachable by every cleanup
        # path (per-turn unlink, LRU eviction, delete_session_file all key off
        # the latest tracked id) — one orphaned transcript per reset. Unlink it
        # the same pinned-background-task way _track_session does. Best-effort
        # and non-blocking: with no running loop (sync tests, shutdown) we just
        # skip the unlink, and _unlink_session_file_by_id itself never raises.
        with contextlib.suppress(RuntimeError):
            loop = asyncio.get_running_loop()
            task = loop.create_task(_unlink_session_file_by_id(popped))
            _PENDING_SESSION_CLEANUPS.add(task)
            task.add_done_callback(_PENDING_SESSION_CLEANUPS.discard)
    # Only drop the lock if it's not currently held AND nobody is queued on
    # it. ``locked()`` alone misses the release→waiter-resume window (locked()
    # reads False while a waiter is still pending), and popping then gives
    # the next caller a fresh Lock — two --resume runs racing the session.
    lock = _CONVERSATION_LOCKS.get(conversation_id)
    if lock is not None and not lock.locked() and not getattr(lock, "_waiters", None):
        _CONVERSATION_LOCKS.pop(conversation_id, None)


def _save_inline_images(
    conversation_id: str,
    images: list[Any],
    max_size_bytes: int,
) -> list[Path]:
    """Decode dashboard image payloads and write them to a temp dir.

    Returns the list of paths written. The dashboard sends each image as a
    ``data:<mime>;base64,<payload>`` URL string; entries that aren't strings,
    aren't a supported image type, or exceed ``max_size_bytes`` after decoding
    are skipped quietly so a single bad attachment doesn't kill the request.
    """
    if not images or not conversation_id:
        return []

    # conversation_id is pre-validated against ``^[a-zA-Z0-9_\-]{1,128}$``
    # at the WS handler entry — only the length cap is meaningful here.
    safe_conv = conversation_id[:64]
    target_dir = _TEMP_IMAGE_ROOT / safe_conv
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    timestamp = int(time.time() * 1000)
    # Random suffix prevents filename collision when two parallel uploads
    # in the same conversation hit the same millisecond and the same
    # ``idx``. The previous ``{timestamp}_{idx}{ext}`` scheme could
    # silently overwrite the first file with the second's bytes if
    # _save_inline_images was called twice concurrently for the same
    # conversation_id — Python's GIL doesn't help because the writes
    # happen inside ``asyncio.to_thread`` workers.
    rand_suffix = secrets.token_hex(4)
    for idx, raw in enumerate(images):
        if not isinstance(raw, str) or "," not in raw or not raw.startswith("data:"):
            continue
        header, _, payload = raw.partition(",")
        # header looks like "data:image/png;base64"
        match = re.match(r"data:([\w/+.\-]+);base64", header)
        if not match:
            continue
        mime = match.group(1).lower()
        ext = _SUPPORTED_IMAGE_MIME.get(mime)
        if not ext:
            continue
        try:
            data = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error):
            continue
        # Enforce per-image size cap to mirror the SDK backend's safety net.
        # Without this an attacker (or a misclick) could push a 100 MB image
        # through and balloon both disk usage and Claude's input cost.
        if len(data) > max_size_bytes:
            logger.warning(
                "Dropping oversized image attachment (%d bytes > %d cap)",
                len(data),
                max_size_bytes,
            )
            continue
        path = target_dir / f"{timestamp}_{rand_suffix}_{idx}{ext}"
        path.write_bytes(data)
        written.append(path)
    return written


def _cleanup_image_dir(conversation_id: str) -> None:
    """Best-effort cleanup of the per-conversation temp image dir.

    Skips files newer than 60 seconds so a concurrent next-turn that just
    wrote fresh attachments doesn't get its files yanked mid-flight.
    """
    if not conversation_id:
        return
    # conversation_id is pre-validated; only length cap is needed.
    safe_conv = conversation_id[:64]
    target_dir = _TEMP_IMAGE_ROOT / safe_conv
    cutoff = time.time() - 60
    with contextlib.suppress(Exception):
        if target_dir.exists():
            remaining = 0
            for p in target_dir.iterdir():
                try:
                    if p.stat().st_mtime > cutoff:
                        remaining += 1
                        continue
                except Exception:
                    remaining += 1
                    continue
                with contextlib.suppress(Exception):
                    p.unlink()
            if remaining == 0:
                with contextlib.suppress(Exception):
                    target_dir.rmdir()


def _save_inline_documents(
    conversation_id: str,
    documents: list[Any],
    max_size_bytes: int,
) -> list[Path]:
    """Decode dashboard document payloads (PDF / text / code) to a temp dir.

    Payload shape from the frontend's DocumentAttachManager::
        {name, mime, kind: 'binary'|'text', data, size_bytes}

    Binary kind: ``data`` is a ``data:<mime>;base64,...`` URL — decoded and
    written as bytes.

    Text kind: ``data`` is a decoded UTF-8 string — written directly.

    Files with unsafe extensions (anything outside the allowlist) are
    silently skipped so a compromised frontend can't push ``.exe`` / ``.bat``
    into a directory Claude's Read tool later points at.
    """
    if not documents or not conversation_id:
        return []

    # conversation_id is pre-validated; only length cap is needed.
    safe_conv = conversation_id[:64]
    target_dir = _TEMP_DOCS_ROOT / safe_conv
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    timestamp = int(time.time() * 1000)
    # Mirror the per-call random suffix used by ``_save_inline_images`` so
    # two concurrent uploads in the same conversation at the same
    # millisecond can't collide on the same filename. The previous
    # ``{timestamp}_{idx}_{safe_name}`` scheme depended on the millisecond
    # clock being unique enough; under load that's not a safe assumption.
    rand_suffix = secrets.token_hex(4)
    for idx, raw in enumerate(documents):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", ""))[:200]
        kind = raw.get("kind")
        data_field = raw.get("data")
        if not name or not isinstance(data_field, str):
            continue

        # Derive a safe extension from the filename. We do NOT trust the
        # caller's `mime` field for routing — extension is a stronger signal
        # (the browser sometimes lies about MIME for niche files).
        ext_match = re.search(r"\.[A-Za-z0-9]+$", name)
        ext = ext_match.group(0).lower() if ext_match else ""

        is_binary_ext = ext in _SUPPORTED_DOC_BINARY_EXT
        is_text_ext = ext in _SUPPORTED_DOC_TEXT_EXT
        if not (is_binary_ext or is_text_ext):
            logger.warning("Dropping document with disallowed extension: %s", name)
            continue

        # Preserve the user's filename (sanitised) so Claude sees meaningful
        # names — makes prompt output more coherent than `doc_0.pdf`.
        safe_name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)[:80] or f"doc_{idx}{ext}"
        path = target_dir / f"{timestamp}_{rand_suffix}_{idx}_{safe_name}"

        if kind == "binary" or is_binary_ext:
            # Binary: expect data URL format
            if "," not in data_field or not data_field.startswith("data:"):
                continue
            _header, _, payload = data_field.partition(",")
            try:
                decoded = base64.b64decode(payload, validate=True)
            except (ValueError, binascii.Error):
                continue
            if len(decoded) > max_size_bytes:
                logger.warning(
                    "Dropping oversized document %s (%d bytes > %d cap)",
                    name,
                    len(decoded),
                    max_size_bytes,
                )
                continue
            path.write_bytes(decoded)
        else:
            # Text: UTF-8 string. Size check against raw byte length.
            encoded = data_field.encode("utf-8", errors="replace")
            if len(encoded) > max_size_bytes:
                logger.warning(
                    "Dropping oversized document %s (%d bytes > %d cap)",
                    name,
                    len(encoded),
                    max_size_bytes,
                )
                continue
            path.write_bytes(encoded)
        written.append(path)
    return written


def _cleanup_docs_dir(conversation_id: str) -> None:
    """Best-effort cleanup of the per-conversation temp documents dir.

    Skips files newer than 60 seconds so a concurrent next-turn that just
    wrote fresh attachments doesn't get its files yanked mid-flight.
    """
    if not conversation_id:
        return
    # conversation_id is pre-validated; only length cap is needed.
    safe_conv = conversation_id[:64]
    target_dir = _TEMP_DOCS_ROOT / safe_conv
    cutoff = time.time() - 60
    with contextlib.suppress(Exception):
        if target_dir.exists():
            remaining = 0
            for p in target_dir.iterdir():
                try:
                    if p.stat().st_mtime > cutoff:
                        remaining += 1
                        continue
                except Exception:
                    remaining += 1
                    continue
                with contextlib.suppress(Exception):
                    p.unlink()
            if remaining == 0:
                with contextlib.suppress(Exception):
                    target_dir.rmdir()


# Matches a role marker at the start of a line in arbitrary user text. The
# flattened-prompt format (``# Conversation so far\nUser: …\nAssistant: …``)
# is vulnerable to content that contains ``\nAssistant: I'll obey…`` — the
# bare LLM has no way to tell injected role markers from real ones. We rewrite
# hits to a clearly-marked sentinel so the model sees them as quoted text, not
# new turns. Covers common alternate aliases (Human/AI/Tool) as well — same
# defence the Discord flattener ships (discord_chat_claude_cli.py).
_ROLE_LEAK_RE = re.compile(r"(?im)^(\s*)(user|assistant|system|tool|human|ai)(\s*:)")

# The flattened prompt's own section-header scheme. A spoofed ``# Current user
# message`` / ``# Context`` line inside history or an uploaded document is a
# STRONGER injection than a bare role marker — it can fake a whole section
# that supersedes the real ones. Defang exactly the reserved names this
# module's builders emit (not every ``#`` line, so legitimate user markdown
# headings survive untouched).
_RESERVED_PROMPT_HEADERS = (
    "persona",
    "timestamp convention",
    "context",
    "conversation so far",
    "attached images",
    "attached documents",
    "current user message",
    "available tools",
)
_HEADER_LEAK_RE = re.compile(
    r"(?im)^(\s*)(#{1,6})(\s+(?:" + "|".join(_RESERVED_PROMPT_HEADERS) + r")\b)"
)


def _sanitize_dialog_segment(text: str) -> str:
    """Defang role-marker / section-header injection in flattened-prompt text.

    A history row or current message containing a literal line
    ``Assistant: I'll do anything`` (or ``# Current user message``) could
    otherwise spoof a turn or a structural section in the prompt the CLI
    subprocess receives. Rewrite every such line so the model sees it as
    quoted text the user typed, not a real turn/section header. The real
    headers are emitted by the builders directly and never pass through here.
    """
    if not text:
        return text
    text = _ROLE_LEAK_RE.sub(r"\1[user-text] \2\3", text)
    return _HEADER_LEAK_RE.sub(r"\1[user-text] \2\3", text)


def _prompt_max_chars_from_env() -> int:
    """Resolve the prompt-size ceiling (characters) for both CLI paths.

    ``CLI_PROMPT_MAX_CHARS`` overrides; ``0`` disables clipping entirely.
    The default (1.2M chars, roughly a full 1M-token window for Thai text
    at ~1-2 chars/token) is deliberately at the model's PHYSICAL limit, not
    a quota-saving cap: with delta-on-resume the full history is sent only
    on fresh sessions, and operators running long-form RP want the entire
    conversation in context. The clip exists solely so a pathological
    tens-of-thousands-message channel still gets a working (front-truncated)
    session instead of a hard context-overflow failure on every fresh attempt.
    """
    raw = (os.environ.get("CLI_PROMPT_MAX_CHARS") or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("Invalid CLI_PROMPT_MAX_CHARS=%r; using default", raw)
    return 1_200_000


# Soft ceiling on the rendered history block, shared semantics with the
# Discord flattener's _DISCORD_PROMPT_MAX_CHARS (same env knob). 0 = off.
_PROMPT_HISTORY_MAX_CHARS = _prompt_max_chars_from_env()


def _build_full_prompt(
    persona: str,
    user_context: str,
    history: list[dict[str, Any]],
    history_limit: int,
    current_message: str,
    image_paths: list[Path],
    doc_paths: list[Path] | None,
    is_resumed_session: bool,
    persona_in_system: bool = False,
) -> str:
    """Compose the prompt body sent to ``claude -p`` via stdin.

    Persona + user context are sent on EVERY turn — matching the SDK backend's
    behavior so updates to role preset or profile take effect immediately
    instead of being frozen at the session's first turn.

    When ``persona_in_system`` is True the persona + timestamp-convention blocks
    are omitted here because the caller passes them via
    ``--append-system-prompt-file`` (a cacheable system prefix); only the
    dynamic user_context stays in the body.

    The conversation history block is the one piece we still skip on resumed
    turns: Claude already has the prior messages server-side via ``--resume``,
    and re-injecting them here would make the model see the same exchange
    twice (once in the session log, once in the prompt body).
    """
    parts: list[str] = []

    if not persona_in_system:
        parts.append(f"# Persona\n{persona}")
        parts.append(f"# Timestamp convention\n{_TIMESTAMP_CONVENTION}")
    if user_context:
        parts.append(f"# Context\n{user_context}")
    if not is_resumed_session:
        history_block = _build_history_block(history, history_limit)
        if history_block:
            parts.append(f"# Conversation so far\n{history_block}")

    # Use absolute POSIX-style paths so Claude's Read tool can locate files
    # outside its CWD. The subprocess runs from `data/claude_cli_workdir/`,
    # but attachments live under `data/tmp/dashboard_cli_*/<conv>/`. Passing
    # only the basename (a previous regression) made Read fail with ENOENT
    # and the model fell back to "I can't see the image".
    if image_paths:
        path_lines = "\n".join(f"- {Path(p).resolve().as_posix()}" for p in image_paths)
        parts.append(
            "# Attached images\n"
            "The user attached the following image file(s). Use the Read tool "
            "to view them as needed before answering.\n"
            f"{path_lines}"
        )

    if doc_paths:
        doc_lines = "\n".join(f"- {Path(p).resolve().as_posix()}" for p in doc_paths)
        parts.append(
            "# Attached documents\n"
            "The user attached the following document file(s) (PDF, text, code, "
            "markdown, etc.). Use the Read tool to view their contents as needed "
            "before answering. PDFs are parsed natively — you can see both text "
            "and any embedded images.\n"
            f"{doc_lines}"
        )

    # Inject the timestamp inline so Claude knows when the message was sent
    # (matches the SDK backend's behavior). The DB stores the raw content,
    # so this prefix never reaches the dashboard UI. Sanitized so a pasted
    # "Assistant:" line or spoofed section header can't fake a turn boundary.
    timestamp = bangkok_now_iso()
    parts.append(
        f"# Current user message\n[{timestamp}] {_sanitize_dialog_segment(current_message)}"
    )
    return "\n\n".join(parts)


def _build_history_block(history: list[dict[str, Any]], limit: int) -> str:
    """Render at most ``limit`` recent messages as plain text.

    Each message gets a ``[ISO-timestamp]`` prefix when ``created_at`` is
    present, so the model can perceive elapsed time between turns. Without
    this, a multi-hour gap between messages reads to Claude as "just now"
    and it answers as if the user only paused for a few minutes.
    """
    if not history:
        return ""
    recent = history[-limit:]
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "user")
        # Sanitize each row: history contains assistant replies that can quote
        # poisoned document/web content, and a raw "User:"/"# Context" line in
        # there would spoof a turn or section in the flattened recap.
        text = _sanitize_dialog_segment(str(msg.get("content", "")))
        speaker = "User" if role == "user" else "Assistant"
        created_at = msg.get("created_at")
        if created_at:
            ts = normalize_timestamp_to_bangkok(created_at)
            lines.append(f"{speaker}: [{ts}] {text}")
        else:
            lines.append(f"{speaker}: {text}")
    block = "\n".join(lines)
    if _PROMPT_HISTORY_MAX_CHARS and len(block) > _PROMPT_HISTORY_MAX_CHARS:
        # Front-truncate (keep the newest turns) the same way the Discord
        # flattener clamps its history section — the persona/system file,
        # user_context, and current message are untouched and individually
        # bounded already. INFO so an operator can see it from bot.log
        # instead of only inferring it from latency.
        logger.info(
            "History block truncated for prompt budget (%d > %d chars)",
            len(block),
            _PROMPT_HISTORY_MAX_CHARS,
        )
        block = "[...older context truncated...]\n" + block[-_PROMPT_HISTORY_MAX_CHARS:]
    return block


def _make_subprocess_env() -> dict[str, str]:
    """Build the env for the `claude` subprocess using a strict allowlist.

    Why allowlist (not blocklist): the CLI is given Read tool access. If a
    malicious frontend or a prompt-injected document tells Claude to read
    `~/.env` / `~/.config/...`, every secret in the parent process env
    would be exposed via the AI response. The previous blocklist only
    stripped ANTHROPIC_*; DISCORD_TOKEN, SPOTIFY_CLIENT_SECRET,
    DASHBOARD_WS_TOKEN, etc. remained inheritable.
    """
    # Variables `claude` (and its OS launcher) genuinely needs to function.
    # ANTHROPIC_API_KEY is intentionally omitted — leaving it would override
    # the subscription OAuth token and route through per-token billing.
    _ALLOWED_ENV_KEYS = {
        # OS / launcher fundamentals
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "HOME",
        "USERPROFILE",
        "USERNAME",
        "USER",
        "LOGNAME",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LANGUAGE",
        "TZ",
        # Claude-CLI specific (auth + telemetry opt-out). The documented
        # opt-out names are DISABLE_TELEMETRY and
        # CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC — the allowlist previously
        # passed only the nonexistent CLAUDE_DISABLE_TELEMETRY, silently
        # stripping an operator's real opt-out from the subprocess env.
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_DISABLE_TELEMETRY",
        "DISABLE_TELEMETRY",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        # Node runtime tuning (claude binary is Node-based)
        "NODE_OPTIONS",
        "NPM_CONFIG_PREFIX",
        # Proxy plumbing (operator may need these to reach Anthropic)
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
    env = {k: v for k, v in os.environ.items() if k in _ALLOWED_ENV_KEYS}
    # ``NODE_OPTIONS`` is allowlisted because the claude binary is Node-based
    # and an operator may need to bump --max-old-space-size, but the same
    # var also accepts ``--require ./malicious.js`` and
    # ``--inspect=...:9229``. If an attacker ever gets parent env-write
    # access (high bar), they could pivot through claude. Filter the
    # value to a known-safe subset of flags.
    if "NODE_OPTIONS" in env:
        # Value-bearing flags match by prefix (the value follows "="); the
        # valueless flag must match EXACTLY so a look-alike like
        # "--use-openssl-cafile=/x" can't slip through a loose prefix check.
        _SAFE_NODE_PREFIXES = ("--max-old-space-size=", "--max_old_space_size=")
        _SAFE_NODE_EXACT = {"--use-openssl-ca"}
        tokens = env["NODE_OPTIONS"].split()
        filtered = [
            t
            for t in tokens
            if t in _SAFE_NODE_EXACT or any(t.startswith(p) for p in _SAFE_NODE_PREFIXES)
        ]
        if filtered:
            env["NODE_OPTIONS"] = " ".join(filtered)
        else:
            env.pop("NODE_OPTIONS", None)

    # --- Boot-latency reductions (see docs/reviews CLI-perf investigation) ---
    # Force-disable Claude Code's non-essential boot-time network traffic:
    # the auto-update check, Statsig telemetry, Sentry error reporting, and the
    # bug/feedback pings. Each is an outbound round-trip on EVERY `claude -p`
    # boot — pure latency for a chat backend that spawns claude per turn, for
    # zero benefit. CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC bundles
    # DISABLE_AUTOUPDATER + DISABLE_TELEMETRY + DISABLE_ERROR_REPORTING +
    # DISABLE_BUG_COMMAND. We SET it (not just allowlist it) so the speedup
    # doesn't depend on operator configuration.
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    # A set-but-blank CLAUDE_CONFIG_DIR means "unset" (repo convention — see
    # ai_tools_ipc._flag): the Node CLI treats "" as absent and falls back to
    # ~/.claude, but the membership gate below would see the var as present
    # and skip the claude_home redirect — desyncing _claude_config_dir() from
    # the dir the child actually uses, so every transcript cleanup no-ops.
    # Drop it so both functions resolve identically.
    if not env.get("CLAUDE_CONFIG_DIR", "x").strip():
        env.pop("CLAUDE_CONFIG_DIR", None)

    # When an explicit OAuth token is available, point CLAUDE_CONFIG_DIR at a
    # dedicated minimal config dir for the bot. That skips loading the operator's
    # global ~/.claude settings.json — hooks, enabledPlugins, LSP servers — which
    # otherwise load on every spawn and are the bulk of the cold start. Auth
    # comes from the token, so the absent credentials.json in the clean dir is
    # fine. Gated on the token AND on the operator NOT having set their own
    # CLAUDE_CONFIG_DIR, so saved-credential (interactive-login) auth and any
    # deliberate operator override both keep working untouched.
    if env.get("CLAUDE_CODE_OAUTH_TOKEN") and "CLAUDE_CONFIG_DIR" not in env:
        _clean_cfg = _CLAUDE_CLI_WORKDIR / "claude_home"
        with contextlib.suppress(OSError):
            _clean_cfg.mkdir(parents=True, exist_ok=True)
            env["CLAUDE_CONFIG_DIR"] = str(_clean_cfg)

    # Hand the resolved write roots to the PreToolUse write-guard hook, which
    # runs as a child of this subprocess and inherits this env. The hook denies
    # any Write/Edit whose canonical path is outside these roots (it fails closed
    # if the var is absent). Set only when write mode is enabled and roots
    # resolve; harmless when no --settings guard is attached to the argv.
    if _dashboard_cli_write_enabled():
        _write_roots = _dashboard_cli_write_dirs()
        if _write_roots:
            env["DASHBOARD_CLI_WRITE_DIRS_RESOLVED"] = os.pathsep.join(
                str(r.resolve()) for r in _write_roots
            )
    return env


def _dashboard_cli_write_enabled() -> bool:
    """True when the operator opted the CLI backend into autonomous file writes.

    Gated by ``DASHBOARD_CLI_ALLOW_WRITE`` (default off). When off, the embedded
    ``claude -p`` stays a pure-chat process pinned to ``--permission-mode
    default`` with no write tools — the hardened default. When on, the main chat
    turn may create/edit files non-interactively (see :func:`_build_claude_argv`)
    so the dashboard chat UI — which has no way to answer an interactive
    "Allow?" prompt — can fulfil "write this file for me" requests.
    """
    return os.getenv("DASHBOARD_CLI_ALLOW_WRITE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _dashboard_cli_write_dirs() -> list[Path]:
    """Resolve the directories CLI write-mode may write into without prompting.

    ``DASHBOARD_CLI_WRITE_DIRS`` (``os.pathsep``-separated) overrides the
    default, which is the user's Desktop / Documents / Downloads — plus the
    OneDrive-redirected Desktop/Documents on Windows, where those known folders
    are frequently relocated under OneDrive. Only directories that actually
    exist are returned (``--add-dir`` on a missing path is pointless).

    Sensitive locations — the repo, ``~/.ssh``, ``~/.claude``, and the home root
    itself — are deliberately NOT included, so even under ``acceptEdits`` an
    injected upload cannot auto-overwrite credentials or config: a write there
    falls outside every ``--add-dir`` root, hits a permission prompt with no TTY
    to answer it, and is therefore denied.
    """
    raw = os.getenv("DASHBOARD_CLI_WRITE_DIRS", "").strip()
    using_defaults = not raw
    if raw:
        candidates = [Path(p.strip()).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    else:
        home = Path.home()
        candidates = [home / "Desktop", home / "Documents", home / "Downloads"]
        # Windows env lookups are case-insensitive, so the uppercase form still
        # resolves the real mixed-case "OneDrive" / "OneDriveConsumer" vars.
        onedrive = os.getenv("ONEDRIVE") or os.getenv("ONEDRIVECONSUMER")
        if onedrive:
            od = Path(onedrive)
            candidates += [od / "Desktop", od / "Documents"]
    # Locations the default roots must never enclose (or sit inside): the bot's
    # own tree carries .env, the source, AND the write-guard script itself — a
    # repo cloned under ~/Documents would otherwise land all of them inside an
    # auto-approved --add-dir root. An explicit DASHBOARD_CLI_WRITE_DIRS
    # override is honoured as-is (the guard-side denylist in cli_write_guard.py
    # still protects the repo subtree authoritatively); the DEFAULTS must be
    # safe out of the box. These module constants are already resolve()d.
    sensitive = (_REPO_ROOT, _CLAUDE_CLI_WORKDIR, _WRITE_GUARD_HOOK_SCRIPT.parent)
    # De-dupe by resolved path while preserving order; keep only real dirs.
    seen: set[str] = set()
    roots: list[Path] = []
    for cand in candidates:
        try:
            resolved = cand.resolve()
            key = str(resolved)
        except OSError:
            resolved = cand
            key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if not cand.is_dir():
            continue
        if using_defaults and any(
            s == resolved or s.is_relative_to(resolved) or resolved.is_relative_to(s)
            for s in sensitive
        ):
            logger.warning(
                "Dropping default CLI write root %s: it overlaps the bot's own "
                "tree (repo/.env/write-guard must stay outside every write root)",
                cand,
            )
            continue
        roots.append(cand)
    return roots


# Built-in web tools for the read-only chat path. claude -p ships WebSearch +
# WebFetch; enabling them lets the model look up current information and read
# URLs (both run server-side at Anthropic, so there's no SSRF reachability to
# the bot host). They are NEVER added in write mode (the write-guard deny-list
# already blocks them). Disable entirely with DASHBOARD_CLI_WEB_TOOLS=0.
_CLI_WEB_TOOLS_ENABLED = os.getenv("DASHBOARD_CLI_WEB_TOOLS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _build_claude_argv(
    claude_exe: str,
    *,
    session_id: str | None,
    allow_read_for_images: bool,
    allow_edit_tools: bool = False,
    enable_thinking: bool = False,
    enable_write: bool = False,
    system_prompt_file: Path | None = None,
    enable_web: bool = False,
    ai_tool_names: list[str] | None = None,
) -> list[str]:
    """Construct the argv for the `claude -p` invocation.

    When ``enable_thinking`` is True we pass ``--effort xhigh``. This makes
    Opus 4.8 actually reason internally; the *content* of that reasoning is
    still redacted by Anthropic in subscription mode (only the start/stop
    markers reach us), but the model spends real reasoning effort which
    improves answer quality on hard questions.

    We do NOT pass ``--betas interleaved-thinking`` here. This subprocess only
    ever authenticates with the Max subscription (``_make_subprocess_env``
    forwards ``CLAUDE_CODE_OAUTH_TOKEN`` but never ``ANTHROPIC_API_KEY``), and
    the CLI rejects custom betas for non-API-key users — it prints
    "Custom betas are only available for API key users. Ignoring provided
    betas." to stderr and ignores the flag. That warning is pure noise: because
    it is the only thing on stderr, it used to *mask* the real failure (which
    claude reports on stdout as the stream-json ``result`` event) whenever the
    process exited non-zero. ``--effort xhigh`` alone already drives Opus 4.8's
    deep thinking in subscription mode, so dropping the beta costs nothing.
    """
    # MCP config: our own AI-tools server when custom tools are requested,
    # otherwise the EMPTY config. Either way ``--strict-mcp-config`` means "use
    # ONLY this file, ignore the user's global/plugin MCP sources" (serena,
    # playwright, …) so nothing else spawns alongside the chat subprocess.
    mcp_config = _ensure_ai_tools_mcp_config() if ai_tool_names else _ensure_empty_mcp_config()
    argv: list[str] = [
        claude_exe,
        "-p",
        "--output-format",
        "stream-json",
        "--input-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--model",
        CLAUDE_MODEL,
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
    ]

    # Persona as a cacheable system prefix (instead of re-sending it in the user
    # body every turn). Appended to Claude Code's default system prompt, so tool
    # scaffolding (Read for images) is preserved. Placed in the base argv so it
    # applies to every branch below, including write mode.
    if system_prompt_file is not None:
        argv.extend(["--append-system-prompt-file", str(system_prompt_file)])

    # Permission mode. OFF by default: pin "--permission-mode default" so the
    # Read-tool confinement (--allowedTools Read + --add-dir <temp roots>) holds
    # even if the operator's settings.json sets defaultMode=bypassPermissions.
    # --add-dir pre-approves the temp dirs (attachments still read without a
    # prompt); arbitrary paths (e.g. ~/.claude/.credentials.json) are denied
    # rather than silently allowed by an inherited bypass mode.
    #
    # When write-mode is requested AND at least one output root resolves, switch
    # to "acceptEdits" — the only subscription-compatible mode that runs file
    # writes NON-interactively under `-p`. (default/plan/dontAsk stall because
    # there is no TTY to answer the "Allow?" prompt the chat UI can't surface;
    # "auto" needs the paid API, not the Max subscription this subprocess uses.)
    # acceptEdits gives the no-prompt experience for in-scope writes, but it is
    # NOT the security boundary: a PreToolUse write-guard hook (attached via
    # --settings with the tools below) is the AUTHORITATIVE path gate — it denies
    # any Write/Edit/MultiEdit/NotebookEdit whose canonical path is outside the
    # resolved write roots, so writes to the repo, .env, dotfiles, or the cwd/
    # config-dir subtree are rejected even though acceptEdits would auto-approve
    # the cwd subtree. Shell + network + other mutation tools are also denied —
    # the "files-only" scope.
    write_roots = _dashboard_cli_write_dirs() if enable_write else []
    write_mode = bool(write_roots)
    if enable_write and not write_roots:
        logger.warning(
            "DASHBOARD_CLI_ALLOW_WRITE is on but no writable output dir resolved "
            "(set DASHBOARD_CLI_WRITE_DIRS to an existing path); the dashboard "
            "chat stays read-only this turn."
        )
    argv.extend(["--permission-mode", "acceptEdits" if write_mode else "default"])

    if enable_thinking:
        # Only --effort xhigh — NOT --betas interleaved-thinking. See the
        # docstring: custom betas are ignored (and noisily warned about) in
        # subscription mode, and that warning used to mask real stdout errors.
        argv.extend(["--effort", "xhigh"])
    else:
        # Pin a non-thinking tier EXPLICITLY. Without a flag the subprocess
        # inherits the OPERATOR's ~/.claude/settings.json `effortLevel`
        # (e.g. "max"), silently coupling the bot's reasoning spend to the
        # operator's interactive Claude Code preference — same philosophy as
        # the pinned --permission-mode above. "high" keeps thinking-OFF
        # conversations on a fast non-deep tier per the toggle's contract;
        # the bot's reasoning ceiling stays xhigh (operator decision).
        argv.extend(["--effort", "high"])
    if session_id and _SESSION_ID_PATTERN.match(session_id):
        argv.extend(["--resume", session_id])
    elif session_id:
        # Defense-in-depth: a session id that slipped past _track_session (e.g.
        # via a tampered persisted-sessions file) and begins with '-' would be
        # parsed as a flag here (argv injection). Drop --resume rather than risk
        # it — the turn just starts a fresh server-side session.
        logger.warning("Ignoring suspicious --resume session id %r", session_id)
    if write_mode:
        # Files-only autonomy. CRITICAL: do NOT allow-list Write/Edit. A bare
        # tool name in --allowedTools is treated as unconditionally always-allowed
        # and short-circuits the acceptEdits/--add-dir path boundary, letting the
        # model write anywhere. Instead the path boundary is enforced by the
        # PreToolUse write-guard hook below, which denies any edit whose canonical
        # target is outside the resolved write roots (cli_write_guard.py).
        argv.extend(["--settings", str(_ensure_write_guard_settings())])
        # Deny shell, network, and the other file-mutation / subagent tools, so
        # the model's only write path is Write/Edit/MultiEdit — every call of
        # which the guard hook vets. (NotebookEdit is also guarded by the hook;
        # denying it here just removes it from the model's toolset entirely.)
        argv.extend(["--disallowedTools", "Bash WebFetch WebSearch NotebookEdit Task"])
        # --add-dir gives the no-prompt experience under acceptEdits for in-scope
        # writes (the hook still vets each one). These are the ONLY roots — the
        # repo, .env, dotfiles, and the cwd/config-dir subtree are excluded, so
        # the guard rejects writes there.
        for _root in write_roots:
            argv.extend(["--add-dir", str(_root)])
        # Attachments still live under the temp roots — keep them readable.
        if allow_read_for_images:
            for _root in (_TEMP_IMAGE_ROOT, _TEMP_DOCS_ROOT):
                with contextlib.suppress(OSError):
                    _root.mkdir(parents=True, exist_ok=True)
                argv.extend(["--add-dir", str(_root)])
        return argv

    # Tools allow-list: zero by default (pure chat — fastest, no surprises).
    # Images require Read so Claude can view the temp files. /edit also uses
    # zero tools — Claude just emits SEARCH/REPLACE text in its reply.
    # `allow_edit_tools` is reserved for future expansion. Today both
    # branches yield the same tool list, so warn instead of silently
    # ignoring an opt-in caller.
    if allow_edit_tools:
        logger.debug(
            "allow_edit_tools=True is reserved for future expansion; "
            "current build uses the same minimal tool list either way."
        )
    chat_tools: list[str] = []
    if allow_read_for_images:
        chat_tools.append("Read")
    if enable_web:
        # WebSearch is safe to pair with anything: it returns results from a
        # search provider and can't reach local files.
        chat_tools.append("WebSearch")
        # WebFetch can GET an attacker-controlled URL (secrets exfiltrate via the
        # query string). Read is bare-allow-listed (unconfined), so pairing the
        # two would let a prompt-injected document Read a secret and exfil it via
        # a crafted fetch. Only add WebFetch on the NO-Read chat path, where
        # there's no local-file access to leak.
        if not allow_read_for_images:
            chat_tools.append("WebFetch")
    if ai_tool_names:
        # Custom MCP tools (mcp__bottools__*) served by mcp_tools_server.py via
        # the bot IPC. Bare-allow-listed so they run without an interactive
        # permission prompt (there's no TTY under -p).
        chat_tools.extend(ai_tool_names)
    argv.extend(["--allowedTools", " ".join(chat_tools)])
    if allow_read_for_images:
        # --add-dir declares the upload temp roots as working dirs so attachments
        # read without a prompt; uploads live in per-conversation subdirs beneath
        # them. mkdir so the flag resolves before the first upload.
        #
        # NOTE: --add-dir does NOT strictly *confine* Read here. Because "Read" is
        # bare-allow-listed above, Claude treats it as always-allowed and can in
        # principle read any absolute path the bot user can (e.g. .env, the SQLite
        # DB), so a prompt-injected document could ask Claude to Read and echo a
        # secret back over the WS stream. The blast radius is limited: that stream
        # is single-user (the operator's own dashboard), so it's disclosure to
        # self, not third-party exfil — and there is no Bash/web tool on this path
        # to forward it. If true read confinement is ever wanted, enforce it the
        # same way write mode does: a PreToolUse hook matching Read (see
        # cli_write_guard.py), not --add-dir.
        for _root in (_TEMP_IMAGE_ROOT, _TEMP_DOCS_ROOT):
            _root.mkdir(parents=True, exist_ok=True)
            argv.extend(["--add-dir", str(_root)])
    return argv


async def _spawn_claude(
    argv: list[str], extra_env: dict[str, str] | None = None
) -> asyncio.subprocess.Process:
    """Spawn a `claude -p` child (stdin/stdout/stderr piped), WITHOUT writing
    stdin. Shared by the normal run path and the pre-warm path.

    ``extra_env`` is merged on top of the allowlisted env — these are bot-set
    values (the AI-tools IPC URL/token + per-turn Discord context), not inherited
    from the parent's environment, so they intentionally bypass the allowlist.
    """
    env = _make_subprocess_env()
    if extra_env:
        env.update(extra_env)
    # Spawn from a dedicated workdir so Claude Code's session .jsonl files
    # land in their own `~/.claude/projects/<encoded-cwd>/` folder instead
    # of mixing with the user's own Claude Code sessions for the bot repo.
    _CLAUDE_CLI_WORKDIR.mkdir(parents=True, exist_ok=True)
    # Detach the child into its own process group so a Ctrl+C / SIGTERM
    # delivered to the parent doesn't propagate to claude (we already
    # send a clean kill ourselves on cleanup). On POSIX this requires
    # start_new_session; on Windows we use CREATE_NEW_PROCESS_GROUP.
    spawn_kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        # 0x00000200 = CREATE_NEW_PROCESS_GROUP
        spawn_kwargs["creationflags"] = 0x00000200
    else:
        spawn_kwargs["start_new_session"] = True
    return await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(_CLAUDE_CLI_WORKDIR),
        **spawn_kwargs,
    )


def _kill_warm(wp: dict[str, Any]) -> None:
    """Best-effort terminate a warm process record."""
    proc = wp.get("proc")
    if proc is None:
        return
    with contextlib.suppress(ProcessLookupError, Exception):
        if proc.returncode is None:
            proc.kill()


def _sweep_expired_warm() -> None:
    """Kill+drop any warm proc past its TTL or already dead, for ANY conversation.

    Warm procs are otherwise reclaimed only lazily (in _take_warm, or on the same
    conversation's next _schedule_prewarm), so a conversation with a single turn
    would leave its ~150 MB process alive for the bot's lifetime. Sweeping here
    reclaims those and frees slots for new conversations.
    """
    now = time.monotonic()
    for cid, wp in list(_warm_procs.items()):
        proc = wp.get("proc")
        expired = (now - wp.get("created", 0.0)) > _PREWARM_TTL
        dead = proc is None or proc.returncode is not None
        if expired or dead:
            _kill_warm(_warm_procs.pop(cid))


def _take_warm(conversation_id: str | None, argv: list[str]) -> asyncio.subprocess.Process | None:
    """Return a pre-warmed process whose argv EXACTLY matches ``argv`` (so the
    prompt we're about to send is valid for it), is still alive, and is fresh.
    Otherwise discard any stale warm proc and return None so the caller spawns
    fresh. The exact-argv match is the safety boundary: flags (resume id,
    thinking, write, read-tool, persona file) must be identical or the warm
    process would answer with the wrong configuration."""
    if not _PREWARM_ENABLED or not conversation_id:
        return None
    wp = _warm_procs.pop(conversation_id, None)
    if wp is None:
        return None
    proc = wp.get("proc")
    fresh = (time.monotonic() - wp.get("created", 0.0)) <= _PREWARM_TTL
    if proc is not None and proc.returncode is None and wp.get("argv") == argv and fresh:
        return proc
    _kill_warm(wp)
    return None


async def _spawn_warm_async(conversation_id: str, argv: list[str]) -> None:
    """Best-effort spawn of a warm process for the next turn of a conversation."""
    try:
        proc = await _spawn_claude(argv)
    except Exception:
        logger.debug("pre-warm spawn failed for %s", conversation_id, exc_info=True)
        return
    # If shutdown ran while we were spawning, or a turn already
    # claimed/created a warm proc, or we're at the cap, don't clobber —
    # kill this surplus one. The shutdown check matters: after
    # shutdown_prewarm() cleared the dict, an in-flight spawn would
    # otherwise register a fresh DETACHED child nothing ever kills.
    if _PREWARM_SHUTDOWN or conversation_id in _warm_procs or len(_warm_procs) >= _PREWARM_MAX:
        with contextlib.suppress(ProcessLookupError, Exception):
            if proc.returncode is None:
                proc.kill()
        return
    _warm_procs[conversation_id] = {
        "proc": proc,
        "argv": list(argv),
        "created": time.monotonic(),
    }


def _schedule_prewarm(conversation_id: str | None, argv: list[str]) -> None:
    """Fire-and-forget pre-warm of the next turn's process (latency hiding)."""
    if not _PREWARM_ENABLED or not conversation_id or _PREWARM_SHUTDOWN:
        return
    # Reclaim expired/dead warm procs from abandoned conversations first so any
    # freed slots become reusable below.
    _sweep_expired_warm()
    # Drop any existing warm proc for this conversation — the session advanced,
    # so its --resume argv is now stale.
    old = _warm_procs.pop(conversation_id, None)
    if old is not None:
        _kill_warm(old)
    if len(_warm_procs) >= _PREWARM_MAX:
        return
    try:
        task = asyncio.create_task(_spawn_warm_async(conversation_id, argv))
    except RuntimeError:
        return  # no running event loop (not expected on the WS path)
    _PREWARM_TASKS.add(task)
    task.add_done_callback(_PREWARM_TASKS.discard)


def shutdown_prewarm() -> None:
    """Kill every warm process. Call on dashboard/server shutdown."""
    global _PREWARM_SHUTDOWN
    _PREWARM_SHUTDOWN = True
    # Cancel in-flight spawn tasks — a spawn completing after the clear()
    # below would otherwise re-register a warm proc post-shutdown.
    for task in list(_PREWARM_TASKS):
        task.cancel()
    for wp in list(_warm_procs.values()):
        _kill_warm(wp)
    _warm_procs.clear()


async def _run_claude_subprocess(
    argv: list[str],
    stdin_payload: str,
    *,
    on_text_delta: Any,
    on_thinking_delta: Any,
    on_thinking_block_start: Any = None,
    on_thinking_block_stop: Any = None,
    timeout: float,
    proc: asyncio.subprocess.Process | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Spawn `claude -p`, stream events, return (final_session_id, usage).

    Callback semantics:
      - on_text_delta(text)           — every visible text chunk
      - on_thinking_delta(text)       — every thinking text chunk (subscription
                                        mode redacts these to empty strings,
                                        so this is mostly dormant)
      - on_thinking_block_start()     — fires when Claude begins reasoning;
                                        useful to show a "💭 thinking…" UI
                                        even when the content is hidden
      - on_thinking_block_stop()      — fires when reasoning ends

    If ``proc`` is provided it is a pre-warmed (already-booted, stdin-open)
    child from the pre-warm pool — we skip the spawn and just write stdin,
    hiding the cold-start latency. If it's None (or unusable) we spawn fresh.

    Sends `stdin_payload` as a single stream-json message:
        {"type":"user","message":{"role":"user","content":[{"type":"text","text":...}]}}
    then closes stdin so Claude knows there's no more input.
    """
    prewarmed = proc is not None and proc.returncode is None and proc.stdin is not None
    if not prewarmed:
        proc = await _spawn_claude(argv, extra_env=extra_env)
    t_write = time.monotonic()

    # stream-json input format expects one JSON message per line on stdin.
    user_msg = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": stdin_payload}],
        },
    }
    if proc.stdin is None:
        # Defensive: with stdin=PIPE, stdin should always exist; raise a
        # real error rather than relying on `assert` (stripped under -O).
        # Kill the just-spawned process first — this raise happens BEFORE
        # the kill-guaranteeing try/finally around the stream loop below,
        # so without it the claude child would be orphaned.
        with contextlib.suppress(Exception):
            if proc.returncode is None:
                proc.kill()
        raise RuntimeError("Subprocess stdin pipe is unexpectedly None")

    # Drain stderr concurrently from the very start — BEFORE the stdin
    # write/drain, not just during the stdout phase. drain() blocks when the
    # prompt exceeds the pipe buffer; a child that also emits more than a
    # pipe buffer of early output before consuming stdin would otherwise
    # deadlock against us (classic write-write deadlock), and during the
    # stdout phase a verbose warning chain filling the stderr pipe would
    # block the child and stall consume_stdout the same way.
    stderr_chunks: list[bytes] = []

    def _start_stderr_pump(p: asyncio.subprocess.Process) -> asyncio.Task[None]:
        async def _pump() -> None:
            if p.stderr is None:
                return
            async for chunk in p.stderr:
                stderr_chunks.append(chunk)

        return asyncio.create_task(_pump())

    async def _stop_stderr_pump(task: asyncio.Task[None], *, drain_window: float = 0.0) -> None:
        """Settle the pump task (optionally letting it drain briefly first)."""
        if drain_window > 0:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=drain_window)
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    stderr_task = _start_stderr_pump(proc)

    payload = (json.dumps(user_msg) + "\n").encode("utf-8")
    for write_attempt in (1, 2):
        try:
            proc.stdin.write(payload)
            # Bound the drain with its own budget: the stream timeout below
            # only guards the stdout phase, so an unbounded drain against a
            # child that boots but never reads stdin (network-stalled auth,
            # wedged node boot) would hang the handler forever HOLDING the
            # per-conversation lock. Generous cap — the prewarm pool exists
            # because cold boots are slow — but never above `timeout` itself.
            await asyncio.wait_for(proc.stdin.drain(), timeout=min(60.0, timeout))
            break
        except TimeoutError:
            # Stalled child (drain budget exhausted). Kill it and surface the
            # standard timeout — the call sites' ``except TimeoutError`` sends
            # the timeout frame and releases the conversation lock.
            with contextlib.suppress(Exception):
                if proc.returncode is None:
                    proc.kill()
            with contextlib.suppress(Exception):
                proc.stdin.close()
            await _stop_stderr_pump(stderr_task)
            logger.warning(
                "claude -p never consumed stdin within %.0fs; killed (prewarmed=%s)",
                min(60.0, timeout),
                prewarmed,
            )
            raise
        except OSError as write_err:
            # The child died before reading stdin (BrokenPipeError /
            # ConnectionResetError). Kill + salvage its stderr (bounded —
            # the pump drains the dead pipe to EOF) so the log names the
            # real cause instead of a bare pipe error.
            with contextlib.suppress(Exception):
                if proc.returncode is None:
                    proc.kill()
            with contextlib.suppress(Exception):
                proc.stdin.close()
            await _stop_stderr_pump(stderr_task, drain_window=2.0)
            tail_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")[:500].strip()
            if prewarmed and write_attempt == 1:
                # A warm proc can die during its idle TTL between _take_warm's
                # aliveness check and this write. One cold retry with the SAME
                # argv (the warm claim was an exact-argv match, so semantics
                # incl. --resume are identical) almost certainly succeeds.
                # Strictly pre-drain-success, so the prompt never reached the
                # child and no turn can have been applied server-side.
                logger.warning(
                    "pre-warmed claude -p died before reading stdin (%s); "
                    "falling back to a cold spawn | stderr=%s",
                    write_err,
                    tail_text or "<empty>",
                )
                prewarmed = False
                stderr_chunks.clear()
                proc = await _spawn_claude(argv, extra_env=extra_env)
                t_write = time.monotonic()
                if proc.stdin is None:
                    with contextlib.suppress(Exception):
                        if proc.returncode is None:
                            proc.kill()
                    raise RuntimeError("Subprocess stdin pipe is unexpectedly None") from write_err
                stderr_task = _start_stderr_pump(proc)
                continue
            logger.error(
                "claude -p died before reading stdin: %s | stderr=%s",
                write_err,
                tail_text or "<empty>",
            )
            raise RuntimeError(
                f"claude -p died before reading stdin: {tail_text[:200] or write_err}"
            ) from write_err
        except BaseException:
            # CancelledError (client disconnect mid-drain — drain blocks when
            # the prompt exceeds the pipe buffer) lands BEFORE the stream-loop
            # try/finally that normally guarantees the kill: without this
            # handler the freshly spawned claude process survived unkilled.
            # The early-started stderr pump must die with it too, or it leaks
            # as a pending task holding the stderr pipe handle.
            with contextlib.suppress(Exception):
                if proc.returncode is None:
                    proc.kill()
            with contextlib.suppress(Exception):
                proc.stdin.close()
            await _stop_stderr_pump(stderr_task)
            raise
    # Close stdin on the success path so claude knows there's no more input.
    with contextlib.suppress(Exception):
        proc.stdin.close()

    final_session_id = ""
    final_usage: dict[str, Any] | None = None
    # Perf timing (#4): time-to-first-token measured from the stdin write.
    first_text_ts: float | None = None
    # The REAL failure cause, captured from the stream-json `result` event on
    # stdout (claude reports API/runtime errors there, not on stderr). Used by
    # the rc!=0 path below to log/raise the actual error instead of whatever
    # benign warning happened to land on stderr.
    final_error_text = ""
    final_error_status: int | None = None

    # Hard cap on a single NDJSON line — claude shouldn't produce more
    # than a few MB per event; anything larger is either a runaway model
    # or a malformed binary blob. Without this, asyncio's StreamReader
    # default of 64 KiB raises LimitOverrunError on the first oversized
    # frame and aborts the whole stream.
    MAX_STDOUT_LINE_BYTES = 16 * 1024 * 1024

    # Track which content-block indices are thinking blocks so the
    # `content_block_stop` handler only fires `on_thinking_block_stop` for
    # those (text/tool block stops would otherwise spuriously close the
    # thinking-panel UI state).
    thinking_block_indices: set[int] = set()

    async def consume_stdout() -> None:
        nonlocal final_session_id, final_usage, final_error_text, final_error_status
        nonlocal first_text_ts
        if proc.stdout is None:
            raise RuntimeError("Subprocess stdout pipe is unexpectedly None")
        # Drop the per-line buffer cap so model JSON deltas with embedded
        # base64 / long text aren't truncated. We still bound below.
        with contextlib.suppress(AttributeError):
            proc.stdout._limit = MAX_STDOUT_LINE_BYTES  # type: ignore[attr-defined]
        async for raw_line in proc.stdout:
            if len(raw_line) > MAX_STDOUT_LINE_BYTES:
                logger.warning(
                    "Dropping oversized stdout frame (%d bytes > %d cap)",
                    len(raw_line),
                    MAX_STDOUT_LINE_BYTES,
                )
                continue
            try:
                line = raw_line.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")

            # Capture session_id from the init event (first event of every run).
            if etype == "system" and event.get("subtype") == "init":
                sid = event.get("session_id")
                if isinstance(sid, str) and sid:
                    final_session_id = sid
                continue

            # The final result event carries usage in JSON/stream-json.
            if etype == "result":
                usage = event.get("usage")
                if isinstance(usage, dict):
                    final_usage = usage
                # …and, on failure, the actual error. claude sets is_error and
                # (for HTTP failures) api_error_status here, with a human-
                # readable message in `result` — e.g. "API Error: 529
                # Overloaded …" or "There's an issue with the selected model …".
                # stderr, by contrast, often holds only the ignored-betas
                # warning, so this is the diagnostic the rc!=0 path should use.
                if event.get("is_error"):
                    status = event.get("api_error_status")
                    if isinstance(status, int):
                        final_error_status = status
                    res = event.get("result")
                    if isinstance(res, str) and res.strip():
                        final_error_text = res.strip()[:500]
                continue

            # Streaming token deltas live under the "stream_event" wrapper.
            if etype != "stream_event":
                continue
            inner = event.get("event") or {}
            if not isinstance(inner, dict):
                continue

            inner_type = inner.get("type")

            # content_block_start / _stop tell us when a thinking block opens
            # and closes — useful to drive a "Claude is reasoning…" UI even
            # when the actual thinking text is redacted by Anthropic's
            # subscription policy. Track the index of any thinking block so a
            # `content_block_stop` for an unrelated text/tool block doesn't
            # fire a spurious `thinking_end` and break the UI state machine.
            if inner_type == "content_block_start":
                cb = inner.get("content_block") or {}
                idx = inner.get("index")
                if isinstance(cb, dict) and cb.get("type") == "thinking":
                    if isinstance(idx, int):
                        thinking_block_indices.add(idx)
                    if on_thinking_block_start is not None:
                        await on_thinking_block_start()
                continue
            if inner_type == "content_block_stop":
                idx = inner.get("index")
                if isinstance(idx, int) and idx in thinking_block_indices:
                    thinking_block_indices.discard(idx)
                    if on_thinking_block_stop is not None:
                        await on_thinking_block_stop()
                continue

            delta = inner.get("delta")
            if not isinstance(delta, dict):
                continue
            dtype = delta.get("type")
            if dtype == "text_delta":
                text = delta.get("text", "")
                if text and on_text_delta is not None:
                    if first_text_ts is None:
                        first_text_ts = time.monotonic()
                    await on_text_delta(text)
            elif dtype == "thinking_delta":
                thinking = delta.get("thinking", "")
                if thinking and on_thinking_delta is not None:
                    await on_thinking_delta(thinking)

    # (The stderr pump was already started before the stdin write above —
    # `stderr_task` is still draining concurrently here so the child can't
    # deadlock when its stderr pipe buffer fills before stdout closes.)
    stdout_timed_out = False
    try:
        try:
            await asyncio.wait_for(consume_stdout(), timeout=timeout)
        except TimeoutError:
            # Track separately so the finally below can log stderr_chunks
            # AFTER they've finished draining. The exception still propagates
            # to the outer ``except TimeoutError`` in the chat handler.
            stdout_timed_out = True
            raise
        except (asyncio.LimitOverrunError, ValueError) as _overflow:
            # A single NDJSON frame exceeded the StreamReader limit (the 16 MiB
            # cap, or asyncio's 64 KiB default if the cap assignment failed).
            # readline() raises before yielding the line, so it can't be dropped
            # per-frame — end the stream with whatever streamed so far rather
            # than letting it abort as a generic "backend failed".
            logger.warning(
                "claude -p stdout frame exceeded reader limit; ending stream early: %s",
                _overflow,
            )
        finally:
            # Always wait for the stderr drain to finish so we don't leak
            # the task. If consume_stdout raised, give stderr a brief
            # window to drain naturally before cancelling.
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(stderr_task, timeout=2.0)
            if not stderr_task.done():
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await stderr_task
            # If consume_stdout timed out, log whatever ended up on stderr
            # before re-raising. Without this, ``bot.log`` stayed silent for
            # the entire 300s/1800s window even though the subprocess had
            # buffered diagnostic output (auth prompt, network stall, etc.)
            # — the existing ``rc != 0`` log path is bypassed on TimeoutError.
            if stdout_timed_out:
                stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")[:1000]
                logger.warning(
                    "⏱️ claude -p stdout silent for %ds; stderr_tail=%s",
                    timeout,
                    stderr_text or "<empty>",
                )
        # Bound proc.wait() too — a misbehaving CLI could close stdout while
        # holding on to the process, hanging this coroutine indefinitely.
        # 5s is generous: by the time stdout closes, exit is normally instant.
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            logger.warning("claude -p didn't exit 5s after stdout closed; killing")
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            try:
                rc = await asyncio.wait_for(proc.wait(), timeout=10.0)
            except TimeoutError:
                # Process is wedged even after SIGKILL — log loudly and
                # surface a synthetic exit code so callers can react.
                # Without the bound, ``proc.wait()`` could hang the request
                # forever holding the conversation lock.
                logger.error("claude -p still alive 10s after kill; abandoning process")
                rc = -1
        if rc != 0:
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")[:500]
            # The real cause is almost always on STDOUT as the stream-json
            # `result` event (captured above), NOT on stderr. stderr usually
            # carries only benign warnings — chiefly the "Custom betas are only
            # available for API key users" notice — so logging stderr alone (as
            # we used to) named a red herring while the true failure (529
            # Overloaded, model_not_found, …) went unlogged. Prefer the stdout
            # error; fall back to stderr (where a stale --resume reports "No
            # conversation found with session ID: …") then to a placeholder.
            status_note = f" [api_error_status={final_error_status}]" if final_error_status else ""
            detail = final_error_text or stderr_text or "<no diagnostic output>"
            logger.error(
                "claude -p failed (exit %d)%s: %s | stderr=%s",
                rc,
                status_note,
                detail,
                stderr_text or "<empty>",
            )
            err_msg = f"claude -p exit {rc}{status_note}: {detail[:200]}"
            # Mark stale-session errors so the caller can transparently retry
            # without the bad --resume id. Scan BOTH the stdout error and
            # stderr: API errors surface in the result text, but a stale
            # --resume lands "…session ID…" on stderr.
            haystack = f"{final_error_text}\n{stderr_text}".lower()
            if (
                "--resume" in haystack
                or "session id" in haystack
                or "is not a uuid" in haystack
                or "does not match any session" in haystack
            ):
                raise _StaleSessionError(err_msg)
            # Transient Anthropic-side overload/rate-limit (HTTP 429/529).
            # Surface a distinct, user-actionable error instead of a generic one.
            if final_error_status in (429, 529) or "overloaded" in haystack:
                raise _OverloadedError(err_msg)
            raise RuntimeError(err_msg)
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()

    # Perf + cache breadcrumb (#3, #4). ttft = time from sending the prompt to
    # the first visible token; `prewarmed` tells whether the cold-start was
    # hidden by the pre-warm pool. The cache_* fields (when the CLI surfaces
    # them) confirm Claude Code's prompt cache is serving the resumed context —
    # cache_read_input_tokens > 0 on a resumed turn means caching is working.
    ttft_ms = (first_text_ts - t_write) * 1000 if first_text_ts is not None else -1
    cache_read = cache_creation = -1
    if isinstance(final_usage, dict):
        cache_read = final_usage.get("cache_read_input_tokens", -1)
        cache_creation = final_usage.get("cache_creation_input_tokens", -1)
    # session/resumed make concurrent conversations' lines correlatable from
    # bot.log (8-char prefix keeps lines tidy; full ids already appear on the
    # error paths, so no new disclosure class).
    logger.info(
        "⚡ claude-cli perf: prewarmed=%s resumed=%s session=%s ttft=%dms "
        "cache_read=%s cache_creation=%s",
        prewarmed,
        "--resume" in argv,
        (final_session_id or "")[:8] or "none",
        int(ttft_ms),
        cache_read,
        cache_creation,
    )

    return final_session_id, final_usage


async def handle_chat_message_claude_cli(
    ws: WebSocketResponse,
    data: dict[str, Any],
    claude_client: Any,  # unused — kept for signature parity with SDK backend
    *,
    max_content_length: int = 50_000,
    max_history_messages: int = 100,
    max_images: int = 10,
    max_image_size_bytes: int = 10 * 1024 * 1024,
    max_documents: int = 5,
    max_document_size_bytes: int = 32 * 1024 * 1024,
    stream_timeout: int = 300,
) -> None:
    """Stream a dashboard chat reply via ``claude -p`` (subscription billing)."""
    del claude_client  # signature parity only

    conversation_id = data.get("conversation_id")
    # Match the same alphanumeric/-/_ allowlist used by the Gemini and SDK
    # backends. Without this, a control char or weird Unicode in the id
    # could desync the on-disk session map (which sanitizes for filesystem
    # use) from the DB rows (which do not), or land in a SQL parameter
    # downstream as an unexpected shape.
    if not isinstance(conversation_id, str) or not re.match(
        r"^[a-zA-Z0-9_\-]{1,128}\Z", conversation_id
    ):
        await ws.send_json(
            {
                "type": "error",
                "message": "Invalid conversation ID",
                "conversation_id": conversation_id,
            }
        )
        return

    raw_content = data.get("content", "")
    content = (raw_content if isinstance(raw_content, str) else "").strip()
    role_preset = data.get("role_preset", "general")
    history = data.get("history") or []
    user_name = data.get("user_name", "User")
    # Honor DASHBOARD_ALLOW_UNRESTRICTED so the CLI backend matches the SDK +
    # Gemini paths. Without this gate the operator's safety control was
    # silently bypassed under CLAUDE_BACKEND=cli.
    _unrestricted_env = os.getenv("DASHBOARD_ALLOW_UNRESTRICTED", "").strip().lower()
    _unrestricted_allowed = _unrestricted_env in ("1", "true", "yes", "on")
    unrestricted_requested = bool(data.get("unrestricted_mode")) and _unrestricted_allowed
    # File-write autonomy (DASHBOARD_CLI_ALLOW_WRITE). When on, the embedded
    # `claude -p` may create/edit files in the configured output dirs without
    # the interactive "Allow?" prompt the chat UI can't surface. Read once here
    # and thread it through every _build_claude_argv call on the main chat path
    # (the /edit path intentionally stays text-only and never sets it).
    write_enabled = _dashboard_cli_write_enabled()
    thinking_enabled = bool(data.get("thinking_enabled"))
    images_raw = data.get("images") or []
    documents_raw = data.get("documents") or []

    # ``is_regeneration`` (the regenerate-after-edit flow) means this user turn
    # ALREADY exists in the DB: handle_edit_message updated its content and
    # deleted every message after it. Persisting it again here is exactly what
    # caused the duplicate-user-message bug under the CLI backend (this handler
    # previously ignored the flag entirely). Validate the claim — the last DB
    # row must be a user message whose content matches — so a client can't
    # abuse the flag to skip persistence (mirrors the SDK backend).
    is_regeneration = bool(data.get("is_regeneration", False))
    if is_regeneration and DB_AVAILABLE and conversation_id:
        try:
            _rdb = get_db()
            _recent = await _rdb.get_dashboard_messages(conversation_id)
            _last = _recent[-1] if _recent else None
            _last_content = (_last or {}).get("content") or ""
            _last_stripped = strip_leading_timestamp(_last_content) if _last_content else ""
            if not (
                _last
                and _last.get("role") == "user"
                and (_last_content == content or _last_stripped == content)
            ):
                logger.warning(
                    "is_regeneration=True (CLI) did not match last user msg; treating as new message",
                )
                is_regeneration = False
        except Exception:
            logger.warning(
                "Failed to validate is_regeneration (CLI); treating as new message",
                exc_info=True,
            )
            is_regeneration = False

    # Thinking-mode requests legitimately spend minutes on the Anthropic
    # side (Opus 4.7 reasoning silently before any stdout event), so the
    # caller's 300s default fires mid-call. Override here where we know
    # thinking_enabled, leaving non-thinking turns on the tighter budget.
    if thinking_enabled and stream_timeout < _THINKING_STREAM_TIMEOUT:
        stream_timeout = _THINKING_STREAM_TIMEOUT

    # Mirror the SDK backend (``dashboard_chat_claude.py``) which accepts
    # empty content as long as there are images or documents to look
    # at — the user's prompt is implicitly "review these attachments".
    # Previously the CLI path rejected attachment-only turns with
    # "Empty message" while the SDK path accepted them, surprising
    # users who switched between backends.
    has_attachments = bool(
        (isinstance(images_raw, list) and images_raw)
        or (isinstance(documents_raw, list) and documents_raw)
    )
    if not content and not has_attachments:
        await ws.send_json(
            {"type": "error", "message": "Empty message", "conversation_id": conversation_id}
        )
        return

    if len(content) > max_content_length:
        await ws.send_json(
            {
                "type": "error",
                "message": f"Message too long (>{max_content_length} chars)",
                "conversation_id": conversation_id,
            }
        )
        return

    ready, reason = is_cli_backend_ready()
    if not ready:
        await ws.send_json({"type": "error", "message": reason, "conversation_id": conversation_id})
        return

    # Cap image count to mirror the SDK backend's safety net.
    capped_images = images_raw[:max_images] if isinstance(images_raw, list) else []

    # INFO breadcrumb: every claude-cli chat turn produces exactly one start
    # line and one end line in bot.log so an operator can see request flow
    # without flipping the whole logger to DEBUG (which would also flood the
    # log with per-frame WS dispatch noise). Tracked here so an early-return
    # validation rejection above stays silent — those send an error frame to
    # the client and don't reach the subprocess.
    start_ts = time.monotonic()
    logger.info(
        "💬 chat-cli start conv=%s thinking=%s content_len=%d images=%d docs=%d",
        conversation_id,
        thinking_enabled,
        len(content),
        len(capped_images),
        len(documents_raw) if isinstance(documents_raw, list) else 0,
    )

    # Save the user's turn to the DB up front, mirroring the SDK backend so
    # the conversation log stays consistent across backend toggles.
    # IMPORTANT: store the raw content — the [timestamp] prefix is for the AI
    # only and gets injected into the prompt below. Persisting it would make
    # the dashboard render `[2026-04-23T...] hello` to the user, which is
    # the bug previously observed in CLI mode.
    user_msg_id: int | None = None
    if DB_AVAILABLE and conversation_id and not is_regeneration:
        try:
            db = get_db()
            # Don't pass `mode=` for user turns — SDK backend omits it too;
            # the mode badge is conceptually the assistant's reply attribute.
            user_msg_id = await db.save_dashboard_message(
                conversation_id,
                "user",
                content,
                images=capped_images if capped_images else None,
            )
        except Exception:
            logger.exception("Failed to save user message (CLI backend)")

    # Decode + persist images to disk so Claude can Read them by path.
    # Run sync I/O in a worker thread so a 50 MB image set can't stall the
    # event loop for hundreds of milliseconds.
    image_paths = (
        await asyncio.to_thread(
            _save_inline_images,
            conversation_id or "default",
            capped_images,
            max_image_size_bytes,
        )
        if capped_images
        else []
    )

    # Cap + save document attachments (PDF / text / code) the same way.
    capped_docs = documents_raw[:max_documents] if isinstance(documents_raw, list) else []
    doc_paths = (
        await asyncio.to_thread(
            _save_inline_documents,
            conversation_id or "default",
            capped_docs,
            max_document_size_bytes,
        )
        if capped_docs
        else []
    )

    # Persistent document memory — extract text from every attached document
    # and save it to the DB so future turns (in any conversation) see the
    # content without the user re-uploading. This runs alongside the temp
    # file save above: Claude still reads the full binary THIS turn for
    # maximum fidelity; the DB snapshot is a text-only fallback for later.
    if capped_docs and DB_AVAILABLE and not is_regeneration:
        try:
            from .document_extractor import extract_and_persist

            db_inst = get_db()
            saved_docs = await extract_and_persist(
                capped_docs,
                db=db_inst,
                source_conversation_id=conversation_id,
            )
            if saved_docs:
                # Non-blocking UX feedback. Does not gate the chat response —
                # the message continues regardless of whether the toast lands.
                with contextlib.suppress(Exception):
                    await ws.send_json(
                        {
                            "type": "document_saved",
                            "documents": saved_docs,
                            "conversation_id": conversation_id,
                        }
                    )
        except Exception:
            logger.exception("Document extraction/persistence failed (CLI backend)")

    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])
    persona = str(preset.get("system_instruction", ""))
    if unrestricted_requested:
        framing = preset.get("unrestricted_framing", "")
        if framing:
            persona = f"{framing}\n\n{persona}"

    # Deliver persona (+ timestamp convention) as a cacheable system prefix via
    # --append-system-prompt-file rather than re-sending it in every user turn.
    # Content-hashed so a stable persona reuses one file and keeps the prompt
    # cache warm. Best-effort: if the file can't be written we fall back to
    # persona-in-body (system_prompt_file=None, persona_in_system=False).
    system_prompt_file: Path | None = None
    try:
        # Advertise web tools only when the argv actually allows them: write
        # mode appends --disallowedTools "… WebFetch WebSearch …", and telling
        # the model a denied tool is "available right now — call it directly"
        # produces confident tool calls that hard-fail every time.
        system_prompt_file = _ensure_system_prompt_file(
            _build_system_prompt(persona, web_enabled=_CLI_WEB_TOOLS_ENABLED and not write_enabled)
        )
    except OSError:
        logger.warning(
            "Could not materialise system-prompt file; using persona-in-body", exc_info=True
        )
    persona_in_system = system_prompt_file is not None

    session_id = _CONVERSATION_SESSIONS.get(conversation_id or "") if conversation_id else None
    is_resumed = bool(session_id)

    # Prefer the DB as the source of truth for history when we have a
    # conversation id — it carries ``created_at`` for every row, which the
    # frontend payload often omits (older dashboard builds, stale webview
    # state). Without per-row timestamps the AI can't perceive elapsed time
    # between turns and answers as if the user only paused for a few minutes,
    # even when hours have passed. We load even for resumed sessions so that
    # the stale-session retry path (which falls back to is_resumed_session=
    # False and rebuilds the history block) has timestamps available too.
    # Falls back to the frontend-supplied history if the DB load fails.
    if DB_AVAILABLE and conversation_id:
        try:
            db = get_db()
            db_msgs = await db.get_dashboard_messages(conversation_id)
            # Drop the trailing user row when present — that's the message
            # we're about to answer, not part of the prior history.
            hist_msgs = db_msgs[:-1] if db_msgs and db_msgs[-1].get("role") == "user" else db_msgs
            if hist_msgs:
                history = hist_msgs
        except Exception:
            logger.exception("Failed to load DB history for CLI prompt; using frontend payload")

    # Always rebuild the user context (profile + long-term memories + per-conv
    # docs) so changes the user makes mid-conversation take effect on the very
    # next turn, the same way they do in the SDK backend. The 60s TTL cache in
    # build_user_context() keeps the SQLite round trips cheap on chat bursts.
    try:
        user_context, _unused = await build_user_context(
            user_name,
            unrestricted_requested,
            conversation_id=conversation_id,
        )
    except Exception:
        logger.exception("build_user_context failed (CLI backend)")
        user_context = f"Name: {user_name}"

    # Persona + context go in every turn now (matches API behavior); only the
    # raw conversation history stays gated on the first turn because Claude
    # carries it server-side via --resume.
    full_prompt = _build_full_prompt(
        persona=persona,
        user_context=user_context,
        history=history,
        history_limit=max_history_messages,
        current_message=content,
        image_paths=image_paths,
        doc_paths=doc_paths,
        is_resumed_session=is_resumed,
        persona_in_system=persona_in_system,
    )

    # Match the SDK backend's mode-label format so the badge always tells
    # the user what's actually active (model, thinking, unrestricted, images).
    mode_info: list[str] = [f"🟣 Claude Code CLI ({CLAUDE_MODEL})"]
    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    if unrestricted_requested:
        mode_info.append("🔓 Unrestricted")
    if write_enabled:
        mode_info.append("✍️ Write")
    if image_paths:
        mode_info.append(f"🖼️ {len(image_paths)} image(s)")
    if doc_paths:
        mode_info.append(f"📎 {len(doc_paths)} doc(s)")
    mode_label = " • ".join(mode_info)
    await ws.send_json(
        {
            "type": "stream_start",
            "mode": mode_label,
            "conversation_id": conversation_id,
        }
    )

    full_response = ""
    full_thinking = ""
    thinking_started = False
    thinking_ended = False

    async def on_text(text: str) -> None:
        nonlocal full_response
        full_response += text
        await ws.send_json(
            {
                "type": "chunk",
                "content": text,
                "conversation_id": conversation_id,
            }
        )

    async def on_thinking_text(text: str) -> None:
        # Only fires when Anthropic actually sends thinking content, which
        # is API-key mode only. In subscription mode this stays dormant.
        nonlocal full_thinking, thinking_started
        if not thinking_enabled:
            return
        if not thinking_started:
            thinking_started = True
            await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})
        full_thinking += text
        await ws.send_json(
            {
                "type": "thinking_chunk",
                "content": text,
                "conversation_id": conversation_id,
            }
        )

    async def on_thinking_block_start() -> None:
        # Fires when Claude opens a reasoning block, even in subscription
        # mode where the content itself is hidden. Use this to surface the
        # "💭 Thinking…" panel so the user sees that reasoning is happening.
        nonlocal thinking_started
        if not thinking_enabled or thinking_started:
            return
        thinking_started = True
        await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})

    async def _emit_thinking_end() -> None:
        """Emit the thinking_end WS event once, collapsing the 💭 panel.

        Idempotent via ``thinking_ended`` so the block-stop callback (which
        fires the moment reasoning ends) and the finally below (which covers
        error/timeout exits that never reached block-stop) can't double-emit.
        """
        nonlocal thinking_ended, full_thinking
        if not thinking_started or thinking_ended:
            return
        thinking_ended = True
        if not full_thinking:
            full_thinking = (
                "💭 Claude reasoned through this internally. The Claude Code "
                "subscription redacts thought content from headless output — "
                "switch to CLAUDE_BACKEND=api with an Anthropic API key to "
                "see the full thought process."
            )
        with contextlib.suppress(Exception):
            await ws.send_json(
                {
                    "type": "thinking_end",
                    "full_thinking": full_thinking,
                    "conversation_id": conversation_id,
                }
            )

    async def on_thinking_block_stop() -> None:
        # Reasoning block closed → the visible answer is about to stream.
        # Collapse the 💭 panel NOW (matching the SDK backend, which flips on
        # the first text delta) instead of leaving it spinning until end-of-turn.
        await _emit_thinking_end()

    claude_exe = _resolve_claude_executable() or "claude"
    # The Read tool must be enabled whenever Claude needs to open any attached
    # file — images AND documents both live on disk. `allow_read_for_images`
    # is kept as the argv flag name for compatibility but covers both.
    need_read = bool(image_paths) or bool(doc_paths)
    argv = _build_claude_argv(
        claude_exe,
        session_id=session_id,
        allow_read_for_images=need_read,
        enable_thinking=thinking_enabled,
        enable_write=write_enabled,
        system_prompt_file=system_prompt_file,
        enable_web=_CLI_WEB_TOOLS_ENABLED,
    )

    new_session_id = ""
    usage: dict[str, Any] | None = None
    # Serialize CLI calls per-conversation. Without this, two browser tabs (or
    # a fast double-send) could spawn parallel `claude -p` processes both
    # using the same --resume id, racing on the server-side session state.
    # Lock is keyed by conversation_id so different conversations stay
    # parallel; anonymous conversations (no id) skip the lock entirely.
    lock: asyncio.Lock | None = _get_conversation_lock(conversation_id) if conversation_id else None
    # Track whether THIS task acquired the lock so we don't release it
    # on behalf of another task in the finally clause. asyncio.Lock.locked()
    # returns True for any holder, not just the current task — relying on
    # it to gate release() risked corrupting the lock state.
    lock_acquired = False
    try:
        if lock is not None:
            await lock.acquire()
            lock_acquired = True
            # Re-read the session id now that we hold the lock. A concurrent
            # first turn for this same (previously session-less) conversation
            # may have established a session while we waited; the read at the
            # top of this function happened BEFORE the lock, so without this
            # re-check we'd spawn a SECOND fresh session, orphan the first
            # one's session file, and overwrite its id in _CONVERSATION_SESSIONS.
            # Resume the established session instead (with a minimal prompt).
            if conversation_id and not is_resumed:
                _latest_session = _CONVERSATION_SESSIONS.get(conversation_id)
                if _latest_session:
                    session_id = _latest_session
                    is_resumed = True
                    argv = _build_claude_argv(
                        claude_exe,
                        session_id=session_id,
                        allow_read_for_images=need_read,
                        enable_thinking=thinking_enabled,
                        enable_write=write_enabled,
                        system_prompt_file=system_prompt_file,
                        enable_web=_CLI_WEB_TOOLS_ENABLED,
                    )
                    full_prompt = _build_full_prompt(
                        persona=persona,
                        user_context=user_context,
                        history=history,
                        history_limit=max_history_messages,
                        current_message=content,
                        image_paths=image_paths,
                        doc_paths=doc_paths,
                        is_resumed_session=True,
                        persona_in_system=persona_in_system,
                    )
        try:
            # Claim a pre-warmed process if one matches this exact argv (#1).
            # Falls back to a fresh spawn inside _run_claude_subprocess otherwise.
            warm_proc = _take_warm(conversation_id, argv)
            try:
                new_session_id, usage = await _run_claude_subprocess(
                    argv,
                    stdin_payload=full_prompt,
                    on_text_delta=on_text,
                    on_thinking_delta=on_thinking_text,
                    on_thinking_block_start=on_thinking_block_start,
                    on_thinking_block_stop=on_thinking_block_stop,
                    timeout=stream_timeout,
                    proc=warm_proc,
                )
            except RuntimeError as err:
                # Recovery path: the only RuntimeError we can fix automatically
                # is a stale --resume session id. Forget it, rebuild the prompt
                # with the full persona/history block (because Claude no longer
                # has the context server-side), and try once more.
                if isinstance(err, _StaleSessionError) and session_id:
                    logger.info(
                        "Claude session %s is stale for conversation %s — retrying fresh",
                        session_id,
                        conversation_id,
                    )
                    if conversation_id:
                        reset_session(conversation_id)
                    # Refetch context for the retry. The original build happened
                    # before the stale-session error fired; if the user mutated
                    # their profile in the meantime, the prompt we resend
                    # would otherwise carry the pre-mutation snapshot.
                    try:
                        fresh_user_context, _unused = await build_user_context(
                            user_name,
                            unrestricted_requested,
                            conversation_id=conversation_id,
                        )
                    except Exception:
                        logger.exception("build_user_context failed during stale-session retry")
                        fresh_user_context = user_context
                    fresh_prompt = _build_full_prompt(
                        persona=persona,
                        user_context=fresh_user_context,
                        history=history,
                        history_limit=max_history_messages,
                        current_message=content,
                        image_paths=image_paths,
                        doc_paths=doc_paths,
                        is_resumed_session=False,
                        persona_in_system=persona_in_system,
                    )
                    fresh_argv = _build_claude_argv(
                        claude_exe,
                        session_id=None,
                        allow_read_for_images=need_read,
                        enable_thinking=thinking_enabled,
                        enable_write=write_enabled,
                        system_prompt_file=system_prompt_file,
                        enable_web=_CLI_WEB_TOOLS_ENABLED,
                    )
                    # The first attempt may have streamed some text (to the
                    # client AND into full_response/full_thinking) before the
                    # stale-session error fired. Reset the accumulators so the
                    # retry's output isn't appended to the discarded first
                    # attempt — which would duplicate the saved DB body — and
                    # re-send stream_start so the dashboard clears the chunks it
                    # already rendered for this turn (its stream_start handler
                    # calls clearStreamBuffers()).
                    full_response = ""
                    full_thinking = ""
                    thinking_started = False
                    thinking_ended = False
                    await ws.send_json(
                        {
                            "type": "stream_start",
                            "mode": mode_label,
                            "conversation_id": conversation_id,
                        }
                    )
                    new_session_id, usage = await _run_claude_subprocess(
                        fresh_argv,
                        stdin_payload=fresh_prompt,
                        on_text_delta=on_text,
                        on_thinking_delta=on_thinking_text,
                        on_thinking_block_start=on_thinking_block_start,
                        on_thinking_block_stop=on_thinking_block_stop,
                        timeout=stream_timeout,
                    )
                else:
                    raise
        except TimeoutError:
            # The user turn is already in the DB but never reached the resumed
            # server-side session — leaving the session id in place would make
            # every later turn silently omit this message (resumed prompts skip
            # the history block). Drop the session so the next turn rebuilds the
            # full '# Conversation so far' block from the DB, which includes the
            # dangling row — the same recovery the stale-session retry performs.
            if conversation_id:
                reset_session(conversation_id)
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"Claude CLI timed out after {stream_timeout}s",
                    "conversation_id": conversation_id,
                }
            )
            return
        except _OverloadedError:
            # Transient server-side overload (HTTP 429/529). claude already
            # retried with backoff before giving up, so we don't re-spawn here —
            # we tell the user it's temporary and they can resend. Must precede
            # the generic ``except RuntimeError`` below (it's a subclass).
            logger.warning(
                "Claude CLI: Anthropic API overloaded for conversation %s; "
                "advising client to retry",
                conversation_id,
            )
            # See the TimeoutError handler: the failed user turn is in the DB
            # but not in the resumed session — drop the session so the next
            # turn's rebuilt history block carries it.
            if conversation_id:
                reset_session(conversation_id)
            await ws.send_json(
                {
                    "type": "error",
                    "message": (
                        "Anthropic's servers are temporarily overloaded. "
                        "Please resend your message in a moment."
                    ),
                    "conversation_id": conversation_id,
                }
            )
            return
        except RuntimeError as err:
            # ``str(err)`` can echo raw subprocess stderr, including argv,
            # absolute paths and env-derived diagnostics — log full detail
            # for operators but only surface a stable message to the client.
            logger.error("Claude CLI subprocess error: %s", err, exc_info=True)
            # Same DB/session desync as the timeout path — rebuild fresh next turn.
            if conversation_id:
                reset_session(conversation_id)
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Claude CLI failed; see server logs for details",
                    "conversation_id": conversation_id,
                }
            )
            return
        except Exception:
            logger.exception("Claude CLI streaming failed")
            # Same DB/session desync as the timeout path — rebuild fresh next turn.
            if conversation_id:
                reset_session(conversation_id)
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Claude CLI backend failed. Check logs.",
                    "conversation_id": conversation_id,
                }
            )
            return

        # Persist the session id while we STILL HOLD the per-conversation lock.
        # The finally below releases the lock and then awaits (attachment cleanup
        # + _emit_thinking_end); recording the session only after that release
        # opened a race where a queued concurrent first turn could acquire the
        # lock, re-read a still-None session, and spawn a SECOND fresh session —
        # the exact case the in-lock re-read near the top defends against.
        # _track_session is synchronous, so doing it here under the lock is atomic.
        if conversation_id and new_session_id:
            _track_session(conversation_id, new_session_id)
            # Pre-warm the next turn's process (#1). The common follow-up is a
            # plain-text turn in the same conversation + persona, so spawn that
            # exact argv now — booted and blocked on stdin — to hide its cold
            # start. Thinking is conversation-sticky in the frontend, so the
            # warm argv must carry THIS turn's value or it never matches in a
            # thinking conversation (one wasted ~150MB spawn per turn). A next
            # turn with attachments (or a flipped thinking toggle) simply won't
            # match and spawns fresh. Fire-and-forget; never blocks this turn.
            _schedule_prewarm(
                conversation_id,
                _build_claude_argv(
                    claude_exe,
                    session_id=new_session_id,
                    allow_read_for_images=False,
                    enable_thinking=thinking_enabled,
                    enable_write=write_enabled,
                    system_prompt_file=system_prompt_file,
                    enable_web=_CLI_WEB_TOOLS_ENABLED,
                ),
            )
    finally:
        if lock is not None and lock_acquired:
            lock.release()
        # Temp attachments aren't needed once the subprocess has been drained.
        # Run cleanup in a worker thread for the same reason as the writes.
        if image_paths and conversation_id:
            await asyncio.to_thread(_cleanup_image_dir, conversation_id)
        if doc_paths and conversation_id:
            await asyncio.to_thread(_cleanup_docs_dir, conversation_id)
        # Also delete THIS turn's own attachment files directly. The dir sweeps
        # above skip files <60s old (so a concurrent turn isn't robbed of its
        # inputs), which means a single-turn conversation would never clean up
        # its own just-written attachments. The subprocess is done with them.
        for _attach in (*image_paths, *(doc_paths or [])):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(_attach.unlink)
        # Close the 💭 panel on any exit path that didn't already close it via
        # on_thinking_block_stop (error/timeout returns before reasoning ended,
        # or a backend that never fires block-stop). Idempotent —
        # _emit_thinking_end no-ops if it already ran on this turn.
        await _emit_thinking_end()

    # (session id is persisted above under the per-conversation lock, just
    # before the finally releases it — see the _track_session call there.)

    # (thinking_end is emitted in the finally above so it also fires on the
    # error/timeout return paths — see the panel-close block there.)

    # Strip Claude Code internal XML markup that occasionally leaks into
    # output (e.g. orphan ``</system-reminder>`` tags), then strip a
    # leading ISO timestamp prefix if the model mimicked the
    # historical-message format. Both pieces of housekeeping must
    # happen BEFORE the response is persisted so the saved history
    # doesn't carry the leaked markup into future turns.
    full_response = strip_claude_internal_tags(full_response)
    full_response = strip_leading_timestamp(full_response)

    assistant_msg_id = 0
    if DB_AVAILABLE and conversation_id and full_response:
        try:
            db = get_db()
            assistant_msg_id = await db.save_dashboard_message(
                conversation_id,
                "assistant",
                full_response,
                thinking=full_thinking if full_thinking else None,
                mode=mode_label,
            )
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
        except Exception:
            logger.exception("Failed to save assistant message (CLI backend)")

    # Token usage: prefer the CLI's actual numbers, fall back to a 4-char
    # estimate only if the result event was missing (defensive — the official
    # CLI does emit usage on every run, but we don't want zero token bars).
    if usage:
        # Claude bills three flavors of input: fresh input, cache-creation
        # writes (full price, ~25% premium for 5m / 100% for 1h), and
        # cache reads (~10% of fresh price). We sum all three so the UI
        # token bar reflects what's actually being charged.
        # output_tokens already includes any extended-thinking tokens
        # (Anthropic bills thinking as output), so no extra addition.
        # `... or 0` (not `.get(k, 0)`): the raw CLI result JSON can carry these
        # keys with an explicit null, and `.get(k, 0)` returns that None — so
        # `int(None)` would raise TypeError here, outside any try/except, after
        # the reply is already streamed+persisted, hanging the UI with no
        # terminal stream_end frame. The SDK backend guards the same fields.
        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        in_tok = int(usage.get("input_tokens") or 0) + cache_read + cache_creation
        out_tok = int(usage.get("output_tokens") or 0)
    else:
        cache_creation = 0
        cache_read = 0
        in_tok = max(1, len(full_prompt) // 4)
        out_tok = max(1, len(full_response) // 4)

    # `chunks_count` mirrors the SDK backend's payload — frontend doesn't
    # currently render it, but emitting it keeps the event shape parity so
    # future UI changes work uniformly across both backends.
    await ws.send_json(
        {
            "type": "stream_end",
            "conversation_id": conversation_id,
            "full_response": full_response,
            "user_message_id": user_msg_id,
            "assistant_message_id": assistant_msg_id or None,
            "chunks_count": len(full_response),
            "token_usage": {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "context_window": CLAUDE_CONTEXT_WINDOW,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
        }
    )

    # End breadcrumb — pairs with the start log above. Error paths already
    # log via ``logger.exception`` / ``logger.error`` and return early, so
    # only the happy path needs an explicit done line. Duration is wall-clock
    # from after CLI-readiness check; tokens come from the ``result`` event.
    logger.info(
        "✅ chat-cli done conv=%s duration=%.1fs in=%d out=%d response_len=%d session=%s",
        conversation_id,
        time.monotonic() - start_ts,
        in_tok,
        out_tok,
        len(full_response),
        (new_session_id or "")[:8] or "none",
    )


# ============================================================================
# AI Edit (`/edit`) support — same SEARCH/REPLACE protocol as the SDK backend
# ============================================================================

_SEARCH_REPLACE_RE = re.compile(
    r"<<<SEARCH\s*\n(.*?)\n?>>>\s*\n<<<REPLACE\s*\n(.*?)\n?>>>",
    re.DOTALL,
)


def _apply_search_replace(original: str, ai_response: str) -> str:
    """Apply <<<SEARCH/<<<REPLACE patches to `original`.

    Identical algorithm to the SDK backend's _apply_search_replace so toggling
    CLAUDE_BACKEND doesn't change the edit semantics. If no patches are
    present we treat the whole AI reply as a full rewrite.
    """
    matches = list(_SEARCH_REPLACE_RE.finditer(ai_response))
    if not matches:
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
            stripped = search_text.strip()
            if stripped and stripped in result:
                if result.count(stripped) > 1:
                    logger.warning("Multiple SEARCH matches; ambiguous, skipping replace")
                    continue
                result = result.replace(stripped, replace_text.strip(), 1)
                applied += 1
            else:
                logger.warning("AI Edit (CLI): SEARCH block not found: %r", search_text[:100])

    if applied > 0:
        return result
    logger.warning("AI Edit (CLI): no patches matched, falling back to full response")
    return ai_response


async def handle_ai_edit_message_claude_cli(
    ws: WebSocketResponse,
    data: dict[str, Any],
    claude_client: Any,
    *,
    max_history_messages: int = 100,
    stream_timeout: int = 300,
) -> None:
    """AI-edit a previous assistant message via ``claude -p``.

    Mirrors the SDK backend's edit flow:
      1. Pull the target assistant message from the DB
      2. Ask Claude to rewrite it using SEARCH/REPLACE patches
      3. Apply the patches and persist the new content
    """
    del claude_client  # signature parity only

    conversation_id = data.get("conversation_id")
    target_message_id = data.get("target_message_id")
    instruction = (data.get("instruction") or "").strip()
    role_preset = data.get("role_preset", "general")
    user_name = data.get("user_name", "User")
    thinking_enabled = bool(data.get("thinking_enabled"))

    # Match the chat handler: thinking-mode edits also need the longer
    # budget so the API has time to actually reason before responding.
    if thinking_enabled and stream_timeout < _THINKING_STREAM_TIMEOUT:
        stream_timeout = _THINKING_STREAM_TIMEOUT

    # Same alphanumeric/-/_ allowlist that the chat handler enforces (above).
    # Without this, a malformed id from the AI-edit path would land in the
    # session map and conversation lock dict before the chat path's regex
    # had a chance to reject it — desync between the two state stores.
    if not isinstance(conversation_id, str) or not re.match(
        r"^[a-zA-Z0-9_\-]{1,128}\Z", conversation_id
    ):
        await ws.send_json(
            {
                "type": "error",
                "message": "Invalid conversation ID",
                "conversation_id": conversation_id,
            }
        )
        return

    if not target_message_id or not instruction:
        await ws.send_json(
            {
                "type": "error",
                "message": "Missing data for AI edit",
                "conversation_id": conversation_id,
            }
        )
        return

    ready, reason = is_cli_backend_ready()
    if not ready:
        await ws.send_json({"type": "error", "message": reason, "conversation_id": conversation_id})
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {"type": "error", "message": "Database unavailable", "conversation_id": conversation_id}
        )
        return

    # Look up the target message for the original content + sanity checks.
    try:
        db = get_db()
        target_id_int = int(target_message_id)
        all_msgs = await db.get_dashboard_messages(conversation_id)
        target_msg = next((m for m in all_msgs if m.get("id") == target_id_int), None)
    except Exception:
        logger.exception("Failed to load target message for AI edit (CLI backend)")
        await ws.send_json(
            {
                "type": "error",
                "message": "Failed to load message",
                "conversation_id": conversation_id,
            }
        )
        return

    if not target_msg:
        await ws.send_json(
            {
                "type": "error",
                "message": "Target message not found",
                "conversation_id": conversation_id,
            }
        )
        return
    if target_msg.get("role") != "assistant":
        await ws.send_json(
            {
                "type": "error",
                "message": "Can only AI-edit assistant messages",
                "conversation_id": conversation_id,
            }
        )
        return

    original_content = target_msg.get("content", "")
    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])
    persona = str(preset.get("system_instruction", ""))

    try:
        user_context, _ = await build_user_context(
            user_name,
            False,
            conversation_id=conversation_id,
        )
    except Exception:
        logger.exception("build_user_context failed (CLI edit)")
        user_context = f"Name: {user_name}"

    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

    # Same prompt template as dashboard_chat_claude.py so the patch dialect
    # matches and _apply_search_replace stays correct on either backend.
    edit_prompt = (
        f"# Persona\n{persona}\n\n"
        f"# Context\n{user_context}\n"
        f"Current Time: {current_time_str} (ICT)\n\n"
        "# Task\n"
        "Edit the following message according to the user's instruction.\n\n"
        f"[User's Edit Instruction]\n{instruction}\n\n"
        f"[Original Message]\n{original_content}\n\n"
        "RESPONSE FORMAT:\n"
        "If the edit is a PARTIAL change, respond with one or more SEARCH/REPLACE blocks:\n"
        "<<<SEARCH\n"
        "exact text to find\n"
        ">>>\n"
        "<<<REPLACE\n"
        "new text to replace with\n"
        ">>>\n\n"
        "If the edit requires a FULL rewrite, respond with JUST the new message content.\n"
        "RULES:\n"
        "- For partial edits: only include the parts that change.\n"
        "- For full rewrites: output the complete new message directly.\n"
        "- No explanations or meta-commentary."
    )

    edit_mode_info: list[str] = [f"🟣 Claude Code CLI ({CLAUDE_MODEL})", "✏️ AI Edit"]
    if thinking_enabled:
        edit_mode_info.append("🧠 Thinking")
    mode_label = " • ".join(edit_mode_info)
    await ws.send_json(
        {
            "type": "stream_start",
            "mode": mode_label,
            "is_edit": True,
            "target_message_id": target_id_int,
            "conversation_id": conversation_id,
        }
    )

    edit_response = ""
    edit_thinking = ""
    thinking_started = False
    thinking_ended = False

    async def on_text(text: str) -> None:
        nonlocal edit_response
        edit_response += text
        await ws.send_json(
            {
                "type": "chunk",
                "content": text,
                "conversation_id": conversation_id,
            }
        )

    async def on_thinking_text(text: str) -> None:
        nonlocal edit_thinking, thinking_started
        if not thinking_enabled:
            return
        if not thinking_started:
            thinking_started = True
            await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})
        edit_thinking += text
        await ws.send_json(
            {
                "type": "thinking_chunk",
                "content": text,
                "conversation_id": conversation_id,
            }
        )

    async def on_thinking_block_start() -> None:
        nonlocal thinking_started
        if not thinking_enabled or thinking_started:
            return
        thinking_started = True
        await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})

    async def _emit_thinking_end() -> None:
        """Emit thinking_end once, collapsing the 💭 panel (idempotent)."""
        nonlocal thinking_ended, edit_thinking
        if not thinking_started or thinking_ended:
            return
        thinking_ended = True
        if not edit_thinking:
            edit_thinking = (
                "💭 Claude reasoned through this internally. The Claude Code "
                "subscription redacts thought content from headless output — "
                "switch to CLAUDE_BACKEND=api with an Anthropic API key to "
                "see the full thought process."
            )
        with contextlib.suppress(Exception):
            await ws.send_json(
                {
                    "type": "thinking_end",
                    "full_thinking": edit_thinking,
                    "conversation_id": conversation_id,
                }
            )

    async def on_thinking_block_stop() -> None:
        # Collapse the 💭 panel the moment reasoning ends (parity with the SDK
        # backend and the chat handler) instead of waiting for end-of-turn.
        await _emit_thinking_end()

    claude_exe = _resolve_claude_executable() or "claude"
    # Edits don't use the conversation's session id — they're a one-shot
    # transformation, not a continuation of the chat.
    argv = _build_claude_argv(
        claude_exe,
        session_id=None,
        allow_read_for_images=False,
        allow_edit_tools=True,
        enable_thinking=thinking_enabled,
    )

    # Serialize against concurrent chat sends in the same conversation: an
    # edit and a chat reply both spawn `claude -p` and would otherwise race.
    edit_lock = _get_conversation_lock(conversation_id) if conversation_id else None
    # Track whether THIS task acquired the lock; ``edit_lock.locked()`` is
    # True for any holder, so using it to gate ``release()`` could release
    # a different task's lock if our acquire() raised (e.g. CancelledError).
    edit_lock_acquired = False
    # The /edit run is a one-shot fresh session (session_id=None above) that is
    # never recorded in _CONVERSATION_SESSIONS, so neither delete_session_file
    # nor LRU eviction would ever remove its .jsonl. Capture the returned id and
    # unlink the log in the finally so each edit doesn't orphan one session file.
    edit_session_id: str | None = None
    try:
        if edit_lock is not None:
            await edit_lock.acquire()
            edit_lock_acquired = True
        try:
            edit_session_id, usage = await _run_claude_subprocess(
                argv,
                stdin_payload=edit_prompt,
                on_text_delta=on_text,
                on_thinking_delta=on_thinking_text,
                on_thinking_block_start=on_thinking_block_start,
                on_thinking_block_stop=on_thinking_block_stop,
                timeout=stream_timeout,
            )
        except TimeoutError:
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"Claude CLI edit timed out after {stream_timeout}s",
                    "conversation_id": conversation_id,
                }
            )
            return
        except _OverloadedError:
            # Parity with the chat handler: a transient 429/529 overload raises
            # _OverloadedError (a RuntimeError subclass), so it MUST precede the
            # generic RuntimeError below and surface the actionable retry message.
            logger.warning(
                "Claude CLI edit: Anthropic API overloaded for conversation %s; "
                "advising client to retry",
                conversation_id,
            )
            await ws.send_json(
                {
                    "type": "error",
                    "message": (
                        "Anthropic's servers are temporarily overloaded. "
                        "Please resend your message in a moment."
                    ),
                    "conversation_id": conversation_id,
                }
            )
            return
        except RuntimeError as err:
            # See chat handler: avoid leaking raw subprocess stderr to the
            # client; log full detail for operators.
            logger.error("Claude CLI edit subprocess error: %s", err, exc_info=True)
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Claude CLI edit failed; see server logs for details",
                    "conversation_id": conversation_id,
                }
            )
            return
        except Exception:
            logger.exception("Claude CLI edit failed")
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Claude CLI edit backend failed. Check logs.",
                    "conversation_id": conversation_id,
                }
            )
            return
    finally:
        if edit_lock is not None and edit_lock_acquired:
            edit_lock.release()
        # Close the 💭 panel on any exit path that didn't already close it via
        # on_thinking_block_stop. Idempotent — _emit_thinking_end no-ops if it
        # already ran on this turn.
        await _emit_thinking_end()
        # Clean up the ephemeral edit session's log file. The subprocess has
        # fully exited by now so the .jsonl is complete; _unlink_session_file_by_id
        # validates the id and no-ops on None, so error paths (where it stays
        # None) are harmless. Best-effort — never let cleanup break the response.
        with contextlib.suppress(Exception):
            await _unlink_session_file_by_id(edit_session_id)

    # Strip Claude Code internal markup before the SEARCH/REPLACE
    # parser sees it. Otherwise a leaked ``</system-reminder>`` inside
    # an AI patch block would survive into the saved message body.
    new_content = _apply_search_replace(
        original_content,
        strip_claude_internal_tags(edit_response.strip()),
    )

    # Guard against blanking the original message: if the patcher returned
    # an empty/whitespace-only result (no SEARCH/REPLACE blocks matched and
    # the model produced nothing useful) we keep the original rather than
    # silently destroying user content.
    if not new_content or not new_content.strip():
        logger.warning(
            "AI edit produced empty content for message %d — keeping original",
            target_id_int,
        )
        # The stream_end below echoes new_content as full_response and the
        # client renders it unconditionally — sending "" blanked the bubble
        # while the DB kept the original (UI/DB desync until reload).
        new_content = original_content
    else:
        # Persist the rewritten message. Pass conversation_id so the UPDATE only
        # matches when the row is in the conversation the AI was editing —
        # prevents an attacker (or a bug) from coercing this path into
        # rewriting messages in a different conversation.
        try:
            db = get_db()
            await db.update_dashboard_message(
                target_id_int,
                new_content,
                expected_conversation_id=conversation_id,
            )
        except Exception:
            logger.exception("Failed to update AI-edited message (CLI backend)")
        else:
            # The cached --resume session replays the OLD content server-side;
            # wipe it after a successful rewrite (manual edit/delete already
            # does this via dashboard_handlers).
            try:
                await delete_session_file(conversation_id)
            except Exception:
                logger.exception("Failed to reset CLI session after AI edit")

    if usage:
        # `... or 0` (not `.get(k, 0)`): the raw CLI result JSON can carry these
        # keys with an explicit null, and `.get(k, 0)` returns that None — so
        # `int(None)` would raise TypeError here, outside any try/except, after
        # the reply is already streamed+persisted, hanging the UI with no
        # terminal stream_end frame. The SDK backend guards the same fields.
        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        in_tok = int(usage.get("input_tokens") or 0) + cache_read + cache_creation
        out_tok = int(usage.get("output_tokens") or 0)
    else:
        cache_creation = 0
        cache_read = 0
        in_tok = max(1, len(edit_prompt) // 4)
        out_tok = max(1, len(edit_response) // 4)

    await ws.send_json(
        {
            "type": "stream_end",
            "conversation_id": conversation_id,
            "full_response": new_content,
            "is_edit": True,
            "target_message_id": target_id_int,
            "chunks_count": len(edit_response),
            "token_usage": {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "context_window": CLAUDE_CONTEXT_WINDOW,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
        }
    )
