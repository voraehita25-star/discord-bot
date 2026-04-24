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
  ✗ `--temperature` / `--max-tokens` — Claude Code CLI does not expose these
  ✗ API failover (`direct ↔ proxy`) — N/A for subscription auth
  ✗ Prompt-cache stats display (CLI does not surface cache_read counts)

Toggle: set ``CLAUDE_BACKEND=cli`` in .env to use this module; anything else
(or unset) keeps the original SDK-based path.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
logger = logging.getLogger(__name__)
import os
import re
import shutil
import time
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
    strip_leading_timestamp,
)
from .dashboard_config import (
    CLAUDE_CONTEXT_WINDOW,
    CLAUDE_MODEL,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
)

# Per-conversation Claude session id. Loaded from _SESSIONS_FILE at import
# time and re-saved on every change — persistence lets us find and delete the
# right .jsonl when the user deletes a Dashboard conversation after a restart.
_CONVERSATION_SESSIONS: dict[str, str] = {}

# Bound the conversation→session map so a long-running bot doesn't accumulate
# entries forever. We evict oldest insertion order on overflow.
_MAX_TRACKED_SESSIONS = 500

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


def _encode_claude_project_dirname(path: Path) -> str:
    """Replicate Claude Code's path encoding for its session-log folder.

    Claude Code stores `~/.claude/projects/<encoded>/<session-id>.jsonl`
    where `<encoded>` replaces `:`, `\\`, `/`, and space with `-`:
        `c:\\Users\\ME\\BOT Discord`  →  `c--Users-ME-BOT-Discord`
    We need the same encoding to locate the session file to delete.
    """
    s = str(path)
    for ch in (":", "\\", "/", " "):
        s = s.replace(ch, "-")
    return s


def _claude_projects_folder() -> Path:
    """Folder where Claude Code writes .jsonl logs for our dedicated CWD."""
    return Path.home() / ".claude" / "projects" / _encode_claude_project_dirname(_CLAUDE_CLI_WORKDIR)


def _load_persisted_sessions() -> None:
    """Populate _CONVERSATION_SESSIONS from the sidecar JSON on import.

    Silently ignores missing/corrupt files — worst case we fail to delete
    old .jsonl files when conversations are deleted (cosmetic only).
    """
    try:
        if not _SESSIONS_FILE.exists():
            return
        raw = _SESSIONS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                _CONVERSATION_SESSIONS[k] = v
    except Exception:
        logger.exception("Failed to load persisted Claude CLI session map")


def _save_persisted_sessions() -> None:
    """Atomically rewrite the sidecar JSON.

    Failure is non-fatal — persistence is a nice-to-have, not critical.
    """
    try:
        _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SESSIONS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_CONVERSATION_SESSIONS, indent=2), encoding="utf-8")
        tmp.replace(_SESSIONS_FILE)
    except Exception:
        logger.exception("Failed to save Claude CLI session map")


def delete_session_file(conversation_id: str) -> bool:
    """Remove the Claude Code .jsonl for a dashboard conversation.

    Called from the delete-conversation handler so the CLI session log
    doesn't linger after the user deletes the chat in the dashboard.
    Returns True if a file was actually deleted.
    """
    session_id = _CONVERSATION_SESSIONS.pop(conversation_id, None)
    _save_persisted_sessions()
    if not session_id:
        return False
    try:
        target = _claude_projects_folder() / f"{session_id}.jsonl"
        if target.exists():
            target.unlink()
            logger.info("Deleted Claude CLI session file for conv %s", conversation_id)
            return True
    except Exception:
        logger.exception("Failed to delete session file for conv %s", conversation_id)
    return False


# Load persisted state once at import so sync-delete works across restarts.
_load_persisted_sessions()

# Per-conversation lock: serializes outbound CLI calls so two messages in the
# SAME conversation can't spawn parallel `claude -p` processes that both try
# to --resume the same session id (which would either race on the server side
# or corrupt the session ordering). Different conversations remain parallel
# — the lock is keyed by conversation_id, not global. Cleaned up alongside
# session ids when a conversation is reset/deleted.
_CONVERSATION_LOCKS: dict[str, asyncio.Lock] = {}


