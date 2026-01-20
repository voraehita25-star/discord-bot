# AI Core Module

> Last Updated: January 20, 2026  
> Version: 3.3.0

ระบบ AI หลักของ Discord Bot - ใช้ Gemini API

## Structure (37 ไฟล์)

```
cogs/ai_core/
├── __init__.py
├── ai_cog.py          # ⭐ Main AI cog (commands & events)
├── logic.py           # ⭐ ChatManager - core AI logic
├── storage.py         # History persistence (SQLite)
├── tools.py           # Agentic tools (webhooks, server commands)
├── emoji.py           # Discord emoji processing
├── voice.py           # Voice channel management
├── fallback_responses.py  # Fallback when AI fails
├── debug_commands.py  # Debug/admin commands
├── memory_commands.py # User memory commands
│
├── data/              # Static data & prompts
│   ├── __init__.py
│   ├── constants.py   # ⚙️ Config constants, API keys, processing limits
│   ├── faust_data.py  # Faust persona instructions
│   └── roleplay_data.py  # RP server lore & characters
│
├── memory/            # 🧠 Memory systems (11 files)
│   ├── __init__.py
│   ├── rag.py         # FAISS-based RAG system
│   ├── rag_rust.py    # 🦀 Rust RAG wrapper (auto-fallback)
│   ├── history_manager.py # Smart history trimming
│   ├── summarizer.py  # Conversation summarization
│   ├── entity_memory.py   # Character/entity facts
│   ├── long_term_memory.py # Permanent user facts
│   ├── memory_consolidator.py # Memory consolidation
│   ├── conversation_branch.py # Branch management
│   ├── state_tracker.py   # RP character states
│   └── consolidator.py    # Fact extraction background task
│
├── processing/        # 🔄 Request processing (5 files)
│   ├── __init__.py
│   ├── guardrails.py  # ⚠️ Safety & unrestricted mode
│   ├── intent_detector.py # Message intent classification
│   ├── prompt_manager.py  # System prompt templates
│   └── self_reflection.py # Response quality checks
│
└── cache/             # 📊 Caching & Analytics (4 files)
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

