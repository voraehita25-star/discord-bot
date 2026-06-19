"""Regression tests for the logging-ssrf audit-2 group.

Covers the fixed behaviour for:
- py-utils-mon-db-M1: SensitiveDataFilter must redact the FULLY-RENDERED message,
  so ``logger.info("api_key=%s", secret)`` no longer leaks after % interpolation.
- py-utils-mon-db-1: _redact_sensitive must scrub webhook URL tokens and
  URL-embedded passwords (user:pass@host).
- py-utils-mon-db-2: ytdl_source.from_url ImportError fallback must reject a host
  whose AAAA record is private/loopback (getaddrinfo, not gethostbyname).
- py-utils-mon-db-4: search_source must return None (not raise) on an unexpected
  non-DownloadError from the first extract_info.

These assert the REAL fixed behaviour (secret actually redacted / SSRF guard
fires / contract honoured), not just that the code runs.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from utils.monitoring.logger import SensitiveDataFilter, _redact_sensitive


def _make_record(msg: str, args: tuple) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


# --- py-utils-mon-db-M1: rendered-message redaction --------------------------

# 46-char opaque secret with NO sk-/AIza/etc. prefix — only becomes
# keyword-adjacent ("api_key=<secret>") AFTER % interpolation.
_OPAQUE_SECRET = "abcDEF0123456789abcDEF0123456789abcDEF012345"  # 44 chars
_OPAQUE_SECRET_46 = _OPAQUE_SECRET + "AB"  # 46 chars, matches {32,128}


def test_filter_redacts_secret_passed_as_arg_under_keyword_template():
    """logger.info('api_key=%s', secret) must NOT leak the secret."""
    filt = SensitiveDataFilter()
    record = _make_record("api_key=%s", (_OPAQUE_SECRET_46,))

    assert filt.filter(record) is True

    rendered = record.getMessage()
    assert _OPAQUE_SECRET_46 not in rendered, f"secret leaked in rendered message: {rendered!r}"
    assert "[REDACTED]" in rendered


def test_filter_redacts_webhook_url_passed_as_arg():
    """logger.info('posting to %s', webhook_url) must redact the webhook token."""
    filt = SensitiveDataFilter()
    token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-AbCdEfGhIjKlMnOpQrStUvWx"
    webhook = f"https://discord.com/api/webhooks/123456789012345678/{token}"
    record = _make_record("posting alert to %s", (webhook,))

    assert filt.filter(record) is True

    rendered = record.getMessage()
    assert token not in rendered, f"webhook token leaked: {rendered!r}"
    assert "[REDACTED]" in rendered


def test_filter_preserves_non_secret_message():
    """A plain message with no secret must pass through unchanged and keep args."""
    filt = SensitiveDataFilter()
    record = _make_record("processing %s items", (42,))

    assert filt.filter(record) is True
    assert record.getMessage() == "processing 42 items"


# --- py-utils-mon-db-1: webhook + URL-userinfo patterns ----------------------


def test_redact_discord_webhook_url():
    token = "ZZZqwerty_-1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"
    url = f"https://discord.com/api/webhooks/987654321098765432/{token}"
    out = _redact_sensitive(url)
    assert token not in out
    assert "[REDACTED]" in out
    # URL shape (host/path prefix) stays visible for debugging.
    assert "discord.com/api/webhooks/987654321098765432/" in out


def test_redact_discordapp_and_slack_webhook_url():
    for host in ("discordapp.com", "slack.com"):
        token = "tok_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
        url = f"https://{host}/api/webhooks/111222333444555666/{token}"
        out = _redact_sensitive(url)
        assert token not in out, f"{host} token leaked: {out!r}"
        assert "[REDACTED]" in out


def test_redact_url_embedded_password():
    out = _redact_sensitive("postgres://dbuser:p4ssw0rdSecret@db.internal:5432/app")
    assert "p4ssw0rdSecret" not in out
    assert "[REDACTED]" in out
    # Username, scheme and host remain readable.
    assert "postgres://dbuser:" in out
    assert "@db.internal:5432/app" in out


def test_redact_url_userinfo_does_not_touch_plain_url():
    plain = "https://example.com/path?a=b"
    assert _redact_sensitive(plain) == plain


# --- py-utils-mon-db-2: from_url ImportError fallback uses getaddrinfo --------


@pytest.mark.asyncio
async def test_from_url_fallback_rejects_private_aaaa_record():
    """When _is_private_url can't be imported, the fallback must reject a host
    whose getaddrinfo returns a loopback IPv6 address (gethostbyname would miss
    the AAAA record entirely)."""
    import socket as _socket

    from utils.media.ytdl_source import YTDLSource

    # getaddrinfo result tuple shape: (family, type, proto, canonname, sockaddr)
    fake_infos = [
        (_socket.AF_INET6, _socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0)),
    ]

    def fake_getaddrinfo(host, port, *a, **k):
        return fake_infos

    # Force the ImportError fallback branch, then stub getaddrinfo.
    with (
        patch.dict("sys.modules", {"utils.web.url_fetcher": None}),
        patch.object(_socket, "getaddrinfo", side_effect=fake_getaddrinfo),
    ):
        with pytest.raises(ValueError, match="non-public IP"):
            await YTDLSource.from_url("https://evil.example/video", stream=True)


@pytest.mark.asyncio
async def test_from_url_fallback_rejects_ipv4_mapped_loopback():
    """An IPv4-mapped IPv6 loopback (::ffff:127.0.0.1) must be unwrapped and
    rejected, not treated as a benign public IPv6 address."""
    import socket as _socket

    from utils.media.ytdl_source import YTDLSource

    fake_infos = [
        (_socket.AF_INET6, _socket.SOCK_STREAM, 0, "", ("::ffff:127.0.0.1", 0, 0, 0)),
    ]

    with (
        patch.dict("sys.modules", {"utils.web.url_fetcher": None}),
        patch.object(_socket, "getaddrinfo", side_effect=lambda *a, **k: fake_infos),
    ):
        with pytest.raises(ValueError, match="non-public IP"):
            await YTDLSource.from_url("https://evil.example/video", stream=True)


# --- py-utils-mon-db-4: search_source contract (dict|None) -------------------


@pytest.mark.asyncio
async def test_search_source_returns_none_on_unexpected_exception():
    """A non-DownloadError from the first extract_info must be normalized to
    None, not propagated (honors the documented dict|None contract)."""
    from utils.media import ytdl_source
    from utils.media.ytdl_source import YTDLSource

    class _Boom(Exception):
        pass

    class _FakeYTDL:
        def extract_info(self, *a, **k):
            raise _Boom("hostile extractor blew up")

    with patch.object(ytdl_source, "get_ytdl_hq", return_value=_FakeYTDL()):
        result = await YTDLSource.search_source("some normal text query")

    assert result is None
