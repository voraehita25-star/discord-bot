"""Unit tests for the Go URL Fetcher HTTP client (utils/web/url_fetcher_client.py).

These tests focus on behaviors NOT already exercised by the block merged into
``tests/test_url_fetcher.py`` (init / property / convenience-function smoke
tests): the real ``_check_service`` HTTP paths and its time-based cache, the
SSRF guard branches in the service/fallback fetch paths, the redirect and
content-size guards, batch blocked-result merging, trace-header propagation,
and the re-check routing performed by ``fetch``/``fetch_batch``.

All network access is mocked — ``aiohttp.ClientSession`` is replaced with a
MagicMock whose ``.get``/``.post`` return async-context-manager mocks (we drive
``__aenter__``/``__aexit__`` directly). Nothing here touches the network, the
clock, or DNS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_cm_response(**attrs):
    """Build a mock that behaves like ``session.get(...)`` / ``session.post(...)``.

    The returned object is itself the async context manager AND the response:
    ``async with session.get(...) as resp`` yields the same mock, matching the
    repo's established pattern (see test_url_fetcher.py / test_health_client.py).
    """
    resp = AsyncMock()
    for key, value in attrs.items():
        setattr(resp, key, value)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


class TestCheckService:
    """Tests for _check_service HTTP probing and its time-based cache."""

    @pytest.mark.asyncio
    async def test_check_service_no_session_returns_false(self):
        """With no session, the probe records unavailable without touching HTTP."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._session = None

        result = await client._check_service()

        assert result is False
        assert client._service_available is False
        assert client._service_check_time != 0

    @pytest.mark.asyncio
    async def test_check_service_http_200_sets_available(self):
        """A 200 from /health marks the service available."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient(base_url="http://localhost:8081")
        resp = _make_cm_response(status=200)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._check_service()

        assert result is True
        assert client._service_available is True
        # Probe hits the /health endpoint on the configured base_url.
        called_url = mock_session.get.call_args.args[0]
        assert called_url == "http://localhost:8081/health"

    @pytest.mark.asyncio
    async def test_check_service_non_200_marks_unavailable(self):
        """A non-200 /health response marks the service unavailable."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        resp = _make_cm_response(status=503)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._check_service()

        assert result is False
        assert client._service_available is False

    @pytest.mark.asyncio
    async def test_check_service_exception_marks_unavailable(self):
        """A connection error during the probe degrades to unavailable, no raise."""
        import aiohttp

        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
        client._session = mock_session

        result = await client._check_service()

        assert result is False
        assert client._service_available is False

    @pytest.mark.asyncio
    async def test_check_service_uses_fresh_cache_without_probing(self, monkeypatch):
        """A recent cached result is returned without issuing a new HTTP probe."""
        import time as _time

        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = True
        # Pretend the last check happened "now"; cache window is wide open.
        # _check_service does a function-local ``import time``, so patch the
        # real time.time it resolves through sys.modules.
        fake_now = 1000.0
        monkeypatch.setattr(_time, "time", lambda: fake_now)
        client._service_check_time = fake_now

        mock_session = MagicMock()
        mock_session.get = MagicMock()
        client._session = mock_session

        result = await client._check_service()

        assert result is True
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_service_reprobes_after_cache_expires(self, monkeypatch):
        """Once the cache window lapses, a fresh HTTP probe is issued."""
        import time as _time

        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = False
        client._service_check_time = 0.0
        # Jump far past SERVICE_CHECK_INTERVAL so the cache is stale.
        monkeypatch.setattr(_time, "time", lambda: float(client.SERVICE_CHECK_INTERVAL + 100))

        resp = _make_cm_response(status=200)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._check_service()

        assert result is True
        mock_session.get.assert_called_once()


