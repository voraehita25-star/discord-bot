# Testing Guide

> Last Updated: January 22, 2026 | Total: 3,157 Tests | 126 Test Files | All passing ✅ | 0 warnings ✅

This document explains how to run tests for the Discord Bot project.

## Quick Start

```bash
# Run all tests
python -m pytest

# Run with verbose output
python -m pytest -v

# Run specific test file
python -m pytest tests/test_database.py

# Run specific test class
python -m pytest tests/test_database.py::TestRateLimiter

# Run specific test method
python -m pytest tests/test_database.py::TestRateLimiter::test_token_consumption

# Collect tests only (verify)
python -m pytest tests/ --collect-only -q
```

## Test Structure (126 Files, 3,157 Tests)

```
tests/
├── __init__.py              # Package init
├── conftest.py              # Shared fixtures
├── test_*.py                # 126 test files covering all modules
│   ├── AI Core              # 25+ test files
│   ├── Music                # 10+ test files
│   ├── Database             # 5+ test files
│   ├── Reliability          # 15+ test files
│   ├── Monitoring           # 10+ test files
│   └── Utilities            # 50+ test files
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
