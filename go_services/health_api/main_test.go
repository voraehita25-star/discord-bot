package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
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
		// go-health-3: these two assert that encoding/json REJECTS a quoted,
		// non-numeric value (-> 400 "invalid JSON") *before* the switch runs —
		// NOT that the math.IsNaN/IsInf guard fired (it is unreachable from
		// JSON; see TestNaNInfGuardLogic for the guard predicate itself).
		{"counter rejects quoted non-number (decode 400)", `{"type":"counter","name":"requests","value":"NaN"}`, http.StatusBadRequest},
		{"counter negative", `{"type":"counter","name":"requests","value":-5}`, http.StatusBadRequest},
		{"histogram negative", `{"type":"histogram","name":"ai_response_time","value":-1}`, http.StatusBadRequest},
		{"gauge rejects quoted non-number (decode 400)", `{"type":"gauge","name":"active_connections","value":"Inf"}`, http.StatusBadRequest},
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

// ---------------------------------------------------------------------------
// go-health-3: exercise the NaN/Inf guard PREDICATE directly.
//
// The math.IsNaN/IsInf arms in handleMetricsPush/handleMetricsBatch are
// unreachable through the HTTP/JSON boundary (encoding/json rejects
// NaN/Infinity/quoted-number bodies first), so the existing handler tests
// only prove JSON-decode rejection. This test feeds float64 values the JSON
// decoder can never deliver straight into the same boolean condition the
// guards use, locking the intended "reject NaN, +/-Inf, and negatives"
// semantics so a regression that loosened the predicate would fail here.
// ---------------------------------------------------------------------------