class TestFetchRouting:
    """Tests for fetch()/fetch_batch() re-check + routing behavior."""

    @pytest.mark.asyncio
    async def test_fetch_rechecks_service_when_session_present(self):
        """With a live session, fetch() re-probes before routing to the service."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._session = MagicMock()
        client._check_service = AsyncMock(return_value=None)
        # Simulate the recheck flipping availability on.
        client._service_available = True
        client._fetch_via_service = AsyncMock(return_value={"url": "http://x.com"})

        await client.fetch("http://x.com")

        client._check_service.assert_awaited_once()
        client._fetch_via_service.assert_awaited_once_with("http://x.com")

    @pytest.mark.asyncio
    async def test_fetch_skips_recheck_when_no_session(self):
        """Without a session, fetch() keeps the existing flag and skips the recheck."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._session = None
        client._service_available = False
        client._check_service = AsyncMock()
        client._fetch_fallback = AsyncMock(return_value={"url": "http://x.com"})

        await client.fetch("http://x.com")

        client._check_service.assert_not_called()
        client._fetch_fallback.assert_awaited_once_with("http://x.com")

    @pytest.mark.asyncio
    async def test_fetch_batch_rechecks_service_when_session_present(self):
        """fetch_batch() mirrors fetch(): re-probe then route to the service."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._session = MagicMock()
        client._check_service = AsyncMock()
        client._service_available = True
        client._fetch_batch_via_service = AsyncMock(return_value={"results": []})

        urls = ["http://a.com", "http://b.com"]
        await client.fetch_batch(urls, timeout=15)

        client._check_service.assert_awaited_once()
        client._fetch_batch_via_service.assert_awaited_once_with(urls, 15)

    @pytest.mark.asyncio
    async def test_fetch_batch_routes_to_fallback_when_unavailable(self):
        """When unavailable, fetch_batch() routes to the aiohttp fallback."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._session = None
        client._service_available = False
        client._fetch_batch_fallback = AsyncMock(return_value={"results": []})

        urls = ["http://a.com"]
        await client.fetch_batch(urls)

        client._fetch_batch_fallback.assert_awaited_once_with(urls)


class TestFetchViaServiceSSRF:
    """Tests for the SSRF guard + trace-header propagation in _fetch_via_service."""

    @pytest.mark.asyncio
    async def test_blocks_private_url_before_request(self, monkeypatch):
        """A private/internal URL is blocked and the session is never touched."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=True))

        client = URLFetcherClient()
        mock_session = MagicMock()
        mock_session.get = MagicMock()
        client._session = mock_session

        result = await client._fetch_via_service("http://169.254.169.254/")

        assert "SSRF blocked" in result["error"]
        assert result["url"] == "http://169.254.169.254/"
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_ssrf_helper_missing_hard_fails(self, monkeypatch):
        """If the SSRF helper can't be imported, the fetch hard-fails (fail-closed)."""
        import builtins

        from utils.web.url_fetcher_client import URLFetcherClient

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("simulated missing SSRF helper")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        client = URLFetcherClient()
        client._session = MagicMock()

        result = await client._fetch_via_service("http://example.com")

        assert "SSRF helper missing" in result["error"]

    @pytest.mark.asyncio
    async def test_no_session_returns_error_dict(self, monkeypatch):
        """A missing session surfaces as an error dict, not an unhandled raise."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        client = URLFetcherClient()
        client._session = None

        result = await client._fetch_via_service("http://example.com")

        assert result["url"] == "http://example.com"
        assert "error" in result
        assert "async context manager" in result["error"]

    @pytest.mark.asyncio
    async def test_propagates_trace_headers_and_url_param(self, monkeypatch):
        """Trace headers are forwarded and the url is passed as a query param."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))
        # Inject a fake tracing module so the lazy import inside the method
        # returns our deterministic header set.
        import sys
        import types

        fake_tracing = types.ModuleType("utils.monitoring.tracing")
        fake_tracing.trace_headers = lambda: {"X-Trace-Id": "abc123"}
        monkeypatch.setitem(sys.modules, "utils.monitoring.tracing", fake_tracing)

        client = URLFetcherClient(base_url="http://localhost:8081")
        resp = _make_cm_response()
        resp.json = AsyncMock(return_value={"url": "http://ok.com", "title": "OK"})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_via_service("http://ok.com")

        assert result["title"] == "OK"
        kwargs = mock_session.get.call_args.kwargs
        assert kwargs["params"] == {"url": "http://ok.com"}
        assert kwargs["headers"] == {"X-Trace-Id": "abc123"}
        assert mock_session.get.call_args.args[0] == "http://localhost:8081/fetch"


