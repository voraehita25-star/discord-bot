"""
URL Content Fetcher Module.
Extracts and fetches content from URLs in user messages for AI context.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import aiohttp
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# URL pattern - matches http/https URLs
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)

# Maximum content length per URL (characters)
# Balanced between context and preventing Gemini silent blocks
MAX_CONTENT_LENGTH = 4500

# Request timeout in seconds
REQUEST_TIMEOUT = 10

# User agent for requests
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Domains that need special handling
GITHUB_DOMAINS = ("github.com", "raw.githubusercontent.com")


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
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
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

Topics: {', '.join(data.get('topics', []))}
Default Branch: {data.get('default_branch', 'main')}
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
                                    content += f"\n--- README ---\n{readme_text[:MAX_CONTENT_LENGTH - len(content)]}"

                            return title, content[:MAX_CONTENT_LENGTH]
                except Exception as e:
                    logger.debug("GitHub API failed for %s: %s", url, e)

        # Standard webpage fetch
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                logger.warning("URL fetch failed: %s (status %d)", url, response.status)
                return url, None

            content_type = response.headers.get("Content-Type", "")

            # Only process HTML/text content
            if "text/html" not in content_type and "text/plain" not in content_type:
                return url, f"[Non-text content: {content_type}]"

            html = await response.text()

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
            for selector in ["article", "main", '[role="main"]', ".content", "#content", ".post-content"]:
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

            return title, cleaned_content

    except asyncio.TimeoutError:
        logger.warning("URL fetch timeout: %s", url)
        return url, None
    except aiohttp.ClientError as e:
        logger.warning("URL fetch error for %s: %s", url, e)
        return url, None
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", url, e)
        return url, None
    finally:
        if close_session:
            await session.close()


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

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url_content(url, session) for url in urls_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    fetched = []
    for url, result in zip(urls_to_fetch, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("Failed to fetch %s: %s", url, result)
            fetched.append((url, url, None))
        else:
            title, content = result
            fetched.append((url, title, content))

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
            truncated = content[:MAX_CONTENT_LENGTH] if len(content) > MAX_CONTENT_LENGTH else content
            parts.append(f"\n--- {title} ({url}) ---")
            parts.append(truncated)
            logger.debug("URL content size: %d chars (truncated: %s)", len(content), len(content) > MAX_CONTENT_LENGTH)
        else:
            parts.append(f"\n--- {url} ---")
            parts.append("[Failed to fetch content]")

    return "\n".join(parts)
