# 📋 Code Audit Guide - คู่มือตรวจสอบโค้ด

> เอกสารนี้อธิบายวิธีการตรวจสอบไฟล์ทั้งหมดในโปรเจค Discord Bot  
> **Last Updated:** February 7, 2026 | **Tests:** 3,157 passed ✅ | **Warnings:** 0 ✅ | **Skipped:** 0 ✅ | **Files:** 251 Python | **Test Files:** 126

## 🛠️ วิธีการตรวจสอบ

### 0. Ruff Check (ตรวจ Code Quality - ควรได้ 0 issues!)
```powershell
python -m ruff check .
# Expected: All checks passed!
```

### 1. Syntax Check (ตรวจ Syntax Error)
```powershell
# ตรวจไฟล์เดียว
python -m py_compile <filename.py>

# ตรวจหลายไฟล์
python -m py_compile bot.py config.py bot_dashboard.py
```

### 2. Import Check (ตรวจ Import Error)
```powershell
python -c "from cogs.ai_core.ai_cog import AI; print('OK')"
python -c "from cogs.music import Music; print('OK')"
python -c "import bot; print('OK')"
```

### 3. Test Collection (ตรวจว่า Tests พร้อมรัน)
```powershell
python -m pytest tests/ --collect-only -q
```

### 4. Run All Tests
```powershell
python -m pytest tests/ -v
```

---

## 📁 รายการไฟล์ทั้งหมด (251 ไฟล์)

### Core Files (3 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `bot.py` | Main entry point, Discord bot initialization |
| `config.py` | Configuration management with dataclasses |
| `create_shortcut.py` | Desktop shortcut creator |

---

### cogs/ (2 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `spotify_handler.py` | Spotify API integration |

---

### cogs/music/ (5 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `cog.py` | Music playback cog (YouTube/Spotify) |
| `queue.py` | Queue management |
| `utils.py` | Music utilities (colors, emojis, formatting) |
| `views.py` | Discord UI components |

---

### cogs/ai_core/ (10 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `ai_cog.py` | Main AI cog - handles Discord commands |
| `logic.py` | ChatManager - core AI logic |
| `storage.py` | Chat history storage (SQLite) |
| `tools.py` | Server management tools, webhooks |
| `emoji.py` | Discord emoji handling |
| `voice.py` | Voice channel integration |
| `fallback_responses.py` | Fallback responses when AI fails |
| `debug_commands.py` | Debug/admin commands |
| `memory_commands.py` | Memory management commands |

---

### cogs/ai_core/cache/ (4 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `ai_cache.py` | LRU cache for AI responses |
| `analytics.py` | AI usage analytics |
| `token_tracker.py` | Token usage tracking |

---

### cogs/ai_core/data/ (4 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `constants.py` | Guild IDs, channel IDs, API keys |
| `faust_data.py` | Faust persona instructions |
| `roleplay_data.py` | Roleplay assistant instructions |

---

### cogs/ai_core/memory/ (10 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `rag.py` | RAG system with FAISS |
| `history_manager.py` | Chat history trimming/management |
| `summarizer.py` | Conversation summarization |
| `entity_memory.py` | Entity/facts extraction |
| `long_term_memory.py` | Permanent facts storage |
| `memory_consolidator.py` | Memory consolidation |
| `conversation_branch.py` | Conversation branching |
| `state_tracker.py` | Character state tracking |
| `consolidator.py` | Memory consolidator (alt) |

---

### cogs/ai_core/processing/ (5 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `guardrails.py` | Input/output validation, safety |
| `intent_detector.py` | User intent detection |
| `prompt_manager.py` | Prompt template management |
| `self_reflection.py` | AI self-reflection |

---

### scripts/ (6 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `bot_manager.py` | CLI bot manager (start/stop/restart) |
| `dev_watcher.py` | Development hot-reload watcher |
| `load_test.py` | Load testing script |
| `test_bot_manager.py` | Bot manager tests |
| `verify_system.py` | System verification script |

