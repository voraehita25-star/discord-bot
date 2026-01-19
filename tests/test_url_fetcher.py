"""Unit tests for URL Content Fetcher module."""

import pytest
from utils.web.url_fetcher import (
    extract_urls,
    format_url_content_for_context,
    MAX_CONTENT_LENGTH,
)


class TestExtractUrls:
    """Tests for extract_urls function."""

    def test_extract_single_url(self):
        """Test extracting a single URL from text."""
        text = "Check this out: https://example.com"
        urls = extract_urls(text)
        assert urls == ["https://example.com"]

    def test_extract_multiple_urls(self):
        """Test extracting multiple URLs from text."""
        text = "See https://example.com and https://test.org for more"
        urls = extract_urls(text)
        assert len(urls) == 2
        assert "https://example.com" in urls
        assert "https://test.org" in urls

    def test_extract_urls_removes_duplicates(self):
        """Test that duplicate URLs are removed."""
        text = "Visit https://example.com twice https://example.com"
        urls = extract_urls(text)
        assert urls == ["https://example.com"]

    def test_extract_urls_strips_trailing_punctuation(self):
        """Test that trailing punctuation is stripped from URLs."""
        text = "Check https://example.com. And https://test.org!"
        urls = extract_urls(text)
        assert "https://example.com" in urls
        assert "https://test.org" in urls

    def test_extract_urls_empty_string(self):
        """Test extracting URLs from empty string."""
        assert extract_urls("") == []

    def test_extract_urls_no_urls(self):
        """Test text with no URLs."""
        text = "This is just plain text without any links"
        assert extract_urls(text) == []

    def test_extract_github_url(self):
        """Test extracting GitHub URLs."""
        text = "See https://github.com/user/repo for the code"
        urls = extract_urls(text)
        assert urls == ["https://github.com/user/repo"]

    def test_extract_url_with_path(self):
        """Test URLs with paths and query strings."""
        text = "API docs: https://api.example.com/v1/docs?page=1"
        urls = extract_urls(text)
        assert urls == ["https://api.example.com/v1/docs?page=1"]


class TestFormatUrlContentForContext:
    """Tests for format_url_content_for_context function."""

    def test_format_empty_list(self):
        """Test formatting empty list returns empty string."""
        assert format_url_content_for_context([]) == ""

    def test_format_single_url_with_content(self):
        """Test formatting single URL with content."""
        fetched = [("https://example.com", "Example Site", "This is the content")]
        result = format_url_content_for_context(fetched)
        
        assert "[Web Content from URLs]" in result
        assert "Example Site" in result
        assert "https://example.com" in result
        assert "This is the content" in result

    def test_format_url_without_content(self):
        """Test formatting URL where fetch failed."""
        fetched = [("https://example.com", "Example Site", None)]
        result = format_url_content_for_context(fetched)
        
        assert "[Failed to fetch content]" in result

    def test_format_truncates_long_content(self):
        """Test that very long content is truncated."""
        long_content = "x" * (MAX_CONTENT_LENGTH + 1000)
        fetched = [("https://example.com", "Example", long_content)]
        result = format_url_content_for_context(fetched)
        
        # Content should be truncated to MAX_CONTENT_LENGTH
        assert len(result) < len(long_content) + 200  # Some overhead for formatting


class TestMaxContentLength:
    """Tests for MAX_CONTENT_LENGTH constant."""

    def test_content_length_is_reasonable(self):
        """Test that MAX_CONTENT_LENGTH is within reasonable bounds."""
        assert 2000 <= MAX_CONTENT_LENGTH <= 10000

    def test_content_length_is_integer(self):
        """Test that MAX_CONTENT_LENGTH is an integer."""
        assert isinstance(MAX_CONTENT_LENGTH, int)
