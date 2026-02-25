# Release Notes v3.3.11

**Release Date:** February 26, 2026

## 🐛 Bug Fixes (7 fixes)

### Critical
- **Fix: `get_ai_history` returned oldest messages instead of newest** — `ORDER BY id ASC LIMIT ?` returned the first N rows from DB instead of the most recent N. This caused duplicate detection in `storage.py` to silently fail, potentially losing or duplicating chat history. Fixed with subquery `ORDER BY id DESC LIMIT ?` wrapped in `ORDER BY id ASC`.

- **Fix: Music auto-disconnect timer never started** — `_DictProxy.__contains__` checked if the guild had *any* state, not whether `auto_disconnect_task` was set. Since the bot was already in voice (creating guild state), the timer creation was always skipped. Bot would stay in empty voice channels forever.

### Medium
- **Fix: Resume/Fix commands could crash with TypeError** — Same `_DictProxy.__contains__` bug affected `pause_start` and `current_track` checks in 4 locations. If the attribute was `None` but guild had state, `time.time() - None` would raise TypeError.

- **Fix: `get_queue` used broken `__contains__` check** — Replaced with direct `_gs().queue` access which is simpler and correct.

### Low
- **Fix: Missing semicolon in migration 003** — Last `CREATE INDEX` in `003_fix_user_facts.sql` lacked trailing `;`.

- **Fix: Pre-existing test failure `test_pool_semaphore_created`** — `_pool_semaphore` is lazily initialized; test now calls `_get_pool_semaphore()` first.

- **Fix: `test_ai_stats_json` mock serialization** — Health API test needed explicit mock for `get_ai_performance_stats()` return value.

## 🧪 Test Suite Consolidation

Major cleanup reducing maintenance burden while preserving full coverage:

| | Before | After | Change |
|---|---|---|---|
| **Test files** | 129 | **82** | **-36%** |
| **Test functions** | 3,372 | **3,007** | **-11%** |
| **Execution time (full)** | 17.2s | **14.8s** | **-14%** |
| **Execution time (fast)** | 10.7s | **8.6s** | **-20%** |

### What changed
- **Parametrized boilerplate** — 39 repetitive tests (`test_module_has_docstring`, `test_singleton_exists`, etc.) consolidated into `test_boilerplate.py` with 38 parametrized tests
- **Merged 28 file groups** — `_extended`, `_more`, `_module`, `_new` variants merged into their base files, removing 47 files
- **Cached conftest import** — `guardrails` module import (933ms) cached at module level instead of per-test teardown

### New: `scripts/run_tests.ps1`
PowerShell test runner that prevents pipe-related hangs:
```powershell
.\scripts\run_tests.ps1              # All tests
.\scripts\run_tests.ps1 -Fast        # Skip slow tests (~8.5s)
.\scripts\run_tests.ps1 database     # Filter by keyword
.\scripts\run_tests.ps1 -Coverage    # With coverage
```

### New: `@pytest.mark.slow`
3 tests with real `asyncio.sleep`/timeout marked as slow (skippable with `-Fast`):
- `test_loop_updates_bot_data` (4.1s)
- `test_stream_timeout` (1.0s)
- `test_timeout_with_broken_ws` (1.0s)

### New: `make test-fast`
Makefile target for fast test runs skipping slow tests.

## 📝 Documentation Updates
- `README.md` — Updated test count, testing section with `run_tests.ps1` commands
- `docs/TESTING.md` — Updated structure, added hang warning, new commands
- `docs/DEVELOPER_GUIDE.md` — Updated header, test suite section, footer
- `docs/CODE_AUDIT_GUIDE.md` — Updated test/file counts
- `Makefile` — Added `test-fast` target

## Files Changed
- **Modified:** 8 source files, 39 test files, 5 docs, 1 Makefile
- **Deleted:** 47 test files (merged into base files)
- **Added:** `tests/test_boilerplate.py`, `scripts/run_tests.ps1`
