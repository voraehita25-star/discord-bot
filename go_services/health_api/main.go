package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"log"
	"math"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

const (
	defaultPort    = "8082"
	maxServices    = 100
	maxLabelLength = 64
)

// Metrics
var (
	requestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "discord_bot_requests_total",
			Help: "Total number of requests",
		},
		[]string{"endpoint", "status"},
	)

	requestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "discord_bot_request_duration_seconds",
			Help:    "Request duration in seconds",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"endpoint"},
	)

	aiResponseTime = promauto.NewHistogram(
		prometheus.HistogramOpts{
			Name:    "discord_bot_ai_response_seconds",
			Help:    "AI response time in seconds",
			Buckets: []float64{0.5, 1, 2, 5, 10, 30, 60},
		},
	)

	activeConnections = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "discord_bot_active_connections",
			Help: "Number of active connections",
		},
	)

	memoryUsage = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "discord_bot_memory_bytes",
			Help: "Current memory usage in bytes",
		},
	)

	goroutineCount = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "discord_bot_goroutines",
			Help: "Number of goroutines",
		},
	)

	circuitBreakerState = promauto.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "discord_bot_circuit_breaker_state",
			Help: "Circuit breaker state (0=closed, 1=half-open, 2=open)",
		},
		[]string{"service"},
	)

	rateLimitHits = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "discord_bot_rate_limit_hits_total",
			Help: "Total rate limit hits",
		},
		[]string{"type"},
	)

	cacheHits = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "discord_bot_cache_total",
			Help: "Cache hits and misses",
		},
		[]string{"result"}, // "hit" or "miss"
	)

	tokensUsed = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "discord_bot_tokens_total",
			Help: "Total tokens used",
		},
		[]string{"type"}, // "input" or "output"
	)
)

// HealthStatus represents the health of the system
type HealthStatus struct {
	Status    string          `json:"status"`
	Timestamp string          `json:"timestamp"`
	Version   string          `json:"version"`
	Uptime    string          `json:"uptime"`
	Services  map[string]bool `json:"services"`
	Metrics   map[string]any  `json:"metrics"`
}

// MetricsPayload for receiving metrics from Python
type MetricsPayload struct {
	Type   string            `json:"type"`
	Name   string            `json:"name"`
	Value  float64           `json:"value"`
	Labels map[string]string `json:"labels,omitempty"`
}

// HealthService manages health checks
type HealthService struct {
	startTime time.Time
	version   string
	mu        sync.RWMutex
	services  map[string]bool
}

// NewHealthService creates a new health service
func NewHealthService(version string) *HealthService {
	return &HealthService{
		startTime: time.Now(),
		version:   version,
		services:  make(map[string]bool),
	}
}

// SetServiceStatus sets the status of a service.
// Returns false if the service map is full and the name is new.
func (h *HealthService) SetServiceStatus(name string, healthy bool) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	// Only allow update for existing keys or insert if under cap
	if _, exists := h.services[name]; !exists && len(h.services) >= maxServices {
		log.Printf("WARNING: service map full (%d), rejecting new service: %s", maxServices, name)
		return false
	}
	h.services[name] = healthy
	return true
}

// Cached MemStats snapshot, refreshed by collectSystemMetrics() on the 10s
// collector tick. GetStatus reads these atomics instead of calling
// runtime.ReadMemStats() inline: that is a stop-the-world pause, and GetStatus
// backs the UNAUTHENTICATED /health, /health/ready and /stats handlers, so an
// inline read let a tight request loop force repeated STW GC pauses (a DoS
// lever once bound to a non-loopback address). The figures stay fresh within
// the collector interval; runtime.NumGoroutine() is cheap and stays inline.
var (
	cachedMemAlloc atomic.Uint64
	cachedMemSys   atomic.Uint64
	cachedNumGC    atomic.Uint32
)