---

### scripts/maintenance/ (7 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `add_local_id.py` | Add local IDs to database |
| `check_db.py` | Database health check |
| `clean_history.py` | Clean old chat history |
| `find_unused.py` | Find unused code |
| `migrate_to_db.py` | Migrate JSON to SQLite |
| `reindex_db.py` | Reindex database |
| `view_db.py` | View database contents |

---

### tests/ (18 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `conftest.py` | Pytest fixtures |
| `test_ai_core.py` | AI core tests |
| `test_ai_integration.py` | AI integration tests |
| `test_circuit_breaker.py` | Circuit breaker tests |
| `test_consolidator.py` | Memory consolidator tests |
| `test_content_processor.py` | Content processor tests |
| `test_database.py` | Database tests |
| `test_emoji_voice.py` | Emoji/voice tests |
| `test_error_recovery.py` | Error recovery tests |
| `test_guardrails.py` | Guardrails tests |
| `test_memory_modules.py` | Memory module tests |
| `test_music_integration.py` | Music integration tests |
| `test_performance_tracker.py` | Performance tracker tests |
| `test_rate_limiter.py` | Rate limiter tests |
| `test_spotify_integration.py` | Spotify integration tests |
| `test_summarizer.py` | Summarizer tests |
| `test_tools.py` | Tools tests |
| `test_url_fetcher.py` | URL content fetcher tests |
| `test_webhooks.py` | Webhook tests |

---

### utils/ (2 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init with re-exports |
| `localization.py` | Thai/English localization |

---

### utils/web/ (2 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `url_fetcher.py` | URL content fetching for AI context |

---

### utils/database/ (2 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `database.py` | Async SQLite database manager |

---

### utils/media/ (3 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `colors.py` | Color constants |
| `ytdl_source.py` | YouTube-DL audio source |

---

### utils/monitoring/ (10 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `health_api.py` | HTTP health check API |
| `logger.py` | Smart logging system |
| `metrics.py` | Performance metrics |
| `performance_tracker.py` | Response time tracking with percentiles |
| `sentry_integration.py` | Sentry error tracking |
| `structured_logger.py` | JSON logging with context tracking |
| `token_tracker.py` | API token tracking |
| `audit_log.py` | Audit logging |
| `feedback.py` | User feedback collection |

---

### utils/reliability/ (6 ไฟล์)
| ไฟล์ | คำอธิบาย |
|------|---------|
| `__init__.py` | Package init |
| `rate_limiter.py` | Rate limiting with token bucket |
| `circuit_breaker.py` | Circuit breaker pattern |
| `self_healer.py` | Auto-healing system |
| `memory_manager.py` | TTL/WeakRef cache, memory monitoring |
| `shutdown_manager.py` | Graceful shutdown coordination |
| `error_recovery.py` | Smart exponential backoff with jitter |

---

## ⚠️ Common Issues to Check

### 1. Import Path Errors
- ตรวจสอบ relative imports (`.module` vs `..module`)
- ตรวจสอบว่า `__init__.py` มี re-exports ถูกต้อง

### 2. Missing Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Environment Variables
- `DISCORD_TOKEN` - Required
- `GEMINI_API_KEY` - Required
- ดูรายละเอียดใน `config.py`

### 4. Database Issues
```powershell
python scripts/maintenance/check_db.py
```

---

## 📅 Audit Log

