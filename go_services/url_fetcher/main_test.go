package main

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
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
	isPrivate, err := isPrivateURL(context.Background(), "http://127.0.0.1/foo")
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
	// httptest.NewServer binds to 127.0.0.1, which is correctly blocked by SSRF protection.
	// This test verifies SSRF blocks localhost test servers as expected.
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte("<html><head><title>Test</title></head><body><p>Hello World</p></body></html>"))
	}))
	defer ts.Close()

	f := NewFetcher()
	result := f.Fetch(context.Background(), ts.URL)

	// SSRF protection correctly blocks loopback addresses
	if result.Error == "" {
		t.Error("expected SSRF block for localhost, but fetch succeeded")
	}
	if !strings.Contains(result.Error, "SSRF") {
		t.Errorf("expected SSRF error, got: %s", result.Error)
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

// ---------------------------------------------------------------------------
// IPv6 / IPv4-mapped SSRF coverage (parity with Python utils/web/url_fetcher.py)
// ---------------------------------------------------------------------------

func TestIsPrivateIP_IPv6Blocked(t *testing.T) {
	blocked := []string{
		"::1",                    // IPv6 loopback
		"::",                     // IPv6 unspecified (parity gap fixed)
		"fe80::1",                // IPv6 link-local
		"fc00::1",                // IPv6 unique local
		"fd00:ec2::254",          // AWS IMDSv2 (within fc00::/7)
		"::ffff:127.0.0.1",       // IPv4-mapped loopback
		"::ffff:169.254.169.254", // IPv4-mapped link-local metadata
		"::ffff:10.0.0.1",        // IPv4-mapped private A
		"64:ff9b::7f00:1",        // NAT64 of 127.0.0.1
		"64:ff9b::a9fe:a9fe",     // NAT64 of 169.254.169.254 (metadata)
		"64:ff9b:1::a9fe:a9fe",   // NAT64 local-use (RFC 8215) of metadata — connect-time parity gap fixed
		"2002:7f00:1::",          // 6to4 of 127.0.0.1
		"2002:a9fe:a9fe::",       // 6to4 of 169.254.169.254 (metadata)
		"2001::1",                // Teredo (embeds an IPv4 endpoint) — parity with Python is_private
		"100::1",                 // Discard-only block (RFC 6666)
		"2001:db8::1",            // Documentation — parity with Python is_private
		"2001:10::1",             // ORCHID (within 2001::/23) — parity with Python
		"3fff::1",                // Documentation, RFC 9637 — parity with Python is_reserved
	}
	for _, ip := range blocked {
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

func TestIsPrivateIP_IPv6Public(t *testing.T) {
	public := []string{
		"2606:4700:4700::1111", // Cloudflare public IPv6
		"2001:4860:4860::8888", // Google public IPv6
		"::ffff:8.8.8.8",       // IPv4-mapped PUBLIC (must stay allowed)
	}
	for _, ip := range public {
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

// TestIsPrivateURL_Blocked asserts isPrivateURL blocks metadata hostnames and
// IP-literal hosts (incl. non-canonical metadata encodings) without resolving.
func TestIsPrivateURL_Blocked(t *testing.T) {
	blocked := []string{
		"http://metadata.google.internal/",
		"http://169.254.169.254/",
		"http://100.100.100.200/",
		"http://[::1]/",
		"http://[::]/",
		"http://[::ffff:169.254.169.254]/", // IPv4-mapped metadata (not in string denylist)
		"http://[64:ff9b::a9fe:a9fe]/",     // NAT64 metadata
	}
	for _, u := range blocked {
		isPrivate, _ := isPrivateURL(context.Background(), u)
		if !isPrivate {
			t.Errorf("isPrivateURL(%q) should block", u)
		}
	}
}

// ---------------------------------------------------------------------------
// CheckRedirect SSRF re-enforcement (scheme allowlist + dangerousHosts + IP)
// ---------------------------------------------------------------------------

func newRedirectReq(t *testing.T, rawURL string) *http.Request {
	t.Helper()
	u, err := url.Parse(rawURL)
	if err != nil {
		t.Fatalf("parse %q: %v", rawURL, err)
	}
	return &http.Request{URL: u}
}

func TestCheckRedirect_BlocksDisallowedScheme(t *testing.T) {
	check := NewFetcher().client.CheckRedirect
	for _, raw := range []string{"file:///etc/passwd", "gopher://x/", "ftp://h/", "dict://h:11/"} {
		if err := check(newRedirectReq(t, raw), nil); err == nil {
			t.Errorf("redirect to %q should be blocked (scheme allowlist)", raw)
		}
	}
	// http/https must still be allowed (host not dangerous).
	if err := check(newRedirectReq(t, "https://example.com/"), nil); err != nil {
		t.Errorf("redirect to https://example.com/ should be allowed, got: %v", err)
	}
}

func TestCheckRedirect_BlocksDangerousHost(t *testing.T) {
	check := NewFetcher().client.CheckRedirect
	for _, raw := range []string{
		"http://169.254.169.254/latest/meta-data/",
		"http://metadata.google.internal/",
		"http://[::ffff:169.254.169.254]/", // non-canonical metadata IP — caught by IP layer
		"http://[::1]/",                    // loopback literal
	} {
		if err := check(newRedirectReq(t, raw), nil); err == nil {
			t.Errorf("redirect to %q should be blocked", raw)
		}
	}
}

func TestCheckRedirect_TooManyHops(t *testing.T) {
	check := NewFetcher().client.CheckRedirect
	via := make([]*http.Request, 5)
	if err := check(newRedirectReq(t, "https://example.com/"), via); err == nil {
		t.Error("6th redirect hop should be blocked")
	}
}

// ---------------------------------------------------------------------------
// DNS-rebind dial-time guard
// ---------------------------------------------------------------------------

func TestSSRFSafeDialContext_BlocksPrivateLiteral(t *testing.T) {
	dial := ssrfSafeDialContext(&net.Dialer{})
	// 127.0.0.1 resolves to itself; the dial-time isPrivateIP guard must fire
	// before any real connection is attempted.
	conn, err := dial(context.Background(), "tcp", "127.0.0.1:80")
	if conn != nil {
		_ = conn.Close()
		t.Fatal("dial to 127.0.0.1 should be blocked, got a connection")
	}
	if err == nil || !strings.Contains(err.Error(), "SSRF blocked") {
		t.Errorf("expected SSRF block error, got: %v", err)
	}
}