// GetStatus returns the current health status
func (h *HealthService) GetStatus() HealthStatus {
	// Read the cached MemStats snapshot (see cachedMem* above) instead of a
	// per-request stop-the-world runtime.ReadMemStats. NumGoroutine() is cheap,
	// so keep it live.
	memAlloc := cachedMemAlloc.Load()
	memSys := cachedMemSys.Load()
	numGC := cachedNumGC.Load()

	h.mu.RLock()
	defer h.mu.RUnlock()

	status := "healthy"
	for _, healthy := range h.services {
		if !healthy {
			status = "degraded"
			break
		}
	}

	servicesCopy := make(map[string]bool)
	for k, v := range h.services {
		servicesCopy[k] = v
	}

	return HealthStatus{
		Status:    status,
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Version:   h.version,
		Uptime:    time.Since(h.startTime).String(),
		Services:  servicesCopy,
		Metrics: map[string]any{
			"memory_alloc_mb": float64(memAlloc) / 1024 / 1024,
			"memory_sys_mb":   float64(memSys) / 1024 / 1024,
			"goroutines":      runtime.NumGoroutine(),
			"gc_cycles":       numGC,
		},
	}
}

// collectSystemMetrics updates system metrics. This is the ONLY place that
// calls the stop-the-world runtime.ReadMemStats (every 10s on the collector
// tick); GetStatus reads the cached snapshot it stores here.
func collectSystemMetrics() {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	cachedMemAlloc.Store(m.Alloc)
	cachedMemSys.Store(m.Sys)
	cachedNumGC.Store(m.NumGC)
	memoryUsage.Set(float64(m.Alloc))
	goroutineCount.Set(float64(runtime.NumGoroutine()))
}

// sanitizeLabel truncates and cleans a Prometheus label value to prevent
// cardinality explosion from arbitrary user-supplied values.
func sanitizeLabel(value string) string {
	if len(value) > maxLabelLength {
		value = value[:maxLabelLength]
	}
	return value
}

// allowedMetricNames restricts which metric names are accepted via push endpoints.
var allowedMetricNames = map[string]bool{
	"requests": true, "rate_limit": true, "cache": true, "tokens": true,
	"request_duration": true, "ai_response_time": true,
	"active_connections": true, "circuit_breaker": true,
}

// allowedLabelValues restricts label values to a known set to prevent cardinality explosion.
var allowedLabelValues = map[string]map[string]bool{
	"status":   {"success": true, "error": true, "timeout": true, "other": true},
	"result":   {"hit": true, "miss": true},
	"type":     {"input": true, "output": true, "user": true, "channel": true, "guild": true},
	"endpoint": {"ai": true, "music": true, "spotify": true, "health": true, "dashboard": true, "command": true, "api": true},
	"service":  {"gemini": true, "spotify": true, "database": true, "health": true, "url_fetcher": true},
}

// requireBearerToken builds an HTTP middleware that requires
// `Authorization: Bearer <token>` on every request. If `expected` is empty
// it fails CLOSED — every write is rejected. That's deliberate: a default
// of "skip auth when no token is configured" would mean a fresh deploy
// that forgot to set HEALTH_API_TOKEN silently runs with no auth at all,
// and an attacker who can reach the bind address can poison every metric.
// Use constant-time comparison to avoid token-length / prefix timing leaks.
func requireBearerToken(expected string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if expected == "" {
				http.Error(w, "service refuses writes: HEALTH_API_TOKEN not configured", http.StatusServiceUnavailable)
				return
			}
			authHdr := r.Header.Get("Authorization")
			const prefix = "Bearer "
			if !strings.HasPrefix(authHdr, prefix) {
				w.Header().Set("WWW-Authenticate", `Bearer realm="health_api"`)
				http.Error(w, "missing bearer token", http.StatusUnauthorized)
				return
			}
			provided := strings.TrimSpace(authHdr[len(prefix):])
			// subtle.ConstantTimeCompare requires equal-length inputs to be
			// useful — guard the length first, then compare bytes.
			if len(provided) != len(expected) || subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) != 1 {
				http.Error(w, "invalid bearer token", http.StatusUnauthorized)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// requireReadToken builds middleware for the READ endpoints (/metrics, /stats)
// that mirrors the Python sibling's posture (utils/monitoring/health_api.py
// _PROTECTED_ENDPOINTS includes /metrics and /stats). It enforces the bearer
// token ONLY when one is configured: with a token set, /metrics + /stats are
// no longer served anonymously (closing the auth-parity gap with Python); with
// no token set, reads stay anonymous so the default tokenless Prometheus scrape
// keeps working — go-health-1's bind gate keeps that case loopback-only.
//
// This is deliberately NOT requireBearerToken: writes must stay fail-CLOSED
// (503 when no token), but a tokenless deploy must still be able to scrape
// /metrics on loopback, so reads degrade to anonymous instead of 503.
// The /health* probes are intentionally NOT wrapped — the Python health
// poller fetches GO_HEALTH_API_URL (/health) with no Authorization header,
// and Kubernetes-style liveness/readiness probes need them unauthenticated.
func requireReadToken(expected string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		if expected == "" {
			// No token configured: reads are anonymous (loopback-only via the
			// bind gate). Return next unwrapped so there's zero per-request cost.
			return next
		}
		// A token is configured — require it, reusing the same constant-time
		// bearer check as the write endpoints.
		return requireBearerToken(expected)(next)
	}
}

