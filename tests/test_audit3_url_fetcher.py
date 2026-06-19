"""Regression tests for audit3 group E-py-url-fetcher.

Covers:
- py-utils-web-001: IPv4 classification short-circuit in ``_ip_is_blocked``
  (benchmarking / TEST-NET / IETF-protocol ranges previously slipped past the
  IPv6-only gate).
- py-utils-web-002: IPv6 CIDR parity with the Go url_fetcher blocklist.
- py-utils-web-003: ``extract_urls`` single-pass trailing-paren stripping keeps
  balanced-paren URLs intact.
"""

from utils.web.url_fetcher import _ip_is_blocked, extract_urls


class TestIPv4ClassificationBlocked:
    """IPv4 ranges that the explicit CIDR list misses must still be blocked."""

    def test_benchmarking_198_18(self):
        assert _ip_is_blocked("198.18.0.1") is True

    def test_test_net_1_192_0_2(self):
        assert _ip_is_blocked("192.0.2.1") is True

    def test_test_net_3_203_0_113(self):
        assert _ip_is_blocked("203.0.113.1") is True

    def test_ietf_protocol_192_0_0(self):
        assert _ip_is_blocked("192.0.0.1") is True

    def test_loopback_still_blocked(self):
        assert _ip_is_blocked("127.0.0.1") is True

    def test_private_still_blocked(self):
        assert _ip_is_blocked("10.0.0.1") is True

    def test_metadata_still_blocked(self):
        assert _ip_is_blocked("169.254.169.254") is True

    def test_public_ipv4_not_blocked(self):
        # Guard must stay STRICTER but not over-block a normal public host.
        assert _ip_is_blocked("8.8.8.8") is False


class TestIPv6Blocked:
    def test_ietf_protocol_assignments_2001_23(self):
        assert _ip_is_blocked("2001:1::1") is True

    def test_loopback_ipv6(self):
        assert _ip_is_blocked("::1") is True

    def test_nat64_well_known(self):
        assert _ip_is_blocked("64:ff9b::7f00:1") is True

    def test_discard_only_100_64(self):
        assert _ip_is_blocked("100::1") is True

    def test_public_ipv6_not_blocked(self):
        assert _ip_is_blocked("2606:4700:4700::1111") is False


class TestIPv4MappedClassification:
    def test_mapped_test_net_blocked(self):
        # ::ffff:192.0.2.1 — mapped TEST-NET must not dodge the block.
        assert _ip_is_blocked("::ffff:192.0.2.1") is True

    def test_mapped_loopback_blocked(self):
        assert _ip_is_blocked("::ffff:127.0.0.1") is True


class TestExtractUrlsParenBalance:
    def test_balanced_paren_preserved(self):
        text = "See https://en.wikipedia.org/wiki/Python_(programming_language) here"
        assert extract_urls(text) == ["https://en.wikipedia.org/wiki/Python_(programming_language)"]

    def test_unbalanced_trailing_paren_stripped(self):
        text = "(see https://example.com)"
        assert extract_urls(text) == ["https://example.com"]

    def test_trailing_sentence_punctuation_stripped(self):
        text = "Go to https://example.com/page."
        assert extract_urls(text) == ["https://example.com/page"]

    def test_balanced_paren_with_trailing_period(self):
        text = "ref https://en.wikipedia.org/wiki/Foo_(bar)."
        assert extract_urls(text) == ["https://en.wikipedia.org/wiki/Foo_(bar)"]

    def test_double_unbalanced_paren(self):
        text = "((https://example.com/x))"
        assert extract_urls(text) == ["https://example.com/x"]
