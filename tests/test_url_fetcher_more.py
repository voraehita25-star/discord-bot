"""
Extended tests for URL Fetcher module.
Tests URL extraction and content fetching functions.
"""

import re

import pytest


class TestUrlPatternConstant:
    """Tests for URL_PATTERN regex constant."""

    def test_url_pattern_exists(self):
        """Test URL_PATTERN is defined."""
        from utils.web.url_fetcher import URL_PATTERN

        assert URL_PATTERN is not None

    def test_url_pattern_is_compiled_regex(self):
        """Test URL_PATTERN is a compiled regex."""
        from utils.web.url_fetcher import URL_PATTERN

        assert isinstance(URL_PATTERN, re.Pattern)

    def test_url_pattern_matches_http(self):
        """Test URL_PATTERN matches http URLs."""
        from utils.web.url_fetcher import URL_PATTERN

        match = URL_PATTERN.search("Check http://example.com/test")
        assert match is not None
        assert "http://example.com/test" in match.group()

    def test_url_pattern_matches_https(self):
        """Test URL_PATTERN matches https URLs."""
        from utils.web.url_fetcher import URL_PATTERN

        match = URL_PATTERN.search("Check https://example.com/test")
        assert match is not None
        assert "https://example.com/test" in match.group()


class TestMaxContentLength:
    """Tests for MAX_CONTENT_LENGTH constant."""

    def test_max_content_length_exists(self):
        """Test MAX_CONTENT_LENGTH is defined."""
        from utils.web.url_fetcher import MAX_CONTENT_LENGTH

        assert MAX_CONTENT_LENGTH is not None

    def test_max_content_length_is_int(self):
        """Test MAX_CONTENT_LENGTH is an integer."""
        from utils.web.url_fetcher import MAX_CONTENT_LENGTH

        assert isinstance(MAX_CONTENT_LENGTH, int)

    def test_max_content_length_is_positive(self):
        """Test MAX_CONTENT_LENGTH is positive."""
        from utils.web.url_fetcher import MAX_CONTENT_LENGTH

        assert MAX_CONTENT_LENGTH > 0


class TestRequestTimeout:
    """Tests for REQUEST_TIMEOUT constant."""

    def test_request_timeout_exists(self):
        """Test REQUEST_TIMEOUT is defined."""
        from utils.web.url_fetcher import REQUEST_TIMEOUT

        assert REQUEST_TIMEOUT is not None

    def test_request_timeout_is_int(self):
        """Test REQUEST_TIMEOUT is an integer."""
        from utils.web.url_fetcher import REQUEST_TIMEOUT

        assert isinstance(REQUEST_TIMEOUT, int)


class TestUserAgent:
    """Tests for USER_AGENT constant."""

    def test_user_agent_exists(self):
        """Test USER_AGENT is defined."""
        from utils.web.url_fetcher import USER_AGENT

        assert USER_AGENT is not None

    def test_user_agent_is_string(self):
        """Test USER_AGENT is a string."""
        from utils.web.url_fetcher import USER_AGENT

        assert isinstance(USER_AGENT, str)

    def test_user_agent_contains_browser_info(self):
        """Test USER_AGENT contains browser info."""
        from utils.web.url_fetcher import USER_AGENT

        assert "Mozilla" in USER_AGENT or "Chrome" in USER_AGENT


class TestGithubDomains:
    """Tests for GITHUB_DOMAINS constant."""

    def test_github_domains_exists(self):
        """Test GITHUB_DOMAINS is defined."""
        from utils.web.url_fetcher import GITHUB_DOMAINS

        assert GITHUB_DOMAINS is not None

    def test_github_domains_is_tuple(self):
        """Test GITHUB_DOMAINS is a tuple."""
        from utils.web.url_fetcher import GITHUB_DOMAINS

        assert isinstance(GITHUB_DOMAINS, tuple)

    def test_github_domains_contains_github(self):
        """Test GITHUB_DOMAINS contains github.com."""
        from utils.web.url_fetcher import GITHUB_DOMAINS

        assert "github.com" in GITHUB_DOMAINS


class TestExtractUrls:
    """Tests for extract_urls function."""

    def test_extract_urls_empty_string(self):
        """Test extract_urls with empty string."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("")
        assert result == []

    def test_extract_urls_none(self):
        """Test extract_urls with None."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls(None)
        assert result == []

    def test_extract_urls_single(self):
        """Test extract_urls with single URL."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("Check this: https://example.com")
        assert len(result) == 1
        assert "https://example.com" in result

    def test_extract_urls_multiple(self):
        """Test extract_urls with multiple URLs."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("https://one.com and https://two.com")
        assert len(result) == 2

    def test_extract_urls_removes_duplicates(self):
        """Test extract_urls removes duplicates."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("https://example.com and https://example.com")
        assert len(result) == 1

    def test_extract_urls_strips_trailing_punctuation(self):
        """Test extract_urls strips trailing punctuation."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("Check https://example.com.")
        assert "https://example.com" in result
        assert not any(url.endswith(".") for url in result)

    def test_extract_urls_no_urls(self):
        """Test extract_urls with no URLs."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("Just some text without URLs")
        assert result == []


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test url_fetcher module has docstring."""
        from utils.web import url_fetcher

        assert url_fetcher.__doc__ is not None


class TestExtractUrlsPreservesOrder:
    """Tests for URL extraction order preservation."""

    def test_preserves_first_occurrence_order(self):
        """Test that URL order is preserved."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("https://first.com then https://second.com")
        assert result[0] == "https://first.com"
        assert result[1] == "https://second.com"


class TestExtractUrlsEdgeCases:
    """Tests for extract_urls edge cases."""

    def test_url_with_query_params(self):
        """Test URL with query parameters."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("https://example.com/page?param=value")
        assert len(result) == 1

    def test_url_with_fragment(self):
        """Test URL with fragment."""
        from utils.web.url_fetcher import extract_urls

        result = extract_urls("https://example.com/page#section")
        assert len(result) == 1


class TestFetchUrlContentSignature:
    """Tests for fetch_url_content function signature."""

    @pytest.mark.asyncio
    async def test_fetch_url_content_is_async(self):
        """Test fetch_url_content is async function."""
        import asyncio

        from utils.web.url_fetcher import fetch_url_content

        # Should be a coroutine function
        assert asyncio.iscoroutinefunction(fetch_url_content)