// isTruthy reports whether an env value should be treated as "on". Stricter
// than the Python sibling's "any non-empty string is truthy" (health_api.py
// :102-104): only an explicit affirmative opens the gate, so a stray
// HEALTH_API_ALLOW_REMOTE=0 / false / no does NOT accidentally allow a
// non-loopback bind. Anything unrecognized is treated as false (fail-safe).
func isTruthy(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

// isLoopbackHost reports whether bindHost is a loopback address that is safe to
// bind without HEALTH_API_ALLOW_REMOTE. Matches the Python sibling's
// _LOCALHOST_ADDRESSES set (health_api.py:77) plus the bracketed-IPv6 form.
func isLoopbackHost(host string) bool {
	switch strings.ToLower(strings.TrimSpace(host)) {
	case "127.0.0.1", "localhost", "::1", "[::1]":
		return true
	default:
		return false
	}
}

// safeLabel returns value only if it's in the allowed set for that label key,
// otherwise returns "other".
func safeLabel(key, value string) string {
	if allowed, ok := allowedLabelValues[key]; ok {
		sanitized := sanitizeLabel(value)
		if allowed[sanitized] {
			return sanitized
		}
	}
	// Unknown key or value not in allowed set — return "other" to prevent label cardinality explosion
	return "other"
}

// handleServiceStatus updates a service's health status (called from Python).
func (h *HealthService) handleServiceStatus(w http.ResponseWriter, r *http.Request) {
	// Limit request body size
	r.Body = http.MaxBytesReader(w, r.Body, 1<<16) // 64KB

	var payload struct {
		Name    string `json:"name"`
		Healthy bool   `json:"healthy"`
	}

	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}

	// Validate service name (prevent unbounded map growth)
	if len(payload.Name) == 0 || len(payload.Name) > 100 {
		http.Error(w, "invalid service name", http.StatusBadRequest)
		return
	}

	if !h.SetServiceStatus(payload.Name, payload.Healthy) {
		http.Error(w, "service map full", http.StatusConflict)
		return
	}
	w.WriteHeader(http.StatusOK)
}

