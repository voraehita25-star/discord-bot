package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode/utf8"

	"github.com/PuerkitoBio/goquery"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"golang.org/x/net/html/charset"
	"golang.org/x/time/rate"
)

const (
	defaultPort        = "8081"
	maxContentLength   = 10 * 1024 * 1024 // 10MB
	maxExtractedLength = 50000            // 50KB of text
	requestTimeout     = 30 * time.Second
	workerCount        = 10
)

// Typed context key so we don't collide with other libraries' string keys
// when storing the propagated trace ID in request context.
type traceIDContextKey struct{}

// privateNetworks is a list of private/internal IP ranges for SSRF protection.
// Initialized once to avoid repeated parsing.
var privateNetworks []*net.IPNet

// dangerousHosts is the denylist of known dangerous hostnames (cloud metadata
// endpoints). Shared between isPrivateURL (initial URL) and the client's
// CheckRedirect (every redirect hop) so the blocklist is enforced on all hops.
var dangerousHosts = []string{
	"metadata.google.internal",
	"metadata.internal",
	"169.254.169.254",           // AWS/GCP instance metadata
	"metadata.google.internal.", // trailing dot variant
	"instance-data",             // AWS alternative
	"100.100.100.200",           // Alibaba Cloud metadata
	"fd00:ec2::254",             // AWS IMDSv2 IPv6
}

func init() {
	ranges := []string{
		"127.0.0.0/8",            // Loopback
		"10.0.0.0/8",             // Private Class A
		"172.16.0.0/12",          // Private Class B
		"192.168.0.0/16",         // Private Class C
		"169.254.0.0/16",         // Link-local
		"0.0.0.0/8",              // Current network
		"100.64.0.0/10",          // Shared address space
		"255.255.255.255/32",     // Broadcast
		"224.0.0.0/4",            // Multicast (parity with Python blocklist)
		"240.0.0.0/4",            // Reserved/future (parity with Python blocklist)
		"::/128",                 // IPv6 unspecified (parity with Python ::/128 + is_unspecified)
		"::1/128",                // IPv6 loopback
		"fc00::/7",               // IPv6 unique local
		"fe80::/10",              // IPv6 link-local
		"64:ff9b::/96",           // NAT64 well-known prefix (embeds IPv4; e.g. 127.0.0.1/metadata)
		"64:ff9b:1::/48",         // NAT64 local-use prefix (RFC 8215; also embeds IPv4 — parity with Python is_reserved)
		"2002::/16",              // 6to4 (embeds IPv4; parity with Python is_private)
		"100::/64",               // Discard-only address block (RFC 6666; parity with Python is_private)
		"2001::/23",              // IETF protocol assignments incl. Teredo 2001::/32 (embeds IPv4 endpoint). Deliberately over-blocks the still-unassigned/protocol portion of 2001::/23 (fail-closed); narrowing this would loosen the SSRF blocklist.
		"2001:db8::/32",          // Documentation (parity with Python is_private)
		"3fff::/20",              // Documentation, RFC 9637 (parity with Python is_reserved)
		"5f00::/16",              // Segment Routing SRv6 reserved (parity with Python is_reserved)
		"::ffff:127.0.0.0/104",   // IPv4-mapped loopback
		"::ffff:10.0.0.0/104",    // IPv4-mapped private A
		"::ffff:172.16.0.0/108",  // IPv4-mapped private B
		"::ffff:192.168.0.0/112", // IPv4-mapped private C
		"::ffff:169.254.0.0/112", // IPv4-mapped link-local
		"::ffff:0.0.0.0/104",     // IPv4-mapped current network
	}
	for _, cidr := range ranges {
		_, network, err := net.ParseCIDR(cidr)
		if err != nil {
			// The ranges list is hardcoded; a parse error means a typo in this
			// source, which silently shrinks the SSRF blocklist. Fail fast at
			// startup (deploy-blocking) instead of swallowing it.
			panic(fmt.Sprintf("invalid hardcoded CIDR %q in privateNetworks: %v", cidr, err))
		}
		privateNetworks = append(privateNetworks, network)
	}
}

