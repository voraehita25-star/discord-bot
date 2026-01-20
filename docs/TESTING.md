# Testing Guide

> Last Updated: January 21, 2026 | Total: 362 Tests | 22 Test Files | Ruff: 0 issues ✅

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

## Test Structure (22 Files, 362 Tests)

```
tests/
├── __init__.py              # Package init
├── conftest.py              # Shared fixtures
├── test_ai_core.py          # AI core functionality
├── test_ai_integration.py   # AI integration tests
├── test_circuit_breaker.py  # Circuit breaker pattern
├── test_consolidator.py     # Memory consolidator tests
├── test_content_processor.py # Content processor tests
├── test_database.py         # Database, sanitization
├── test_emoji_voice.py      # Emoji/voice handling
├── test_error_recovery.py   # Error recovery tests
├── test_fast_json.py        # Fast JSON utilities
├── test_guardrails.py       # Guardrails tests
├── test_memory_modules.py   # Memory systems
├── test_music_integration.py # Music player tests
├── test_music_queue.py      # Queue manager tests
├── test_performance_tracker.py # Performance tracker tests
├── test_rate_limiter.py     # Rate limiting
├── test_self_reflection.py  # Self reflector tests
├── test_spotify_handler.py  # Spotify handler tests
├── test_spotify_integration.py # Spotify integration
├── test_summarizer.py       # Summarizer tests
├── test_tools.py            # Server tools
├── test_url_fetcher.py      # URL content fetcher
└── test_webhooks.py         # Webhook handling
```

## Test Categories

### AI Tests
- **test_ai_core.py**: RAG, chat storage, session management
- **test_ai_integration.py**: End-to-end AI integration
- **test_memory_modules.py**: History, guardrails, intent, entity, cache

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