// handleMetricsPush ingests a single metric (called from Python).
func (h *HealthService) handleMetricsPush(w http.ResponseWriter, r *http.Request) {
	// Limit request body size
	r.Body = http.MaxBytesReader(w, r.Body, 1<<16) // 64KB

	var payload MetricsPayload
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}

	// Validate metric name against allowlist
	if !allowedMetricNames[payload.Name] {
		http.Error(w, "unknown metric name", http.StatusBadRequest)
		return
	}

	switch payload.Type {
	case "counter":
		// Prometheus Counter.Add() panics on negative values, and NaN/Inf
		// will silently corrupt the metric (any subsequent Add becomes
		// NaN-poisoned). Reject all three up-front. Note: `value < 0`
		// is `false` for NaN, so we have to check NaN/Inf explicitly.
		//
		// DEFENSE-IN-DEPTH NOTE (go-health-3): the NaN/Inf arms are
		// currently UNREACHABLE via this HTTP path — encoding/json rejects
		// NaN/Infinity/overflow/quoted-number bodies before the switch runs,
		// so every such request already returns 400 "invalid JSON". They are
		// kept (not deleted) so that if a future non-JSON ingestion path is
		// ever wired to this validation it stays poison-proof. The predicate
		// itself is locked by TestNaNInfGuardLogic in main_test.go (which
		// exercises the guard condition directly, bypassing the decoder). The
		// `value < 0` arm IS reachable and is the live, tested protection.
		if math.IsNaN(payload.Value) || math.IsInf(payload.Value, 0) || payload.Value < 0 {
			http.Error(w, "counter value must be non-negative finite", http.StatusBadRequest)
			return
		}
		switch payload.Name {
		case "requests":
			status := safeLabel("status", payload.Labels["status"])
			endpoint := safeLabel("endpoint", payload.Labels["endpoint"])
			requestsTotal.WithLabelValues(endpoint, status).Add(payload.Value)
		case "rate_limit":
			rateLimitHits.WithLabelValues(safeLabel("type", payload.Labels["type"])).Add(payload.Value)
		case "cache":
			cacheHits.WithLabelValues(safeLabel("result", payload.Labels["result"])).Add(payload.Value)
		case "tokens":
			tokensUsed.WithLabelValues(safeLabel("type", payload.Labels["type"])).Add(payload.Value)
		default:
			http.Error(w, "metric name/type mismatch", http.StatusBadRequest)
			return
		}
	case "histogram":
		// Reject NaN/Infinity values that would corrupt metrics.
		// Histogram metrics are durations (non-negative); a negative
		// observation poisons the histogram _sum, so reject those too.
		if math.IsNaN(payload.Value) || math.IsInf(payload.Value, 0) || payload.Value < 0 {
			http.Error(w, "metric value must be finite", http.StatusBadRequest)
			return
		}
		switch payload.Name {
		case "request_duration":
			requestDuration.WithLabelValues(safeLabel("endpoint", payload.Labels["endpoint"])).Observe(payload.Value)
		case "ai_response_time":
			aiResponseTime.Observe(payload.Value)
		default:
			http.Error(w, "metric name/type mismatch", http.StatusBadRequest)
			return
		}
	case "gauge":
		if math.IsNaN(payload.Value) || math.IsInf(payload.Value, 0) {
			http.Error(w, "gauge value must be finite", http.StatusBadRequest)
			return
		}
		switch payload.Name {
		case "active_connections":
			// active_connections is a count — reject negatives, like the
			// counter/histogram branches above.
			if payload.Value < 0 {
				http.Error(w, "active_connections must be non-negative", http.StatusBadRequest)
				return
			}
			activeConnections.Set(payload.Value)
		case "circuit_breaker":
			// circuit_breaker is a tri-state enum (0=closed, 1=half-open,
			// 2=open per the gauge Help text) — reject anything else so a
			// bad push can't corrupt dashboards/alerts that map it to a state.
			if payload.Value != 0 && payload.Value != 1 && payload.Value != 2 {
				http.Error(w, "circuit_breaker value must be 0, 1, or 2", http.StatusBadRequest)
				return
			}
			circuitBreakerState.WithLabelValues(safeLabel("service", payload.Labels["service"])).Set(payload.Value)
		default:
			http.Error(w, "metric name/type mismatch", http.StatusBadRequest)
			return
		}
	default:
		http.Error(w, "unknown metric type", http.StatusBadRequest)
		return
	}

	w.WriteHeader(http.StatusOK)
}

