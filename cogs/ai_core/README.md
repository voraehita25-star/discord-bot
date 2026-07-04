# AI Core Module

> Last Updated: June 16, 2026
> Version: 3.5.0

ระบบ AI หลักของ Discord Bot — ใช้ Claude Opus 4.8 (1M context, Max thinking; ช่องทาง SDK หรือ Claude Code CLI) + Gemini สำหรับ embeddings/RAG

## Structure (Reorganized v3.3.7, deeper subdir split v3.3.8)

```text
cogs/ai_core/
├── __init__.py        # Package exports
├── ai_cog.py          # ⭐ Main AI cog (commands & events)
├── logic.py           # ⭐ ChatManager - core AI logic
├── storage.py         # History persistence (SQLite)
├── sanitization.py    # 🛡️ Input sanitization
├── emoji.py           # Discord emoji processing
├── voice.py           # Voice channel management
├── fallback_responses.py  # Fallback when AI fails
├── session_mixin.py   # Session management mixin
├── media_processor.py # Media processing
├── claude_payloads.py # Typed Claude message builders + prompt-cache helpers
├── character_tags.py  # Cached character-name → {{Tag}} replacement
├── imports.py         # Centralised optional-dependency imports
│
├── api/               # 🔌 AI APIs + dashboard backend
│   ├── __init__.py
│   ├── api_handler.py            # Claude API calls (anthropic SDK), streaming, retry
│   ├── api_failover.py           # Direct + proxy failover for Claude
│   ├── ws_dashboard.py           # Dashboard WebSocket server (auth, origin check)
│   ├── dashboard_chat.py         # Gemini-backed dashboard chat
│   ├── dashboard_chat_claude.py  # Claude via anthropic SDK (per-token billing)
│   ├── dashboard_chat_claude_cli.py  # Claude via `claude -p` subprocess (Max subscription)
│   ├── dashboard_common.py       # Shared helpers (timestamps, persona+context builder)
│   ├── dashboard_config.py       # Dashboard env config
│   ├── dashboard_handlers.py     # Conversation/memory CRUD + AI-history browse/edit/delete/restore handlers
│   ├── chat_manager_registry.py  # Weakref registry exposing the live ChatManager to dashboard handlers
│   ├── document_extractor.py     # PDF/DOCX/text extraction for dashboard attachments
│   ├── discord_chat_claude_cli.py    # Discord-side `claude -p` client (CLAUDE_BACKEND=cli)
│   ├── ai_tools_ipc.py           # Localhost IPC endpoint executing the AI's tool calls in the bot process
│   ├── mcp_tools_server.py       # Stdio MCP proxy that `claude -p` spawns for custom AI tools
│   └── cli_write_guard.py        # 🛡️ PreToolUse hook: confines CLI file-write mode to allowed roots
│
├── core/              # 🏗️ Core components
│   ├── __init__.py
│   ├── performance.py # 📊 Performance tracking
│   └── message_queue.py # 📬 Message queue
│
├── response/          # 📤 Response handling
│   ├── __init__.py
│   ├── response_mixin.py  # Response processing mixin
│   └── webhook_cache.py   # Webhook caching
│
├── commands/          # 🔧 Command modules
│   ├── __init__.py
│   ├── debug_commands.py  # Debug/admin commands
│   ├── memory_commands.py # User memory commands
│   └── server_commands.py # Server management
│
├── tools/             # ⚡ AI function calling
│   ├── __init__.py
│   ├── tools.py       # Facade module
│   ├── tool_definitions.py # Gemini tool definitions
│   └── tool_executor.py   # Tool execution
│
├── data/              # Static data & prompts
│   ├── __init__.py
│   ├── constants.py   # ⚙️ Config constants
│   ├── constants_env.py # Env-loaded config (explicit env-dependency boundary)
│   ├── faust_data.py  # Faust persona instructions
│   └── roleplay_data.py  # RP server lore
│
├── memory/            # 🧠 Memory systems
│   ├── __init__.py
│   ├── rag.py         # FAISS-based RAG system
│   ├── rag_rust.py    # 🦀 Rust RAG wrapper
│   ├── history_manager.py # Smart history trimming
│   ├── summarizer.py  # Conversation summarization
│   ├── entity_memory.py   # Character/entity facts
│   ├── long_term_memory.py # Permanent user facts
│   ├── memory_consolidator.py # Memory consolidation
│   ├── state_tracker.py   # RP character states
│   └── consolidator.py    # Background task
│
├── processing/        # 🔄 Request processing
│   ├── __init__.py
│   ├── unrestricted.py    # Per-channel unrestricted-mode registry (persona injection)
│   └── intent_detector.py # Intent classification
│
└── cache/             # 📊 Caching & Analytics
    ├── __init__.py
    ├── ai_cache.py    # LRU response cache
    ├── analytics.py   # Metrics & tracking
    └── token_tracker.py # Token usage tracking
```

