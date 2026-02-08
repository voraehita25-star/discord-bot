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
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
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
            async with self._session.get(f"{self.base_url}/health", timeout=aiohttp.ClientTimeout(total=2)) as resp:
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
        if self._service_available:
            return await self._fetch_via_service(url)
        return await self._fetch_fallback(url)

    async def _fetch_via_service(self, url: str) -> dict[str, Any]:
        """Fetch via Go service."""
        try:
            async with self._session.get(
                f"{self.base_url}/fetch",
                params={"url": url}
            ) as resp:
                return await resp.json()
        except Exception as e:
            return {"url": url, "error": str(e)}

    async def _fetch_fallback(self, url: str) -> dict[str, Any]:
        """Fallback fetch using aiohttp."""
        import time

        from bs4 import BeautifulSoup

        start = time.time()
        result = {"url": url}

        try:
            async with self._session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            ) as resp:
                result["status_code"] = resp.status
                result["content_type"] = resp.headers.get("Content-Type", "")

                if resp.status != 200:
                    result["error"] = f"HTTP {resp.status}"
                else:
                    text = await resp.text()

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

    async def _fetch_batch_via_service(self, urls: list[str], timeout: int | None) -> dict[str, Any]:
        """Batch fetch via Go service."""
        try:
            payload = {"urls": urls}
            if timeout:
                payload["timeout"] = timeout

            async with self._session.post(
                f"{self.base_url}/fetch/batch",
                json=payload
            ) as resp:
                return await resp.json()
        except Exception as e:
            return {
                "results": [{"url": u, "error": str(e)} for u in urls],
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
            if isinstance(result, Exception):
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
        return await client.fetch(url)


async def fetch_urls(urls: list[str]) -> dict[str, Any]:
    """Fetch multiple URLs."""
    async with URLFetcherClient() as client:
        return await client.fetch_batch(urls)
