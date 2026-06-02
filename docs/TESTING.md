# Testing Guide

> Last Updated: May 29, 2026 | Python 3.14+ | Python Tests: 3,143 ✅ (98 files) + 1 skipped | Frontend Tests: 190 ✅ (10 vitest files) + 73 ✅ (8 Playwright spec files: smoke + interactions + a11y + visual regression + h5-importmap + h7-csp + inspection + screenshots) | Timeout: 30s per test
>
> Counts drift as tests are added — run `make test` / `npm test` / `npm run test:e2e` for the live numbers.

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

## Test Structure (98 Python files, 3,143 tests)

```text
tests/
├── __init__.py              # Package init
├── conftest.py              # Shared fixtures (mock bot, temp DB, guardrails reset)
├── test_boilerplate.py      # Parametrized structural tests (docstrings, singletons)
├── test_*.py                # 95 consolidated test files
│   ├── AI Core              # ~25 test files (ai_cache, ai_cog, logic, storage, dashboard_chat*, etc.)
│   ├── Music                # ~6 test files (music_cog, music_queue, spotify, ytdl, etc.)
│   ├── Dashboard            # 1 test file (dashboard_handlers — 53 tests)
│   ├── Database             # 1 test file (consolidated from 3)
│   ├── Reliability          # ~8 test files (circuit_breaker, rate_limiter, etc.)
│   ├── Monitoring           # ~5 test files (health_api, metrics, feedback, etc.)
│   └── Utilities            # ~25 test files (fast_json, localization, url_fetcher, etc.)
```

> Earlier consolidation (~early 2026) merged `_extended`, `_more`, `_module` variants
> into their base files and parametrized boilerplate tests. Current count: **98 files**.

## Frontend Test Structure (10 vitest files, 190 tests)

TypeScript tests run under [vitest](https://vitest.dev/) with a `jsdom` environment
(DOMPurify + KaTeX globals attached via test setup).

```text
native_dashboard/src-ts/
├── app.test.ts                     # app.ts — status/logs/DB/settings (legacy suite)
├── chat-manager.test.ts            # ChatManager — handleMessage dispatcher + state (23 tests)
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

## Headless E2E Tests (8 Playwright files, 70 tests)

Playwright drives a real Chromium against the **static dashboard UI** (`native_dashboard/ui/index.html`)
served by `python -m http.server`. Tauri's IPC layer is replaced at test time by a shim
(`tests-e2e/_fixtures/mock-tauri.ts`) that mocks `window.__TAURI__.core.invoke` and the WebSocket
stream — so no Tauri runtime, no bot process, no Discord token needed. (For a *real* Tauri Rust-IPC
round-trip — no mock — see the `validate_ipc.py` validator below.)

```text
native_dashboard/tests-e2e/
├── _fixtures/
│   └── mock-tauri.ts            # Tauri IPC shim + WS mock + page-error tracker
├── dashboard-smoke.spec.ts      # smoke tests covering recent UI fixes
├── interactions.spec.ts         # user-flow tests (click/type/keyboard)
├── a11y.spec.ts                 # axe-core audits — zero critical/serious WCAG 2.1 AA violations
├── visual-regression.spec.ts    # baselines — pages, themes, modals
├── visual-regression.spec.ts-snapshots/  # PNG baselines (chromium-win32, in git)
├── h5-importmap.spec.ts         # H5: import-map IPC resolves under withGlobalTauri:false
├── h7-csp.spec.ts               # H7: render under strict `style-src 'self'` (MathML, CSSOM)
├── dashboard-inspection.spec.ts # deep UI inspection (z-index, layout, console-error vigilance)
└── screenshots.spec.ts          # manual-inspection captures
```

Run from `native_dashboard/`:

```bash
npm run test:e2e                 # All 70 tests, headless Chromium
npm run test:e2e:ui              # Interactive UI mode for debugging
npm run test:e2e -- --update-snapshots   # Re-bake visual baselines after intentional UI changes
npm run test:e2e:screenshots     # Just the screenshot captures
```

CI: the `dashboard-test` job in `.github/workflows/ci.yml` runs vitest then Playwright.
On failure, `playwright-report/` and `test-results/` are uploaded as artifacts (7-day retention)
so the diff is debuggable without re-running locally.

## Opt-in Runtime Validators (`scripts/dev/`)

Unlike the hermetic, mocked pytest/vitest suites above, these scripts exercise the **real**
code paths end-to-end — they spawn the real `claude` CLI, call the real Anthropic SDK, run the
real document extractor, and drive the real Tauri app. They need auth / cost API calls, so they
are **NOT** part of `make test` or CI — run them manually when validating a release or a change
to those paths.

```bash
# Real AI / document / CLI paths (run from repo root)
python scripts/dev/validate_runtime.py            # docx + cli + confine (default; no SDK billing)
python scripts/dev/validate_runtime.py --all      # + anthropic SDK smoke (needs API credit)
python scripts/dev/validate_runtime.py --docx     # pick individual checks
#   --docx     DOCX extraction + XXE confinement   (no API; needs python-docx + defusedxml)
#   --cli      Claude CLI smoke via the bot's real subprocess path   (1 CLI call)
#   --confine  H1: a prompt-injected doc must NOT leak an out-of-dir file   (1 CLI call)
#   --sdk      anthropic SDK smoke   (1 API call; needs ANTHROPIC_API_KEY with credit)

# Real Tauri Rust-IPC round-trip (no mock) via WebDriver/WebView2
python scripts/dev/validate_ipc.py                # get_base_path (raw bridge) + get_status (import-map)
```

`validate_ipc.py` prerequisites (one-time, Windows):

```bash
cargo install tauri-driver --locked
# download msedgedriver matching the installed WebView2 runtime version into
#   native_dashboard/.drivers/msedgedriver.exe   (https://msedgedriver.microsoft.com)
pip install selenium
cargo tauri build --no-bundle      # so target/release/bot-dashboard.exe exists
```

Both scripts exit 0 on success / 1 on failure (SDK billing errors are reported but don't fail the
run), so they can be wired into a manual release-gate if desired.

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