def _get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    """Return (creating if needed) the per-conversation send lock."""
    lock = _CONVERSATION_LOCKS.get(conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _CONVERSATION_LOCKS[conversation_id] = lock
    return lock

# Where to drop temp image files Claude reads via the Read tool.
_TEMP_IMAGE_ROOT = Path(__file__).resolve().parents[3] / "data" / "tmp" / "dashboard_cli_images"

# Allowed image MIME types — must match what the SDK backend accepts so users
# don't get inconsistent behavior across the toggle.
_SUPPORTED_IMAGE_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
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
    # Pop first (if present) so the re-insert below puts the entry at the
    # end of insertion order. Without this, dict[key] = value keeps the
    # original position and a long-active conversation would be evicted
    # ahead of recently-touched ones.
    _CONVERSATION_SESSIONS.pop(conversation_id, None)
    if len(_CONVERSATION_SESSIONS) >= _MAX_TRACKED_SESSIONS:
        oldest = next(iter(_CONVERSATION_SESSIONS))
        _CONVERSATION_SESSIONS.pop(oldest, None)
    _CONVERSATION_SESSIONS[conversation_id] = session_id
    _save_persisted_sessions()


def reset_session(conversation_id: str) -> None:
    """Forget the Claude session for a conversation (e.g. after a reload).

    Exposed so the WS server can call this when the user loads a conversation
    fresh from the database — the in-memory session would be stale relative
    to the DB-loaded message list. Also drops the per-conversation send lock
    so it doesn't accumulate forever in a long-running bot.
    """
    if _CONVERSATION_SESSIONS.pop(conversation_id, None) is not None:
        _save_persisted_sessions()
    # Only drop the lock if it's not currently held. If it IS held a delete
    # would orphan the in-flight waiter; let the next finished holder be the
    # one to clean up via the natural eviction path.
    lock = _CONVERSATION_LOCKS.get(conversation_id)
    if lock is not None and not lock.locked():
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

    safe_conv = re.sub(r"[^A-Za-z0-9_\-]", "_", conversation_id)[:64]
    target_dir = _TEMP_IMAGE_ROOT / safe_conv
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    timestamp = int(time.time() * 1000)
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
        except (ValueError, base64.binascii.Error):
            continue
        # Enforce per-image size cap to mirror the SDK backend's safety net.
        # Without this an attacker (or a misclick) could push a 100 MB image
        # through and balloon both disk usage and Claude's input cost.
        if len(data) > max_size_bytes:
            logger.warning(
                "Dropping oversized image attachment (%d bytes > %d cap)",
                len(data), max_size_bytes,
            )
            continue
        path = target_dir / f"{timestamp}_{idx}{ext}"
        path.write_bytes(data)
        written.append(path)
    return written


def _cleanup_image_dir(conversation_id: str) -> None:
    """Best-effort cleanup of the per-conversation temp image dir."""
    if not conversation_id:
        return
    safe_conv = re.sub(r"[^A-Za-z0-9_\-]", "_", conversation_id)[:64]
    target_dir = _TEMP_IMAGE_ROOT / safe_conv
    with contextlib.suppress(Exception):
        if target_dir.exists():
            for p in target_dir.iterdir():
                with contextlib.suppress(Exception):
                    p.unlink()
            with contextlib.suppress(Exception):
                target_dir.rmdir()


def _build_full_prompt(
    persona: str,
    user_context: str,
    memories_context: str,
    history: list[dict[str, Any]],
    history_limit: int,
    current_message: str,
    image_paths: list[Path],
    is_resumed_session: bool,
) -> str:
    """Compose the prompt body sent to ``claude -p`` via stdin.

    When ``is_resumed_session`` is True the persona/history headers are
    omitted because Claude already has them in the resumed session — sending
    them again would waste the prompt cache and inflate token usage.
    """
    parts: list[str] = []

    if not is_resumed_session:
        parts.append(f"# Persona\n{persona}")
        if user_context:
            parts.append(f"# Context\n{user_context}{memories_context}")
        history_block = _build_history_block(history, history_limit)
        if history_block:
            parts.append(f"# Conversation so far\n{history_block}")

    if image_paths:
        path_lines = "\n".join(f"- {p}" for p in image_paths)
        parts.append(
            "# Attached images\n"
            "The user attached the following image file(s). Use the Read tool "
            "to view them as needed before answering.\n"
            f"{path_lines}"
        )

    # Inject the timestamp inline so Claude knows when the message was sent
    # (matches the SDK backend's behavior). The DB stores the raw content,
    # so this prefix never reaches the dashboard UI.
    timestamp = bangkok_now_iso()
    parts.append(f"# Current user message\n[{timestamp}] {current_message}")
    return "\n\n".join(parts)


def _build_history_block(history: list[dict[str, Any]], limit: int) -> str:
    """Render at most ``limit`` recent messages as plain text."""
    if not history:
        return ""
    recent = history[-limit:]
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "user")
        text = str(msg.get("content", ""))
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _make_subprocess_env() -> dict[str, str]:
    """Build the env for the `claude` subprocess.

    Strip ANTHROPIC_API_KEY: the CLI's auth-resolution order puts the API key
    ahead of the subscription OAuth token, so leaving it in would silently
    fall back to per-token billing — defeating the whole point of CLI mode.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _build_claude_argv(
    claude_exe: str,
    *,
    session_id: str | None,
    allow_read_for_images: bool,
    allow_edit_tools: bool = False,
    enable_thinking: bool = False,
) -> list[str]:
    """Construct the argv for the `claude -p` invocation.

    When ``enable_thinking`` is True we pass ``--effort max`` and the
    ``interleaved-thinking`` beta header. This makes Opus 4.7 actually
    reason internally; the *content* of that reasoning is still redacted
    by Anthropic in subscription mode (only the start/stop markers reach
    us), but the model spends real reasoning effort which improves answer
    quality on hard questions.
    """
    argv: list[str] = [
        claude_exe, "-p",
        "--output-format", "stream-json",
        "--input-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--model", CLAUDE_MODEL,
    ]
    if enable_thinking:
        argv.extend(["--effort", "max", "--betas", "interleaved-thinking"])
    if session_id:
        argv.extend(["--resume", session_id])
    # Tools allow-list: zero by default (pure chat — fastest, no surprises).
    # Images require Read so Claude can view the temp files. /edit also uses
    # zero tools — Claude just emits SEARCH/REPLACE text in its reply.
    del allow_edit_tools  # currently identical to default; kept for future expansion
    tools = "Read" if allow_read_for_images else ""
    argv.extend(["--allowedTools", tools])
    return argv


async def _run_claude_subprocess(
    argv: list[str],
    stdin_payload: str,
    *,
    on_text_delta: Any,
    on_thinking_delta: Any,
    on_thinking_block_start: Any = None,
    on_thinking_block_stop: Any = None,
    timeout: float,
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

    Sends `stdin_payload` as a single stream-json message:
        {"type":"user","message":{"role":"user","content":[{"type":"text","text":...}]}}
    then closes stdin so Claude knows there's no more input.
    """
    env = _make_subprocess_env()
    # Spawn from a dedicated workdir so Claude Code's session .jsonl files
    # land in their own `~/.claude/projects/<encoded-cwd>/` folder instead
    # of mixing with the user's own Claude Code sessions for the bot repo.
    _CLAUDE_CLI_WORKDIR.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(_CLAUDE_CLI_WORKDIR),
    )

    # stream-json input format expects one JSON message per line on stdin.
    user_msg = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": stdin_payload}],
        },
    }
    assert proc.stdin is not None
    try:
        proc.stdin.write((json.dumps(user_msg) + "\n").encode("utf-8"))
        await proc.stdin.drain()
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()

    final_session_id = ""
    final_usage: dict[str, Any] | None = None

    async def consume_stdout() -> None:
        nonlocal final_session_id, final_usage
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
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
            # subscription policy.
            if inner_type == "content_block_start":
                cb = inner.get("content_block") or {}
                if isinstance(cb, dict) and cb.get("type") == "thinking" and on_thinking_block_start is not None:
                    await on_thinking_block_start()
                continue
            if inner_type == "content_block_stop":
                # We don't know which block stopped without tracking indices,
                # but for chat we never have multiple thinking blocks in one
                # turn, so any stop after a thinking_start is fine.
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
                    await on_text_delta(text)
            elif dtype == "thinking_delta":
                thinking = delta.get("thinking", "")
                if thinking and on_thinking_delta is not None:
                    await on_thinking_delta(thinking)

    try:
        await asyncio.wait_for(consume_stdout(), timeout=timeout)
        # Bound proc.wait() too — a misbehaving CLI could close stdout while
        # holding on to the process, hanging this coroutine indefinitely.
        # 5s is generous: by the time stdout closes, exit is normally instant.
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            logger.warning("claude -p didn't exit 5s after stdout closed; killing")
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            rc = await proc.wait()
        if rc != 0:
            stderr_text = ""
            if proc.stderr is not None:
                err_bytes = await proc.stderr.read()
                stderr_text = err_bytes.decode("utf-8", errors="replace")[:500]
            logger.error("claude -p failed (exit %d): %s", rc, stderr_text)
            # Mark stale-session errors so the caller can transparently retry
            # without the bad --resume id instead of bouncing the error to
            # the user.
            err_msg = f"claude -p exit {rc}: {stderr_text[:200]}"
            err = RuntimeError(err_msg)
            lower = stderr_text.lower()
            if (
                "--resume" in lower
                or "session id" in lower
                or "is not a uuid" in lower
                or "does not match any session" in lower
            ):
                err.is_stale_session = True  # type: ignore[attr-defined]
            raise err
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()

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
    stream_timeout: int = 300,
) -> None:
    """Stream a dashboard chat reply via ``claude -p`` (subscription billing)."""
    del claude_client  # signature parity only

    conversation_id = data.get("conversation_id")
    raw_content = data.get("content", "")
    content = (raw_content if isinstance(raw_content, str) else "").strip()
    role_preset = data.get("role_preset", "general")
    history = data.get("history") or []
    user_name = data.get("user_name", "User")
    unrestricted_requested = bool(data.get("unrestricted_mode"))
    thinking_enabled = bool(data.get("thinking_enabled"))
    images_raw = data.get("images") or []

    if not content:
        await ws.send_json({"type": "error", "message": "Empty message", "conversation_id": conversation_id})
        return

    if len(content) > max_content_length:
        await ws.send_json({
            "type": "error",
            "message": f"Message too long (>{max_content_length} chars)",
            "conversation_id": conversation_id,
        })
        return

    ready, reason = is_cli_backend_ready()
    if not ready:
        await ws.send_json({"type": "error", "message": reason, "conversation_id": conversation_id})
        return

    # Cap image count to mirror the SDK backend's safety net.
    capped_images = images_raw[:max_images] if isinstance(images_raw, list) else []

    # Save the user's turn to the DB up front, mirroring the SDK backend so
    # the conversation log stays consistent across backend toggles.
    # IMPORTANT: store the raw content — the [timestamp] prefix is for the AI
    # only and gets injected into the prompt below. Persisting it would make
    # the dashboard render `[2026-04-23T...] hello` to the user, which is
    # the bug previously observed in CLI mode.
    user_msg_id: int | None = None
    if DB_AVAILABLE and conversation_id:
        try:
            db = get_db()
            # Don't pass `mode=` for user turns — SDK backend omits it too;
            # the mode badge is conceptually the assistant's reply attribute.
            user_msg_id = await db.save_dashboard_message(
                conversation_id, "user", content,
                images=capped_images if capped_images else None,
            )
        except Exception:
            logger.exception("Failed to save user message (CLI backend)")

    # Decode + persist images to disk so Claude can Read them by path.
    image_paths = (
        _save_inline_images(conversation_id or "default", capped_images, max_image_size_bytes)
        if capped_images
        else []
    )

    # Build the prompt
    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])
    persona = str(preset.get("system_instruction", ""))
    if unrestricted_requested:
        framing = preset.get("unrestricted_framing", "")
        if framing:
            persona = f"{framing}\n\n{persona}"

    session_id = _CONVERSATION_SESSIONS.get(conversation_id or "") if conversation_id else None
    is_resumed = bool(session_id)

    # Skip the user-context DB query on resumed turns — the persona/context
    # block is only injected on the first turn of a session, so the lookup
    # would be wasted work (and an extra round trip to SQLite) otherwise.
    if is_resumed:
        user_context, memories_context = "", ""
    else:
        try:
            user_context, memories_context, _unused = await build_user_context(
                user_name, unrestricted_requested,
            )
        except Exception:
            logger.exception("build_user_context failed (CLI backend)")
            user_context, memories_context = f"Name: {user_name}", ""

    # Inject a persona+history header only on the first turn of the session.
    # Resumed sessions already have everything cached on the Claude side.
    full_prompt = _build_full_prompt(
        persona=persona,
        user_context=user_context,
        memories_context=memories_context,
        history=history,
        history_limit=max_history_messages,
        current_message=content,
        image_paths=image_paths,
        is_resumed_session=is_resumed,
    )

    # Match the SDK backend's mode-label format so the badge always tells
    # the user what's actually active (model, thinking, unrestricted, images).
    mode_info: list[str] = [f"🟣 Claude Code CLI ({CLAUDE_MODEL})"]
    if thinking_enabled:
        mode_info.append("🧠 Thinking")
    if unrestricted_requested:
        mode_info.append("🔓 Unrestricted")
    if image_paths:
        mode_info.append(f"🖼️ {len(image_paths)} image(s)")
    mode_label = " • ".join(mode_info)
    await ws.send_json({
        "type": "stream_start",
        "mode": mode_label,
        "conversation_id": conversation_id,
    })

    full_response = ""
    full_thinking = ""
    thinking_started = False

    async def on_text(text: str) -> None:
        nonlocal full_response
        full_response += text
        await ws.send_json({
            "type": "chunk",
            "content": text,
            "conversation_id": conversation_id,
        })

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
        await ws.send_json({
            "type": "thinking_chunk",
            "content": text,
            "conversation_id": conversation_id,
        })

    async def on_thinking_block_start() -> None:
        # Fires when Claude opens a reasoning block, even in subscription
        # mode where the content itself is hidden. Use this to surface the
        # "💭 Thinking…" panel so the user sees that reasoning is happening.
        nonlocal thinking_started
        if not thinking_enabled or thinking_started:
            return
        thinking_started = True
        await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})

    claude_exe = _resolve_claude_executable() or "claude"
    argv = _build_claude_argv(
        claude_exe,
        session_id=session_id,
        allow_read_for_images=bool(image_paths),
        enable_thinking=thinking_enabled,
    )

    new_session_id = ""
    usage: dict[str, Any] | None = None
    # Serialize CLI calls per-conversation. Without this, two browser tabs (or
    # a fast double-send) could spawn parallel `claude -p` processes both
    # using the same --resume id, racing on the server-side session state.
    # Lock is keyed by conversation_id so different conversations stay
    # parallel; anonymous conversations (no id) skip the lock entirely.
    lock: asyncio.Lock | None = (
        _get_conversation_lock(conversation_id) if conversation_id else None
    )
    try:
        if lock is not None:
            await lock.acquire()
        try:
            try:
                new_session_id, usage = await _run_claude_subprocess(
                    argv,
                    stdin_payload=full_prompt,
                    on_text_delta=on_text,
                    on_thinking_delta=on_thinking_text,
                    on_thinking_block_start=on_thinking_block_start,
                    timeout=stream_timeout,
                )
            except RuntimeError as err:
                # Recovery path: the only RuntimeError we can fix automatically
                # is a stale --resume session id. Forget it, rebuild the prompt
                # with the full persona/history block (because Claude no longer
                # has the context server-side), and try once more.
                if getattr(err, "is_stale_session", False) and session_id:
                    logger.info(
                        "Claude session %s is stale for conversation %s — retrying fresh",
                        session_id, conversation_id,
                    )
                    if conversation_id:
                        reset_session(conversation_id)
                    fresh_prompt = _build_full_prompt(
                        persona=persona,
                        user_context=user_context,
                        memories_context=memories_context,
                        history=history,
                        history_limit=max_history_messages,
                        current_message=content,
                        image_paths=image_paths,
                        is_resumed_session=False,
                    )
                    fresh_argv = _build_claude_argv(
                        claude_exe,
                        session_id=None,
                        allow_read_for_images=bool(image_paths),
                        enable_thinking=thinking_enabled,
                    )
                    new_session_id, usage = await _run_claude_subprocess(
                        fresh_argv,
                        stdin_payload=fresh_prompt,
                        on_text_delta=on_text,
                        on_thinking_delta=on_thinking_text,
                        on_thinking_block_start=on_thinking_block_start,
                        timeout=stream_timeout,
                    )
                else:
                    raise
        except TimeoutError:
            await ws.send_json({
                "type": "error",
                "message": f"Claude CLI timed out after {stream_timeout}s",
                "conversation_id": conversation_id,
            })
            return
        except RuntimeError as err:
            await ws.send_json({
                "type": "error",
                "message": str(err),
                "conversation_id": conversation_id,
            })
            return
        except Exception:
            logger.exception("Claude CLI streaming failed")
            await ws.send_json({
                "type": "error",
                "message": "Claude CLI backend failed. Check logs.",
                "conversation_id": conversation_id,
            })
            return
    finally:
        if lock is not None and lock.locked():
            lock.release()
        # Temp images aren't needed once the subprocess has been drained.
        if image_paths and conversation_id:
            _cleanup_image_dir(conversation_id)

    # Save session id for next turn so Claude keeps context server-side.
    if conversation_id and new_session_id:
        _track_session(conversation_id, new_session_id)

    # Surface a "thinking complete" event so the UI can collapse the panel.
    # If the model reasoned but the content was redacted (subscription mode
    # always redacts), substitute a short explanation so the user sees why
    # the panel is empty rather than a blank box.
    if thinking_started:
        if not full_thinking:
            full_thinking = (
                "💭 Claude reasoned through this internally. The Claude Code "
                "subscription redacts thought content from headless output — "
                "switch to CLAUDE_BACKEND=api with an Anthropic API key to "
                "see the full thought process."
            )
        await ws.send_json({
            "type": "thinking_end",
            "full_thinking": full_thinking,
            "conversation_id": conversation_id,
        })

    full_response = strip_leading_timestamp(full_response)

    assistant_msg_id = 0
    if DB_AVAILABLE and conversation_id and full_response:
        try:
            db = get_db()
            assistant_msg_id = await db.save_dashboard_message(
                conversation_id, "assistant", full_response,
                thinking=full_thinking if full_thinking else None,
                mode=mode_label,
            )
            conv = await db.get_dashboard_conversation(conversation_id)
            if conv and (not conv.get("title") or conv.get("title") == "New Conversation"):
                title = content[:40].strip()
                if title:
                    await db.update_dashboard_conversation(conversation_id, title=title)
                    await ws.send_json({
                        "type": "title_updated",
                        "conversation_id": conversation_id,
                        "title": title,
                    })
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
        cache_creation = int(usage.get("cache_creation_input_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        in_tok = int(usage.get("input_tokens", 0)) + cache_read + cache_creation
        out_tok = int(usage.get("output_tokens", 0))
    else:
        cache_creation = 0
        cache_read = 0
        in_tok = max(1, len(full_prompt) // 4)
        out_tok = max(1, len(full_response) // 4)

    # `chunks_count` mirrors the SDK backend's payload — frontend doesn't
    # currently render it, but emitting it keeps the event shape parity so
    # future UI changes work uniformly across both backends.
    await ws.send_json({
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
    })


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
            result = result.replace(search_text, replace_text, 1)
            applied += 1
        else:
            stripped = search_text.strip()
            if stripped and stripped in result:
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

    if not conversation_id or not target_message_id or not instruction:
        await ws.send_json({"type": "error", "message": "Missing data for AI edit", "conversation_id": conversation_id})
        return

    ready, reason = is_cli_backend_ready()
    if not ready:
        await ws.send_json({"type": "error", "message": reason, "conversation_id": conversation_id})
        return

    if not DB_AVAILABLE:
        await ws.send_json({"type": "error", "message": "Database unavailable", "conversation_id": conversation_id})
        return

    # Look up the target message for the original content + sanity checks.
    try:
        db = get_db()
        target_id_int = int(target_message_id)
        all_msgs = await db.get_dashboard_messages(conversation_id)
        target_msg = next((m for m in all_msgs if m.get("id") == target_id_int), None)
    except Exception:
        logger.exception("Failed to load target message for AI edit (CLI backend)")
        await ws.send_json({"type": "error", "message": "Failed to load message", "conversation_id": conversation_id})
        return

    if not target_msg:
        await ws.send_json({"type": "error", "message": "Target message not found", "conversation_id": conversation_id})
        return
    if target_msg.get("role") != "assistant":
        await ws.send_json({"type": "error", "message": "Can only AI-edit assistant messages", "conversation_id": conversation_id})
        return

    original_content = target_msg.get("content", "")
    preset = DASHBOARD_ROLE_PRESETS.get(role_preset, DASHBOARD_ROLE_PRESETS["general"])
    persona = str(preset.get("system_instruction", ""))

    try:
        user_context, memories_context, _ = await build_user_context(user_name, False)
    except Exception:
        logger.exception("build_user_context failed (CLI edit)")
        user_context, memories_context = f"Name: {user_name}", ""

    now = datetime.now(tz=ZoneInfo("Asia/Bangkok"))
    current_time_str = now.strftime("%A, %d %B %Y %H:%M:%S")

    # Same prompt template as dashboard_chat_claude.py so the patch dialect
    # matches and _apply_search_replace stays correct on either backend.
    edit_prompt = (
        f"# Persona\n{persona}\n\n"
        f"# Context\n{user_context}\n"
        f"Current Time: {current_time_str} (ICT)\n"
        f"{memories_context}\n\n"
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
    await ws.send_json({
        "type": "stream_start",
        "mode": mode_label,
        "is_edit": True,
        "target_message_id": target_id_int,
        "conversation_id": conversation_id,
    })

    edit_response = ""
    edit_thinking = ""
    thinking_started = False

    async def on_text(text: str) -> None:
        nonlocal edit_response
        edit_response += text
        await ws.send_json({
            "type": "chunk",
            "content": text,
            "conversation_id": conversation_id,
        })

    async def on_thinking_text(text: str) -> None:
        nonlocal edit_thinking, thinking_started
        if not thinking_enabled:
            return
        if not thinking_started:
            thinking_started = True
            await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})
        edit_thinking += text
        await ws.send_json({
            "type": "thinking_chunk",
            "content": text,
            "conversation_id": conversation_id,
        })

    async def on_thinking_block_start() -> None:
        nonlocal thinking_started
        if not thinking_enabled or thinking_started:
            return
        thinking_started = True
        await ws.send_json({"type": "thinking_start", "conversation_id": conversation_id})

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
    try:
        if edit_lock is not None:
            await edit_lock.acquire()
        try:
            _new_sid, usage = await _run_claude_subprocess(
                argv,
                stdin_payload=edit_prompt,
                on_text_delta=on_text,
                on_thinking_delta=on_thinking_text,
                on_thinking_block_start=on_thinking_block_start,
                timeout=stream_timeout,
            )
        except TimeoutError:
            await ws.send_json({
                "type": "error",
                "message": f"Claude CLI edit timed out after {stream_timeout}s",
                "conversation_id": conversation_id,
            })
            return
        except RuntimeError as err:
            await ws.send_json({
                "type": "error",
                "message": str(err),
                "conversation_id": conversation_id,
            })
            return
        except Exception:
            logger.exception("Claude CLI edit failed")
            await ws.send_json({
                "type": "error",
                "message": "Claude CLI edit backend failed. Check logs.",
                "conversation_id": conversation_id,
            })
            return
    finally:
        if edit_lock is not None and edit_lock.locked():
            edit_lock.release()

    if thinking_started:
        if not edit_thinking:
            edit_thinking = (
                "💭 Claude reasoned through this internally. The Claude Code "
                "subscription redacts thought content from headless output — "
                "switch to CLAUDE_BACKEND=api with an Anthropic API key to "
                "see the full thought process."
            )
        await ws.send_json({
            "type": "thinking_end",
            "full_thinking": edit_thinking,
            "conversation_id": conversation_id,
        })

    new_content = _apply_search_replace(original_content, edit_response.strip())

    # Persist the rewritten message
    try:
        db = get_db()
        await db.update_dashboard_message(target_id_int, new_content)
    except Exception:
        logger.exception("Failed to update AI-edited message (CLI backend)")

    if usage:
        cache_creation = int(usage.get("cache_creation_input_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        in_tok = int(usage.get("input_tokens", 0)) + cache_read + cache_creation
        out_tok = int(usage.get("output_tokens", 0))
    else:
        cache_creation = 0
        cache_read = 0
        in_tok = max(1, len(edit_prompt) // 4)
        out_tok = max(1, len(edit_response) // 4)

    await ws.send_json({
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
    })
