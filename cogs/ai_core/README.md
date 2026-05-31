# AI Core Module

> Last Updated: May 29, 2026
> Version: 3.4.0

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
│   ├── dashboard_handlers.py     # Conversation/memory CRUD handlers (with cache invalidation hooks)
│   └── document_extractor.py     # PDF/DOCX/text extraction for dashboard attachments
│
├── core/              # 🏗️ Core components
│   ├── __init__.py
│   ├── performance.py # 📊 Performance tracking
│   ├── message_queue.py # 📬 Message queue
│   └── context_builder.py # AI context building
│
├── response/          # 📤 Response handling
│   ├── __init__.py
│   ├── response_sender.py # Webhook sending, chunking
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
│   ├── conversation_branch.py # Branch management
│   ├── state_tracker.py   # RP character states
│   └── consolidator.py    # Background task
│
├── processing/        # 🔄 Request processing
│   ├── __init__.py
│   ├── guardrails.py  # ⚠️ Safety (is_silent_block) & unrestricted mode
│   ├── intent_detector.py # Intent classification
│   ├── prompt_manager.py  # Loads system prompts from prompts/*.yaml
│   └── self_reflection.py # Response quality
│
├── prompts/           # 📝 System prompt templates (YAML)
│   └── base.yaml      # Base persona/system prompt
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
| `ContextBuilder` | `core/context_builder.py` | AI context building |
| `ResponseSender` | `response/response_sender.py` | Response sending with webhooks |

## Modular Components Integration

**ChatManager (`logic.py`) uses modular components internally:**

- `PerformanceTracker` — metrics collection
- `RequestDeduplicator` — prevents duplicate requests for the same channel+message
- `MessageQueue` — pending-message buffering and per-channel lock
- `ResponseSender` — webhook + chunked response delivery

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

### Context Building

```python
from cogs.ai_core.core.context_builder import ContextBuilder

builder = ContextBuilder(
    memory_manager=rag_system,
    entity_memory=entity_memory,
    state_tracker=state_tracker,
)

ctx = await builder.build_context(channel_id, user_id, message, guild=guild)
system_context = ctx.build_system_context()
```

### Response Sending

```python
from cogs.ai_core.response.response_sender import response_sender

result = await response_sender.send_response(
    channel=channel,
    content="Long response...",
    avatar_name="Faust",
    use_webhook=True,
)
if result.success:
    print(f"Sent via {result.sent_via}, chunks: {result.chunk_count}")
```

## Native Extensions

AI Core รองรับ Rust extensions สำหรับ performance:

> **Build Status:** ✅ Rust RAG engine built (April 2, 2026)
> **File:** `cogs/ai_core/memory/rag_engine.pyd` (~653 KB) — SIMD cosine similarity, 10-25x faster

```python
# Auto-selects Rust if available, else Python
from cogs.ai_core.memory.rag_rust import RagEngineWrapper

engine = RagEngineWrapper(dimension=384, similarity_threshold=0.7)
engine.add(entry)  # SIMD-optimized vector ops
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
# (returns None; use response_sender / webhook_cache to inspect what went out).
await chat_manager.process_chat(
    channel, user, message, attachments
)
```

## Tests

```bash
# All AI tests
python -m pytest tests/test_ai_core.py -v
python -m pytest tests/test_ai_integration.py -v
python -m pytest tests/test_emoji_voice.py -v
python -m pytest tests/test_memory_modules.py -v
python -m pytest tests/test_tools.py -v
python -m pytest tests/test_webhooks.py -v
```

## Recent Updates

### v3.4.0 — Claude Opus 4.8 (1M context, Max thinking) (May 29, 2026)

- **Default model → `claude-opus-4-8`** across `api/dashboard_config.py`,
  `api/api_failover.py` health check, and `data/constants_env.py`.
- **`CLAUDE_EFFORT` defaults to `max`** with adaptive thinking; effort is now
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
- **Memory cache invalidation hooks.** `dashboard_handlers.save_dashboard_memory`
  and `delete_dashboard_memory` now call `invalidate_user_context_cache(None)`
  so the next chat turn rebuilds context with the current memory list.
- **`_CONVERSATION_LOCKS` capped at 500.** The CLI session-lock dict was
  unbounded; now LRU-evicts oldest entries past the cap.
- **`token_tracker` is fully tz-aware.** `_aware_now()` / `_ensure_aware()`
  helpers replace every naive `datetime.now()`. Naive timestamps loaded from
  older DB rows are wrapped as UTC, fixing comparison drift in
  `get_usage_in_period`.
- **`storage.py` dedup hashes full content.** Was hashing only the first
  500 chars, so two long messages sharing a prefix collapsed into one row.
- **`response_sender` is code-fence-aware.** `_detect_open_fence()` re-opens
  ` ``` ` in the next chunk so long replies don't break formatting on Discord.
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