## Key Classes

| Class | File | Purpose |
| ----- | ---- | ------- |
| `AI` | `ai_cog.py` | Main Discord cog - commands & events |
| `ChatManager` | `logic.py` | AI handler - sessions, API, streaming (uses `asyncio.wait_for` for lock timeout) |
| `MemorySystem` | `memory/rag.py` | FAISS-based long-term memory |
| `RagEngineWrapper` | `memory/rag_rust.py` | 🦀 Rust RAG with Python fallback (10-25x faster) |
| `HistoryManager` | `memory/history_manager.py` | Smart context trimming |
| `EntityMemoryManager` | `memory/entity_memory.py` | Character facts storage |
| `AICache` | `cache/ai_cache.py` | Response caching |
| `AIAnalytics` | `cache/analytics.py` | Usage metrics |
| `PerformanceTracker` | `core/performance.py` | Performance metrics tracking |
| `MessageQueue` | `core/message_queue.py` | Message queue management |

## Modular Components Integration

**ChatManager (`logic.py`) uses modular components internally:**

- `PerformanceTracker` — metrics collection
- `RequestDeduplicator` — prevents duplicate requests for the same channel+message
- `MessageQueue` — pending-message buffering and per-channel lock

`logic.py` is the largest module (the `ChatManager` orchestrator); each helper above lives in its own subpackage so the manager focuses on orchestration. (Run `wc -l cogs/ai_core/logic.py` for the current line count — a hard-coded figure drifts every refactor.)

### Performance Tracking

```python
from cogs.ai_core.core.performance import performance_tracker, request_deduplicator

# Track timing
performance_tracker.record_timing("api_call", 0.5)
stats = performance_tracker.get_stats()
print(performance_tracker.get_summary())

# Deduplicate requests
key = request_deduplicator.generate_key(channel_id, user_id, message)
if not request_deduplicator.is_duplicate(key):
    request_deduplicator.add_request(key)
    # Process...
    request_deduplicator.remove_request(key)
```

### Message Queue

```python
from cogs.ai_core.core.message_queue import message_queue

# Queue messages for concurrent handling
message_queue.queue_message(channel_id, channel, user, "Hello")

# Merge pending messages
latest, combined = message_queue.merge_pending_messages(channel_id)

# Lock management
await message_queue.acquire_lock_with_timeout(channel_id, timeout=30.0)
message_queue.release_lock(channel_id)
```

## Native Extensions

AI Core รองรับ Rust extensions สำหรับ performance:

> **Build Status:** ✅ Rust RAG engine built (April 2, 2026)
> **File:** `cogs/ai_core/memory/rag_engine.pyd` (~653 KB) — SIMD cosine similarity, 10-25x faster

