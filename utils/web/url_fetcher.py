"""
URL Content Fetcher Module.
Extracts and fetches content from URLs in user messages for AI context.
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import logging
import re
import socket
from typing import TYPE_CHECKING

import aiohttp
import yarl
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    pass

# Import centralized timeout constant
try:
    from cogs.ai_core.data.constants import HTTP_REQUEST_TIMEOUT
except ImportError:
    HTTP_REQUEST_TIMEOUT = 10  # Fallback default

logger = logging.getLogger(__name__)

# Shared session for connection pooling (lazily initialized)
_shared_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()

# URL content cache: url -> (title, content, timestamp)
_url_cache: dict[str, tuple[str, str | None, float]] = {}
_url_cache_lock = asyncio.Lock()
_URL_CACHE_TTL = 300.0  # 5 minutes
_URL_CACHE_MAX_SIZE = 100


class _SSRFSafeResolver(aiohttp.abc.AbstractResolver):
    """Resolver wrapper that rejects any host resolving to a private IP.

    Defense-in-depth against DNS rebinding: `_is_private_url` checks once at
    request-entry, but aiohttp re-resolves at connect time. Without this
    wrapper an attacker-controlled DNS could return a public IP for the first
    lookup (bypassing the pre-check) and a private IP for the second
    (reaching internal services). Enforcing the SSRF policy inside aiohttp's
    own resolver closes that TOCTOU window.
    """

    def __init__(self, base: aiohttp.abc.AbstractResolver) -> None:
        self._base = base

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[dict]:
        addrs = await self._base.resolve(host, port, family)
        for addr in addrs:
            ip_str = addr.get("host")
            if not ip_str:
                continue
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    logger.warning(
                        "SSRF blocked at connect time: %s -> private IP %s",
                        host, ip_str,
                    )
                    raise OSError(
                        f"SSRF blocked: {host} resolves to private IP {ip_str}"
                    )
        return addrs

    async def close(self) -> None:
        await self._base.close()


async def _get_shared_session() -> aiohttp.ClientSession:
    """Get or create a shared aiohttp session with connection pooling."""
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        async with _session_lock:
            if _shared_session is None or _shared_session.closed:
                resolver = _SSRFSafeResolver(aiohttp.ThreadedResolver())
                connector = aiohttp.TCPConnector(
                    limit=20,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True,
                    resolver=resolver,
                )
                _shared_session = aiohttp.ClientSession(connector=connector)
    return _shared_session


async def close_shared_session() -> None:
    """Close the shared session. Call during bot shutdown."""
    global _shared_session
    async with _session_lock:
        if _shared_session is not None and not _shared_session.closed:
            await _shared_session.close()
        _shared_session = None


# URL pattern - matches http/https URLs
URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

# Maximum content length per URL (characters)
# Balanced between context and preventing Gemini silent blocks
MAX_CONTENT_LENGTH = 4500

# Maximum response body size (bytes) to prevent memory exhaustion
MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB

# Request timeout in seconds (from centralized constants)
REQUEST_TIMEOUT = HTTP_REQUEST_TIMEOUT

# User agent for requests
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Domains that need special handling
GITHUB_DOMAINS = ("github.com", "raw.githubusercontent.com")

# Blocked private/internal IP ranges for SSRF protection
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),      # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),     # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("100.64.0.0/10"),      # Shared address space (CGN)
    ipaddress.ip_network("100.100.100.200/32"), # Alibaba Cloud metadata
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


async def _is_private_url(url: str) -> bool:
    """Check if a URL resolves to a private/internal IP address (SSRF protection)."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True

        # Resolve hostname to IP - use executor to avoid blocking the event loop
        try:
            loop = asyncio.get_running_loop()
            addr_info = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    functools.partial(
                        socket.getaddrinfo, hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
                    ),
                ),
                timeout=5.0,  # Prevent indefinite hang on slow DNS
            )
        except (socket.gaierror, TimeoutError):
            return True  # Block on DNS resolution failure/timeout for safety

        for _family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        logger.warning("SSRF blocked: %s resolves to private IP %s", url, ip_str)
                        return True
            except ValueError:
                continue

        return False
    except Exception:
        return True  # Block on any error for safety


def extract_urls(text: str) -> list[str]:
    """
    Extract URLs from text.

    Args:
        text: Input text containing URLs

    Returns:
        List of unique URLs found in text
    """
    if not text:
        return []

    urls = URL_PATTERN.findall(text)
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        # Clean trailing punctuation
        url = url.rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls


