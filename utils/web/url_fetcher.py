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
from bs4 import BeautifulSoup, FeatureNotFound

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
_session_lock: asyncio.Lock | None = None  # constructed on first use

# URL content cache: url -> (title, content, timestamp)
_url_cache: dict[str, tuple[str, str | None, float]] = {}
_url_cache_lock: asyncio.Lock | None = None  # constructed on first use
_URL_CACHE_TTL = 300.0  # 5 minutes
_URL_CACHE_MAX_SIZE = 100


def _get_session_lock() -> asyncio.Lock:
    """Lazily construct the asyncio.Lock so it binds to the running loop.

    Building it at module-import time can attach the lock to a stale loop
    (or fail outright on Python ≤ 3.9) when this module is imported before
    the bot's event loop starts.
    """
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


def _get_url_cache_lock() -> asyncio.Lock:
    """Lazily construct the URL-cache lock — same rationale as session lock."""
    global _url_cache_lock
    if _url_cache_lock is None:
        _url_cache_lock = asyncio.Lock()
    return _url_cache_lock


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
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[aiohttp.abc.ResolveResult]:
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
                        host,
                        ip_str,
                    )
                    raise OSError(f"SSRF blocked: {host} resolves to private IP {ip_str}")
        return addrs

    async def close(self) -> None:
        await self._base.close()


async def _get_shared_session() -> aiohttp.ClientSession:
    """Get or create a shared aiohttp session with connection pooling.

    The previous double-checked pattern (outer check before the lock,
    re-check inside) had a subtle hole: between the outer ``closed`` check
    returning False and the body returning ``_shared_session``, another
    coroutine could call ``close_shared_session`` and close+null the
    global, after which the caller would receive a closed session and
    every request would raise. Performing the check + recreate + return
    entirely inside the lock closes that window. The lock contention is
    cheap because the body only runs work on the (rare) first/recreate
    path; the common-case ``return`` is just a coroutine context switch.
    """
    global _shared_session
    async with _get_session_lock():
        if _shared_session is None or _shared_session.closed:
            resolver = _SSRFSafeResolver(aiohttp.ThreadedResolver())
            connector = aiohttp.TCPConnector(
                limit=20,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                resolver=resolver,
            )
            # ``trust_env=False`` ignores ``HTTP_PROXY``/``HTTPS_PROXY``
            # / ``NO_PROXY`` env vars on the request path. Without it,
            # a proxy set in the host environment would route requests
            # through the proxy IP — bypassing the SSRF resolver above
            # (the resolver checks the destination DNS, but the proxy
            # connect handshake hits the proxy IP first, which the
            # resolver never sees). Hardening: refuse to honour
            # process-environment proxy hints.
            _shared_session = aiohttp.ClientSession(
                connector=connector, trust_env=False
            )
        return _shared_session


async def close_shared_session() -> None:
    """Close the shared session. Call during bot shutdown."""
    global _shared_session
    async with _get_session_lock():
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
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local + AWS/Azure/GCP metadata
    ipaddress.ip_network("0.0.0.0/8"),  # Current network
    ipaddress.ip_network("100.64.0.0/10"),  # Shared address space (CGN)
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("224.0.0.0/4"),  # IPv4 multicast
    ipaddress.ip_network("240.0.0.0/4"),  # IPv4 reserved future
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    # IPv4-mapped IPv6 covers ::ffff:0:0/96 — closes the bypass where an
    # attacker-controlled DNS returns ::ffff:127.0.0.1 to dodge the IPv4
    # blocks above. We additionally call ip.ipv4_mapped below as belt-and-
    # suspenders in case ipaddress treats the mapped form differently across
    # Python versions.
    ipaddress.ip_network("::ffff:0:0/96"),
]

# Allowlist of URL schemes the fetcher will follow. Anything else (file://,
# gopher://, dict://, ldap://, ftp://, javascript:, data:) is rejected at
# both the initial URL and at every redirect target.
_ALLOWED_URL_SCHEMES = {"http", "https"}