```python
# Auto-selects Rust if available, else Python
from cogs.ai_core.memory.rag_rust import RagEngineWrapper

engine = RagEngineWrapper(dimension=768, similarity_threshold=0.7)  # 768 = Gemini gemini-embedding-2 (output_dimensionality=768)
engine.add("mem-1", "some text", embedding_vector, importance=1.0)  # add(entry_id, text, embedding, ...)
results = engine.search(query_embedding, top_k=5)

# Check backend
print(f"Using Rust: {engine.is_rust}")  # True if Rust loaded
```

Build Rust extension:

```powershell
.\scripts\build_rust.ps1 -Release
```

## Usage

```python
from cogs.ai_core.logic import ChatManager

# Initialize
chat_manager = ChatManager(bot)

# Process a message — sends the response via webhook/channel as a side effect
# (returns None; use webhook_cache to inspect what went out).
await chat_manager.process_chat(
    channel, user, message, attachments
)
```

## Tests

```powershell
# AI tests — use the wrapper (raw `pytest -v` can hang; see repo CLAUDE.md)
.\scripts\run_tests.ps1 -File test_ai_core.py
.\scripts\run_tests.ps1 -File test_ai_integration.py
.\scripts\run_tests.ps1 -File test_emoji_voice.py
.\scripts\run_tests.ps1 -File test_memory_modules.py
.\scripts\run_tests.ps1 -File test_tools.py
.\scripts\run_tests.ps1 -File test_webhooks.py
```

## Recent Updates

### Unreleased — Dashboard AI-history editor + Claude CLI session overhaul

- **AI-history editing over the dashboard WS** (`api/dashboard_handlers.py`,
  dispatched from `ws_dashboard.py`): `list_ai_channels` / `load_ai_history` /
  `edit_ai_history_message` / `delete_ai_history_message` /
  `restore_ai_history_message` → `ai_channels_list` / `ai_history_loaded` /
  `ai_history_message_edited` / `_deleted` / `_restored`. Loads default to the
  newest 200 rows (max 2000) under a ~20MB content budget with a `truncated`
  flag; every error carries `scope:"ai_history"` plus a stable code
  (`MISSING_ID`, `INVALID_ID`, `INVALID_PAYLOAD`, `MISSING_CONTENT`,
  `CONTENT_TOO_LONG`, `MSG_NOT_FOUND`, `ROW_CONFLICT`, `DB_UNAVAILABLE`,
  `INTERNAL_ERROR`); snowflakes travel as JSON strings; only
  `list_ai_channels` is rate-limit-exempt. Delete/restore acks include a
  best-effort `total_count`.
- **Live-session sync.** Every mutation also patches the in-memory
  `ChatManager` session via new `logic.py` methods
  (`patch_history_content` / `remove_history_content` /
  `insert_history_content`, twin-ordinal matching) and reports a five-state
  `live_session` in the ack — `patched` / `not_loaded` / `no_match` /
  `unavailable` / `error` (legacy `live_session_patched` kept) — and resets
  the channel's Discord CLI `--resume` session so delta-on-resume prompts
  can't keep answering from the pre-edit context.
- **`api/chat_manager_registry.py`** (new) — weakref registry, registered in
  `AICog.cog_load`, so the argument-less dashboard WS server can reach the
  live `ChatManager` without holding it alive past a cog unload.
- **`storage.py`** — per-channel asyncio history lock (`get_history_lock`,
  held by `_save_history_db` / `_replace_history_db` and the dashboard edit
  handler) plus a cache generation counter (`invalidate_cache` bumps it;
  `load_history` re-reads when its DB snapshot went stale mid-await), so
  dashboard row edits and bot saves can't clobber each other.
- **Claude CLI delta-on-resume** (`api/discord_chat_claude_cli.py` +
  `dashboard_chat_claude_cli.py`): resumed turns send only `# System` +
  `# Formatting rules` + `# Current user message` — the server-side session
  already holds the history. Only fresh sessions (incl. the attempt-2
  stale-session retry) send the full flattened history. Failure paths
  (timeout/overload/unclassified) drop the session so the next turn
  self-heals fresh, and infrastructure error strings are no longer persisted
  into history (the Discord streaming path posts a `delete_after=30` notice
  instead). Superseded/reset session `.jsonl` transcripts are unlinked on
  both sides.
