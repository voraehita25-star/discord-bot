package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// HealthService unit tests
// ---------------------------------------------------------------------------

func TestNewHealthService(t *testing.T) {
	hs := NewHealthService("1.0.0")
	if hs == nil {
		t.Fatal("NewHealthService returned nil")
	}
	if hs.version != "1.0.0" {
		t.Errorf("expected version '1.0.0', got '%s'", hs.version)
	}
}

func TestGetStatusHealthy(t *testing.T) {
	hs := NewHealthService("test")
	hs.SetServiceStatus("bot", true)
	hs.SetServiceStatus("database", true)

	status := hs.GetStatus()
	if status.Status != "healthy" {
		t.Errorf("expected 'healthy', got '%s'", status.Status)
	}
	if status.Version != "test" {
		t.Errorf("expected version 'test', got '%s'", status.Version)
	}
}

func TestGetStatusDegraded(t *testing.T) {
	hs := NewHealthService("test")
	hs.SetServiceStatus("bot", true)
	hs.SetServiceStatus("database", false) // unhealthy → degraded

	status := hs.GetStatus()
	if status.Status != "degraded" {
		t.Errorf("expected 'degraded', got '%s'", status.Status)
	}
}

func TestSetServiceStatusCap(t *testing.T) {
	hs := NewHealthService("test")

	// Fill to maxServices
	for i := 0; i < maxServices; i++ {
		hs.SetServiceStatus(fmt.Sprintf("svc-%d", i), true)
	}

	// One more should be silently rejected
	hs.SetServiceStatus("overflow", true)

	hs.mu.RLock()
	count := len(hs.services)
	hs.mu.RUnlock()

	if count > maxServices {
		t.Errorf("expected at most %d services, got %d", maxServices, count)
	}
}

func TestSetServiceStatusUpdate(t *testing.T) {
	hs := NewHealthService("test")
	hs.SetServiceStatus("bot", true)
	hs.SetServiceStatus("bot", false) // update existing

	hs.mu.RLock()
	healthy := hs.services["bot"]
	hs.mu.RUnlock()

	if healthy {
		t.Error("expected bot to be unhealthy after update")
	}
}

func TestHealthStatusJSON(t *testing.T) {
	hs := NewHealthService("v1")
	hs.SetServiceStatus("bot", true)

	status := hs.GetStatus()
	data, err := json.Marshal(status)
	if err != nil {
		t.Fatalf("failed to marshal HealthStatus: %v", err)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if parsed["status"] != "healthy" {
		t.Errorf("expected status 'healthy' in JSON, got %v", parsed["status"])
	}
	if parsed["version"] != "v1" {
		t.Errorf("expected version 'v1' in JSON, got %v", parsed["version"])
	}
}

// ---------------------------------------------------------------------------
// sanitizeLabel / safeLabel
// ---------------------------------------------------------------------------

func TestSanitizeLabel(t *testing.T) {
	short := sanitizeLabel("ok")
	if short != "ok" {
		t.Errorf("expected 'ok', got '%s'", short)
	}

	long := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" // >64
	result := sanitizeLabel(long)
	if len(result) > maxLabelLength {
		t.Errorf("sanitizeLabel should truncate to %d, got %d", maxLabelLength, len(result))
	}
}

func TestSafeLabelAllowed(t *testing.T) {
	// "status" key with "success" value is in the allowlist
	result := safeLabel("status", "success")
	if result != "success" {
		t.Errorf("expected 'success', got '%s'", result)
	}
}

func TestSafeLabelDisallowed(t *testing.T) {
	// unknown key/value should return "other"
	result := safeLabel("unknown_key", "unknown_value")
	if result != "other" {
		t.Errorf("expected 'other', got '%s'", result)
	}
}

// ---------------------------------------------------------------------------
// requireBearerToken auth middleware (fail-closed)
// ---------------------------------------------------------------------------

func TestRequireBearerToken(t *testing.T) {
	const token = "s3cret-token"
	nextCalled := false
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nextCalled = true
		w.WriteHeader(http.StatusOK)
	})

	tests := []struct {
		name       string
		expected   string
		authHeader string
		wantStatus int
		wantNext   bool
	}{
		// Empty configured token => fail CLOSED with 503, never reach next.
		{"empty token fails closed", "", "Bearer anything", http.StatusServiceUnavailable, false},
		{"empty token no header", "", "", http.StatusServiceUnavailable, false},
		{"missing header", token, "", http.StatusUnauthorized, false},
		{"missing bearer prefix", token, token, http.StatusUnauthorized, false},
		{"wrong-length token", token, "Bearer short", http.StatusUnauthorized, false},
		{"wrong-value same-length", token, "Bearer s3cret-toleN", http.StatusUnauthorized, false},
		{"correct token", token, "Bearer " + token, http.StatusOK, true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			nextCalled = false
			mw := requireBearerToken(tc.expected)(next)
			req := httptest.NewRequest(http.MethodPost, "/metrics/push", nil)
			if tc.authHeader != "" {
				req.Header.Set("Authorization", tc.authHeader)
			}
			rec := httptest.NewRecorder()
			mw.ServeHTTP(rec, req)

			if rec.Code != tc.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tc.wantStatus)
			}
			if nextCalled != tc.wantNext {
				t.Errorf("next called = %v, want %v", nextCalled, tc.wantNext)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// handleMetricsPush input validation
// ---------------------------------------------------------------------------

func postJSON(t *testing.T, handler http.HandlerFunc, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(body))
	rec := httptest.NewRecorder()
	handler(rec, req)
	return rec
}