def _ip_is_blocked(ip_str: str) -> bool:
    """Return True if ``ip_str`` falls in any blocked network.

    Handles IPv4-mapped IPv6 explicitly: ``::ffff:127.0.0.1`` is unwrapped
    via ``ipv4_mapped`` and re-checked against the IPv4 blocklist so an
    attacker can't bypass loopback/private-network blocks by serving
    AAAA records pointing at the mapped form.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    for network in _BLOCKED_NETWORKS:
        if ip in network:
            return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        for network in _BLOCKED_NETWORKS:
            if ip.ipv4_mapped in network:
                return True
    return False


async def _is_private_url(url: str) -> bool:
    """Check if a URL resolves to a private/internal IP address (SSRF protection).

    Also enforces the scheme allowlist — only ``http``/``https`` URLs are
    permitted. Returns True (block) for anything else so redirect chains
    can't escape into ``file://``, ``gopher://``, ``dict://``, ``ldap://``,
    ``ftp://``, ``javascript:``, or ``data:``.
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
            logger.warning("SSRF blocked: disallowed scheme %r in %s", parsed.scheme, url)
            return True
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
            # sockaddr[0] is always a str host for AF_INET/AF_INET6 from
            # getaddrinfo, but the typeshed stub types it as str | int because
            # AF_NETLINK uses an int. Coerce explicitly so the SSRF block
            # path can rely on a str.
            ip_str = str(sockaddr[0])
            if _ip_is_blocked(ip_str):
                logger.warning("SSRF blocked: %s resolves to %s (blocked)", url, ip_str)
                return True

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
        session: DEPRECATED — ignored. The function now always uses the
            shared session (with SSRF-safe resolver). A caller-supplied
            session may not have the resolver attached, opening a DNS
            rebinding window between the static _is_private_url check and
            the actual connect, so we no longer accept it.
        timeout: Request timeout in seconds

    Returns:
        Tuple of (title, content) - content is None if fetch failed
    """
    if session is not None:
        logger.debug(
            "fetch_url_content: ignoring caller-supplied session; using shared SSRF-safe session"
        )
        session = None
    try:
        # Check URL cache first (under lock to prevent duplicate fetches)
        import time as _time

        async with _get_url_cache_lock():
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
        # Use parsed hostname (not substring) so attacker domains like
        # `github.com.evil.com` don't trigger the API rewrite path.
        from urllib.parse import urlparse as _urlparse

        try:
            _parsed_url = _urlparse(url)
            _host = (_parsed_url.hostname or "").lower()
        except (ValueError, TypeError):
            _host = ""
        if _host == "github.com" or _host.endswith(".github.com"):
            # Convert github.com URLs to raw content for README
            if _host == "github.com" and "/blob/" not in url and "/raw/" not in url:
                # Try to get README
                if not url.endswith("/"):
                    url += "/"
                # GitHub API for repo info — rebuild via urlparse so we only
                # touch the hostname, never a substring of the full URL.
                _re_parsed = _urlparse(url)
                api_url = _re_parsed._replace(
                    netloc="api.github.com",
                    path="/repos" + (_re_parsed.path or "/"),
                ).geturl()
                api_url = api_url.rstrip("/")

                # Re-check SSRF on transformed URL
                if await _is_private_url(api_url):
                    logger.warning(
                        "Blocked SSRF attempt on transformed GitHub API URL: %s", api_url
                    )
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
                                    # Guard the slice — if ``content`` is
                                    # already >= MAX_CONTENT_LENGTH the
                                    # subtraction goes negative and Python's
                                    # ``s[:-n]`` strips from the END instead
                                    # of returning empty. ``max(0, ...)``
                                    # gives the empty-slice semantics we want.
                                    remaining = max(0, MAX_CONTENT_LENGTH - len(content))
                                    content += f"\n--- README ---\n{readme_text[:remaining]}"

                            result_content = content[:MAX_CONTENT_LENGTH]
                            # Cache GitHub result
                            async with _get_url_cache_lock():
                                if len(_url_cache) >= _URL_CACHE_MAX_SIZE:
                                    oldest_key = next(iter(_url_cache))
                                    del _url_cache[oldest_key]
                                _url_cache[url] = (title, result_content, _time.time())
                            return title, result_content
                except Exception as e:
                    logger.debug("GitHub API failed for %s: %s", url, e)

        # Standard webpage fetch — disable auto-redirects and check each
        # target for SSRF. Each session.get() opens a connection that holds
        # a slot in the pool until the response is closed; we collect every
        # opened response in ``responses`` and close all of them in a
        # ``finally`` block. The previous code closed the *previous*
        # response just before issuing the next request, which left a
        # window where an exception (TimeoutError, SSRF block, etc.) could
        # leak the most recently opened response. Holding strong refs in
        # one list and closing them all unconditionally eliminates that.
        responses: list[aiohttp.ClientResponse] = []
        try:
            initial = await session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=False,
            )
            responses.append(initial)
            final_response = initial
            redirect_count = 0
            visited_urls: set[str] = {url}

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
                next_resp = await session.get(
                    redirect_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=False,
                )
                responses.append(next_resp)
                final_response = next_resp

            if final_response.status != 200:
                logger.warning("URL fetch failed: %s (status %d)", url, final_response.status)
                return url, None

            content_type = final_response.headers.get("Content-Type", "")
            # Parse only the MIME portion (strip charset/boundary) and
            # match exactly. The previous substring check accepted
            # ``application/text/html-weird``-style values that contain
            # ``text/html`` as a substring; harmless for downstream
            # consumers but a non-zero attack surface for content-type
            # smuggling.
            primary_mime = content_type.split(";", 1)[0].strip().lower()

            # Only process HTML/text content
            if primary_mime not in ("text/html", "text/plain"):
                return url, f"[Non-text content: {content_type}]"

            # Early rejection if Content-Length exceeds limit (avoids wasting bandwidth)
            content_length = final_response.headers.get("Content-Length")
            if (
                content_length
                and content_length.isdigit()
                and int(content_length) > MAX_RESPONSE_SIZE
            ):
                logger.warning("URL content too large: %s (%s bytes)", url, content_length)
                return url, f"[Content too large: {content_length} bytes]"

            # Handle encoding with fallback, size-limited to prevent memory
            # exhaustion. Read one byte past the cap so a body that overflows
            # the limit is distinguishable from one exactly at it — when the
            # server sent no/incorrect Content-Length, reject rather than
            # silently parse a truncated half-document.
            raw_bytes = await final_response.content.read(MAX_RESPONSE_SIZE + 1)
            if len(raw_bytes) > MAX_RESPONSE_SIZE:
                logger.warning(
                    "URL content exceeded %d bytes (streamed, no/!Content-Length): %s",
                    MAX_RESPONSE_SIZE,
                    url,
                )
                return url, f"[Content too large: >{MAX_RESPONSE_SIZE} bytes]"
            # Magic-byte check: even when the server claims text/html,
            # the body may be binary (PDF, ZIP, image, executable). The
            # latin-1 fallback would happily decode garbage and feed it
            # to BeautifulSoup. Reject obvious binaries here.
            if (
                raw_bytes[:5] in (b"%PDF-",)
                or raw_bytes[:4]
                in (
                    b"PK\x03\x04",  # ZIP
                    b"\x7fELF",  # ELF
                    b"MZ\x90\x00",  # PE/COFF Windows .exe (partial)
                )
                or (len(raw_bytes) >= 2 and raw_bytes[:2] == b"MZ")
            ):
                return url, f"[Binary content despite Content-Type={content_type}]"
            try:
                encoding = final_response.get_encoding()
                html = raw_bytes.decode(encoding or "utf-8")
            except (UnicodeDecodeError, LookupError):
                # Fallback to latin-1 which accepts all byte values
                html = raw_bytes.decode("latin-1", errors="replace")

            # Parse HTML. Prefer ``lxml`` for speed, fall back to the
            # stdlib ``html.parser`` if lxml isn't installed in the
            # deployment env. Without the fallback, ``FeatureNotFound``
            # bubbled up as an opaque error and the whole URL fetch
            # failed instead of degrading to slower-but-working parsing.
            try:
                soup = BeautifulSoup(html, "lxml")
            except FeatureNotFound:
                soup = BeautifulSoup(html, "html.parser")

            # Get title. ``get_text(strip=True)`` on a present-but-empty
            # ``<title></title>`` returns ``""`` which the previous code
            # accepted — leaving the embed with an empty title. Fall back
            # to the URL whenever the extracted title is falsy.
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            title = title or url

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

            # Store in URL cache.
            # Eviction is FIFO (oldest by INSERTION time), not access-time
            # LRU — ``_url_cache`` is a ``dict``/``OrderedDict`` whose
            # iteration order matches insertion. A read of an existing key
            # does NOT move it to the end. Hot URLs can therefore be
            # evicted before stale ones; if access-time LRU becomes
            # important later, switch to ``move_to_end`` on read.
            async with _get_url_cache_lock():
                if len(_url_cache) >= _URL_CACHE_MAX_SIZE:
                    oldest_key = next(iter(_url_cache))
                    del _url_cache[oldest_key]
                _url_cache[url] = (title, cleaned_content, _time.time())

            return title, cleaned_content
        finally:
            # Close every response we opened. ``ClientResponse.close()`` is
            # idempotent and safe even if the connection has already been
            # released, so closing the same response twice is a no-op.
            for resp in responses:
                try:
                    resp.close()
                except Exception:
                    pass

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

    # ``fetch_url_content`` ignores its ``session`` argument (it always
    # uses the SSRF-safe shared session internally). Don't pre-fetch one
    # here just to throw it away.
    tasks = [fetch_url_content(url) for url in urls_to_fetch]
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
