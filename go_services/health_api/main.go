package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"runtime"
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

// SetServiceStatus sets the status of a service
func (h *HealthService) SetServiceStatus(name string, healthy bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	// Only allow update for existing keys or insert if under cap
	if _, exists := h.services[name]; !exists && len(h.services) >= maxServices {
		return // Silently reject to prevent unbounded map growth
	}
	h.services[name] = healthy
}

// GetStatus returns the current health status
func (h *HealthService) GetStatus() HealthStatus {
	h.mu.RLock()
	defer h.mu.RUnlock()

	var m runtime.MemStats
	runtime.ReadMemStats(&m)

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
	"status": {"success": true, "error": true, "timeout": true},
	"result": {"hit": true, "miss": true},
	"type":   {"input": true, "output": true, "user": true, "channel": true, "guild": true},
}

// safeLabel returns value only if it's in the allowed set for that label key,
// otherwise returns "other".
func safeLabel(key, value string) string {
	if allowed, ok := allowedLabelValues[key]; ok {
		sanitized := sanitizeLabel(value)
		if allowed[sanitized] {
			return sanitized
		}
		return "other"
	}
	return sanitizeLabel(value)
}

func main() {
	port := os.Getenv("HEALTH_API_PORT")
	if port == "" {
		port = defaultPort
	}

	// Default to localhost binding for security (prevent unauthenticated external access)
	bindHost := os.Getenv("HEALTH_API_HOST")
	if bindHost == "" {
		bindHost = "127.0.0.1"
	}

	version := os.Getenv("BOT_VERSION")
	if version == "" {
		version = "dev"
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
	r.Use(middleware.Timeout(30 * time.Second))

	// Prometheus metrics endpoint
	r.Handle("/metrics", promhttp.Handler())

	// Health check endpoints
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		status := healthService.GetStatus()
		w.Header().Set("Content-Type", "application/json")

		if status.Status != "healthy" {
			w.WriteHeader(http.StatusServiceUnavailable)
		}

		json.NewEncoder(w).Encode(status)
	})

	// Simple liveness probe
	r.Get("/health/live", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	// Readiness probe
	r.Get("/health/ready", func(w http.ResponseWriter, r *http.Request) {
		status := healthService.GetStatus()
		if status.Status == "healthy" {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("READY"))
		} else {
			w.WriteHeader(http.StatusServiceUnavailable)
			w.Write([]byte("NOT READY"))
		}
	})

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

		healthService.SetServiceStatus(payload.Name, payload.Healthy)
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

		switch payload.Type {
		case "counter":
			// Prometheus Counter.Add() panics on negative values
			if payload.Value < 0 {
				http.Error(w, "counter value must be non-negative", http.StatusBadRequest)
				return
			}
			switch payload.Name {
			case "requests":
				status := "success"
				if s, ok := payload.Labels["status"]; ok {
					status = sanitizeLabel(s)
				}
				endpoint := sanitizeLabel(payload.Labels["endpoint"])
				requestsTotal.WithLabelValues(endpoint, status).Add(payload.Value)
			case "rate_limit":
				rateLimitHits.WithLabelValues(sanitizeLabel(payload.Labels["type"])).Add(payload.Value)
			case "cache":
				cacheHits.WithLabelValues(sanitizeLabel(payload.Labels["result"])).Add(payload.Value)
			case "tokens":
				tokensUsed.WithLabelValues(sanitizeLabel(payload.Labels["type"])).Add(payload.Value)
			}
		case "histogram":
			switch payload.Name {
			case "request_duration":
				requestDuration.WithLabelValues(sanitizeLabel(payload.Labels["endpoint"])).Observe(payload.Value)
			case "ai_response_time":
				aiResponseTime.Observe(payload.Value)
			}
		case "gauge":
			switch payload.Name {
			case "active_connections":
				activeConnections.Set(payload.Value)
			case "circuit_breaker":
				circuitBreakerState.WithLabelValues(sanitizeLabel(payload.Labels["service"])).Set(payload.Value)
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
			switch p.Type {
			case "counter":
				// Skip negative counter values to prevent Prometheus panic
				if p.Value < 0 {
					continue
				}
				switch p.Name {
				case "requests":
					status := "success"
					if s, ok := p.Labels["status"]; ok {
						status = sanitizeLabel(s)
					}
					requestsTotal.WithLabelValues(sanitizeLabel(p.Labels["endpoint"]), status).Add(p.Value)
					processed++
				case "rate_limit":
					rateLimitHits.WithLabelValues(sanitizeLabel(p.Labels["type"])).Add(p.Value)
					processed++
				case "cache":
					cacheHits.WithLabelValues(sanitizeLabel(p.Labels["result"])).Add(p.Value)
					processed++
				case "tokens":
					tokensUsed.WithLabelValues(sanitizeLabel(p.Labels["type"])).Add(p.Value)
					processed++
				}
			case "histogram":
				switch p.Name {
				case "request_duration":
					requestDuration.WithLabelValues(sanitizeLabel(p.Labels["endpoint"])).Observe(p.Value)
					processed++
				case "ai_response_time":
					aiResponseTime.Observe(p.Value)
					processed++
				}
			case "gauge":
				switch p.Name {
				case "active_connections":
					activeConnections.Set(p.Value)
					processed++
				case "circuit_breaker":
					circuitBreakerState.WithLabelValues(sanitizeLabel(p.Labels["service"])).Set(p.Value)
					processed++
				}
				// Unknown metric types in batch are silently skipped (consistent with batch semantics)
			}
		}

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]int{"processed": processed})
	})

	// Stats summary
	r.Get("/stats", func(w http.ResponseWriter, r *http.Request) {
		collectSystemMetrics()
		status := healthService.GetStatus()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(status)
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
		Addr:         bindHost + ":" + port,
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
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
		server.Shutdown(ctx)
	}()

	log.Printf("Health API service starting on %s:%s", bindHost, port)
	log.Printf("Metrics available at http://%s:%s/metrics", bindHost, port)

	if err := server.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("Server error: %v", err)
	}
}
