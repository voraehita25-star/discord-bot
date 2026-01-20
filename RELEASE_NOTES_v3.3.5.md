# Release v3.3.5

## 🔨 Major Refactoring

### tools.py Split into 5 Modules
Refactored the monolithic `tools.py` (1,405 lines) into focused, single-responsibility modules:

| Module | Lines | Purpose |
|--------|-------|---------|
| `sanitization.py` | 72 | Input sanitization (channels, roles, messages) |
| `webhook_cache.py` | 139 | Webhook caching system |
| `server_commands.py` | 606 | Discord server management commands |
| `tool_definitions.py` | 228 | Gemini API tool definitions |
| `tool_executor.py` | 307 | Tool execution & webhook sending |
| `tools.py` | 110 | Facade for backward compatibility |

**Benefits:**
- ✅ Better code organization
- ✅ Single responsibility per module
- ✅ Easier testing and maintenance
- ✅ 100% backward compatible

---

## 🧪 Testing Improvements

### New Test Files (+67 tests)
| File | Tests | Coverage |
|------|-------|----------|
| `test_music_queue.py` | 17 | QueueManager class |
| `test_fast_json.py` | 18 | Fast JSON utilities |
| `test_self_reflection.py` | 19 | SelfReflector class |
| `test_spotify_handler.py` | 14 | SpotifyHandler class |

**Total Tests: 218 → 285** ✅

---

## 🔄 CI/CD Improvements

### GitHub Actions
- Added **Python 3.10** to test matrix (3.10, 3.11, 3.12)
- Added **pytest-cov** for coverage reporting
- Added **Codecov** integration

### Dependabot
- Added `.github/dependabot.yml` for automated dependency updates
- Weekly updates for pip and github-actions

---

## 📦 Dependency Updates

| Package | Old | New |
|---------|-----|-----|
| google-genai | 1.56.0 | 1.59.0 |
| aiohttp | 3.13.2 | 3.13.3 |
| certifi | - | ≥2026.1.4 (security) |

---

## 📊 Stats

| Metric | Value |
|--------|-------|
| ✅ **Tests** | 285 passing |
| 📁 **Python Files** | 118 |
| 🔧 **Ruff Issues** | 0 |
| 📦 **New Modules** | 5 |

---

## 🔄 Migration Notes

No breaking changes. The `tools.py` refactoring maintains full backward compatibility - all existing imports continue to work.

---

**Full Changelog**: https://github.com/voraehita25-star/discord-bot/compare/v3.3.4...v3.3.5
