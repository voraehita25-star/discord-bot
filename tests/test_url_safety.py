"""Unit Tests for Music URL Safety (SSRF guards).

Covers cogs/music/url_safety.py: scheme/host validation, literal-IP and
non-canonical IPv4 SSRF guards, loopback hostname blocking, and the async
DNS-resolution wrapper. All tests are hermetic — DNS resolution is
monkeypatched so no real network access occurs.
"""

from __future__ import annotations


class TestSchemeValidation:
    """is_url_query_safe: scheme handling."""

    def test_https_public_host_ok(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("https://www.youtube.com/watch?v=abc")

        assert ok is True
        assert reason == ""

    def test_http_public_host_ok(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://example.com/song.mp3")

        assert ok is True
        assert reason == ""

    def test_scheme_case_insensitive(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("HTTPS://example.com/")

        assert ok is True
        assert reason == ""

    def test_file_scheme_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("file:///etc/passwd")

        assert ok is False
        assert reason != ""

    def test_ftp_scheme_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("ftp://example.com/file")

        assert ok is False
        assert "http" in reason

    def test_no_scheme_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # Plain search text (no ://) has empty scheme and is rejected here.
        ok, reason = is_url_query_safe("never gonna give you up")

        assert ok is False
        assert reason != ""

    def test_empty_string_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("")

        assert ok is False
        assert reason != ""


class TestHostValidation:
    """is_url_query_safe: host presence and loopback names."""

    def test_missing_host_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # https with no host (urlparse yields empty hostname)
        ok, reason = is_url_query_safe("https:///path/only")

        assert ok is False
        assert "host" in reason

    def test_localhost_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://localhost/admin")

        assert ok is False
        assert reason != ""

    def test_localhost_trailing_dot_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # Trailing dot is normalised away, so the loopback name still matches.
        ok, reason = is_url_query_safe("http://localhost./admin")

        assert ok is False
        assert reason != ""

    def test_localhost_uppercase_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://LOCALHOST/admin")

        assert ok is False
        assert reason != ""

    def test_localhost_localdomain_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://localhost.localdomain/")

        assert ok is False
        assert reason != ""

    def test_ip6_localhost_name_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://ip6-localhost/")

        assert ok is False
        assert reason != ""


class TestLiteralIpv4Guards:
    """is_url_query_safe: canonical IPv4 literal SSRF targets."""

    def test_loopback_ip_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://127.0.0.1/")

        assert ok is False
        assert reason != ""

    def test_private_10_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://10.0.0.5/internal")

        assert ok is False
        assert reason != ""

    def test_private_192_168_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://192.168.1.1/router")

        assert ok is False
        assert reason != ""

    def test_link_local_metadata_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # AWS/cloud metadata endpoint (link-local).
        ok, reason = is_url_query_safe("http://169.254.169.254/latest/meta-data/")

        assert ok is False
        assert reason != ""

    def test_unspecified_0_0_0_0_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://0.0.0.0/")

        assert ok is False
        assert reason != ""

    def test_public_literal_ip_ok(self):
        from cogs.music.url_safety import is_url_query_safe

        # A public, routable literal IP must pass the synchronous check.
        ok, reason = is_url_query_safe("http://8.8.8.8/")

        assert ok is True
        assert reason == ""


class TestLiteralIpv6Guards:
    """is_url_query_safe: IPv6 literal SSRF targets."""

    def test_ipv6_loopback_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        ok, reason = is_url_query_safe("http://[::1]/")

        assert ok is False
        assert reason != ""

    def test_ipv6_mapped_loopback_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # IPv4-mapped IPv6 form of 127.0.0.1 must be unwrapped and rejected.
        ok, reason = is_url_query_safe("http://[::ffff:127.0.0.1]/")

        assert ok is False
        assert reason != ""

    def test_ipv6_public_ok(self):
        from cogs.music.url_safety import is_url_query_safe

        # Public Google DNS IPv6 — routable, should pass sync check.
        ok, reason = is_url_query_safe("http://[2001:4860:4860::8888]/")

        assert ok is True
        assert reason == ""


class TestAltFormIpv4Guards:
    """is_url_query_safe: non-canonical IPv4 literals that bypass ipaddress."""

    def test_hex_loopback_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # 0x7f000001 == 127.0.0.1 to the OS resolver.
        ok, reason = is_url_query_safe("http://0x7f000001/")

        assert ok is False
        assert reason != ""

    def test_decimal_loopback_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # 2130706433 == 127.0.0.1 (single 32-bit decimal).
        ok, reason = is_url_query_safe("http://2130706433/")

        assert ok is False
        assert reason != ""

    def test_short_form_loopback_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # 127.1 expands to 127.0.0.1 (class-A short form).
        ok, reason = is_url_query_safe("http://127.1/")

        assert ok is False
        assert reason != ""

    def test_octal_loopback_rejected(self):
        from cogs.music.url_safety import is_url_query_safe

        # 0177.0.0.1 == 127.0.0.1 (leading-zero octal octet).
        ok, reason = is_url_query_safe("http://0177.0.0.1/")

        assert ok is False
        assert reason != ""


class TestInternalHelpers:
    """Direct coverage of the private helpers."""

    def test_ip_is_private_loopback(self):
        from cogs.music.url_safety import _ip_is_private

        assert _ip_is_private("127.0.0.1") is True

    def test_ip_is_private_private_range(self):
        from cogs.music.url_safety import _ip_is_private

        assert _ip_is_private("10.1.2.3") is True

    def test_ip_is_private_public(self):
        from cogs.music.url_safety import _ip_is_private

        assert _ip_is_private("8.8.8.8") is False

    def test_ip_is_private_invalid_returns_false(self):
        from cogs.music.url_safety import _ip_is_private

        # Not an IP at all — helper returns False (no crash).
        assert _ip_is_private("not-an-ip") is False

    def test_ip_is_private_ipv4_mapped(self):
        from cogs.music.url_safety import _ip_is_private

        assert _ip_is_private("::ffff:127.0.0.1") is True

    def test_normalize_host_lowercases_and_strips_dots(self):
        from cogs.music.url_safety import _normalize_host

        assert _normalize_host("LocalHost..") == "localhost"

    def test_normalize_host_handles_empty(self):
        from cogs.music.url_safety import _normalize_host

        assert _normalize_host("") == ""

    def test_normalize_host_strips_whitespace(self):
        from cogs.music.url_safety import _normalize_host

        assert _normalize_host("  Example.COM  ") == "example.com"

    def test_parse_alt_ipv4_hex(self):
        from cogs.music.url_safety import _parse_alt_ipv4

        assert _parse_alt_ipv4("0x7f000001") == "127.0.0.1"

    def test_parse_alt_ipv4_decimal(self):
        from cogs.music.url_safety import _parse_alt_ipv4

        assert _parse_alt_ipv4("2130706433") == "127.0.0.1"

    def test_parse_alt_ipv4_short_form(self):
        from cogs.music.url_safety import _parse_alt_ipv4

        assert _parse_alt_ipv4("127.1") == "127.0.0.1"

    def test_parse_alt_ipv4_non_ip_returns_none(self):
        from cogs.music.url_safety import _parse_alt_ipv4

        assert _parse_alt_ipv4("example.com") is None

    def test_parse_alt_ipv4_empty_returns_none(self):
        from cogs.music.url_safety import _parse_alt_ipv4

        assert _parse_alt_ipv4("") is None


class TestResolveAndCheckSync:
    """_resolve_and_check_sync: DNS-answer vetting (monkeypatched)."""

    def _make_addrinfo(self, ip: str):
        # getaddrinfo returns 5-tuples; index [4] is the sockaddr.
        import socket

        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]

    def test_public_resolution_ok(self, monkeypatch):
        from cogs.music import url_safety

        monkeypatch.setattr(
            url_safety.socket,
            "getaddrinfo",
            lambda *a, **k: self._make_addrinfo("93.184.216.34"),
        )

        ok, reason = url_safety._resolve_and_check_sync("example.com")

        assert ok is True
        assert reason == ""

    def test_private_resolution_rejected(self, monkeypatch):
        from cogs.music import url_safety

        # Attacker DNS that points a public name at a private IP.
        monkeypatch.setattr(
            url_safety.socket,
            "getaddrinfo",
            lambda *a, **k: self._make_addrinfo("10.0.0.1"),
        )

        ok, reason = url_safety._resolve_and_check_sync("evil.example.com")

        assert ok is False
        assert reason != ""

    def test_dns_failure_conservative_reject(self, monkeypatch):
        import socket

        from cogs.music import url_safety

        def _boom(*a, **k):
            raise socket.gaierror("no such host")

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _boom)

        ok, reason = url_safety._resolve_and_check_sync("does-not-exist.invalid")

        assert ok is False
        assert reason != ""


class TestIsUrlQuerySafeAsync:
    """is_url_query_safe_async: literal short-circuit + DNS wrapper."""

    async def test_rejects_bad_scheme_without_dns(self, monkeypatch):
        from cogs.music import url_safety

        def _should_not_call(*a, **k):
            raise AssertionError("DNS resolution must not run for a bad scheme")

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _should_not_call)

        ok, reason = await url_safety.is_url_query_safe_async("file:///etc/passwd")

        assert ok is False
        assert reason != ""

    async def test_literal_public_ip_short_circuits(self, monkeypatch):
        from cogs.music import url_safety

        def _should_not_call(*a, **k):
            raise AssertionError("literal IPs must not trigger DNS resolution")

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _should_not_call)

        ok, reason = await url_safety.is_url_query_safe_async("http://8.8.8.8/")

        assert ok is True
        assert reason == ""

    async def test_alt_form_literal_short_circuits(self, monkeypatch):
        from cogs.music import url_safety

        # 0x7f000001 is a literal (alt-form) loopback: rejected by the sync
        # pass, and DNS must not be consulted.
        def _should_not_call(*a, **k):
            raise AssertionError("alt-form literal IPs must not trigger DNS")

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _should_not_call)

        ok, reason = await url_safety.is_url_query_safe_async("http://0x7f000001/")

        assert ok is False
        assert reason != ""

    async def test_dns_host_public_ok(self, monkeypatch):
        import socket

        from cogs.music import url_safety

        def _fake(*a, **k):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
            ]

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake)

        ok, reason = await url_safety.is_url_query_safe_async("https://example.com/song")

        assert ok is True
        assert reason == ""

    async def test_dns_host_private_rejected(self, monkeypatch):
        import socket

        from cogs.music import url_safety

        def _fake(*a, **k):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.0.10", 0))
            ]

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake)

        ok, reason = await url_safety.is_url_query_safe_async("https://rebind.example.com/")

        assert ok is False
        assert reason != ""

    async def test_dns_timeout_rejected(self, monkeypatch):
        from cogs.music import url_safety

        async def _slow_to_thread(func, *args, **kwargs):
            import asyncio

            await asyncio.sleep(10)  # never completes within the timeout
            return func(*args, **kwargs)

        monkeypatch.setattr(url_safety.asyncio, "to_thread", _slow_to_thread)

        ok, reason = await url_safety.is_url_query_safe_async(
            "https://slow.example.com/", resolve_timeout=0.01
        )

        assert ok is False
        assert "timeout" in reason.lower()

    async def test_public_alt_form_literal_short_circuits(self, monkeypatch):
        from cogs.music import url_safety

        # 134744072 is the single-decimal alt-form of the PUBLIC IP 8.8.8.8.
        # It passes the synchronous check (not private), is NOT a canonical
        # ipaddress literal (so ipaddress.ip_address raises -> is_literal_ip
        # stays False), but _parse_alt_ipv4 recognises it -> the alt-form
        # branch flips is_literal_ip back to True, so DNS must NOT be consulted.
        def _should_not_call(*a, **k):
            raise AssertionError("public alt-form literal IPs must not trigger DNS")

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _should_not_call)

        ok, reason = await url_safety.is_url_query_safe_async("http://134744072/")

        assert ok is True
        assert reason == ""


class TestEdgeCases:
    """Coverage of the urlparse-failure and empty-sockaddr defensive branches."""

    def test_invalid_ipv6_url_raises_caught(self):
        from cogs.music.url_safety import is_url_query_safe

        # An unterminated IPv6 bracket makes urlparse raise ValueError
        # ("Invalid IPv6 URL"); the helper must catch it and reject cleanly.
        ok, reason = is_url_query_safe("http://[::1")

        assert ok is False
        assert reason == "URL ที่ใส่มาไม่ถูกต้อง"

    def test_resolve_skips_empty_sockaddr_entry(self, monkeypatch):
        import socket

        from cogs.music import url_safety

        # First addrinfo entry has a falsy sockaddr (index [4]) and must be
        # skipped via `continue`; the second is a public IP, so the overall
        # result is OK.
        def _fake(*a, **k):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ()),
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
            ]

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake)

        ok, reason = url_safety._resolve_and_check_sync("example.com")

        assert ok is True
        assert reason == ""
