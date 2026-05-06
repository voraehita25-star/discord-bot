"""
Python client for Go URL Fetcher service.

Provides fallback to aiohttp if service is not available.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Service configuration
URL_FETCHER_HOST = os.getenv("URL_FETCHER_HOST", "localhost")
URL_FETCHER_PORT = os.getenv("URL_FETCHER_PORT", "8081")
URL_FETCHER_URL = f"http://{URL_FETCHER_HOST}:{URL_FETCHER_PORT}"


class URLFetcherClient:
    """
    Client for Go URL Fetcher service with fallback to aiohttp.

    Usage:
        async with URLFetcherClient() as client:
            result = await client.fetch("https://example.com")
            results = await client.fetch_batch(["https://a.com", "https://b.com"])
    """

    # Cache service availability for 5 minutes to allow recovery
    SERVICE_CHECK_INTERVAL = 300  # seconds

    def __init__(self, base_url: str | None = None, timeout: int = 30):
        self.base_url = base_url or URL_FETCHER_URL
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._service_available: bool | None = None
        self._service_check_time: float = 0

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        await self._check_service()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    async def _check_service(self) -> bool:
        """Check if Go service is available (with cache expiration)."""
        import time

        # Check if cache is still valid
        now = time.time()
        if self._service_available is not None:
            if now - self._service_check_time < self.SERVICE_CHECK_INTERVAL:
                return self._service_available
            # Cache expired, recheck

        if self._session is None:
            self._service_available = False
            self._service_check_time = now
            return False

        try:
            async with self._session.get(
                f"{self.base_url}/health", timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                self._service_available = resp.status == 200
                self._service_check_time = now
                if self._service_available:
                    logger.info("✅ Go URL Fetcher service available")
                return self._service_available
        except Exception as e:
            self._service_available = False
            self._service_check_time = now
            logger.debug("Go URL Fetcher health check failed: %s", e)
            logger.warning("⚠️ Go URL Fetcher not available, using aiohttp fallback")
            return False

    async def fetch(self, url: str) -> dict[str, Any]:
        """
        Fetch content from a URL.

        Returns:
            Dict with: url, title, content, description, error, status_code, fetch_time_ms
        """
        # Re-check service availability when we have a real session so we
        # don't keep routing to a Go service that has died after the last
        # check. _check_service has its own backoff. If there's no session
        # at all we keep the previously-set flag so callers that fake it
        # for tests still see the expected route.
        if self._session is not None:
            await self._check_service()
        if self._service_available:
            return await self._fetch_via_service(url)
        return await self._fetch_fallback(url)

    async def _fetch_via_service(self, url: str) -> dict[str, Any]:
        """Fetch via Go service."""
        # SSRF check before forwarding to Go service. Hard-fail the request if
        # the SSRF helper isn't importable: silently trusting the Go side to
        # re-validate is a posture decision the Python side shouldn't make.
        try:
            from utils.web.url_fetcher import _is_private_url
        except ImportError as exc:
            logger.error("url_fetcher SSRF helper unavailable; refusing to fetch %s", url)
            return {"url": url, "error": f"SSRF helper missing: {exc}"}
        if await _is_private_url(url):
            return {"url": url, "error": "SSRF blocked: URL resolves to private/internal address"}

        try:
            if self._session is None:
                raise RuntimeError("URLFetcherClient must be used as an async context manager")
            # Propagate trace ID to Go service
            headers: dict[str, str] = {}
            try:
                from utils.monitoring.tracing import trace_headers

                headers = trace_headers()
            except ImportError:
                pass
            async with self._session.get(
                f"{self.base_url}/fetch",
                params={"url": url},
                headers=headers,
            ) as resp:
                return await resp.json()  # type: ignore[no-any-return]
        except Exception as e:
            return {"url": url, "error": str(e)}

    async def _fetch_fallback(self, url: str) -> dict[str, Any]:
        """Fallback fetch using aiohttp."""
        import time

        from bs4 import BeautifulSoup

        start = time.time()
        result: dict[str, Any] = {"url": url}

        # SSRF Protection: Block private/internal IPs
        try:
            from utils.web.url_fetcher import _is_private_url

            if await _is_private_url(url):
                result["error"] = "SSRF blocked: URL resolves to private/internal address"
                result["fetch_time_ms"] = int((time.time() - start) * 1000)
                return result
        except ImportError:
            # url_fetcher not available — apply basic SSRF protection with DNS resolution
            import asyncio as _asyncio
            import ipaddress
            import socket as _socket
            from urllib.parse import urlparse

            try:
                parsed = urlparse(url)
                # Enforce http(s) scheme up front. Without this an attacker
                # could craft `file:///etc/passwd` and our hostname-based
                # SSRF check would silently no-op (hostname is None) — only
                # the eventual DNS-failure branch would catch it. Reject
                # other schemes explicitly so the failure mode is clear.
                if parsed.scheme not in ("http", "https"):
                    result["error"] = f"SSRF blocked: unsupported scheme '{parsed.scheme}'"
                    result["fetch_time_ms"] = int((time.time() - start) * 1000)
                    return result
                hostname = parsed.hostname or ""
                if not hostname:
                    result["error"] = "SSRF blocked: URL has no hostname"
                    result["fetch_time_ms"] = int((time.time() - start) * 1000)
                    return result
                # Resolve hostname to IP addresses for proper SSRF protection.
                # Use SOCK_STREAM rather than 0 for the type filter — passing
                # 0 ("any") will, on some platforms, return only one address
                # family, leaking the SSRF check past the other family. With
                # SOCK_STREAM the resolver returns the family pair we'd
                # actually use to dial, so AAAA + A both get checked.
                loop = _asyncio.get_running_loop()
                addr_infos = await loop.getaddrinfo(hostname, None, type=_socket.SOCK_STREAM)
                for _family, _, _, _, sockaddr in addr_infos:
                    ip_str = sockaddr[0]
                    try:
                        addr = ipaddress.ip_address(ip_str)
                        if (
                            addr.is_private
                            or addr.is_loopback
                            or addr.is_reserved
                            or addr.is_link_local
                            or addr.is_unspecified  # 0.0.0.0 / ::
                        ):
                            result["error"] = (
                                "SSRF blocked: URL resolves to private/internal address"
                            )
                            result["fetch_time_ms"] = int((time.time() - start) * 1000)
                            return result
                    except ValueError:
                        continue
            except (TimeoutError, OSError, _socket.gaierror):
                # DNS resolution failed — block for safety. Catching the
                # broad ``Exception`` here used to swallow ``KeyboardInterrupt``
                # cousins in some Python versions and made debugging
                # genuine programming errors (e.g. NameError) inside the
                # try-block impossible. Restrict the catch to actual
                # network/DNS failures.
                result["error"] = "SSRF blocked: DNS resolution failed"
                result["fetch_time_ms"] = int((time.time() - start) * 1000)
                return result

        try:
            if self._session is None:
                raise RuntimeError("URLFetcherClient must be used as an async context manager")
            # allow_redirects=False closes the SSRF redirect-bypass window: the
            # initial host was checked above, but a 302 pointing at 169.254.169.254
            # or 127.0.0.1 would otherwise be followed by aiohttp's default
            # redirect chaser without re-resolving through the private-IP guard.
            async with self._session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                allow_redirects=False,
            ) as resp:
                # If we got a redirect, surface it as an error rather than
                # silently following to a possibly-private target.
                if 300 <= resp.status < 400:
                    result["status_code"] = resp.status
                    result["error"] = (
                        f"Redirect not followed (SSRF guard): {resp.headers.get('Location', '')}"
                    )
                    result["fetch_time_ms"] = int((time.time() - start) * 1000)
                    return result
                result["status_code"] = resp.status
                result["content_type"] = resp.headers.get("Content-Type", "")

                if resp.status != 200:
                    result["error"] = f"HTTP {resp.status}"
                else:
                    # Limit response size to 5MB to prevent memory exhaustion
                    MAX_RESPONSE_SIZE = 5 * 1024 * 1024
                    raw_bytes = await resp.content.read(MAX_RESPONSE_SIZE)
                    text = raw_bytes.decode("utf-8", errors="replace")

                    if "text/html" in result["content_type"]:
                        soup = BeautifulSoup(text, "html.parser")

                        # Extract title
                        title_tag = soup.find("title")
                        if title_tag:
                            result["title"] = title_tag.get_text(strip=True)

                        # Extract description
                        meta_desc = soup.find("meta", attrs={"name": "description"})
                        if meta_desc:
                            result["description"] = meta_desc.get("content", "")

                        # Extract main content
                        for tag in soup(["script", "style", "nav", "footer", "header"]):
                            tag.decompose()

                        main = soup.find("main") or soup.find("article") or soup.find("body")
                        if main:
                            result["content"] = main.get_text(separator="\n", strip=True)[:5000]
                    else:
                        result["content"] = text[:5000]
        except Exception as e:
            result["error"] = str(e)

        result["fetch_time_ms"] = int((time.time() - start) * 1000)
        return result

    async def fetch_batch(self, urls: list[str], timeout: int | None = None) -> dict[str, Any]:
        """
        Fetch multiple URLs concurrently.

        Returns:
            Dict with: results, total_time_ms, success_count, error_count
        """
        if self._service_available:
            return await self._fetch_batch_via_service(urls, timeout)
        return await self._fetch_batch_fallback(urls)

    async def _fetch_batch_via_service(
        self, urls: list[str], timeout: int | None
    ) -> dict[str, Any]:
        """Batch fetch via Go service.

        Per-URL SSRF check BEFORE forwarding to the Go side. Without this,
        the Go service would receive a list of arbitrary URLs and any URL
        that bypasses the Go-side check (or any future config drift between
        the two sides) becomes an SSRF. Doing it here guarantees the
        Python-side policy is the floor; the Go side can be stricter but
        never more permissive.
        """
        # Filter the batch through the SSRF helper. Failed URLs are turned
        # into per-URL error entries in the response so callers can still
        # match results back to inputs by index/URL.
        try:
            from utils.web.url_fetcher import _is_private_url
        except ImportError as exc:
            logger.error("url_fetcher SSRF helper unavailable; refusing batch fetch")
            return {
                "results": [{"url": u, "error": f"SSRF helper missing: {exc}"} for u in urls],
                "error_count": len(urls),
                "success_count": 0,
            }

        safe_urls: list[str] = []
        blocked_results: list[dict[str, Any]] = []
        for u in urls:
            if await _is_private_url(u):
                blocked_results.append(
                    {"url": u, "error": "SSRF blocked: URL resolves to private/internal address"}
                )
            else:
                safe_urls.append(u)

        # If everything was blocked, short-circuit without touching the Go side.
        if not safe_urls:
            return {
                "results": blocked_results,
                "error_count": len(blocked_results),
                "success_count": 0,
            }

        try:
            payload: dict[str, Any] = {"urls": safe_urls}
            if timeout:
                payload["timeout"] = timeout

            if self._session is None:
                raise RuntimeError("URLFetcherClient must be used as an async context manager")
            async with self._session.post(f"{self.base_url}/fetch/batch", json=payload) as resp:
                service_response = await resp.json()
            # Merge blocked entries back in so callers see a 1:1 mapping
            # with their original input list.
            if blocked_results:
                merged_results = list(service_response.get("results", []))
                merged_results.extend(blocked_results)
                service_response["results"] = merged_results
                service_response["error_count"] = service_response.get("error_count", 0) + len(
                    blocked_results
                )
            return service_response  # type: ignore[no-any-return]
        except Exception as e:
            return {
                "results": ([{"url": u, "error": str(e)} for u in safe_urls] + blocked_results),
                "error_count": len(urls),
                "success_count": 0,
            }

    async def _fetch_batch_fallback(self, urls: list[str]) -> dict[str, Any]:
        """Batch fetch using aiohttp."""
        import time

        start = time.time()

        # Fetch all URLs concurrently
        tasks = [self._fetch_fallback(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        processed = []
        success_count = 0
        error_count = 0

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                processed.append({"url": urls[i], "error": str(result)})
                error_count += 1
            else:
                processed.append(result)
                if "error" not in result:
                    success_count += 1
                else:
                    error_count += 1

        return {
            "results": processed,
            "total_time_ms": int((time.time() - start) * 1000),
            "success_count": success_count,
            "error_count": error_count,
        }

    @property
    def is_service_available(self) -> bool:
        """Check if using Go service backend."""
        return self._service_available or False


# Convenience function
async def fetch_url(url: str) -> dict[str, Any]:
    """Fetch a single URL."""
    async with URLFetcherClient() as client:
        return await client.fetch(url)  # type: ignore[no-any-return]


async def fetch_urls(urls: list[str]) -> dict[str, Any]:
    """Fetch multiple URLs."""
    async with URLFetcherClient() as client:
        return await client.fetch_batch(urls)  # type: ignore[no-any-return]