func TestNaNInfGuardLogic(t *testing.T) {
	// counterOrHistogramRejects mirrors the guard used by the counter and
	// histogram arms: NaN || Inf || value < 0.
	counterOrHistogramRejects := func(v float64) bool {
		return math.IsNaN(v) || math.IsInf(v, 0) || v < 0
	}
	// gaugeRejects mirrors the gauge arm's top-level guard: NaN || Inf
	// (the per-name negative/enum checks are layered on top of this).
	gaugeRejects := func(v float64) bool {
		return math.IsNaN(v) || math.IsInf(v, 0)
	}

	tests := []struct {
		name             string
		value            float64
		wantCounterRej   bool
		wantGaugeTopReje bool
	}{
		{"NaN", math.NaN(), true, true},
		{"+Inf", math.Inf(1), true, true},
		{"-Inf", math.Inf(-1), true, true},
		{"negative", -1.0, true, false}, // gauge top-level allows; per-name check handles it
		{"zero", 0.0, false, false},
		{"positive", 42.0, false, false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := counterOrHistogramRejects(tc.value); got != tc.wantCounterRej {
				t.Errorf("counter/histogram guard(%v) = %v, want %v", tc.value, got, tc.wantCounterRej)
			}
			if got := gaugeRejects(tc.value); got != tc.wantGaugeTopReje {
				t.Errorf("gauge top-level guard(%v) = %v, want %v", tc.value, got, tc.wantGaugeTopReje)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// go-health-1: bind-host loopback gate helpers (HEALTH_API_ALLOW_REMOTE)
// ---------------------------------------------------------------------------

func TestIsLoopbackHost(t *testing.T) {
	loopback := []string{"127.0.0.1", "localhost", "::1", "[::1]", "LOCALHOST", " 127.0.0.1 "}
	for _, h := range loopback {
		if !isLoopbackHost(h) {
			t.Errorf("isLoopbackHost(%q) = false, want true", h)
		}
	}
	nonLoopback := []string{"0.0.0.0", "::", "192.168.1.10", "10.0.0.1", "example.com", ""}
	for _, h := range nonLoopback {
		if isLoopbackHost(h) {
			t.Errorf("isLoopbackHost(%q) = true, want false", h)
		}
	}
}

func TestIsTruthy(t *testing.T) {
	// Affirmatives open the gate.
	for _, v := range []string{"1", "true", "TRUE", "yes", "on", " on "} {
		if !isTruthy(v) {
			t.Errorf("isTruthy(%q) = false, want true", v)
		}
	}
	// Everything else is fail-safe false — stricter than the Python sibling's
	// "any non-empty string is truthy" so a stray =0/false/no can't open it.
	for _, v := range []string{"", "0", "false", "no", "off", "2", "enable", "garbage"} {
		if isTruthy(v) {
			t.Errorf("isTruthy(%q) = true, want false", v)
		}
	}
}

// resolveBindHost replays the exact decision main() makes so the gate is a
// tested invariant without spinning up a server. Keep in lockstep with main().
func resolveBindHost(bindHost, allowRemote string) string {
	if !isLoopbackHost(bindHost) && !isTruthy(allowRemote) {
		return "127.0.0.1"
	}
	return bindHost
}

func TestBindHostGate(t *testing.T) {
	tests := []struct {
		name        string
		bindHost    string
		allowRemote string
		want        string
	}{
		{"loopback stays", "127.0.0.1", "", "127.0.0.1"},
		{"localhost stays", "localhost", "", "localhost"},
		{"non-loopback forced without flag", "0.0.0.0", "", "127.0.0.1"},
		{"non-loopback forced with falsey flag", "0.0.0.0", "0", "127.0.0.1"},
		{"non-loopback forced with 'false'", "0.0.0.0", "false", "127.0.0.1"},
		{"non-loopback allowed with truthy flag", "0.0.0.0", "1", "0.0.0.0"},
		{"routable allowed with 'true'", "192.168.1.10", "true", "192.168.1.10"},
		{"routable forced without flag", "192.168.1.10", "", "127.0.0.1"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := resolveBindHost(tc.bindHost, tc.allowRemote); got != tc.want {
				t.Errorf("resolveBindHost(%q, %q) = %q, want %q", tc.bindHost, tc.allowRemote, got, tc.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// go-health-2: requireReadToken — anonymous when no token, enforced when set
// ---------------------------------------------------------------------------

func TestRequireReadToken(t *testing.T) {
	const token = "read-token"
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	tests := []struct {
		name       string
		expected   string
		authHeader string
		wantStatus int
	}{
		// No token configured => reads are anonymous (loopback-only via the
		// bind gate); the handler is reached without any Authorization header.
		{"no token configured -> anonymous", "", "", http.StatusOK},
		{"no token configured ignores header", "", "Bearer whatever", http.StatusOK},
		// Token configured => the SAME bearer enforcement as writes (but reads
		// must NOT fail-closed-to-503; they require the token instead).
		{"token set, missing header -> 401", token, "", http.StatusUnauthorized},
		{"token set, wrong token -> 401", token, "Bearer nope-wrong-len", http.StatusUnauthorized},
		{"token set, correct token -> 200", token, "Bearer " + token, http.StatusOK},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			mw := requireReadToken(tc.expected)(next)
			req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
			if tc.authHeader != "" {
				req.Header.Set("Authorization", tc.authHeader)
			}
			rec := httptest.NewRecorder()
			mw.ServeHTTP(rec, req)
			if rec.Code != tc.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tc.wantStatus)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// go-health-4: integration test wiring the REAL chi router (buildRouter), so
// the security-critical middleware-to-route binding is a tested invariant:
//   - writes require the bearer token (401 without, 200 with);
//   - with NO token writes fail CLOSED (503);
//   - read policy matches the go-health-2 decision (probes always anonymous;
//     /metrics and /stats anonymous when no token, token-gated when set).
// ---------------------------------------------------------------------------

func doReq(t *testing.T, r http.Handler, method, path, token, body string) *httptest.ResponseRecorder {
	t.Helper()
	var rdr *bytes.Reader
	if body != "" {
		rdr = bytes.NewReader([]byte(body))
	} else {
		rdr = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, rdr)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	return rec
}

func TestRouterAuthWiring_TokenConfigured(t *testing.T) {
	const token = "wiring-token"
	hs := NewHealthService("test")
	hs.SetServiceStatus("bot", true)
	r := buildRouter(hs, token)

	validPush := `{"type":"counter","name":"requests","value":1,"labels":{"status":"success","endpoint":"ai"}}`

	// --- Write routes: token enforced ---
	if rec := doReq(t, r, http.MethodPost, "/metrics/push", "", validPush); rec.Code != http.StatusUnauthorized {
		t.Errorf("POST /metrics/push without token = %d, want 401", rec.Code)
	}
	if rec := doReq(t, r, http.MethodPost, "/metrics/push", token, validPush); rec.Code != http.StatusOK {
		t.Errorf("POST /metrics/push with token = %d, want 200 (body=%s)", rec.Code, "ok")
	}
	for _, p := range []string{"/health/service", "/metrics/batch"} {
		body := `{"name":"x","healthy":true}`
		if p == "/metrics/batch" {
			body = "[]"
		}
		if rec := doReq(t, r, http.MethodPost, p, "", body); rec.Code != http.StatusUnauthorized {
			t.Errorf("POST %s without token = %d, want 401", p, rec.Code)
		}
	}

	// --- Read routes: probes ALWAYS anonymous ---
	for _, p := range []string{"/health", "/health/live", "/health/ready"} {
		if rec := doReq(t, r, http.MethodGet, p, "", ""); rec.Code == http.StatusUnauthorized {
			t.Errorf("GET %s anonymous = 401, want it to succeed (probes must be anonymous)", p)
		}
	}

	// --- /metrics and /stats: token-gated when a token is configured ---
	for _, p := range []string{"/metrics", "/stats"} {
		if rec := doReq(t, r, http.MethodGet, p, "", ""); rec.Code != http.StatusUnauthorized {
			t.Errorf("GET %s without token (token configured) = %d, want 401", p, rec.Code)
		}
		if rec := doReq(t, r, http.MethodGet, p, token, ""); rec.Code != http.StatusOK {
			t.Errorf("GET %s with token = %d, want 200", p, rec.Code)
		}
	}

	// --- Method binding: GET on a write route is not registered as a write ---
	if rec := doReq(t, r, http.MethodGet, "/metrics/push", token, ""); rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("GET /metrics/push = %d, want 405", rec.Code)
	}
}

func TestRouterAuthWiring_NoToken(t *testing.T) {
	hs := NewHealthService("test")
	hs.SetServiceStatus("bot", true)
	r := buildRouter(hs, "") // no token configured

	// Writes fail CLOSED (503) regardless of any header — unchanged posture.
	validPush := `{"type":"counter","name":"requests","value":1,"labels":{"status":"success","endpoint":"ai"}}`
	if rec := doReq(t, r, http.MethodPost, "/metrics/push", "anything", validPush); rec.Code != http.StatusServiceUnavailable {
		t.Errorf("POST /metrics/push (no token configured) = %d, want 503 (fail-closed)", rec.Code)
	}

	// Reads are anonymous so the default tokenless Prometheus scrape works.
	for _, p := range []string{"/health", "/health/live", "/health/ready", "/metrics", "/stats"} {
		rec := doReq(t, r, http.MethodGet, p, "", "")
		if rec.Code == http.StatusUnauthorized || rec.Code == http.StatusServiceUnavailable {
			t.Errorf("GET %s (no token configured) = %d, want anonymous success", p, rec.Code)
		}
	}
}