// isPrivateIP checks if an IP address is in a private/internal range (SSRF protection)
func isPrivateIP(ip net.IP) bool {
	// Short-circuit on the unspecified address (0.0.0.0 / ::). Belt-and-
	// suspenders alongside the 0.0.0.0/8 and ::/128 CIDRs above — mirrors the
	// Python `ip.is_unspecified` guard so both implementations stay at parity.
	if ip.IsUnspecified() {
		return true
	}
	for _, network := range privateNetworks {
		if network.Contains(ip) {
			return true
		}
	}
	// Stricter IPv6 fallback (defense-in-depth beyond the explicit CIDR list):
	// blocks any non-global-unicast IPv6 (multicast, link-local-unicast, the
	// unspecified address, etc.) that slipped past the CIDRs above. Real public
	// IPv6 (Cloudflare/Google etc.) and IPv4-mapped public addresses ARE global
	// unicast, so this does not over-block legitimate targets. IPv4 is left to
	// the CIDR list above (To4() != nil) to avoid touching its existing parity.
	// Note: still-unallocated upper space (e.g. 4000::/3) is IsGlobalUnicast()==true
	// in Go and is NOT blocked here — currently IANA-unallocated/unroutable, a known
	// residual parity gap vs Python is_reserved; accepted because unroutable.
	if ip.To4() == nil && !ip.IsGlobalUnicast() {
		return true
	}
	return false
}

// isPrivateURL checks if a URL resolves to a private/internal IP (SSRF protection).
// Takes ctx so the pre-check DNS lookup honors the request's deadline/cancellation
// (req.Timeout) — same as the dial-time ssrfSafeDialContext guard. A context-less
// net.LookupIP here would block the worker for the full OS resolver timeout against
// a tarpit/hanging DNS server, ignoring the request context.
func isPrivateURL(ctx context.Context, rawURL string) (bool, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return true, fmt.Errorf("invalid URL: %v", err)
	}
	hostname := parsed.Hostname()
	if hostname == "" {
		return true, fmt.Errorf("empty hostname")
	}

	// Block known dangerous hostnames (cloud metadata endpoints)
	for _, h := range dangerousHosts {
		if strings.EqualFold(hostname, h) {
			return true, nil
		}
	}

	// If the host is an IP literal, check it directly before resolving.
	// Non-canonical encodings of metadata IPs (e.g. ::ffff:169.254.169.254)
	// don't match the string denylist above; running them through isPrivateIP
	// keeps the string layer no weaker than the dial-time IP guard and mirrors
	// Python's _ip_is_blocked, which unwraps such forms.
	if ip := net.ParseIP(hostname); ip != nil && isPrivateIP(ip) {
		return true, nil
	}

	// Resolve hostname to IP and check. Use a context-aware resolver so this
	// pre-check respects req.Timeout/cancellation, mirroring ssrfSafeDialContext.
	ipAddrs, err := (&net.Resolver{}).LookupIPAddr(ctx, hostname)
	if err != nil {
		// Fail CLOSED on DNS failure (block), matching the Python guard in
		// utils/web/url_fetcher.py. Relying only on the dial-time check is
		// fragile (pooled connections can skip the dialer — see
		// DisableKeepAlives on the transport), and an unresolvable host
		// can't be fetched anyway, so blocking here loses nothing.
		return true, fmt.Errorf("DNS resolution failed (blocked): %v", err)
	}
	for _, ipAddr := range ipAddrs {
		if isPrivateIP(ipAddr.IP) {
			return true, nil
		}
	}
	return false, nil
}

// FetchRequest represents a URL fetch request
type FetchRequest struct {
	URLs    []string `json:"urls"`
	Timeout int      `json:"timeout,omitempty"` // seconds
}

// FetchResult represents the result of fetching a URL
type FetchResult struct {
	URL         string `json:"url"`
	Title       string `json:"title,omitempty"`
	Content     string `json:"content,omitempty"`
	Description string `json:"description,omitempty"`
	Error       string `json:"error,omitempty"`
	StatusCode  int    `json:"status_code,omitempty"`
	ContentType string `json:"content_type,omitempty"`
	FetchTimeMs int64  `json:"fetch_time_ms"`
}

// FetchResponse is the response for batch fetch
type FetchResponse struct {
	Results      []FetchResult `json:"results"`
	TotalTimeMs  int64         `json:"total_time_ms"`
	SuccessCount int           `json:"success_count"`
	ErrorCount   int           `json:"error_count"`
}

// Fetcher handles URL fetching with rate limiting
type Fetcher struct {
	client  *http.Client
	limiter *rate.Limiter
}