async def fetch_url_content(
    url: str,
    session: aiohttp.ClientSession | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> tuple[str, str | None]:
    """
    Fetch and extract main content from a URL.

    Args:
        url: URL to fetch
        session: Optional aiohttp session to reuse
        timeout: Request timeout in seconds

    Returns:
        Tuple of (title, content) - content is None if fetch failed
    """
    try:
        # Check URL cache first (under lock to prevent duplicate fetches)
        import time as _time

        async with _url_cache_lock:
            cached = _url_cache.get(url)
            if cached is not None:
                title, content, ts = cached
                if _time.time() - ts < _URL_CACHE_TTL:
                    logger.debug("URL cache hit: %s", url)
                    return title, content
                else:
                    del _url_cache[url]

        # SSRF protection: block private/internal IPs
        if await _is_private_url(url):
            logger.warning("Blocked SSRF attempt to private URL: %s", url)
            return url, None

        if session is None:
            session = await _get_shared_session()

        headers = {"User-Agent": USER_AGENT}

        # Special handling for GitHub
        if any(domain in url for domain in GITHUB_DOMAINS):
            # Convert github.com URLs to raw content for README
            if "github.com" in url and "/blob/" not in url and "/raw/" not in url:
                # Try to get README
                if not url.endswith("/"):
                    url += "/"
                # GitHub API for repo info
                api_url = url.replace("github.com", "api.github.com/repos")
                api_url = api_url.rstrip("/")

                # Re-check SSRF on transformed URL
                if await _is_private_url(api_url):
                    logger.warning("Blocked SSRF attempt on transformed GitHub API URL: %s", api_url)
                    return url, None

                try:
                    async with session.get(
                        api_url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            title = data.get("full_name", url)
                            description = data.get("description", "")
                            language = data.get("language", "Unknown")
                            stars = data.get("stargazers_count", 0)
                            forks = data.get("forks_count", 0)

                            content = f"""Repository: {title}
Description: {description}
Language: {language}
Stars: {stars} | Forks: {forks}

Topics: {", ".join(data.get("topics", []))}
Default Branch: {data.get("default_branch", "main")}
"""
                            # Try to get README
                            readme_url = f"{api_url}/readme"
                            async with session.get(
                                readme_url,
                                headers={**headers, "Accept": "application/vnd.github.raw"},
                                timeout=aiohttp.ClientTimeout(total=timeout),
                            ) as readme_resp:
                                if readme_resp.status == 200:
                                    readme_text = await readme_resp.text()
                                    content += f"\n--- README ---\n{readme_text[: MAX_CONTENT_LENGTH - len(content)]}"

                            result_content = content[:MAX_CONTENT_LENGTH]
                            # Cache GitHub result
                            async with _url_cache_lock:
                                if len(_url_cache) >= _URL_CACHE_MAX_SIZE:
                                    oldest_key = next(iter(_url_cache))
                                    del _url_cache[oldest_key]
                                _url_cache[url] = (title, result_content, _time.time())
                            return title, result_content
                except Exception as e:
                    logger.debug("GitHub API failed for %s: %s", url, e)

        # Standard webpage fetch — disable auto-redirects and check each target for SSRF
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=False,
        ) as response:
            # Manually follow redirects with SSRF check on each target
            final_response = response
            redirect_count = 0
            visited_urls: set[str] = {url}
            try:
                while final_response.status in (301, 302, 303, 307, 308) and redirect_count < 5:
                    redirect_url = final_response.headers.get("Location")
                    if not redirect_url:
                        break
                    # Resolve relative URLs
                    redirect_url = str(final_response.url.join(yarl.URL(redirect_url)))
                    if redirect_url in visited_urls:
                        logger.warning("Blocked circular redirect: %s", redirect_url)
                        return url, None
                    if await _is_private_url(redirect_url):
                        logger.warning("Blocked SSRF: redirect to private URL: %s", redirect_url)
                        return url, None
                    visited_urls.add(redirect_url)
                    redirect_count += 1
                    # Close previous redirect response to avoid resource leak
                    if final_response is not response:
                        final_response.close()
                    try:
                        final_response = await session.get(
                            redirect_url,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=timeout),
                            allow_redirects=False,
                        )
                    except Exception:
                        # Reset to original so finally doesn't double-close
                        final_response = response
                        raise

                if final_response.status != 200:
                    logger.warning("URL fetch failed: %s (status %d)", url, final_response.status)
                    return url, None

                content_type = final_response.headers.get("Content-Type", "")

                # Only process HTML/text content
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return url, f"[Non-text content: {content_type}]"

                # Early rejection if Content-Length exceeds limit (avoids wasting bandwidth)
                content_length = final_response.headers.get("Content-Length")
                if content_length and content_length.isdigit() and int(content_length) > MAX_RESPONSE_SIZE:
                    logger.warning("URL content too large: %s (%s bytes)", url, content_length)
                    return url, f"[Content too large: {content_length} bytes]"

                # Handle encoding with fallback, size-limited to prevent memory exhaustion
                try:
                    raw_bytes = await final_response.content.read(MAX_RESPONSE_SIZE)
                    encoding = final_response.get_encoding()
                    html = raw_bytes.decode(encoding or 'utf-8')
                except (UnicodeDecodeError, LookupError):
                    # Fallback to latin-1 which accepts all byte values
                    html = raw_bytes.decode('latin-1', errors='replace')

                # Parse HTML
                soup = BeautifulSoup(html, "lxml")

                # Get title
                title_tag = soup.find("title")
                title = title_tag.get_text(strip=True) if title_tag else url

                # Remove script, style, nav, footer elements
                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                    tag.decompose()

                # Try to find main content
                main_content = None

                # Look for main content containers
                for selector in [
                    "article",
                    "main",
                    '[role="main"]',
                    ".content",
                    "#content",
                    ".post-content",
                ]:
                    element = soup.select_one(selector)
                    if element:
                        main_content = element.get_text(separator="\n", strip=True)
                        break

                # Fallback to body
                if not main_content:
                    body = soup.find("body")
                    if body:
                        main_content = body.get_text(separator="\n", strip=True)
                    else:
                        main_content = soup.get_text(separator="\n", strip=True)

                # Clean up whitespace
                lines = [line.strip() for line in main_content.split("\n") if line.strip()]
                cleaned_content = "\n".join(lines)

                # Truncate if too long
                if len(cleaned_content) > MAX_CONTENT_LENGTH:
                    cleaned_content = cleaned_content[:MAX_CONTENT_LENGTH] + "\n[Content truncated...]"

                # Store in URL cache
                async with _url_cache_lock:
                    if len(_url_cache) >= _URL_CACHE_MAX_SIZE:
                        # Evict oldest entry
                        oldest_key = next(iter(_url_cache))
                        del _url_cache[oldest_key]
                    _url_cache[url] = (title, cleaned_content, _time.time())

                return title, cleaned_content
            finally:
                # Ensure redirect responses (not managed by `async with`) are closed
                if final_response is not response:
                    final_response.close()

    except TimeoutError:
        logger.warning("URL fetch timeout: %s", url)
        return url, None
    except aiohttp.ClientError as e:
        logger.warning("URL fetch error for %s: %s", url, e)
        return url, None
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", url, e)
        return url, None


