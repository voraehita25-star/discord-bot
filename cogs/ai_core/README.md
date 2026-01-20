# AI Core Module

> Last Updated: January 21, 2026  
> Version: 3.3.8

ระบบ AI หลักของ Discord Bot - ใช้ Gemini API

## Structure (Reorganized v3.3.8)

```
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
├── content_processor.py # Content processing
├── media_processor.py # Media processing
│
├── # Backward compatibility re-exports (thin wrappers)
├── tools.py           # → tools/
├── api_handler.py     # → api/
├── performance.py     # → core/
├── message_queue.py   # → core/
├── context_builder.py # → core/
├── response_sender.py # → response/
├── response_mixin.py  # → response/
├── webhook_cache.py   # → response/
├── debug_commands.py  # → commands/
├── memory_commands.py # → commands/
├── server_commands.py # → commands/
├── tool_definitions.py # → tools/
├── tool_executor.py   # → tools/
│
├── api/               # 🔌 Gemini API integration
│   ├── __init__.py
│   └── api_handler.py # API calls, streaming, retry logic
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
│   ├── guardrails.py  # ⚠️ Safety & unrestricted mode
│   ├── intent_detector.py # Intent classification
│   ├── prompt_manager.py  # System prompts
│   └── self_reflection.py # Response quality
│
└── cache/             # 📊 Caching & Analytics
    ├── __init__.py
    ├── ai_cache.py    # LRU response cache
    ├── analytics.py   # Metrics & tracking
    └── token_tracker.py # Token usage tracking
```

## Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `AI` | `ai_cog.py` | Main Discord cog - commands & events |
| `ChatManager` | `logic.py` | AI handler - sessions, API, streaming (uses `asyncio.wait_for` for lock timeout) |
| `MemorySystem` | `memory/rag.py` | FAISS-based long-term memory |
| `RagEngineWrapper` | `memory/rag_rust.py` | 🦀 Rust RAG with Python fallback (10-25x faster) |
| `HistoryManager` | `memory/history_manager.py` | Smart context trimming |
| `EntityMemoryManager` | `memory/entity_memory.py` | Character facts storage |
| `AICache` | `cache/ai_cache.py` | Response caching |
| `AIAnalytics` | `cache/analytics.py` | Usage metrics |
| `PerformanceTracker` | `performance.py` | 🆕 Performance metrics tracking |
| `MessageQueue` | `message_queue.py` | 🆕 Message queue management |
| `ContextBuilder` | `context_builder.py` | 🆕 AI context building |
| `ResponseSender` | `response_sender.py` | 🆕 Response sending with webhooks |

## 🆕 Modular Components Integration (v3.3.6)

**ChatManager now uses modular components internally:**
- `PerformanceTracker` - For metrics collection
- `RequestDeduplicator` - For preventing duplicate requests  
- `MessageQueue` - For message queuing and merging
- `ResponseSender` - For webhook and chunked responses

This reduces ChatManager from 1,224 to 999 lines (~18% reduction) while maintaining backward compatibility.

### Performance Tracking
```python
from cogs.ai_core.performance import performance_tracker, request_deduplicator

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
from cogs.ai_core.message_queue import message_queue

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
from cogs.ai_core.context_builder import ContextBuilder

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
from cogs.ai_core.response_sender import response_sender

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

> **Build Status:** ✅ Rust RAG engine built (January 20, 2026)  
> **File:** `rag_engine.pyd` (651 KB) - SIMD cosine similarity, 10-25x faster

```python
# Auto-selects Rust if available, else Python
from cogs.ai_core.memory.rag_rust import RagEngine

engine = RagEngine(dimension=384, similarity_threshold=0.7)
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

# Process message
response = await chat_manager.process_chat(
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

## Recent Updates (January 21, 2026)

### v3.3.8 - ai_core Reorganization + E501 Fixes
- 📁 **Reorganized ai_core** into logical subdirectories:
  - `api/` - Gemini API integration (api_handler.py)
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