// ssrfSafeDialContext returns a DialContext function that checks resolved IPs
// against private ranges at connect time, preventing DNS rebinding attacks.
func ssrfSafeDialContext(dialer *net.Dialer) func(ctx context.Context, network, addr string) (net.Conn, error) {
	resolver := &net.Resolver{}
	return func(ctx context.Context, network, addr string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(addr)
		if err != nil {
			return nil, fmt.Errorf("SSRF blocked: invalid address %q: %v", addr, err)
		}

		// Use context-aware DNS resolution to respect timeouts
		ips, err := resolver.LookupIPAddr(ctx, host)
		if err != nil {
			return nil, fmt.Errorf("SSRF blocked: DNS resolution failed for %q: %v", host, err)
		}

		if len(ips) == 0 {
			return nil, fmt.Errorf("SSRF blocked: DNS returned no IPs for %q", host)
		}

		for _, ip := range ips {
			if isPrivateIP(ip.IP) {
				return nil, fmt.Errorf("SSRF blocked: %q resolves to private IP %s", host, ip.IP)
			}
		}

		// Dial the IPs we just validated instead of re-resolving the hostname.
		// Passing the original host to DialContext triggers a SECOND DNS
		// lookup inside the dialer, which could return a private IP that
		// bypassed the check above (classic DNS-rebinding). http.Transport
		// derives the TLS ServerName (SNI) and Host header from the request
		// URL, not from the dial address, so HTTPS still works when we connect
		// by IP literal. Try each validated IP in order to keep multi-homed
		// failover.
		var lastErr error
		for _, ip := range ips {
			conn, derr := dialer.DialContext(ctx, network, net.JoinHostPort(ip.IP.String(), port))
			if derr == nil {
				return conn, nil
			}
			lastErr = derr
		}
		if lastErr == nil {
			lastErr = fmt.Errorf("SSRF blocked: no dialable IP for %q", host)
		}
		return nil, lastErr
	}
}

// NewFetcher creates a new Fetcher with SSRF-safe transport
func NewFetcher() *Fetcher {
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	transport := &http.Transport{
		DialContext: ssrfSafeDialContext(dialer),
		// Disable HTTP keep-alive so EVERY request re-dials through
		// ssrfSafeDialContext. Idle/pooled connections are keyed by
		// host:port, not the validated IP, so reusing one would skip the
		// dial-time SSRF re-validation (a DNS-rebind hole). Cost is a new
		// handshake per fetch — acceptable for a bot's occasional fetches.
		DisableKeepAlives:     true,
		MaxIdleConns:          200,
		MaxIdleConnsPerHost:   20,
		MaxConnsPerHost:       50,
		IdleConnTimeout:       120 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		WriteBufferSize:       64 * 1024, // 64KB
		ReadBufferSize:        64 * 1024, // 64KB
	}

	return &Fetcher{
		client: &http.Client{
			Timeout:   requestTimeout,
			Transport: transport,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				if len(via) >= 5 {
					return fmt.Errorf("too many redirects")
				}
				// Re-enforce the http/https scheme allowlist on every redirect
				// hop, matching the Python guard (_is_private_url re-checks the
				// scheme on each hop). Go's transport already rejects non-http(s)
				// schemes before dialing, but this makes the invariant explicit
				// instead of relying on that implicit stdlib behavior.
				if s := strings.ToLower(req.URL.Scheme); s != "http" && s != "https" {
					return fmt.Errorf("SSRF blocked: redirect to disallowed scheme %q", req.URL.Scheme)
				}
				// Redirect target IP is validated by ssrfSafeDialContext, but
				// the dangerousHosts metadata denylist (isPrivateURL) is only
				// applied to the initial URL — re-enforce it on every hop so a
				// redirect can't reach a metadata hostname.
				host := req.URL.Hostname()
				for _, h := range dangerousHosts {
					if strings.EqualFold(host, h) {
						return fmt.Errorf("SSRF blocked: redirect to dangerous host %q", host)
					}
				}
				// Defense-in-depth: if the host is an IP literal (incl. non-
				// canonical encodings of metadata IPs like ::ffff:169.254.169.254),
				// run it through isPrivateIP so the string denylist above is no
				// weaker than the dial-time IP guard. Mirrors Python's
				// _ip_is_blocked, which unwraps such forms.
				if ip := net.ParseIP(host); ip != nil && isPrivateIP(ip) {
					return fmt.Errorf("SSRF blocked: redirect to private IP %q", host)
				}
				return nil
			},
		},
		limiter: rate.NewLimiter(rate.Limit(50), 100), // 50 requests/sec, burst 100 (R7 9800X3D)
	}
}

