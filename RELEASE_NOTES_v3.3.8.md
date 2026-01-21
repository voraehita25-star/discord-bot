# Release Notes v3.3.8

**Release Date:** January 21, 2026  
**Status:** ✅ Stable  
**Tests:** 452 passing

## 🎯 Major Changes

### 📁 ai_core Reorganization

Reorganized `cogs/ai_core/` into logical subdirectories for better maintainability:

```
cogs/ai_core/
├── api/           # 🔌 Gemini API integration
│   └── api_handler.py
│
├── core/          # 🏗️ Core components
│   ├── performance.py
│   ├── message_queue.py
│   └── context_builder.py
│
├── response/      # 📤 Response handling
│   ├── response_sender.py
│   ├── response_mixin.py
│   └── webhook_cache.py
│
├── commands/      # 🔧 Command modules
│   ├── debug_commands.py
│   ├── memory_commands.py
│   └── server_commands.py
│
├── tools/         # ⚡ AI function calling
│   ├── tools.py
│   ├── tool_definitions.py
│   └── tool_executor.py
│
└── [14 re-export files for backward compatibility]
```

### 🛡️ New Reliability Modules (Phase 5)

#### Memory Manager (`utils/reliability/memory_manager.py`)
- **TTLCache** - LRU cache with time-to-live expiration
- **WeakRefCache** - Auto-release cache using weak references
- **MemoryMonitor** - Background memory monitoring with cleanup triggers
- **@cached_with_ttl** - Decorator for function result caching

#### Shutdown Manager (`utils/reliability/shutdown_manager.py`)
- **Priority-based cleanup** - CRITICAL → HIGH → NORMAL → LOW → BACKGROUND
- **Signal handling** - SIGTERM, SIGINT support on all platforms
- **@on_shutdown** - Decorator for registering cleanup functions
- **Timeout management** - Per-handler timeouts with force-kill fallback

#### Error Recovery (`utils/reliability/error_recovery.py`)
- **Smart jitter strategies** - Full, Equal, Decorrelated jitter
- **Adaptive backoff** - Adjusts based on service health
- **Retry-After support** - Honors HTTP 429 headers
- **Circuit breaker integration** - Respects open circuits

#### Structured Logger (`utils/monitoring/structured_logger.py`)
- **JSON format** - ELK/Prometheus/Loki compatible
- **Context tracking** - Request/correlation IDs
- **Performance timing** - `@timed` decorator
- **Human-readable mode** - Colored console output

### 🔄 Backward Compatibility

All existing imports continue to work unchanged.

## 📊 Statistics

| Metric | Before | After |
|--------|--------|-------|
| Tests | 362 | 452 (+90) |
| Python Files | 125 | 128 (+3) |
| Lint Errors | 0 | 0 |
| New Modules | 0 | 4 |

## 📝 Documentation Updates

- **README.md** - Added reliability features, updated test count
- **DEVELOPER_GUIDE.md** - Full Phase 5 documentation, new key classes
- Updated `__init__.py` exports for reliability and monitoring modules

## 🔬 New Test Files

- `tests/test_memory_manager.py` - 26 tests for TTL/WeakRef caches
- `tests/test_shutdown_manager.py` - 20 tests for graceful shutdown
- `tests/test_structured_logger.py` - 26 tests for JSON logging
- `tests/test_error_recovery.py` - Enhanced with 18 new tests

## 📥 Upgrade Guide

No breaking changes. Simply update and restart:

```bash
git pull origin main
python -m pytest tests/ -q  # Verify 452 tests pass
python bot.py
```

## Usage Examples

### Memory Management
```python
from utils.reliability import TTLCache, memory_monitor

# Create a TTL cache
cache = TTLCache[str, dict](ttl=300, max_size=1000)
cache.set("key", {"data": "value"})

# Start memory monitoring
memory_monitor.register_cleanup("cache", cache.cleanup_expired)
memory_monitor.start()
```

### Graceful Shutdown
```python
from utils.reliability import shutdown_manager, on_shutdown, Priority

@on_shutdown(priority=Priority.HIGH)
async def cleanup_connections():
    await db.close()

shutdown_manager.setup_signal_handlers()
```

### Structured Logging
```python
from utils.monitoring import get_logger, timed

logger = get_logger("my_module")

with logger.request(user_id=123) as req_id:
    logger.info("Processing", tokens=500)

@timed(logger)
async def my_function():
    ...
```

---

**Full Changelog:** [v3.3.5...v3.3.8](https://github.com/voraehita25-star/discord-bot/compare/v3.3.5...v3.3.8)