class TestFetchFallbackGuards:
    """Tests for redirect / content-size / content-type guards in _fetch_fallback."""

    @pytest.mark.asyncio
    async def test_blocks_private_url(self, monkeypatch):
        """The fallback also blocks private URLs and records fetch_time_ms."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=True))

        client = URLFetcherClient()
        mock_session = MagicMock()
        mock_session.get = MagicMock()
        client._session = mock_session

        result = await client._fetch_fallback("http://10.0.0.1/")

        assert "SSRF blocked" in result["error"]
        assert "fetch_time_ms" in result
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_redirect_not_followed(self, monkeypatch):
        """A 3xx is surfaced as an error rather than chased (SSRF redirect guard)."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        client = URLFetcherClient()
        resp = _make_cm_response(status=302, headers={"Location": "http://127.0.0.1/admin"})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://example.com")

        assert result["status_code"] == 302
        assert "Redirect not followed" in result["error"]
        assert "127.0.0.1" in result["error"]
        # allow_redirects must be disabled.
        assert mock_session.get.call_args.kwargs["allow_redirects"] is False

    @pytest.mark.asyncio
    async def test_content_too_large_rejected(self, monkeypatch):
        """A body over the 5MB cap is rejected instead of parsed truncated."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        client = URLFetcherClient()
        max_size = 5 * 1024 * 1024
        oversized = b"x" * (max_size + 1)
        resp = _make_cm_response(status=200, headers={"Content-Type": "text/html"})
        resp.content = MagicMock()
        resp.content.read = AsyncMock(return_value=oversized)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://example.com")

        assert "Content too large" in result["error"]
        assert "fetch_time_ms" in result

    @pytest.mark.asyncio
    async def test_content_too_large_rejected_across_chunks(self, monkeypatch):
        """A >5MB body delivered across many small reads is drained and rejected.

        Regression: aiohttp's StreamReader.read(n) returns only what is currently
        buffered (~one 64 KiB flow-control window), NOT n bytes. The old single
        ``read(cap + 1)`` therefore saw just the first window — it neither reached
        the cap (so the >5MB rejection was unreachable) nor read the rest (the page
        was silently parsed truncated). The capped-read loop must keep reading past
        the first window, exceed the cap, and reject. The existing test above hands
        back the whole body in one read(); this one forces the chunked path.
        """
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        max_size = 5 * 1024 * 1024
        window = b"x" * (64 * 1024)  # one ~64 KiB flow-control window per read
        # A few more windows than the cap needs; the loop stops as soon as it
        # overshoots, so it won't exhaust the list.
        windows = [window] * (max_size // len(window) + 4)

        client = URLFetcherClient()
        resp = _make_cm_response(status=200, headers={"Content-Type": "text/html"})
        resp.content = MagicMock()
        resp.content.read = AsyncMock(side_effect=windows)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://example.com")

        assert "Content too large" in result["error"]
        assert "fetch_time_ms" in result
        # The old code read exactly once; the capped-read loop must read the body
        # across multiple windows before it can detect the overflow.
        assert resp.content.read.await_count > 1

    @pytest.mark.asyncio
    async def test_html_parsing_extracts_title_and_content(self, monkeypatch):
        """A 200 text/html body has title/description/main content extracted."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        html = (
            b"<html><head><title>My Title</title>"
            b'<meta name="description" content="A page">'
            b"</head><body><main>Hello world body</main></body></html>"
        )
        client = URLFetcherClient()
        resp = _make_cm_response(status=200, headers={"Content-Type": "text/html"})
        resp.content = MagicMock()
        # Body on the first read, then b"" (EOF) — the capped-read loop drains to EOF.
        resp.content.read = AsyncMock(side_effect=[html, b""])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://example.com")

        assert result["status_code"] == 200
        assert result["title"] == "My Title"
        assert result["description"] == "A page"
        assert "Hello world body" in result["content"]

    @pytest.mark.asyncio
    async def test_non_html_content_returned_raw(self, monkeypatch):
        """A non-HTML 200 body is returned as raw text (truncated to 5000 chars)."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        body = b'{"key": "value"}'
        client = URLFetcherClient()
        resp = _make_cm_response(status=200, headers={"Content-Type": "application/json"})
        resp.content = MagicMock()
        # Body on the first read, then b"" (EOF) — the capped-read loop drains to EOF.
        resp.content.read = AsyncMock(side_effect=[body, b""])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://api.example.com")

        assert result["status_code"] == 200
        assert result["content"] == '{"key": "value"}'
        assert "title" not in result

    @pytest.mark.asyncio
    async def test_content_type_substring_not_treated_as_html(self, monkeypatch):
        """A Content-Type merely containing 'text/html' takes the raw-text branch.

        Mirrors url_fetcher.fetch_url_content's exact primary-MIME match so a
        content-type-smuggling value like 'application/x-text/html-weird' is not
        routed through BeautifulSoup.
        """
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        body = b"<title>Not parsed</title>plain body"
        client = URLFetcherClient()
        resp = _make_cm_response(
            status=200, headers={"Content-Type": "application/x-text/html-weird"}
        )
        resp.content = MagicMock()
        # Body on the first read, then b"" (EOF) — the capped-read loop drains to EOF.
        resp.content.read = AsyncMock(side_effect=[body, b""])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://example.com")

        assert result["status_code"] == 200
        assert result["content"] == "<title>Not parsed</title>plain body"
        assert "title" not in result


class TestFetchFallbackNoHelperSSRF:
    """Tests for the built-in SSRF fallback when url_fetcher helper is absent."""

    def _patch_helper_import_error(self, monkeypatch):
        """Make the lazy ``from utils.web.url_fetcher import _is_private_url`` fail."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("no helper")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self, monkeypatch):
        """Without the helper, a file:// URL is rejected on scheme grounds."""
        from utils.web.url_fetcher_client import URLFetcherClient

        self._patch_helper_import_error(monkeypatch)

        client = URLFetcherClient()
        client._session = MagicMock()

        result = await client._fetch_fallback("file:///etc/passwd")

        assert "unsupported scheme" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_url_without_hostname(self, monkeypatch):
        """A URL with no hostname is rejected before any DNS resolution."""
        from utils.web.url_fetcher_client import URLFetcherClient

        self._patch_helper_import_error(monkeypatch)

        client = URLFetcherClient()
        client._session = MagicMock()

        result = await client._fetch_fallback("http://")

        assert "no hostname" in result["error"]

    @pytest.mark.asyncio
    async def test_blocks_private_resolved_ip(self, monkeypatch):
        """A hostname resolving to a private IP is blocked (DNS-rebind guard)."""
        import asyncio
        import socket

        from utils.web.url_fetcher_client import URLFetcherClient

        self._patch_helper_import_error(monkeypatch)

        async def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.1.2.3", 0))]

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

        client = URLFetcherClient()
        client._session = MagicMock()

        result = await client._fetch_fallback("http://evil.example.com")

        assert "private/internal address" in result["error"]

    @pytest.mark.asyncio
    async def test_dns_failure_blocks(self, monkeypatch):
        """A DNS resolution failure blocks the fetch for safety."""
        import asyncio
        import socket

        from utils.web.url_fetcher_client import URLFetcherClient

        self._patch_helper_import_error(monkeypatch)

        async def fake_getaddrinfo(host, port, **kwargs):
            raise socket.gaierror("name resolution failed")

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

        client = URLFetcherClient()
        client._session = MagicMock()

        result = await client._fetch_fallback("http://nope.example.com")

        assert "DNS resolution failed" in result["error"]

    @pytest.mark.asyncio
    async def test_public_ip_passes_through_to_fetch(self, monkeypatch):
        """A hostname resolving to a public IP passes the guard and fetches."""
        import asyncio
        import socket

        from utils.web.url_fetcher_client import URLFetcherClient

        self._patch_helper_import_error(monkeypatch)

        async def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

        client = URLFetcherClient()
        resp = _make_cm_response(status=200, headers={"Content-Type": "text/plain"})
        resp.content = MagicMock()
        resp.content.read = AsyncMock(side_effect=[b"public body", b""])  # body, then EOF
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=resp)
        client._session = mock_session

        result = await client._fetch_fallback("http://public.example.com")

        assert result["status_code"] == 200
        assert result["content"] == "public body"


