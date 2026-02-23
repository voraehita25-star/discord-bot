package main

import (
	"encoding/json"
	"fmt"
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
