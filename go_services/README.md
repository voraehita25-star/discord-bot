# Go Microservices

This directory contains high-performance microservices written in Go.

## Services

### 1. URL Fetcher (`url_fetcher/`)
Concurrent URL fetching service with content extraction.

**Features:**
- High-concurrency fetching with goroutines
- Rate limiting (20 req/s, burst 50)
- Automatic charset detection
- HTML content extraction (title, description, main text)
- Batch fetching (up to 20 URLs)
- URL scheme validation (http/https only — SSRF prevention)
- Request body size limit (1MB per batch request)
- User-provided timeout capped at 120 seconds

**Endpoints:**
- `GET /health` - Health check
- `GET /fetch?url=<url>` - Fetch single URL
- `POST /fetch/batch` - Fetch multiple URLs

### 2. Health API (`health_api/`)
Prometheus-compatible metrics and health monitoring.

**Features:**
- Prometheus metrics endpoint
- Service health tracking
- Kubernetes-compatible probes (liveness, readiness)
- Metrics push from Python
- Request body size limits (64KB single, 1MB batch)
- Batch processing with metric type validation (counter/histogram/gauge)
- Service name validation (max 100 characters)

**Endpoints:**
- `GET /metrics` - Prometheus metrics
- `GET /health` - Full health status
- `GET /health/live` - Liveness probe
- `GET /health/ready` - Readiness probe
- `POST /health/service` - Update service status
- `POST /metrics/push` - Push single metric
- `POST /metrics/batch` - Push batch metrics
- `GET /stats` - System statistics

## Building

### Prerequisites
- Go 1.22+ (install from https://go.dev/dl/)

### Build Commands

```powershell
# From project root
.\scripts\build_go.ps1           # Debug build
.\scripts\build_go.ps1 -Release  # Release build (optimized)
.\scripts\build_go.ps1 -Clean    # Clean and rebuild
.\scripts\build_go.ps1 -Run      # Build and start services
```

### Manual Build

```bash
cd go_services
go mod download
go build -o ../bin/url_fetcher.exe ./url_fetcher
go build -o ../bin/health_api.exe ./health_api
```

## Running

### Start Services

```powershell
# Start URL Fetcher (port 8081)
.\bin\url_fetcher.exe

# Start Health API (port 8082)
.\bin\health_api.exe
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `URL_FETCHER_PORT` | 8081 | URL Fetcher port |
| `HEALTH_API_PORT` | 8082 | Health API port |
| `BOT_VERSION` | dev | Version for health endpoint |

## Usage from Python

### URL Fetcher Client

```python
from utils.web.url_fetcher_client import URLFetcherClient, fetch_url, fetch_urls

# Single URL
result = await fetch_url("https://example.com")
print(result["title"])
print(result["content"][:500])

# Batch URLs
async with URLFetcherClient() as client:
    results = await client.fetch_batch([
        "https://a.com",
        "https://b.com",
    ])
    print(f"Success: {results['success_count']}")

# Check if Go service is used
print(f"Using Go service: {client.is_service_available}")
```

### Health API Client

```python
from utils.monitoring.health_client import (
    push_request_metric,
    push_ai_response_time,
    push_cache_metric,
    get_health_status,
)

# Push metrics
await push_request_metric("/api/chat", status="success", duration=0.5)
await push_ai_response_time(2.5)
await push_cache_metric(hit=True)

# Get health status
status = await get_health_status()
print(f"Status: {status['status']}")
```

## API Reference

### URL Fetcher

#### `GET /fetch?url=<url>`

Response:
```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "description": "This domain is for use in illustrative examples.",
  "content": "Example Domain\n\nThis domain is for use in illustrative examples...",
  "status_code": 200,
  "content_type": "text/html; charset=UTF-8",
  "fetch_time_ms": 234
}
```

#### `POST /fetch/batch`

Request:
```json
{
  "urls": ["https://a.com", "https://b.com"],
  "timeout": 30
}
```

Response:
```json
{
  "results": [...],
  "total_time_ms": 456,
  "success_count": 2,
  "error_count": 0
}
```

### Health API

#### `GET /health`

Response:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-20T12:00:00Z",
  "version": "3.2.4",
  "uptime": "2h30m15s",
  "services": {
    "bot": true,
    "database": true,
    "gemini_api": true
  },
  "metrics": {
    "memory_alloc_mb": 45.2,
    "memory_sys_mb": 100.5,
    "goroutines": 12,
    "gc_cycles": 5
  }
}
```

#### `POST /metrics/push`

Request:
```json
{
  "type": "histogram",
  "name": "ai_response_time",
  "value": 2.5,
  "labels": {}
}
```

## Prometheus Metrics

Available at `http://localhost:8082/metrics`:

```
# HELP discord_bot_requests_total Total number of requests
# TYPE discord_bot_requests_total counter
discord_bot_requests_total{endpoint="/api/chat",status="success"} 150

# HELP discord_bot_ai_response_seconds AI response time in seconds
# TYPE discord_bot_ai_response_seconds histogram
discord_bot_ai_response_seconds_bucket{le="0.5"} 10
discord_bot_ai_response_seconds_bucket{le="1"} 45
discord_bot_ai_response_seconds_bucket{le="2"} 120
...

# HELP discord_bot_memory_bytes Current memory usage
# TYPE discord_bot_memory_bytes gauge
discord_bot_memory_bytes 47185920
```

## Architecture

```
go_services/
├── go.mod                  # Go module definition
├── url_fetcher/
│   └── main.go             # URL fetcher service
└── health_api/
    └── main.go             # Health & metrics service
```

## Troubleshooting

### Service Not Starting

1. Check port availability: `netstat -an | findstr 8081`
2. Check firewall settings
3. Verify Go installation: `go version`

### Connection Refused from Python

1. Ensure services are running
2. Check environment variables match
3. Try direct curl: `curl http://localhost:8081/health`

### High Memory Usage

1. URL Fetcher has 10MB limit per response
2. Adjust `maxContentLength` if needed
3. Health API auto-collects metrics every 10s

## Development

### Running Tests

```bash
cd go_services
go test ./...
```

### Code Style

```bash
go fmt ./...
go vet ./...
```

### Adding New Endpoints

1. Add handler in `main.go`
2. Register with router: `r.Get("/new", handler)`
3. Update Python client if needed
