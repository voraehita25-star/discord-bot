# Contributing Guide

ขอบคุณที่สนใจ contribute! นี่คือแนวทางสำหรับการพัฒนาโปรเจคนี้

## Development Setup

```bash
# Clone & install
git clone https://github.com/voraehita25-star/discord-bot.git
cd discord-bot
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov ruff mypy bandit[toml]

# Install pre-commit hooks
make install-hooks

# Copy and configure environment
cp env.example .env
```

## Code Standards

### Python

- **Formatter/Linter:** ruff (config in `pyproject.toml`)
- **Line length:** 100 characters
- **Target:** Python 3.14+
- **Type hints:** ใช้ modern syntax (`list[str]`, `dict[str, Any]`, `X | None`)
- **Async:** ใช้ `async/await` สำหรับ I/O ทั้งหมด (database, network, file)

### Rust

- **Linter:** `cargo clippy -- -W clippy::all`
- **Format:** `cargo fmt`

### Go

- **Linter:** `golangci-lint run`
- **Format:** `gofmt`

### TypeScript

- **Compiler:** `tsc --noEmit`
- **Test:** `npx vitest run`

## Branch & Commit Convention

### Branch Naming

```text
feature/short-description
fix/issue-description
refactor/area-description
```

### Commit Messages

```text
type: short description

type = feat | fix | refactor | test | docs | ci | chore
```

ตัวอย่าง:

```text
feat: add WebSocket idle timeout
fix: database pool semaphore timeout
test: add integration tests for shutdown sequence
docs: update database schema documentation
```

## Pull Request Process

1. สร้าง branch จาก `main`
2. เขียน/อัปเดต tests สำหรับ changes ทั้งหมด
3. รัน full test suite ก่อน push:

   ```bash
   make lint          # ruff check
   make test          # pytest (3,071 Python tests) — also run `npm test` in native_dashboard/ for 189 frontend tests
   make build-rust    # cargo test + clippy
   make build-go      # go test + go vet
   ```

4. ตรวจสอบว่า CI ผ่านทั้งหมด
5. อธิบาย changes ใน PR description

## Testing

```bash
# Run all Python tests
make test

# Run specific test file
pytest tests/test_database.py -v

# Run with coverage
pytest --cov=cogs --cov=utils --cov-report=term-missing

# Run Rust tests
cd rust_extensions && cargo test

# Run Go tests
cd go_services && go test ./... -v -race

# Run TypeScript tests
cd native_dashboard && npx vitest run
```

## Project Structure

| Directory            | Description                                                |
| -------------------- | ---------------------------------------------------------- |
| `cogs/ai_core/`      | AI chat system (Claude/Gemini, RAG, memory, dashboard API) |
| `cogs/music/`        | Music playback cog                                         |
| `utils/database/`    | Async SQLite with connection pool, migrations              |
| `utils/monitoring/`  | Health API, metrics, Sentry, structured logging            |
| `utils/reliability/` | Circuit breaker, rate limiter, error recovery              |
| `utils/web/`         | URL fetcher with SSRF protection                           |
| `rust_extensions/`   | PyO3 native extensions (media_processor, rag_engine)       |
| `go_services/`       | Go microservices (health_api, url_fetcher)                 |
| `native_dashboard/`  | Tauri v2 desktop dashboard                                 |

## Security

- **อย่า** commit secrets หรือ API keys (ตรวจสอบ `.gitignore`)
- ใช้ `hmac.compare_digest()` สำหรับ token comparison
- ใช้ parameterized queries สำหรับ SQL ทั้งหมด
- Validate user input ที่ system boundaries
- Report security issues ผ่าน private channel ไม่ใช่ public issue