// Fetch retrieves content from a URL
func (f *Fetcher) Fetch(ctx context.Context, rawURL string) FetchResult {
	start := time.Now()
	result := FetchResult{URL: rawURL}

	// SSRF Protection: Block private/internal IPs. Pass ctx so the pre-check
	// DNS lookup honors the request deadline/cancellation.
	if isPrivate, err := isPrivateURL(ctx, rawURL); isPrivate {
		errMsg := "SSRF blocked: URL resolves to private/internal address"
		if err != nil {
			errMsg = fmt.Sprintf("SSRF blocked: %v", err)
		}
		result.Error = errMsg
		result.FetchTimeMs = time.Since(start).Milliseconds()
		log.Printf("⚠️ SSRF blocked: %s", rawURL)
		return result
	}

	// Wait for rate limiter. Wait returns the CONTEXT error on
	// cancellation/deadline, not a rate-limit condition — labeling every
	// failure "rate limited" hid real timeouts/cancellations. Surface the
	// actual cause.
	if err := f.limiter.Wait(ctx); err != nil {
		result.Error = fmt.Sprintf("aborted before fetch (timeout/cancelled): %v", err)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, "GET", rawURL, nil)
	if err != nil {
		result.Error = fmt.Sprintf("invalid URL: %v", err)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Set headers
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; DiscordBot/1.0)")
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	req.Header.Set("Accept-Language", "en-US,en;q=0.5")

	// Execute request
	resp, err := f.client.Do(req)
	if err != nil {
		result.Error = fmt.Sprintf("fetch error: %v", err)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}
	defer func() { _ = resp.Body.Close() }()

	result.StatusCode = resp.StatusCode
	result.ContentType = resp.Header.Get("Content-Type")

	if resp.StatusCode != http.StatusOK {
		// Drain body to allow TCP connection reuse
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		result.Error = fmt.Sprintf("HTTP %d", resp.StatusCode)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Limit body size
	limitedReader := io.LimitReader(resp.Body, maxContentLength)

	// Read raw body first to avoid consuming bytes on charset detection failure
	rawBody, err := io.ReadAll(limitedReader)
	if err != nil {
		result.Error = fmt.Sprintf("read error: %v", err)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Handle charset conversion
	body := rawBody
	utf8Reader, err := charset.NewReader(bytes.NewReader(rawBody), result.ContentType)
	if err == nil {
		// Cap the post-conversion size as well: transcoding from a multi-byte
		// charset (e.g. UTF-16/GBK) to UTF-8 can expand beyond the input cap,
		// so limiting only rawBody above is not enough to bound memory.
		if converted, convErr := io.ReadAll(io.LimitReader(utf8Reader, maxContentLength)); convErr == nil {
			body = converted
		} else {
			// Transcoding read failed: body silently stays the original
			// source-charset bytes (mojibake risk downstream). charset readers
			// rarely error after construction, so this is a best-effort degraded
			// fallback — log it so the garbled path is at least observable.
			log.Printf("⚠️ charset transcode failed for %s (content-type %q), using raw bytes: %v",
				rawURL, result.ContentType, convErr)
		}
	}

	// Extract content. Title/description are capped too — a hostile page can
	// carry a multi-megabyte <title> or meta description (body cap is 10MB),
	// and uncapped fields would flow into the bot's AI prompt.
	// Route on the EXACT primary MIME type (the part before any ";" parameters),
	// not a substring match. strings.Contains let a smuggled type like
	// "application/x-text/html-evil" route as HTML; comparing the trimmed,
	// lowercased primary type closes that and matches the Python implementation.
	primary := strings.ToLower(strings.TrimSpace(strings.SplitN(result.ContentType, ";", 2)[0]))
	switch primary {
	case "text/html":
		title, description, content := extractHTMLContent(body)
		result.Title = truncateString(title, 500)
		result.Description = truncateString(description, 2000)
		result.Content = truncateString(content, maxExtractedLength)
	case "text/plain":
		result.Content = truncateString(string(body), maxExtractedLength)
	default:
		result.Content = "[Binary content]"
	}

	result.FetchTimeMs = time.Since(start).Milliseconds()
	return result
}

// FetchBatch fetches multiple URLs concurrently
func (f *Fetcher) FetchBatch(ctx context.Context, urls []string) FetchResponse {
	start := time.Now()
	response := FetchResponse{
		Results: make([]FetchResult, len(urls)),
	}

	var wg sync.WaitGroup
	semaphore := make(chan struct{}, workerCount)

	for i, url := range urls {
		wg.Add(1)
		go func(idx int, u string) {
			defer wg.Done()

			// Recover from any panic on the fetch path (goquery DOM walk /
			// charset decode runs on attacker-controlled response bodies).
			// These worker goroutines run OUTSIDE middleware.Recoverer's
			// coverage — that only guards the handler goroutine — so an
			// unrecovered panic here would crash the whole process (a DoS
			// vector via a crafted URL in a batch). Turn it into a per-URL error.
			defer func() {
				if rec := recover(); rec != nil {
					response.Results[idx] = FetchResult{
						URL:         u,
						Error:       fmt.Sprintf("panic during fetch: %v", rec),
						FetchTimeMs: time.Since(start).Milliseconds(),
					}
				}
			}()

			// Check context before acquiring semaphore
			select {
			case <-ctx.Done():
				response.Results[idx] = FetchResult{
					URL:         u,
					Error:       "context cancelled",
					FetchTimeMs: time.Since(start).Milliseconds(),
				}
				return
			case semaphore <- struct{}{}:
				defer func() { <-semaphore }()
			}

			response.Results[idx] = f.Fetch(ctx, u)
		}(i, url)
	}

	// Wait for all goroutines to finish before reading Results.
	// We MUST wait unconditionally (even if ctx is cancelled) to avoid a
	// data race on response.Results, which is written by the goroutines.
	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()
	<-done

	// Count results (safe: all writers have returned).
	for _, r := range response.Results {
		if r.Error == "" {
			response.SuccessCount++
		} else {
			response.ErrorCount++
		}
	}

	response.TotalTimeMs = time.Since(start).Milliseconds()
	return response
}

// extractHTMLContent extracts meaningful content from HTML
func extractHTMLContent(body []byte) (title, description, content string) {
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(body))
	if err != nil {
		return "", "", string(body)
	}

	// Extract title
	title = strings.TrimSpace(doc.Find("title").First().Text())

	// Extract meta description
	description, _ = doc.Find(`meta[name="description"]`).Attr("content")
	if description == "" {
		description, _ = doc.Find(`meta[property="og:description"]`).Attr("content")
	}

	// Remove unwanted elements
	doc.Find("script, style, nav, footer, header, aside, iframe, noscript").Remove()

	// Extract main content
	var contentBuilder strings.Builder

	// Try specific content selectors
	selectors := []string{"article", "main", ".content", "#content", ".post-content", ".entry-content"}
	var mainContent *goquery.Selection

	for _, sel := range selectors {
		s := doc.Find(sel).First()
		if s.Length() > 0 {
			mainContent = s
			break
		}
	}

	if mainContent == nil {
		mainContent = doc.Find("body")
	}

	// Extract text with paragraph breaks
	mainContent.Find("p, h1, h2, h3, h4, h5, h6, li").Each(func(i int, s *goquery.Selection) {
		text := strings.TrimSpace(s.Text())
		if len(text) > 0 {
			contentBuilder.WriteString(text)
			contentBuilder.WriteString("\n\n")
		}
	})

	content = strings.TrimSpace(contentBuilder.String())

	// Fallback to all text if content is too short
	if len(content) < 100 {
		content = strings.TrimSpace(mainContent.Text())
	}

	// Clean up whitespace
	content = cleanWhitespace(content)

	return title, description, content
}

// cleanWhitespace normalizes whitespace in text
func cleanWhitespace(s string) string {
	var result strings.Builder
	prevSpace := false

	for _, r := range s {
		switch r {
		case ' ', '\t':
			if !prevSpace {
				result.WriteRune(' ')
				prevSpace = true
			}
		case '\n':
			if !prevSpace {
				result.WriteRune('\n')
				prevSpace = true
			}
		default:
			result.WriteRune(r)
			prevSpace = false
		}
	}

	return strings.TrimSpace(result.String())
}

// truncateString truncates a string to max length
func truncateString(s string, maxLen int) string {
	if utf8.RuneCountInString(s) <= maxLen {
		return s
	}

	runes := []rune(s)
	return string(runes[:maxLen]) + "..."
}

func main() {
	port := os.Getenv("URL_FETCHER_PORT")
	if port == "" {
		port = defaultPort
	}

	fetcher := NewFetcher()

	r := chi.NewRouter()

	// Middleware
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	// 125s: must exceed the /fetch/batch handler's documented 120s cap — a
	// child context can never outlive its parent, so a 60s value here
	// silently truncated every batch timeout in (60,120] and made the
	// handler's cap dead logic.
	r.Use(middleware.Timeout(125 * time.Second))
	// Trace ID propagation: pass through X-Trace-ID from Python caller.
	// Use a typed context key (Go idiom) so we don't collide with other
	// libraries' string keys in the same context.
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			traceID := r.Header.Get("X-Trace-ID")
			if traceID != "" {
				w.Header().Set("X-Trace-ID", traceID)
				ctx := context.WithValue(r.Context(), traceIDContextKey{}, traceID)
				r = r.WithContext(ctx)
			}
			next.ServeHTTP(w, r)
		})
	})
	// Security headers
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("X-Content-Type-Options", "nosniff")
			w.Header().Set("X-Frame-Options", "DENY")
			next.ServeHTTP(w, r)
		})
	})

	// Health check
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(map[string]string{"status": "healthy"}); err != nil {
			log.Printf("Failed to encode health response: %v", err)
		}
	})

	// Single URL fetch
	r.Get("/fetch", func(w http.ResponseWriter, r *http.Request) {
		url := r.URL.Query().Get("url")
		if url == "" {
			http.Error(w, "url parameter required", http.StatusBadRequest)
			return
		}

		// Reject excessively long URLs to prevent memory/parser abuse
		if len(url) > 8192 {
			http.Error(w, "url too long (max 8192 bytes)", http.StatusBadRequest)
			return
		}

		// Basic URL validation - must be http/https
		if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
			http.Error(w, "url must use http or https scheme", http.StatusBadRequest)
			return
		}

		result := fetcher.Fetch(r.Context(), url)
		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(result); err != nil {
			log.Printf("Failed to encode fetch response: %v", err)
		}
	})

	// Batch URL fetch
	r.Post("/fetch/batch", func(w http.ResponseWriter, r *http.Request) {
		// Limit request body size to 1MB
		r.Body = http.MaxBytesReader(w, r.Body, 1<<20)

		var req FetchRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}

		if len(req.URLs) == 0 {
			http.Error(w, "urls required", http.StatusBadRequest)
			return
		}

		if len(req.URLs) > 20 {
			http.Error(w, "max 20 URLs per batch", http.StatusBadRequest)
			return
		}

		// Validate all URLs use http/https
		for _, u := range req.URLs {
			if len(u) > 8192 {
				http.Error(w, "url too long (max 8192 bytes)", http.StatusBadRequest)
				return
			}
			if !strings.HasPrefix(u, "http://") && !strings.HasPrefix(u, "https://") {
				http.Error(w, "all URLs must use http or https scheme", http.StatusBadRequest)
				return
			}
		}

		ctx := r.Context()
		if req.Timeout > 0 {
			// Cap user-provided timeout to 120 seconds max
			timeout := min(req.Timeout, 120)
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
			defer cancel()
		}

		response := fetcher.FetchBatch(ctx, req.URLs)
		w.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(w).Encode(response); err != nil {
			log.Printf("Failed to encode batch response: %v", err)
		}
	})

	// Server — bind to localhost to prevent unauthenticated external access
	server := &http.Server{
		Addr:              "127.0.0.1:" + port,
		Handler:           r,
		ReadTimeout:       15 * time.Second,
		ReadHeaderTimeout: 5 * time.Second,
		// Must exceed the 125s request-timeout middleware (and the batch
		// handler's 120s cap) or the connection is cut before the
		// handler's own deadline machinery can respond.
		WriteTimeout: 130 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh

		log.Println("Shutting down...")
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("Graceful shutdown failed: %v", err)
		}
	}()

	log.Printf("URL Fetcher service starting on :%s", port)
	// Use errors.Is for forward-compatible error comparison.
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatalf("Server error: %v", err)
	}
}