// handleMetricsBatch ingests a batch of metrics (called from Python).
func (h *HealthService) handleMetricsBatch(w http.ResponseWriter, r *http.Request) {
	// Limit request body size to 1MB to prevent abuse
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)

	var payloads []MetricsPayload
	if err := json.NewDecoder(r.Body).Decode(&payloads); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}

	// Limit batch size to prevent abuse
	if len(payloads) > 1000 {
		http.Error(w, "batch too large (max 1000)", http.StatusBadRequest)
		return
	}

	processed := 0
	for _, p := range payloads {
		// Skip unknown metric names
		if !allowedMetricNames[p.Name] {
			continue
		}
		switch p.Type {
		case "counter":
			// Skip negative / NaN / Inf — Counter.Add panics on negative
			// and is silently poisoned by NaN/Inf (`p.Value < 0` is
			// false for NaN so the explicit checks are required).
			if math.IsNaN(p.Value) || math.IsInf(p.Value, 0) || p.Value < 0 {
				continue
			}
			switch p.Name {
			case "requests":
				status := safeLabel("status", p.Labels["status"])
				requestsTotal.WithLabelValues(safeLabel("endpoint", p.Labels["endpoint"]), status).Add(p.Value)
				processed++
			case "rate_limit":
				rateLimitHits.WithLabelValues(safeLabel("type", p.Labels["type"])).Add(p.Value)
				processed++
			case "cache":
				cacheHits.WithLabelValues(safeLabel("result", p.Labels["result"])).Add(p.Value)
				processed++
			case "tokens":
				tokensUsed.WithLabelValues(safeLabel("type", p.Labels["type"])).Add(p.Value)
				processed++
			}
		case "histogram":
			// Skip NaN/Infinity values to prevent Prometheus histogram corruption.
			// Histogram metrics are durations (non-negative); a negative
			// observation poisons the histogram _sum, so skip those too.
			if math.IsNaN(p.Value) || math.IsInf(p.Value, 0) || p.Value < 0 {
				continue
			}
			switch p.Name {
			case "request_duration":
				requestDuration.WithLabelValues(safeLabel("endpoint", p.Labels["endpoint"])).Observe(p.Value)
				processed++
			case "ai_response_time":
				aiResponseTime.Observe(p.Value)
				processed++
			}
		case "gauge":
			if math.IsNaN(p.Value) || math.IsInf(p.Value, 0) {
				continue
			}
			switch p.Name {
			case "active_connections":
				// Reject negatives — see the single-push branch.
				if p.Value < 0 {
					continue
				}
				activeConnections.Set(p.Value)
				processed++
			case "circuit_breaker":
				// Tri-state enum {0,1,2} only — see the single-push branch.
				if p.Value != 0 && p.Value != 1 && p.Value != 2 {
					continue
				}
				circuitBreakerState.WithLabelValues(safeLabel("service", p.Labels["service"])).Set(p.Value)
				processed++
			}
		default:
			// Unknown metric type: not counted in processed (so it shows up
			// in the reported skipped count). The single-push endpoint
			// returns 400 for this; batch surfaces it via skipped instead.
			continue
		}
	}

	w.WriteHeader(http.StatusOK)
	// Report skipped alongside processed so a client with a typo in
	// type/name can detect that entries were dropped (the single-push
	// endpoint returns 400 for the same conditions; surface it here too).
	if err := json.NewEncoder(w).Encode(map[string]int{
		"processed": processed,
		"skipped":   len(payloads) - processed,
	}); err != nil {
		log.Printf("Failed to encode batch response: %v", err)
	}
}

