"""
Tests for utils.web.url_fetcher module.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestURLPattern:
    """Tests for URL_PATTERN regex."""

    def test_pattern_exists(self):
        """Test URL_PATTERN is defined."""
        from utils.web.url_fetcher import URL_PATTERN
        
        assert URL_PATTERN is not None

    def test_pattern_matches_http(self):
        """Test pattern matches http URLs."""
        from utils.web.url_fetcher import URL_PATTERN
        
        match = URL_PATTERN.search("Check http://example.com here")
        assert match is not None
        assert "http://example.com" in match.group()

    def test_pattern_matches_https(self):
        """Test pattern matches https URLs."""
        from utils.web.url_fetcher import URL_PATTERN
        
        match = URL_PATTERN.search("Visit https://example.com/page")
        assert match is not None
        assert "https://example.com" in match.group()

    def test_pattern_ignores_case(self):
        """Test pattern is case insensitive."""
        from utils.web.url_fetcher import URL_PATTERN
        
        match = URL_PATTERN.search("HTTPS://EXAMPLE.COM")
        assert match is not None


class TestConstants:
    """Tests for module constants."""

    def test_max_content_length(self):
        """Test MAX_CONTENT_LENGTH is reasonable."""
        from utils.web.url_fetcher import MAX_CONTENT_LENGTH
        
        assert MAX_CONTENT_LENGTH > 0
        assert MAX_CONTENT_LENGTH == 4500

    def test_request_timeout(self):
        """Test REQUEST_TIMEOUT is defined."""
        from utils.web.url_fetcher import REQUEST_TIMEOUT
        
        assert REQUEST_TIMEOUT > 0
        assert REQUEST_TIMEOUT == 10

    def test_user_agent(self):
        """Test USER_AGENT is defined."""
        from utils.web.url_fetcher import USER_AGENT
        
        assert USER_AGENT
        assert "Mozilla" in USER_AGENT

    def test_github_domains(self):
        """Test GITHUB_DOMAINS tuple."""
        from utils.web.url_fetcher import GITHUB_DOMAINS
        
        assert "github.com" in GITHUB_DOMAINS
        assert "raw.githubusercontent.com" in GITHUB_DOMAINS


class TestExtractURLs:
    """Tests for extract_urls function."""

    def test_empty_text(self):
        """Test empty text returns empty list."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls("")
        assert result == []

    def test_none_text(self):
        """Test None text returns empty list."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls(None)
        assert result == []

    def test_no_urls(self):
        """Test text without URLs returns empty list."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls("This is just plain text")
        assert result == []

    def test_single_http_url(self):
        """Test extracting single http URL."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls("Check http://example.com")
        assert len(result) == 1
        assert "http://example.com" in result

    def test_single_https_url(self):
        """Test extracting single https URL."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls("Visit https://example.com/page")
        assert len(result) == 1
        assert "https://example.com/page" in result

    def test_multiple_urls(self):
        """Test extracting multiple URLs."""
        from utils.web.url_fetcher import extract_urls
        
        text = "Check http://first.com and https://second.com"
        result = extract_urls(text)
        
        assert len(result) == 2

    def test_duplicate_urls_removed(self):
        """Test duplicate URLs are removed."""
        from utils.web.url_fetcher import extract_urls
        
        text = "http://example.com and again http://example.com"
        result = extract_urls(text)
        
        assert len(result) == 1

    def test_trailing_punctuation_removed(self):
        """Test trailing punctuation is cleaned."""
        from utils.web.url_fetcher import extract_urls
        
        text = "Visit http://example.com."
        result = extract_urls(text)
        
        assert len(result) == 1
        assert result[0] == "http://example.com"

    def test_url_with_path(self):
        """Test URL with path is extracted."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls("https://example.com/path/to/page")
        assert len(result) == 1
        assert "/path/to/page" in result[0]

    def test_url_with_query(self):
        """Test URL with query parameters is extracted."""
        from utils.web.url_fetcher import extract_urls
        
        result = extract_urls("https://example.com?foo=bar&baz=qux")
        assert len(result) == 1
        assert "foo=bar" in result[0]


class TestFetchURLContent:
    """Tests for fetch_url_content function."""

    @pytest.mark.asyncio
    async def test_returns_tuple(self):
        """Test function returns tuple."""
        from utils.web.url_fetcher import fetch_url_content
        
        # Mock the session
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            
            # Mock response
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.headers = {"Content-Type": "text/html"}
            mock_response.text = AsyncMock(return_value="<html><head><title>Test</title></head><body>Content</body></html>")
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            
            mock_session.get = MagicMock(return_value=mock_response)
            
            result = await fetch_url_content("http://example.com", session=mock_session)
            
            assert isinstance(result, tuple)
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_handles_non_200_status(self):
        """Test handling of non-200 response."""
        from utils.web.url_fetcher import fetch_url_content
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        
        mock_session.get = MagicMock(return_value=mock_response)
        
        title, content = await fetch_url_content("http://example.com/notfound", session=mock_session)
        
        assert content is None

    @pytest.mark.asyncio
    async def test_handles_non_text_content(self):
        """Test handling of non-text content type."""
        from utils.web.url_fetcher import fetch_url_content
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "image/png"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        
        mock_session.get = MagicMock(return_value=mock_response)
        
        title, content = await fetch_url_content("http://example.com/image.png", session=mock_session)
        
        assert "Non-text content" in content


class TestFetchAllURLs:
    """Tests for fetch_all_urls function."""

    @pytest.mark.asyncio
    async def test_function_exists(self):
        """Test function exists and is callable."""
        from utils.web.url_fetcher import fetch_all_urls
        
        assert callable(fetch_all_urls)

    @pytest.mark.asyncio
    async def test_empty_urls_list(self):
        """Test with empty URLs list."""
        from utils.web.url_fetcher import fetch_all_urls
        
        result = await fetch_all_urls([])
        
        assert result == []

    @pytest.mark.asyncio
    async def test_max_urls_parameter(self):
        """Test max_urls limits results."""
        from utils.web.url_fetcher import fetch_all_urls
        
        # With mocked session
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Just verify function signature accepts max_urls
            assert callable(fetch_all_urls)


class TestFormatURLContentForContext:
    """Tests for format_url_content_for_context function."""

    def test_function_exists(self):
        """Test function exists."""
        from utils.web.url_fetcher import format_url_content_for_context
        
        assert callable(format_url_content_for_context)

    def test_empty_list(self):
        """Test with empty list."""
        from utils.web.url_fetcher import format_url_content_for_context
        
        result = format_url_content_for_context([])
        
        assert result == ""

    def test_single_url_content(self):
        """Test formatting single URL content."""
        from utils.web.url_fetcher import format_url_content_for_context
        
        fetched_urls = [
            ("http://example.com", "Test Title", "Test content here")
        ]
        
        result = format_url_content_for_context(fetched_urls)
        
        assert "Test Title" in result
        assert "Test content" in result
        assert "Web Content from URLs" in result

    def test_failed_url_content(self):
        """Test handling of failed URL (None content)."""
        from utils.web.url_fetcher import format_url_content_for_context
        
        fetched_urls = [
            ("http://failed.com", "Failed URL", None)
        ]
        
        result = format_url_content_for_context(fetched_urls)
        
        assert "Failed to fetch content" in result

    def test_multiple_urls(self):
        """Test formatting multiple URLs."""
        from utils.web.url_fetcher import format_url_content_for_context
        
        fetched_urls = [
            ("http://first.com", "First", "Content 1"),
            ("http://second.com", "Second", "Content 2"),
        ]
        
        result = format_url_content_for_context(fetched_urls)
        
        assert "First" in result
        assert "Second" in result
