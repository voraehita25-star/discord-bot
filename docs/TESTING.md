# Testing Guide

> Last Updated: February 26, 2026 | Total: 3,007 Tests | 82 Test Files | All passing ✅ | 0 skipped ✅ | 3 warnings (harmless mock RuntimeWarning)

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
> ```powershell
> Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
> ```

## Test Structure (82 Files, 3,007 Tests)

```
tests/
├── __init__.py              # Package init
├── conftest.py              # Shared fixtures (mock bot, temp DB, guardrails reset)
├── test_boilerplate.py      # Parametrized structural tests (docstrings, singletons)
├── test_*.py                # 82 consolidated test files
│   ├── AI Core              # ~20 test files (ai_cache, ai_cog, logic, storage, etc.)
│   ├── Music                # ~5 test files (music_cog, music_queue, spotify, ytdl)
│   ├── Database             # 1 test file (consolidated from 3)
│   ├── Reliability          # ~8 test files (circuit_breaker, rate_limiter, etc.)
│   ├── Monitoring           # ~5 test files (health_api, metrics, feedback, etc.)
│   └── Utilities            # ~20 test files (fast_json, localization, url_fetcher, etc.)
```

> Tests were consolidated from 129 → 82 files by merging `_extended`, `_more`, `_module`
> variants into their base files and parametrizing boilerplate tests.

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
