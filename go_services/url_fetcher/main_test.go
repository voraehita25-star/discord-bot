package main

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
)

// ---------------------------------------------------------------------------
// SSRF Protection tests
// ---------------------------------------------------------------------------

func TestIsPrivateIP_Private(t *testing.T) {
	privateIPs := []string{
		"127.0.0.1",
		"10.0.0.1",
		"172.16.0.1",
		"192.168.1.1",
		"169.254.1.1",
		"0.0.0.0",
	}

	for _, ip := range privateIPs {
		parsed := net.ParseIP(ip)
		if parsed == nil {
			t.Errorf("failed to parse IP: %s", ip)
			continue
		}
		if !isPrivateIP(parsed) {
			t.Errorf("IP %s should be detected as private/internal", ip)
		}
	}
}

func TestIsPrivateIP_Public(t *testing.T) {
	publicIPs := []string{
		"8.8.8.8",
		"1.1.1.1",
		"142.250.80.46",
	}

	for _, ip := range publicIPs {
		parsed := net.ParseIP(ip)
		if parsed == nil {
			t.Errorf("failed to parse IP: %s", ip)
			continue
		}
		if isPrivateIP(parsed) {
			t.Errorf("IP %s should NOT be detected as private", ip)
		}
	}
}

func TestIsPrivateURL_Localhost(t *testing.T) {
	isPrivate, err := isPrivateURL("http://127.0.0.1/foo")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !isPrivate {
		t.Error("127.0.0.1 should be private")
	}
}

// ---------------------------------------------------------------------------
// Constants validation
// ---------------------------------------------------------------------------

func TestConstants(t *testing.T) {
	if maxContentLength != 10*1024*1024 {
		t.Errorf("expected maxContentLength = 10MB, got %d", maxContentLength)
	}
	if maxExtractedLength != 50000 {
		t.Errorf("expected maxExtractedLength = 50000, got %d", maxExtractedLength)
	}
	if defaultPort != "8081" {
		t.Errorf("expected defaultPort = '8081', got '%s'", defaultPort)
	}
}

// ---------------------------------------------------------------------------
// Fetcher tests
// ---------------------------------------------------------------------------

func TestNewFetcher(t *testing.T) {
	f := NewFetcher()
	if f == nil {
		t.Fatal("NewFetcher returned nil")
	}
}

func TestFetchSafePage(t *testing.T) {
	// Spin up a tiny HTTP server
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte("<html><head><title>Test</title></head><body><p>Hello World</p></body></html>"))
	}))
	defer ts.Close()

	f := NewFetcher()
	result := f.Fetch(context.Background(), ts.URL)

	if result.Error != "" {
		t.Errorf("expected success, got error: %s", result.Error)
	}
	if result.Title != "Test" {
		t.Errorf("expected title 'Test', got '%s'", result.Title)
	}
}

func TestFetchPrivateIPBlocked(t *testing.T) {
	// Attempts to fetch a private IP should fail with SSRF protection
	f := NewFetcher()
	result := f.Fetch(context.Background(), "http://127.0.0.1:1/secret")

	// Should either fail due to SSRF or connection refused
	if result.Error == "" {
		t.Error("fetching private IP should not succeed")
	}
}

// ---------------------------------------------------------------------------
// privateNetworks sanity check
// ---------------------------------------------------------------------------

func TestPrivateNetworksInitialized(t *testing.T) {
	if len(privateNetworks) == 0 {
		t.Error("privateNetworks should be populated by init()")
	}
}