- **`CLI_PROMPT_MAX_CHARS` over-limit flow** (default 1.2M chars ≈ the
  1M-token window for Thai; `0` = off): on the Discord path a fresh-session
  prompt over the ceiling is **never silently truncated** — the turn stops
  and the bot posts a warning with OWNER-ONLY buttons: 📝 สรุปแชททั้งหมด
  (same trim+force-save as `!auto_summarize`, target 500k tokens, then the
  CLI session resets and chat continues) or ❌ ไม่สรุป (พักแชทนี้ไว้)
  (history kept intact; the channel can't continue until summarized or
  `!reset_ai`). A 10-minute cooldown posts short auto-deleting reminders
  instead of stacking button views; the non-streaming path just logs and
  skips the turn. The dashboard path front-truncates its history block
  (newest turns kept) instead.
- **CLI hardening** — prompt-injection defang on both sides now covers role
  markers *and* the prompt's own section headers (dashboard prompts also got
  a size budget); `cli_write_guard.py` denylists the repo root, `~/.ssh` and
  `~/.claude` even when `DASHBOARD_CLI_WRITE_DIRS` points at an ancestor;
  `api_failover` no longer counts 4xx client errors toward the failover trip
  threshold; the pre-warm pool only reuses a warm `claude -p` whose argv
  exactly matches the turn (incl. thinking), falling back to a cold spawn;
  perf/debug logs carry session ids.

### Unreleased — Dashboard CLI file-write mode

- **`DASHBOARD_CLI_ALLOW_WRITE`** (default off) opts the `CLAUDE_BACKEND=cli`
  dashboard backend into a *files-only* autonomous write mode: the embedded
  `claude -p` may create/edit files in **`DASHBOARD_CLI_WRITE_DIRS`** (default
  Desktop / Documents / Downloads, plus OneDrive-redirected Desktop/Documents on
  Windows) without an interactive Allow prompt the chat UI can't answer.
- **`api/cli_write_guard.py`** — a `PreToolUse` hook is the authoritative path
  gate: it denies (exit 2, fail-closed) any `Write`/`Edit`/`MultiEdit`/
  `NotebookEdit` whose canonical target is outside the resolved write roots, so
  the repo, `.env`, `~/.ssh`, `~/.claude`, and the home root stay protected.
  Bash, web, NotebookEdit, and Task tools are denied entirely. When write mode
  is off, the CLI backend stays a pure-chat process.

### v3.4.0 — Claude Opus 4.8 (1M context, Max thinking) (May 29, 2026)

- **Default model → `claude-opus-4-8`** across `api/dashboard_config.py`,
  `api/api_failover.py` health check, and `data/constants_env.py`.
- **`CLAUDE_EFFORT` defaults to `xhigh`** with adaptive thinking; effort is now
  forwarded on the Discord API path too, not just the dashboard.
- **Adaptive-thinking detection hardened** — extracted `_uses_adaptive_thinking()`;
  Opus 4.7+/4.8 (adaptive-only) no longer fall through to the removed
  `budget_tokens` path, which 400s on 4.8.
- **`api/document_extractor.py`** — fixed a stale diagnostic log
  ("defusedxml missing" → "python-docx not installed").

### v3.3.15 — AI/Memory Audit (April 27, 2026)

Three rounds of audits surfaced 17 bugs; key behavioural fixes:

- **CLI memory now matches API.** `dashboard_chat_claude_cli._build_full_prompt`
  always injects persona + user context every turn (same as the Anthropic SDK
  path); only the `# Conversation so far` history block is skipped on resumed
  sessions where `claude -p --resume` already replays it. Without this,
  edits to long-term memory were not reflected on the next CLI turn until
  the bot restarted.