func TestHandleMetricsPush_Validation(t *testing.T) {
	hs := NewHealthService("test")
	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{"valid counter", `{"type":"counter","name":"requests","value":1,"labels":{"status":"success","endpoint":"ai"}}`, http.StatusOK},
		{"valid gauge circuit_breaker", `{"type":"gauge","name":"circuit_breaker","value":2,"labels":{"service":"gemini"}}`, http.StatusOK},
		{"invalid JSON", `{not json`, http.StatusBadRequest},
		{"unknown name", `{"type":"counter","name":"bogus","value":1}`, http.StatusBadRequest},
		{"unknown type", `{"type":"guage","name":"requests","value":1}`, http.StatusBadRequest},
		{"name/type mismatch", `{"type":"counter","name":"active_connections","value":1}`, http.StatusBadRequest},
		{"counter NaN", `{"type":"counter","name":"requests","value":"NaN"}`, http.StatusBadRequest},
		{"counter negative", `{"type":"counter","name":"requests","value":-5}`, http.StatusBadRequest},
		{"histogram negative", `{"type":"histogram","name":"ai_response_time","value":-1}`, http.StatusBadRequest},
		{"gauge Inf", `{"type":"gauge","name":"active_connections","value":"Inf"}`, http.StatusBadRequest},
		// go-health-3 regressions:
		{"circuit_breaker out of range high", `{"type":"gauge","name":"circuit_breaker","value":999,"labels":{"service":"gemini"}}`, http.StatusBadRequest},
		{"circuit_breaker negative", `{"type":"gauge","name":"circuit_breaker","value":-5,"labels":{"service":"gemini"}}`, http.StatusBadRequest},
		{"active_connections negative", `{"type":"gauge","name":"active_connections","value":-1}`, http.StatusBadRequest},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			rec := postJSON(t, hs.handleMetricsPush, tc.body)
			if rec.Code != tc.wantStatus {
				t.Errorf("status = %d, want %d (body=%s)", rec.Code, tc.wantStatus, rec.Body.String())
			}
		})
	}
}

func TestHandleServiceStatus_Validation(t *testing.T) {
	hs := NewHealthService("test")
	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{"valid", `{"name":"gemini","healthy":true}`, http.StatusOK},
		{"invalid JSON", `nope`, http.StatusBadRequest},
		{"empty name", `{"name":"","healthy":true}`, http.StatusBadRequest},
		{"name too long", `{"name":"` + strings.Repeat("a", 101) + `","healthy":true}`, http.StatusBadRequest},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			rec := postJSON(t, hs.handleServiceStatus, tc.body)
			if rec.Code != tc.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tc.wantStatus)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// handleMetricsBatch: processed/skipped accounting + unknown-type consistency
// ---------------------------------------------------------------------------

func TestHandleMetricsBatch_ProcessedSkipped(t *testing.T) {
	hs := NewHealthService("test")
	// 2 valid, then: unknown name, unknown type, name/type-mismatch (no inner
	// case), out-of-range circuit_breaker, negative counter => all skipped.
	body := `[
		{"type":"counter","name":"requests","value":1,"labels":{"status":"success","endpoint":"ai"}},
		{"type":"gauge","name":"circuit_breaker","value":1,"labels":{"service":"gemini"}},
		{"type":"counter","name":"bogus","value":1},
		{"type":"guage","name":"requests","value":1},
		{"type":"counter","name":"active_connections","value":1},
		{"type":"gauge","name":"circuit_breaker","value":999,"labels":{"service":"gemini"}},
		{"type":"counter","name":"requests","value":-1}
	]`
	rec := postJSON(t, hs.handleMetricsBatch, body)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body=%s)", rec.Code, rec.Body.String())
	}
	var resp map[string]int
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if resp["processed"] != 2 {
		t.Errorf("processed = %d, want 2", resp["processed"])
	}
	if resp["skipped"] != 5 {
		t.Errorf("skipped = %d, want 5", resp["skipped"])
	}
}

func TestHandleMetricsBatch_TooLarge(t *testing.T) {
	hs := NewHealthService("test")
	var sb strings.Builder
	sb.WriteByte('[')
	for i := 0; i < 1001; i++ {
		if i > 0 {
			sb.WriteByte(',')
		}
		sb.WriteString(`{"type":"counter","name":"requests","value":1}`)
	}
	sb.WriteByte(']')
	rec := postJSON(t, hs.handleMetricsBatch, sb.String())
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d, want 400 for >1000 batch", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// go-health-2: GetStatus reads the cached MemStats snapshot (no inline STW read)
// ---------------------------------------------------------------------------

func TestGetStatusUsesCachedMemStats(t *testing.T) {
	// Prime the cache the way main() does, then assert GetStatus surfaces it.
	collectSystemMetrics()
	hs := NewHealthService("test")
	status := hs.GetStatus()
	if _, ok := status.Metrics["memory_alloc_mb"]; !ok {
		t.Error("expected memory_alloc_mb in metrics")
	}
	// A live Go process always has a non-zero heap; the cached snapshot must
	// reflect that rather than the zero value.
	if alloc, _ := status.Metrics["memory_alloc_mb"].(float64); alloc <= 0 {
		t.Errorf("memory_alloc_mb should be > 0 after priming, got %v", status.Metrics["memory_alloc_mb"])
	}
}
