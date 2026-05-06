"""Tests for the SSRF / IP-block helpers in utils.web.url_fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from utils.web import url_fetcher as uf


class TestIpIsBlocked:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "127.5.5.5",
            "10.0.0.1",
            "192.168.1.1",
            "172.16.0.1",
            "169.254.169.254",  # AWS metadata
            "0.0.0.0",
            "::1",
            "fe80::1",
        ],
    )
    def test_blocks_private_ips(self, ip):
        assert uf._ip_is_blocked(ip) is True

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
    def test_allows_public_ips(self, ip):
        assert uf._ip_is_blocked(ip) is False

    def test_invalid_ip_blocked(self):
        # Unparseable IP defaults to blocked for safety.
        assert uf._ip_is_blocked("not-an-ip") is True
        assert uf._ip_is_blocked("") is True

    def test_blocks_ipv4_mapped_ipv6_loopback(self):
        # ::ffff:127.0.0.1 unwraps to 127.0.0.1 — must be blocked even when
        # served via AAAA so an attacker can't bypass the IPv4 loopback rule.
        assert uf._ip_is_blocked("::ffff:127.0.0.1") is True

    def test_blocks_ipv4_mapped_ipv6_private(self):
        assert uf._ip_is_blocked("::ffff:10.0.0.1") is True


@pytest.mark.asyncio
class TestIsPrivateUrl:
    async def test_blocks_file_scheme(self):
        assert await uf._is_private_url("file:///etc/passwd") is True

    async def test_blocks_gopher_scheme(self):
        assert await uf._is_private_url("gopher://example.com/") is True

    async def test_blocks_javascript_scheme(self):
        assert await uf._is_private_url("javascript:alert(1)") is True

    async def test_blocks_ftp_scheme(self):
        assert await uf._is_private_url("ftp://example.com/file") is True

    async def test_blocks_data_scheme(self):
        assert await uf._is_private_url("data:text/html,<h1>x</h1>") is True

    async def test_blocks_dns_failure(self):
        # DNS failure should result in block (fail-closed for safety).
        with patch("utils.web.url_fetcher.asyncio.wait_for", new=AsyncMock(side_effect=TimeoutError())):
            assert await uf._is_private_url("https://nonexistent.invalid") is True

    async def test_blocks_loopback_dns(self):
        # A real getaddrinfo for "localhost" will resolve to 127.0.0.1 — blocked.
        result = await uf._is_private_url("https://localhost/")
        assert result is True

    async def test_blocks_missing_hostname(self):
        # URLs with no hostname (e.g. "https://") are blocked.
        result = await uf._is_private_url("https://")
        assert result is True


class TestExtractUrlsExtra:
    def test_keeps_query_string(self):
        urls = uf.extract_urls("see https://example.com/path?q=hello&n=1")
        assert urls == ["https://example.com/path?q=hello&n=1"]

    def test_keeps_fragment(self):
        urls = uf.extract_urls("see https://example.com/page#section")
        assert urls == ["https://example.com/page#section"]

    def test_empty_input(self):
        assert uf.extract_urls("") == []
        assert uf.extract_urls(None) == []  # type: ignore[arg-type]

    def test_dedups_in_order(self):
        urls = uf.extract_urls(
            "https://a.example.com and again https://a.example.com plus https://b.example.com"
        )
        assert urls == ["https://a.example.com", "https://b.example.com"]


class TestFormatUrlContentExtra:
    def test_returns_empty_for_empty_list(self):
        assert uf.format_url_content_for_context([]) == ""

    def test_includes_failure_marker(self):
        out = uf.format_url_content_for_context([("https://broken.example", "Title", None)])
        assert "Failed to fetch" in out
        assert "https://broken.example" in out

    def test_includes_title_and_url(self):
        out = uf.format_url_content_for_context(
            [("https://x.example", "Title X", "Hello body")]
        )
        assert "Title X" in out
        assert "https://x.example" in out
        assert "Hello body" in out

    def test_truncates_long_content(self):
        long_body = "x" * (uf.MAX_CONTENT_LENGTH * 2)
        out = uf.format_url_content_for_context([("https://big.example", "Big", long_body)])
        # Truncated to MAX_CONTENT_LENGTH plus formatting overhead.
        assert len(out) < uf.MAX_CONTENT_LENGTH * 2
