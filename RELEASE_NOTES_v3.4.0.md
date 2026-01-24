# 📋 Release Notes - v3.4.0

**Release Date:** January 25, 2026  
**Type:** Minor Release (Security & Reliability Improvements)

---

## 🔒 Security & Reliability - Deep Code Audit

### Exception Handling Improvements
ปรับปรุง exception handling ทั้งโปรเจคจาก broad `except Exception` เป็น specific exceptions เพื่อ:
- ป้องกันการซ่อน bugs ที่ไม่คาดคิด
- ทำให้ debugging ง่ายขึ้น
- เพิ่มความปลอดภัยของโค้ด

| File | Change |
|------|--------|
| `database.py` | `except Exception` → `except aiosqlite.OperationalError` (ALTER TABLE) |
| `rag.py` | `except Exception` → `except (ValueError, TypeError, AttributeError)` (datetime) |
| `views.py` | `except Exception` → `except (discord.NotFound, discord.HTTPException)` |
| `guardrails.py` | `except Exception` → `except (json.JSONDecodeError, OSError, ValueError)` |
| `consolidator.py` | Split into parsing errors vs unexpected errors |
| `summarizer.py` | Split into specific exception types |
| `health_client.py` | `except Exception` → `except (aiohttp.ClientError, asyncio.TimeoutError)` |
| `logic.py` | 7 broad exceptions → specific types (aiohttp, asyncio, KeyError, etc.) |
| `response_sender.py` | `except Exception` → `except (discord.HTTPException, Forbidden, NotFound)` |
| `media_processor.py` | `except Exception` → `except (OSError, ValueError, Image.DecompressionBombError)` |

### Memory Bounds & Eviction
เพิ่ม limits เพื่อป้องกัน unbounded memory growth:

| Component | Limit | Eviction Strategy |
|-----------|-------|-------------------|
| `RateLimiter` | 10,000 buckets | LRU (oldest first) |
| `MessageQueue` | 5,000 channels, 50 pending/channel | LRU eviction |
| `StateTracker` | 2,000 channels, 100 chars/channel | Oldest eviction |

### Resource Leak Fixes
- **PIL Images:** เพิ่ม `try/finally` blocks เพื่อ cleanup Images อย่างถูกต้อง
  - `media_processor.py` - `is_animated_gif()`, `convert_gif_to_video()`
  - `media_rust.py` - Image processing functions

### Safe Shutdown
- `cog.py` (Music): เพิ่ม `_safe_run_coroutine()` helper สำหรับ `asyncio.run_coroutine_threadsafe`
- ป้องกัน unhandled exceptions ระหว่าง shutdown

### Configuration
- `pyproject.toml`: เปลี่ยนจาก blanket deprecation ignore เป็น selective (`discord.*`, `aiohttp.*`, `google.*`)

---

## 📝 Documentation Updates

- `DEVELOPER_GUIDE.md`: 
  - เพิ่ม Phase 6 - Deep Code Audit (18 items)
  - เพิ่ม Known Gotchas ข้อ 10-11
  - อัพเดตวันที่และ version
- `docs/CODE_AUDIT_GUIDE.md`: อัพเดตวันที่

---

## 📊 Test Results

```
===================== 3,157 passed in 10.24s =====================
```

✅ All 3,157 tests passing  
✅ 0 errors after changes  
✅ 126 test files

---

## 📁 Files Changed (18 files)

### Core AI Logic
- `cogs/ai_core/logic.py` - 7 exception fixes + import aiohttp
- `cogs/ai_core/response/response_sender.py` - Exception fix + import discord
- `cogs/ai_core/media_processor.py` - PIL cleanup + exception fixes

### Memory Systems  
- `cogs/ai_core/memory/rag.py` - Datetime exception fix
- `cogs/ai_core/memory/consolidator.py` - Split exceptions
- `cogs/ai_core/memory/state_tracker.py` - Memory bounds
- `cogs/ai_core/memory/summarizer.py` - Split exceptions

### Processing & Safety
- `cogs/ai_core/processing/guardrails.py` - Specific exceptions
- `cogs/ai_core/core/message_queue.py` - Memory bounds

### Music
- `cogs/music/cog.py` - Safe coroutine helper
- `cogs/music/views.py` - Discord exception fix

### Utilities
- `utils/database/database.py` - SQLite exception fix
- `utils/monitoring/health_client.py` - HTTP exception fix
- `utils/reliability/rate_limiter.py` - Memory bounds
- `utils/media/media_rust.py` - PIL cleanup

### Config & Docs
- `config.py` - Documentation clarification
- `pyproject.toml` - Selective deprecation warnings
- `DEVELOPER_GUIDE.md` - Phase 6 updates
- `docs/CODE_AUDIT_GUIDE.md` - Date update

---

## ⬆️ Upgrade Instructions

```bash
# Pull latest changes
git pull origin main

# No new dependencies required
# Just restart the bot
python bot.py
```

---

## ⚠️ Breaking Changes

None - All changes are backward compatible.

---

**Full Changelog:** v3.3.9 → v3.4.0
