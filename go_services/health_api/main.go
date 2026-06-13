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

// GetStatus returns the current health status
func (h *HealthService) GetStatus() HealthStatus {
	// ReadMemStats is a stop-the-world operation that reads only runtime state,
	// not h.services, so take it BEFORE acquiring the read lock. This keeps
	// frequently-polled probes (/health, /health/ready, /stats) from serializing
	// the brief STW pause behind h.mu.RLock().
	var m runtime.MemStats
	runtime.ReadMemStats(&m)

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
			"memory_alloc_mb": float64(m.Alloc) / 1024 / 1024,
			"memory_sys_mb":   float64(m.Sys) / 1024 / 1024,
			"goroutines":      runtime.NumGoroutine(),
			"gc_cycles":       m.NumGC,
		},
	}
}

// collectSystemMetrics updates system metrics
func collectSystemMetrics() {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
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

	// Prometheus metrics endpoint
	r.Handle("/metrics", promhttp.Handler())

	// Health check endpoints
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

		// Update service status (called from Python)
		r.Post("/health/service", func(w http.ResponseWriter, r *http.Request) {
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

			if !healthService.SetServiceStatus(payload.Name, payload.Healthy) {
				http.Error(w, "service map full", http.StatusConflict)
				return
			}
			w.WriteHeader(http.StatusOK)
		})

		// Push metrics (called from Python)
		r.Post("/metrics/push", func(w http.ResponseWriter, r *http.Request) {
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
				}
			case "histogram":
				// Reject NaN/Infinity values that would corrupt metrics
				if math.IsNaN(payload.Value) || math.IsInf(payload.Value, 0) {
					http.Error(w, "metric value must be finite", http.StatusBadRequest)
					return
				}
				switch payload.Name {
				case "request_duration":
					requestDuration.WithLabelValues(safeLabel("endpoint", payload.Labels["endpoint"])).Observe(payload.Value)
				case "ai_response_time":
					aiResponseTime.Observe(payload.Value)
				}
			case "gauge":
				if math.IsNaN(payload.Value) || math.IsInf(payload.Value, 0) {
					http.Error(w, "gauge value must be finite", http.StatusBadRequest)
					return
				}
				switch payload.Name {
				case "active_connections":
					activeConnections.Set(payload.Value)
				case "circuit_breaker":
					circuitBreakerState.WithLabelValues(safeLabel("service", payload.Labels["service"])).Set(payload.Value)
				}
			default:
				http.Error(w, "unknown metric type", http.StatusBadRequest)
				return
			}

			w.WriteHeader(http.StatusOK)
		})

		// Batch push metrics
		r.Post("/metrics/batch", func(w http.ResponseWriter, r *http.Request) {
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
					// Skip NaN/Infinity values to prevent Prometheus histogram corruption
					if math.IsNaN(p.Value) || math.IsInf(p.Value, 0) {
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
						activeConnections.Set(p.Value)
						processed++
					case "circuit_breaker":
						circuitBreakerState.WithLabelValues(safeLabel("service", p.Labels["service"])).Set(p.Value)
						processed++
					}
					// Unknown metric types in batch are silently skipped (consistent with batch semantics)
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
		})
	}) // end auth-protected Group

	// Stats summary
	r.Get("/stats", func(w http.ResponseWriter, r *http.Request) {
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

	// Graceful shutdown
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
	}()

	log.Printf("Health API service starting on %s:%s", bindHost, port)
	log.Printf("Metrics available at http://%s:%s/metrics", bindHost, port)

	// Use errors.Is for forward-compatible comparison.
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatalf("Server error: %v", err)
	}
}
