"""Regression tests for audit-2 group ``aicore-misc``.

Covers two confirmed findings:

* ``py-aicore-core-resp-M1`` — ``AI.on_guild_channel_delete`` must call
  ``reset_channel_session`` in CLI mode so a deleted channel's Claude
  ``--resume`` session entry and its on-disk ``.jsonl`` transcript are torn
  down (data-retention / disk-leak symmetry with ``!reset_ai``).
* ``py-aicore-api-3`` — the PROXY endpoint display label must not echo an
  embedded basic-auth credential (``user:pass@host``) that flows out to
  dashboard WS clients via ``get_status()``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_cog():
    """Create an AI cog with ChatManager and rate_limiter patched out.

    Mirrors the helper in ``test_ai_cog_coverage.py`` so the construction
    matches the rest of the suite.
    """
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        cm.get_chat_session = AsyncMock(return_value=None)
        cm.chats = {}
        cm.seen_users = {}
        cm.last_accessed = {}
        cm.processing_locks = {}
        cm.streaming_enabled = {}
        cm._message_queue = MagicMock()
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


# ---------------------------------------------------------------------------
# py-aicore-core-resp-M1 — on_guild_channel_delete CLI session teardown
# ---------------------------------------------------------------------------


class TestOnGuildChannelDeleteResetsCliSession:
    @pytest.mark.asyncio
    async def test_resets_cli_session_when_cli_mode(self):
        """In CLI mode the deleted channel's session must be reset."""
        cog = _make_cog()
        cog.chat_manager.cli_mode = True
        cid = 424242

        channel = MagicMock()
        channel.id = cid
        with (
            patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete"),
            patch("cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session") as reset,
        ):
            await cog.on_guild_channel_delete(channel)

        # The real fixed behavior: the deleted channel's CLI session (and its
        # on-disk .jsonl transcript) is unlinked exactly once for this id.
        reset.assert_called_once_with(cid)

    @pytest.mark.asyncio
    async def test_does_not_reset_session_when_not_cli_mode(self):
        """Outside CLI mode there is no session to tear down — skip it."""
        cog = _make_cog()
        cog.chat_manager.cli_mode = False
        cid = 515151

        channel = MagicMock()
        channel.id = cid
        with (
            patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete"),
            patch("cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session") as reset,
        ):
            await cog.on_guild_channel_delete(channel)

        reset.assert_not_called()


# ---------------------------------------------------------------------------
# py-aicore-api-3 — proxy label must not echo basic-auth credentials
# ---------------------------------------------------------------------------


class TestProxyDisplayHostRedactsUserinfo:
    def test_strips_userinfo_from_authority_url(self):
        from cogs.ai_core.api.api_failover import _proxy_display_host

        out = _proxy_display_host("https://user:pass@proxy.example.com")
        assert out == "proxy.example.com"
        assert "user" not in out
        assert "pass" not in out
        assert "@" not in out

    def test_strips_userinfo_but_keeps_port(self):
        from cogs.ai_core.api.api_failover import _proxy_display_host

        out = _proxy_display_host("https://user:pass@proxy.example.com:8443")
        assert out == "proxy.example.com:8443"
        assert ":pass@" not in out

    def test_plain_url_unchanged(self):
        from cogs.ai_core.api.api_failover import _proxy_display_host

        assert _proxy_display_host("https://proxy.example.com") == "proxy.example.com"

    def test_bare_host_without_scheme_strips_userinfo(self):
        from cogs.ai_core.api.api_failover import _proxy_display_host

        # urlsplit only fills netloc when a '//' authority is present; the
        # fallback path must still drop the userinfo.
        assert _proxy_display_host("user:pass@proxy.example.com") == "proxy.example.com"

    def test_built_proxy_label_does_not_leak_creds_to_status(self, monkeypatch):
        """End-to-end: a credentialed proxy base must not surface creds in the
        label that get_status() broadcasts to dashboard WS clients."""
        from cogs.ai_core.api import api_failover as mod

        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_PROXY_API_KEY", "proxy-key-xyz")
        monkeypatch.setenv("ANTHROPIC_PROXY_BASE_URL", "https://user:s3cr3t@proxy.example.com")
        # Avoid any DIRECT/legacy endpoint interfering with the assertion.
        monkeypatch.delenv("ANTHROPIC_DIRECT_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        manager = mod.APIFailoverManager()
        manager.initialize()

        status = manager.get_status()
        labels = [ep["label"] for ep in status["endpoints"]]
        assert any("proxy.example.com" in lbl for lbl in labels)
        for lbl in labels:
            assert "s3cr3t" not in lbl
            assert "user:" not in lbl
            assert "@" not in lbl
