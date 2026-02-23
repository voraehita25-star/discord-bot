# Cross-platform Makefile for Discord Bot
# Works on Linux, macOS, and Windows (with GNU Make)

.PHONY: help test lint build run docker clean install

# Default target
help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ======================== Development ========================

install: ## Install Python dependencies
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov ruff bandit[toml]

install-hooks: ## Install pre-commit hooks
	pip install pre-commit
	pre-commit install

run: ## Run the bot
	python bot.py

dev: ## Run the bot with dev watcher
	python scripts/dev_watcher.py

# ======================== Testing ========================

test: ## Run all Python tests
	python -m pytest tests/ -v --tb=short

test-quick: ## Run tests without verbose output
	python -m pytest tests/ --tb=short -q

test-cov: ## Run tests with coverage report
	python -m pytest tests/ --cov=cogs --cov=utils --cov-report=term --cov-report=html

test-go: ## Run Go tests
	cd go_services && go test ./... -v -race

test-rust: ## Run Rust tests
	cd rust_extensions && cargo test --all --verbose

test-all: test test-go test-rust ## Run all tests (Python + Go + Rust)

# ======================== Linting ========================

lint: ## Run Python linter (ruff)
	ruff check .

lint-fix: ## Run Python linter with auto-fix
	ruff check --fix .

lint-go: ## Run Go linter
	cd go_services && golangci-lint run ./...

lint-rust: ## Run Rust linter (clippy)
	cd rust_extensions && cargo clippy --all -- -D warnings

lint-all: lint lint-go lint-rust ## Run all linters

format: ## Format Python code
	ruff format .

security: ## Run security scan (bandit)
	bandit -c pyproject.toml -r cogs/ utils/ -ll

audit: ## Run dependency audit
	pip-audit --strict --desc

# ======================== Building ========================

build-go: ## Build Go services
	powershell -File scripts/build_go.ps1

build-rust: ## Build Rust extensions
	powershell -File scripts/build_rust.ps1

build-all: build-go build-rust ## Build all native extensions

# ======================== Docker ========================

docker: ## Build Docker image
	docker build -f docker/Dockerfile -t discord-bot .

docker-run: ## Run bot in Docker
	docker-compose -f docker/docker-compose.yml up -d

docker-stop: ## Stop Docker containers
	docker-compose -f docker/docker-compose.yml down

docker-logs: ## View Docker logs
	docker-compose -f docker/docker-compose.yml logs -f bot

docker-rebuild: ## Rebuild and restart Docker
	docker-compose -f docker/docker-compose.yml up -d --build

# ======================== Database ========================

db-check: ## Check database health
	python scripts/maintenance/check_db.py

db-migrate: ## Run database migrations
	python -c "import asyncio; from utils.database.database import Database; db = Database(); asyncio.run(db.init_schema())"

db-export: ## Export database to JSON
	python scripts/maintenance/view_db.py

# ======================== Cleanup ========================

clean: ## Clean temporary files and caches
	rm -rf __pycache__ **/__pycache__ .pytest_cache .ruff_cache htmlcov .coverage
	rm -rf temp/*.mp3 temp/*.webm temp/*.wav
	rm -rf rust_extensions/target/debug rust_extensions/target/release

clean-all: clean ## Deep clean including build artifacts
	rm -rf go_services/health_api/health_api go_services/url_fetcher/url_fetcher
	rm -rf native_dashboard/target
