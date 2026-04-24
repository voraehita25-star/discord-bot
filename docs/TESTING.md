# Testing Guide

> Last Updated: April 24, 2026 | Python 3.14+ | Python Tests: 3,071 ✅ (91 files) + 1 skipped | Frontend Tests: 189 ✅ (10 vitest files) | Timeout: 30s per test

This document explains how to run tests for the Discord Bot project.

## Quick Start

```powershell
# Recommended: use the test runner script (prevents pipe-related hangs)
.\scripts\run_tests.ps1              # Run all tests (~15s)
.\scripts\run_tests.ps1 -Fast        # Skip slow tests (~8.5s)
.\scripts\run_tests.ps1 database     # Run tests matching "database"
.\scripts\run_tests.ps1 -File test_ai_core.py
.\scripts\run_tests.ps1 -File test_database.py -TestName test_pool
.\scripts\run_tests.ps1 -Coverage    # With coverage report
```

```bash
# Or use pytest directly
python -m pytest tests/ -v
python -m pytest tests/test_database.py
python -m pytest tests/test_database.py::TestDatabaseInit::test_pool_semaphore_created
python -m pytest tests/ --collect-only -q
```

> **⚠️ Note:** If tests hang, kill stale Python processes first:
>
> ```powershell
> Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
> ```

## Test Structure (91 Python files, 3,071 tests)

```text
tests/
├── __init__.py              # Package init
├── conftest.py              # Shared fixtures (mock bot, temp DB, guardrails reset)
├── test_boilerplate.py      # Parametrized structural tests (docstrings, singletons)
├── test_*.py                # 89 consolidated test files
│   ├── AI Core              # ~20 test files (ai_cache, ai_cog, logic, storage, etc.)
│   ├── Music                # ~5 test files (music_cog, music_queue, spotify, ytdl)
│   ├── Dashboard            # 1 test file (dashboard_handlers - 42 tests)
│   ├── Database             # 1 test file (consolidated from 3)
│   ├── Reliability          # ~8 test files (circuit_breaker, rate_limiter, etc.)
│   ├── Monitoring           # ~5 test files (health_api, metrics, feedback, etc.)
│   └── Utilities            # ~20 test files (fast_json, localization, url_fetcher, etc.)
```

> Tests were consolidated from 129 → 84 files by merging `_extended`, `_more`, `_module`
> variants into their base files and parametrizing boilerplate tests.

## Frontend Test Structure (10 vitest files, 189 tests)

TypeScript tests run under [vitest](https://vitest.dev/) with a `jsdom` environment
(DOMPurify + KaTeX globals attached via test setup).

```text
native_dashboard/src-ts/
├── app.test.ts                     # app.ts — status/logs/DB/settings (legacy suite)
├── chat-manager.test.ts            # ChatManager — handleMessage dispatcher + state (22 tests)
├── e2e_smoke.test.ts               # Smoke-level end-to-end flows
└── chat/
    ├── formatter.test.ts           # Markdown + LaTeX + code fences + XSS (25 tests)
    ├── message-template.test.ts    # computeWindow + renderMessagesHtml (19 tests)
    ├── context-window.test.ts      # Token bar + LRU cache + localStorage (16 tests)
    ├── conversation-list.test.ts   # Filter + 200-cap + tag chips (18 tests)
    ├── conversation-modals.test.ts # Rename + delete isStreaming guard (16 tests)
    ├── search.test.ts              # wrapMatches + step cycling + keys (21 tests)
    └── prism.test.ts               # canonicalPrismLang + code highlight (13 tests)
```

Run from `native_dashboard/`:

```bash
npm test                 # Run all vitest suites once
npm run test:watch       # Watch mode
npm run test:coverage    # With coverage report
```

## Test Categories

### AI Tests

- **test_ai_core*.py**: RAG, chat storage, session management
- **test_ai_integration.py**: End-to-end AI integration
- **test_memory_*.py**: History, guardrails, intent, entity, cache

## Running Tests with Markers

```bash
# Skip slow tests
python -m pytest -m "not slow"

# Run only integration tests
python -m pytest -m integration

# Run tests that require API keys (need .env)
python -m pytest -m requires_api
```

## Coverage Report

```bash
# Install coverage
pip install pytest-cov

# Run with coverage
python -m pytest --cov=utils --cov=cogs --cov-report=html

# Open coverage report
start htmlcov/index.html
```

## Writing New Tests

### Example Test

```python
class TestMyFeature:
    """Test my feature functionality."""
    
    def test_basic_case(self) -> None:
        """Test the basic case."""
        result = my_function(input_value)
        assert result == expected_value
    
    @pytest.mark.asyncio
    async def test_async_function(self) -> None:
        """Test an async function."""
        result = await my_async_function()
        assert result is not None
    
    @pytest.mark.slow
    def test_slow_operation(self) -> None:
        """Test that takes a long time."""
        # This test will be skipped with -m "not slow"
        pass
```

### Using Fixtures

```python
def test_with_mock_bot(self, mock_bot) -> None:
    """Test using the mock bot fixture from conftest.py."""
    assert mock_bot.is_ready()

def test_with_temp_db(self, temp_db) -> None:
    """Test using temporary database."""
    # temp_db is the path to a temp .db file
    assert os.path.exists(temp_db)
```

## CI/CD Integration

Add to your CI workflow:

```yaml
- name: Run tests
  run: |
    pip install -r requirements.txt
    python -m pytest -v --tb=short
```