// buildRouter wires the chi router: middleware, read endpoints and the
// token-gated write Group. Extracted from main() so the same wiring (and thus
// the security-critical middleware-to-route binding) can be exercised by an
// httptest integration test (TestRouterAuthWiring) instead of being reachable
// only by running the whole binary.
func buildRouter(healthService *HealthService, authToken string) chi.Router {
	r := chi.NewRouter()

	// Middleware
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	// NOTE: chi's middleware.Timeout only signals via the request context — it
	// does NOT interrupt handlers that ignore ctx, and can cause a
	// "superfluous response.WriteHeader" race if a slow handler eventually
	// writes after the timeout fires. We rely on http.Server.WriteTimeout
	// (configured below) to bound per-request time instead.
	// Security headers
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("X-Content-Type-Options", "nosniff")
			w.Header().Set("X-Frame-Options", "DENY")
			next.ServeHTTP(w, r)
		})
	})

	// Prometheus metrics endpoint. Gated by requireReadToken: when
	// HEALTH_API_TOKEN is set the full Prometheus surface (token counts, cache
	// ratios, AI latency histograms, circuit-breaker states, ...) requires the
	// bearer token, matching the Python sibling's _PROTECTED_ENDPOINTS; when no
	// token is set it stays anonymous so the default loopback scrape works.
	r.With(requireReadToken(authToken)).Handle("/metrics", promhttp.Handler())

	// Health check endpoints. These probes (/health, /health/live,
	// /health/ready) are intentionally anonymous: the Python health poller
	// fetches /health with no Authorization header, and liveness/readiness
	// probes must not require a token. Only /metrics and /stats (which expose
	// the richer telemetry/version surface) are token-gated above/below.
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		status := healthService.GetStatus()
		w.Header().Set("Content-Type", "application/json")

		if status.Status != "healthy" {
			w.WriteHeader(http.StatusServiceUnavailable)
		}

		if err := json.NewEncoder(w).Encode(status); err != nil {
			log.Printf("Failed to encode health status: %v", err)
		}
	})

	// Simple liveness probe
	r.Get("/health/live", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		if _, err := w.Write([]byte("OK")); err != nil {
			log.Printf("Failed to write liveness response: %v", err)
		}
	})

	// Readiness probe
	r.Get("/health/ready", func(w http.ResponseWriter, r *http.Request) {
		status := healthService.GetStatus()
		if status.Status == "healthy" {
			w.WriteHeader(http.StatusOK)
			if _, err := w.Write([]byte("READY")); err != nil {
				log.Printf("Failed to write readiness response: %v", err)
			}
		} else {
			w.WriteHeader(http.StatusServiceUnavailable)
			if _, err := w.Write([]byte("NOT READY")); err != nil {
				log.Printf("Failed to write readiness response: %v", err)
			}
		}
	})

	// All write endpoints below require a bearer token. We wrap them in a
	// Group so the middleware applies to every Post() but does NOT touch
	// the read-only /health, /metrics, /stats handlers above.
	r.Group(func(r chi.Router) {
		r.Use(requireBearerToken(authToken))

		// Handlers are named methods (see below) so they can be exercised
		// directly by httptest in main_test.go — the security-critical input
		// validation here is the source of truth for the contract.
		r.Post("/health/service", healthService.handleServiceStatus)
		r.Post("/metrics/push", healthService.handleMetricsPush)
		r.Post("/metrics/batch", healthService.handleMetricsBatch)
	}) // end auth-protected Group

	// Stats summary. Token-gated like /metrics (see requireReadToken): the JSON
	// body exposes version, uptime, service names and memory/goroutine/GC
	// figures, which the Python sibling treats as a protected endpoint.
	r.With(requireReadToken(authToken)).Get("/stats", func(w http.ResponseWriter, r *http.Request) {
		// GetStatus() does its own fresh runtime.ReadMemStats for the JSON
		// body, and the background collector already refreshes the Prometheus
		// gauges every 10s — so calling collectSystemMetrics() here was a
		// redundant second stop-the-world MemStats read per request with no
		// effect on the response. Dropped.
		status := healthService.GetStatus()
		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(status); err != nil {
			log.Printf("Failed to encode stats response: %v", err)
		}
	})

	return r
}

