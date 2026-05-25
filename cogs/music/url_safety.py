"""SSRF guards for music URL queries.

The ``!play`` command accepts free text — yt-dlp interprets text with
``://`` as a URL and HAPPILY fetches whatever scheme is given, including
``file://``, ``http://169.254.169.254/`` (AWS metadata), ``http://localhost/``,
and similar dangerous internal addresses.

``is_url_query_safe`` rejects anything that is not a plain http(s) URL
pointing at a public host. Search queries with no ``://`` are caller-side
filtered before reaching this helper and are not validated here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Final
from urllib.parse import urlparse

_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


def _ip_is_private(ip_str: str) -> bool:
    """Return True for any address we never want yt-dlp to dial."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped  # type: ignore[assignment]
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _normalize_host(host: str) -> str:
    """Normalise a hostname for allowlist comparison.

    Strips trailing dots (``localhost.`` resolves to the same IP as
    ``localhost``) and lower-cases so allowlist checks aren't bypassed
    by case toggles or trailing-dot tricks.
    """
    h = (host or "").lower().strip()
    while h.endswith("."):
        h = h[:-1]
    return h


def _parse_alt_ipv4(host: str) -> str | None:
    """Return the dotted-quad form of a non-canonical IPv4 literal, or None.

    glibc ``inet_aton`` (and on most platforms ``getaddrinfo``) accepts
    a number of legacy IPv4 syntaxes that ``ipaddress.ip_address``
    rejects, including:

    * ``0x7f000001``        — single 32-bit hex
    * ``2130706433``        — single 32-bit decimal
    * ``0177.0.0.1``        — leading-zero octets (octal)
    * ``127.1``             — class-A short form (1 implies the bottom 24)

    An attacker can spoof these to bypass a naive ``ipaddress.ip_address``
    check and have the OS resolver still target 127.0.0.1 / 169.254.169.254
    / etc. Use ``socket.inet_aton`` (which mirrors the OS's accept rules
    on Linux) to extract the canonical 4-byte form so the standard
    ``_ip_is_private`` branch can vet it.
    """
    if not host:
        return None
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return ".".join(str(b) for b in packed)


def is_url_query_safe(query: str) -> tuple[bool, str]:
    """Validate that a user-supplied URL is safe to hand to yt-dlp.

    Returns a tuple ``(ok, reason)``. ``reason`` is empty on success and a
    short user-facing string when rejection happens.
    """
    try:
        parsed = urlparse(query)
    except (ValueError, TypeError):
        return False, "URL ที่ใส่มาไม่ถูกต้อง"

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False, f"รองรับเฉพาะ http/https ไม่ใช่ {scheme!r}"

    host = _normalize_host(parsed.hostname or "")
    if not host:
        return False, "URL ไม่มี host"

    # Direct-IP host: reject any private/loopback/link-local target before
    # yt-dlp performs DNS itself. DNS-based hosts cannot be cheaply
    # resolved synchronously here without blocking the event loop; yt-dlp
    # will dial whatever the OS resolver returns. The downstream
    # ``url_fetcher`` resolver-level guard is the broader defense — this
    # function blocks the obvious literal-IP exfil cases.
    if any(ch.isdigit() for ch in host) or ":" in host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if _ip_is_private(host):
                return False, "host เป็นเครือข่ายภายใน/ไม่อนุญาต"

    # Non-canonical IPv4 forms (``0x7f000001``, ``2130706433``, ``127.1``,
    # ``0177.0.0.1``) bypass ``ipaddress.ip_address`` but the OS resolver
    # still treats them as 127.0.0.1 / etc. Use ``inet_aton`` to coerce
    # them to canonical dotted-quad so ``_ip_is_private`` can vet.
    canonical_ipv4 = _parse_alt_ipv4(host)
    if canonical_ipv4 and _ip_is_private(canonical_ipv4):
        return False, "host เป็นเครือข่ายภายใน (alt-form IPv4)"

    # Block obvious loopback hostnames too — DNS might resolve them to
    # 127.0.0.1 / ::1, which the IP branch above can't catch without a
    # blocking lookup. The set covers ``localhost.localdomain`` (some
    # Linux distros' default) on top of the bare names.
    if host in {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
    }:
        return False, "host เป็น loopback"

    return True, ""


def _resolve_and_check_sync(host: str) -> tuple[bool, str]:
    """Resolve ``host`` and check that every answer is publicly routable.

    Blocking — must run in a worker thread. Returns ``(ok, reason)``.
    A DNS failure here is conservative-fail (rejects the URL); a real
    site usually resolves, and refusing on transient DNS hiccups is
    safer than letting an attacker's host get one good answer through.
    """
    try:
        results = socket.getaddrinfo(
            host, None, proto=socket.IPPROTO_TCP, type=socket.SOCK_STREAM
        )
    except (socket.gaierror, OSError, UnicodeError) as exc:
        return False, f"resolve ไม่สำเร็จ: {exc.__class__.__name__}"
    seen_private = False
    for entry in results:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        addr = sockaddr[0]
        if _ip_is_private(addr):
            seen_private = True
            break
    if seen_private:
        return False, "host เครือข่ายภายในจาก DNS"
    return True, ""


async def is_url_query_safe_async(
    query: str, *, resolve_timeout: float = 2.0
) -> tuple[bool, str]:
    """Async wrapper: literal-IP/scheme check + DNS-resolution check.

    Adds a thread-pool DNS resolution pass so attacker-controlled DNS
    that points to private IPs is rejected before yt-dlp dials. Times
    out after ``resolve_timeout`` seconds; on timeout we conservatively
    refuse the URL rather than let the loop hang.
    """
    ok, reason = is_url_query_safe(query)
    if not ok:
        return ok, reason

    parsed = urlparse(query)
    host = _normalize_host(parsed.hostname or "")
    # If the host is a literal IP (canonical OR alt-form like 0x7f000001),
    # the synchronous pass above already checked it — no DNS needed.
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False
    if not is_literal_ip and _parse_alt_ipv4(host):
        is_literal_ip = True
    if is_literal_ip:
        return True, ""

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_resolve_and_check_sync, host), timeout=resolve_timeout
        )
    except TimeoutError:
        return False, "DNS timeout"