class TestFetchBatchViaServiceSSRF:
    """Tests for batch SSRF filtering + blocked-result merging."""

    @pytest.mark.asyncio
    async def test_helper_missing_marks_all_errors(self, monkeypatch):
        """Missing SSRF helper turns the whole batch into per-URL errors."""
        import builtins

        from utils.web.url_fetcher_client import URLFetcherClient

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("no helper")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        client = URLFetcherClient()
        client._session = MagicMock()

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_via_service(urls, timeout=None)

        assert result["error_count"] == 2
        assert result["success_count"] == 0
        assert all("SSRF helper missing" in r["error"] for r in result["results"])

    @pytest.mark.asyncio
    async def test_all_blocked_short_circuits(self, monkeypatch):
        """If every URL is private, the Go service is never contacted."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=True))

        client = URLFetcherClient()
        mock_session = MagicMock()
        mock_session.post = MagicMock()
        client._session = mock_session

        urls = ["http://10.0.0.1", "http://localhost"]
        result = await client._fetch_batch_via_service(urls, timeout=None)

        assert result["error_count"] == 2
        assert result["success_count"] == 0
        mock_session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_results_merged_with_service_results(self, monkeypatch):
        """Blocked URLs are merged back into the service response 1:1 with input."""
        from utils.web.url_fetcher_client import URLFetcherClient

        async def selective_private(url):
            return "blocked" in url

        monkeypatch.setattr(
            "utils.web.url_fetcher._is_private_url",
            AsyncMock(side_effect=selective_private),
        )

        client = URLFetcherClient()
        resp = _make_cm_response()
        resp.json = AsyncMock(
            return_value={
                "results": [{"url": "http://safe.com", "title": "Safe"}],
                "success_count": 1,
                "error_count": 0,
            }
        )
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=resp)
        client._session = mock_session

        urls = ["http://safe.com", "http://blocked.internal"]
        result = await client._fetch_batch_via_service(urls, timeout=None)

        # 1 service result + 1 blocked = 2 total, in input-mappable order.
        assert len(result["results"]) == 2
        assert result["error_count"] == 1
        urls_in_results = {r["url"] for r in result["results"]}
        assert urls_in_results == {"http://safe.com", "http://blocked.internal"}
        # Only safe URLs are forwarded to the Go service.
        assert mock_session.post.call_args.kwargs["json"]["urls"] == ["http://safe.com"]

    @pytest.mark.asyncio
    async def test_timeout_added_to_payload(self, monkeypatch):
        """A non-None timeout is included in the POST payload."""
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False))

        client = URLFetcherClient()
        resp = _make_cm_response()
        resp.json = AsyncMock(return_value={"results": []})
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=resp)
        client._session = mock_session

        await client._fetch_batch_via_service(["http://a.com"], timeout=42)

        assert mock_session.post.call_args.kwargs["json"]["timeout"] == 42

    @pytest.mark.asyncio
    async def test_service_exception_marks_safe_urls_errored(self, monkeypatch):
        """A POST exception turns safe URLs into errors and keeps blocked entries."""
        from utils.web.url_fetcher_client import URLFetcherClient

        async def selective_private(url):
            return "blocked" in url

        monkeypatch.setattr(
            "utils.web.url_fetcher._is_private_url",
            AsyncMock(side_effect=selective_private),
        )

        client = URLFetcherClient()
        client._service_available = True
        client._service_check_time = 123.0
        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=Exception("connreset"))
        client._session = mock_session

        urls = ["http://safe.com", "http://blocked.internal"]
        result = await client._fetch_batch_via_service(urls, timeout=None)

        assert result["success_count"] == 0
        assert result["error_count"] == len(urls)
        assert len(result["results"]) == 2
        # A mid-interval batch failure invalidates the cached availability so the
        # next call re-routes through the aiohttp fallback (self-heals like the
        # single-URL path) instead of hard-failing for SERVICE_CHECK_INTERVAL.
        assert client._service_available is False
        assert client._service_check_time == 0


class TestConstantsAndConfig:
    """Tests for module-level host/port allowlist + validation logic."""

    def test_default_constants_well_formed(self):
        """Default URL is http://<host>:<port> with allowlisted host + valid port."""
        from utils.web.url_fetcher_client import (
            URL_FETCHER_HOST,
            URL_FETCHER_PORT,
            URL_FETCHER_URL,
        )

        assert URL_FETCHER_URL == f"http://{URL_FETCHER_HOST}:{URL_FETCHER_PORT}"
        assert URL_FETCHER_HOST in {"localhost", "127.0.0.1", "::1", "url-fetcher"}
        assert 1 <= int(URL_FETCHER_PORT) <= 65535

    def test_disallowed_host_falls_back_to_localhost(self, monkeypatch):
        """A host outside the allowlist is rejected at import in favor of localhost."""
        import importlib

        import utils.web.url_fetcher_client as mod

        monkeypatch.setenv("URL_FETCHER_HOST", "evil.example.com")
        monkeypatch.setenv("URL_FETCHER_PORT", "8081")
        try:
            reloaded = importlib.reload(mod)
            assert reloaded.URL_FETCHER_HOST == "localhost"
        finally:
            # Restore the module to its env-default state for other tests.
            monkeypatch.delenv("URL_FETCHER_HOST", raising=False)
            monkeypatch.delenv("URL_FETCHER_PORT", raising=False)
            importlib.reload(mod)

    def test_allowed_host_override_is_honored(self, monkeypatch):
        """An allowlisted host override (url-fetcher) is honored at import."""
        import importlib

        import utils.web.url_fetcher_client as mod

        monkeypatch.setenv("URL_FETCHER_HOST", "url-fetcher")
        try:
            reloaded = importlib.reload(mod)
            assert reloaded.URL_FETCHER_HOST == "url-fetcher"
        finally:
            monkeypatch.delenv("URL_FETCHER_HOST", raising=False)
            importlib.reload(mod)

    def test_invalid_port_falls_back_to_8081(self, monkeypatch):
        """A non-numeric / out-of-range port falls back to 8081."""
        import importlib

        import utils.web.url_fetcher_client as mod

        monkeypatch.setenv("URL_FETCHER_PORT", "not-a-number")
        try:
            reloaded = importlib.reload(mod)
            assert reloaded.URL_FETCHER_PORT == "8081"
        finally:
            monkeypatch.delenv("URL_FETCHER_PORT", raising=False)
            importlib.reload(mod)

    def test_out_of_range_port_falls_back_to_8081(self, monkeypatch):
        """A port above 65535 is treated as invalid and falls back to 8081."""
        import importlib

        import utils.web.url_fetcher_client as mod

        monkeypatch.setenv("URL_FETCHER_PORT", "70000")
        try:
            reloaded = importlib.reload(mod)
            assert reloaded.URL_FETCHER_PORT == "8081"
        finally:
            monkeypatch.delenv("URL_FETCHER_PORT", raising=False)
            importlib.reload(mod)