- **`_CONVERSATION_LOCKS` capped at 500.** The CLI session-lock dict was
  unbounded; now LRU-evicts oldest entries past the cap.
- **`token_tracker` is fully tz-aware.** `_aware_now()` / `_ensure_aware()`
  helpers replace every naive `datetime.now()`. Naive timestamps loaded from
  older DB rows are wrapped as UTC, fixing comparison drift in
  `get_usage_in_period`.
- **`storage.py` dedup hashes full content.** Was hashing only the first
  500 chars, so two long messages sharing a prefix collapsed into one row.
- **Webhook cache uses `pop(k, None)` + LRU evict** instead of `clear()`,
  preventing in-flight webhook deletion from racing the cleanup task.
- **RAG embeddings skip empty/whitespace text** before hitting the API.

New module: **`api/document_extractor.py`** — extracts text from
PDF/DOCX/text-like dashboard attachments and persists it in
`dashboard_document_memories` so RP material auto-injects every turn.

### v3.3.10 - Deep Code Audit & Test Verification (February 7, 2026)

- 🛡️ **Security hardening** across all modules (specific exceptions, input validation, resource cleanup)
- 🔒 **XSS prevention** in server_commands with `sanitize_channel_name` fallback to `"untitled"`
- 🧪 **Test suite perfected** - 3,157 passed, 0 skipped, 0 warnings
- 🧹 **Removed duplicate code** in webhook_cache event loop validation
- ✅ All broad `except Exception` replaced with specific types

### v3.3.8 - ai_core Reorganization + E501 Fixes (January 21, 2026)

- 📁 **Reorganized ai_core** into logical subdirectories:
  - `api/` - AI APIs (Claude SDK + dashboard backend handlers)
  - `core/` - Performance, message queue, context builder
  - `response/` - Response sending, webhooks
  - `commands/` - Debug, memory, server commands
  - `tools/` - Tool definitions and execution
- 🔧 **Fixed all E501** (line-too-long) lint errors
- 📄 **Backward compatible** re-export files at root level
- ✅ All 362 tests passing

### v3.3.7 - logic.py Refactoring

- 🔨 **Refactored `logic.py`** into 4 modular components:
  - `performance.py` - Performance tracking & deduplication
  - `message_queue.py` - Message queue management
  - `context_builder.py` - AI context building
  - `response_sender.py` - Response sending with webhooks
- ✅ Reduced ChatManager from 1,224 to 999 lines (~18%)

### v3.3.5 - Tools Module Refactoring

- 🔨 **Refactored `tools.py`** (1,405 lines) into 5 focused modules:
  - `sanitization.py` - Input sanitization (72 lines)
  - `webhook_cache.py` - Webhook caching (139 lines)
  - `server_commands.py` - Server commands (606 lines)
  - `tool_definitions.py` - Gemini API tools (228 lines)
  - `tool_executor.py` - Execution logic (307 lines)
  - `tools.py` - Facade for backward compatibility (110 lines)
- ✅ All 285 tests passing
- 🔄 Backward compatible - existing imports work unchanged

### v3.3.4 - Bug Fixes (January 20, 2026)

- ✅ Removed duplicate `IMAGEIO_AVAILABLE` import in `logic.py`
- ✅ Removed dead code `knowledge_context` variable
- ✅ Fixed PIL Images NameError in finally block
- ✅ Added `on_guild_channel_delete` listener to cleanup webhook cache
- ✅ Changed background task exception handling with backoff
- ✅ Added `guild.me` None check in role commands
- ✅ Changed `storage.py` cache to use `copy.deepcopy()`
- ✅ Added `MAX_CACHE_SIZE` limit (1000) in `storage.py`
- ✅ Added `bot_has_guild_permissions` checks for music commands
- ✅ Added periodic storage cache cleanup (every 5 minutes)
