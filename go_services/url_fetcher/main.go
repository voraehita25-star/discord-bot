package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
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

// NewFetcher creates a new Fetcher
func NewFetcher() *Fetcher {
	return &Fetcher{
		client: &http.Client{
			Timeout: requestTimeout,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				if len(via) >= 5 {
					return fmt.Errorf("too many redirects")
				}
				return nil
			},
		},
		limiter: rate.NewLimiter(rate.Limit(20), 50), // 20 requests/sec, burst 50
	}
}

// Fetch retrieves content from a URL
func (f *Fetcher) Fetch(ctx context.Context, url string) FetchResult {
	start := time.Now()
	result := FetchResult{URL: url}

	// Wait for rate limiter
	if err := f.limiter.Wait(ctx); err != nil {
		result.Error = "rate limited"
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
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
	defer resp.Body.Close()

	result.StatusCode = resp.StatusCode
	result.ContentType = resp.Header.Get("Content-Type")

	if resp.StatusCode != http.StatusOK {
		result.Error = fmt.Sprintf("HTTP %d", resp.StatusCode)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Limit body size
	limitedReader := io.LimitReader(resp.Body, maxContentLength)

	// Handle charset
	utf8Reader, err := charset.NewReader(limitedReader, result.ContentType)
	if err != nil {
		utf8Reader = limitedReader
	}

	// Read body
	body, err := io.ReadAll(utf8Reader)
	if err != nil {
		result.Error = fmt.Sprintf("read error: %v", err)
		result.FetchTimeMs = time.Since(start).Milliseconds()
		return result
	}

	// Extract content
	if strings.Contains(result.ContentType, "text/html") {
		title, description, content := extractHTMLContent(body)
		result.Title = title
		result.Description = description
		result.Content = truncateString(content, maxExtractedLength)
	} else if strings.Contains(result.ContentType, "text/plain") {
		result.Content = truncateString(string(body), maxExtractedLength)
	} else {
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

	// Wait with context cancellation support
	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case <-ctx.Done():
		// Context cancelled, wait briefly for in-flight requests
		timer := time.NewTimer(500 * time.Millisecond)
		select {
		case <-done:
			timer.Stop()
		case <-timer.C:
			// Timeout waiting for in-flight requests
		}
	case <-done:
		// All requests completed
	}

	// Count results
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
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(string(body)))
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
	r.Use(middleware.Timeout(60 * time.Second))

	// Health check
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
	})

	// Single URL fetch
	r.Get("/fetch", func(w http.ResponseWriter, r *http.Request) {
		url := r.URL.Query().Get("url")
		if url == "" {
			http.Error(w, "url parameter required", http.StatusBadRequest)
			return
		}

		// Basic URL validation - must be http/https
		if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
			http.Error(w, "url must use http or https scheme", http.StatusBadRequest)
			return
		}

		result := fetcher.Fetch(r.Context(), url)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(result)
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
			if !strings.HasPrefix(u, "http://") && !strings.HasPrefix(u, "https://") {
				http.Error(w, "all URLs must use http or https scheme", http.StatusBadRequest)
				return
			}
		}

		ctx := r.Context()
		if req.Timeout > 0 {
			// Cap user-provided timeout to 120 seconds max
			timeout := req.Timeout
			if timeout > 120 {
				timeout = 120
			}
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
			defer cancel()
		}

		response := fetcher.FetchBatch(ctx, req.URLs)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	})

	// Server
	server := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 60 * time.Second,
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
		server.Shutdown(ctx)
	}()

	log.Printf("URL Fetcher service starting on :%s", port)
	if err := server.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("Server error: %v", err)
	}
}