async def fetch_all_urls(urls: list[str], max_urls: int = 3) -> list[tuple[str, str, str | None]]:
    """
    Fetch content from multiple URLs concurrently.

    Args:
        urls: List of URLs to fetch
        max_urls: Maximum number of URLs to process

    Returns:
        List of (url, title, content) tuples
    """
    if not urls:
        return []

    # Limit number of URLs
    urls_to_fetch = urls[:max_urls]

    session = await _get_shared_session()
    tasks = [fetch_url_content(url, session) for url in urls_to_fetch]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    fetched: list[tuple[str, str, str | None]] = []
    for url, result in zip(urls_to_fetch, results, strict=False):
        if isinstance(result, BaseException):
            logger.warning("Failed to fetch %s: %s", url, result)
            fetched.append((url, url, None))
        elif isinstance(result, tuple) and len(result) == 2:
            title, content = result
            fetched.append((url, title, content))
        else:
            # Unexpected result type
            fetched.append((url, url, None))

    return fetched


def format_url_content_for_context(fetched_urls: list[tuple[str, str, str | None]]) -> str:
    """
    Format fetched URL content for injection into AI context.

    Args:
        fetched_urls: List of (url, title, content) tuples

    Returns:
        Formatted string for AI context
    """
    if not fetched_urls:
        return ""

    parts = ["[Web Content from URLs]"]

    for url, title, content in fetched_urls:
        if content:
            # Truncate very long content to prevent context overflow
            truncated = (
                content[:MAX_CONTENT_LENGTH] if len(content) > MAX_CONTENT_LENGTH else content
            )
            parts.append(f"\n--- {title} ({url}) ---")
            parts.append(truncated)
            logger.debug(
                "URL content size: %d chars (truncated: %s)",
                len(content),
                len(content) > MAX_CONTENT_LENGTH,
            )
        else:
            parts.append(f"\n--- {url} ---")
            parts.append("[Failed to fetch content]")

    return "\n".join(parts)