| วันที่ | ผู้ตรวจ | บัคที่พบ | สถานะ |
|--------|---------|---------|-------|
| 2026-01-16 | ME | `ai_cog.py` import path error | ✅ Fixed |
| 2026-01-17 | ME | `rate_limiter.py` format_rate_limit_stats crash | ✅ Fixed |
| 2026-01-17 | ME | `tools.py` sanitize_message_content security bugs | ✅ Fixed |
| 2026-01-17 | ME | 19 tests out of sync with implementation | ✅ Fixed |
| 2026-01-19 | ME | `music/cog.py` circular import with spotify_handler | ✅ Fixed |
| 2026-01-19 | ME | `constants.py` missing `GAME_SEARCH_KEYWORDS` | ✅ Fixed |
| 2026-01-19 | ME | `faust_data.py` missing `ESCALATION_FRAMINGS` | ✅ Fixed |
| 2026-01-19 | ME | `roleplay_data.py` missing `SERVER_LORE` dict | ✅ Fixed |
| 2026-01-19 | ME | `logic.py` duplicate function redefinition (F811) | ✅ Fixed |
| 2026-01-19 | ME | `memory_commands.py` wrong import path for Colors | ✅ Fixed |
| 2026-01-19 | ME | `ai_core/__init__.py` missing AI cog export | ✅ Fixed |
| 2026-01-19 | ME | `migrate_to_db.py` wrong PROJECT_ROOT path | ✅ Fixed |
| 2026-01-19 | ME | `database.py` export_to_json now splits by channel | ✅ Enhanced |
| 2026-01-20 | ME | `logic.py` duplicate IMAGEIO_AVAILABLE import | ✅ Fixed |
| 2026-01-20 | ME | `logic.py` dead code knowledge_context | ✅ Fixed |
| 2026-01-20 | ME | `logic.py` PIL Images NameError in finally | ✅ Fixed |
| 2026-01-20 | ME | `tools.py` webhook cache not cleared on channel delete | ✅ Fixed |
| 2026-01-20 | ME | `tools.py` background task only catches RuntimeError | ✅ Fixed |
| 2026-01-20 | ME | `tools.py` missing guild.me None check | ✅ Fixed |
| 2026-01-20 | ME | `storage.py` shallow copy in cache return | ✅ Fixed |
| 2026-01-20 | ME | `logic.py` magic number max_history | ✅ Fixed |
| 2026-01-25 | ME | 18 issues in Phase 6 deep code audit (exceptions, memory bounds, resource leaks) | ✅ Fixed |
| 2026-02-06 | ME | 38 issues in native_dashboard (Tauri) - XSS, CSP, async mutex, connection leaks | ✅ Fixed |
| 2026-02-06 | ME | 4 issues in rust_extensions - dimension check, stale refs, overflow, crop bounds | ✅ Fixed |
| 2026-02-06 | ME | 3 issues in `health_api/main.go` - dead stub, input validation, body limits | ✅ Fixed |
| 2026-02-06 | ME | 3 issues in `url_fetcher/main.go` - SSRF, body limit, timeout cap | ✅ Fixed |
| 2026-02-06 | ME | `check_db.py` connection leak - converted to `async with` | ✅ Fixed |
| 2026-02-06 | ME | `migrate_to_db.py` sync/async mismatch + non-existent method | ✅ Fixed |
| 2026-02-07 | ME | Phase 10: 9 test issues (skipped, warnings, incorrect assertions, duplicate code) | ✅ Fixed |

---

## 🔧 Quick Commands

```powershell
# ตรวจสอบทุกไฟล์
Get-ChildItem -Recurse -Filter "*.py" -File | 
  Where-Object { $_.FullName -notmatch "node_modules|__pycache__|\.venv|temp" } | 
  ForEach-Object { python -m py_compile $_.FullName }

# รันบอท
python bot.py

# รัน Dashboard (Tauri)
cd native_dashboard && .\target\release\bot-dashboard.exe

# รัน Tests
python -m pytest tests/ -v
```

---

## 🖥️ Native Dashboard (Tauri)

Dashboard ถูกเขียนใหม่เป็น Tauri (Rust + HTML/CSS/JS):

| Component | Path |
|-----------|------|
| Rust Backend | `native_dashboard/src/` |
| Frontend UI | `native_dashboard/ui/` |
| Executable | `native_dashboard/target/release/bot-dashboard.exe` |

### Features
- Bot Control (Start/Stop/Restart/Dev)
- Real-time Status
- Log Viewer
- Database Stats

### Build
```powershell
cd native_dashboard
cargo build --release
```