func main() {
	port := os.Getenv("GO_HEALTH_API_PORT")
	if port == "" {
		legacyPort := os.Getenv("HEALTH_API_PORT")
		if legacyPort != "" && legacyPort != "8080" {
			port = legacyPort
		} else {
			port = defaultPort
		}
	}

	// Default to localhost binding for security (prevent unauthenticated external access)
	bindHost := os.Getenv("GO_HEALTH_API_HOST")
	if bindHost == "" {
		bindHost = os.Getenv("HEALTH_API_HOST")
	}
	if bindHost == "" {
		bindHost = "127.0.0.1"
	}

	// Accidental-exposure gate, mirroring the Python sibling
	// (utils/monitoring/health_api.py:102-112) and the env.example footgun
	// note: a non-loopback bindHost is forced back to 127.0.0.1 UNLESS
	// HEALTH_API_ALLOW_REMOTE is explicitly truthy. HEALTH_API_HOST is shared
	// with the Python service, so without this gate an operator who set
	// HEALTH_API_HOST=0.0.0.0 (+ALLOW_REMOTE) to expose the Python server would
	// unknowingly also expose this Go sidecar's anonymous read endpoints to all
	// interfaces. 127.0.0.1 stays the fail-safe default.
	if !isLoopbackHost(bindHost) && !isTruthy(os.Getenv("HEALTH_API_ALLOW_REMOTE")) {
		log.Printf(
			"WARNING: health host %q is not loopback — forcing bind to 127.0.0.1. "+
				"Set HEALTH_API_ALLOW_REMOTE=1 to opt into remote binding.",
			bindHost,
		)
		bindHost = "127.0.0.1"
	}

	version := os.Getenv("BOT_VERSION")
	if version == "" {
		version = "dev"
	}

	// Bearer token for write endpoints. Empty = writes are rejected entirely.
	// Read once at startup so a later env mutation can't sneak in a weaker
	// value while the server is running.
	authToken := os.Getenv("HEALTH_API_TOKEN")
	if authToken == "" {
		log.Println("WARNING: HEALTH_API_TOKEN not set — write endpoints (/health/service, /metrics/push, /metrics/batch) will refuse all requests")
	}

	healthService := NewHealthService(version)

	// Initialize default services
	healthService.SetServiceStatus("bot", true)
	healthService.SetServiceStatus("database", true)
	healthService.SetServiceStatus("gemini_api", true)

	// Build the router. Extracted into buildRouter so main_test.go can wire the
	// REAL router (same middleware-to-route binding) and assert the auth
	// boundary as a tested invariant — see TestRouterAuthWiring.
	r := buildRouter(healthService, authToken)

	// Prime the cached MemStats snapshot so the first /health|/stats request
	// (which reads the cache, not a live STW read) has real numbers before the
	// first 10s collector tick.
	collectSystemMetrics()

	// Create context for metrics collector goroutine
	metricsCtx, metricsCancel := context.WithCancel(context.Background())

	// Start metrics collector with cancellation support
	go func(ctx context.Context) {
		ticker := time.NewTicker(10 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				log.Println("Metrics collector stopped")
				return
			case <-ticker.C:
				collectSystemMetrics()
			}
		}
	}(metricsCtx)

	// Server
	server := &http.Server{
		Addr:              bindHost + ":" + port,
		Handler:           r,
		ReadTimeout:       15 * time.Second,
		ReadHeaderTimeout: 5 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	// Graceful shutdown. server.Shutdown closes the listener, which makes the
	// blocking ListenAndServe below return http.ErrServerClosed immediately —
	// but the in-flight connection drain keeps running here. main() must wait
	// on idleConnsClosed before returning, otherwise the process exits the
	// instant the listener closes and the drain (up to the 10s timeout) is cut
	// short, killing in-flight /metrics/batch, /metrics/push and
	// /health/service responses mid-write.
	idleConnsClosed := make(chan struct{})
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh

		log.Println("Shutting down...")
		// Cancel metrics collector first
		metricsCancel()

		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("Health API server shutdown error: %v", err)
		}
		close(idleConnsClosed)
	}()

	log.Printf("Health API service starting on %s:%s", bindHost, port)
	log.Printf("Metrics available at http://%s:%s/metrics", bindHost, port)

	// Use errors.Is for forward-compatible comparison.
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatalf("Server error: %v", err)
	}

	// ListenAndServe returned ErrServerClosed (clean shutdown path) — wait for
	// the drain goroutine to finish before exiting so in-flight requests can
	// complete or hit the 10s timeout.
	<-idleConnsClosed
}
