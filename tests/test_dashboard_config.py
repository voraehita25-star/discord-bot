"""
Tests for cogs/ai_core/api/dashboard_config.py module.

This module computes all of its public constants at *import time* from the
process environment, so the tests exercise its behavior by reloading the
module under a patched (and cleared) ``os.environ``. Each test cleans up by
reloading the module a final time so the session-wide singleton is left in a
sane, default state for other test files.
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

MODULE = "cogs.ai_core.api.dashboard_config"


def _reload(env: dict[str, str]):
    """Reload dashboard_config with ``os.environ`` cleared then set to ``env``.

    ``api_failover.initialize`` is patched to a no-op so that reloading in
    ``api`` backend mode never touches the network or instantiates a real
    Anthropic client.
    """
    import cogs.ai_core.api.dashboard_config as dc

    with patch.dict(os.environ, env, clear=True):
        with patch("cogs.ai_core.api.api_failover.api_failover.initialize"):
            return importlib.reload(dc)


@pytest.fixture(autouse=True)
def _restore_module():
    """Restore the module to a clean default state after each test."""
    yield
    _reload({"CLAUDE_BACKEND": "cli"})


class TestIntEnv:
    """Tests for the _int_env helper."""

    def test_returns_int_from_valid_env(self):
        from cogs.ai_core.api.dashboard_config import _int_env

        with patch.dict(os.environ, {"DC_TEST_INT": "42"}):
            assert _int_env("DC_TEST_INT", 0) == 42

    def test_returns_default_when_missing(self):
        from cogs.ai_core.api.dashboard_config import _int_env

        with patch.dict(os.environ, {}, clear=True):
            assert _int_env("DC_NOPE", 999) == 999

    def test_returns_default_on_empty_string(self):
        from cogs.ai_core.api.dashboard_config import _int_env

        with patch.dict(os.environ, {"DC_TEST_INT": ""}):
            assert _int_env("DC_TEST_INT", 50) == 50

    def test_returns_default_on_invalid_int(self):
        from cogs.ai_core.api.dashboard_config import _int_env

        with patch.dict(os.environ, {"DC_TEST_INT": "not_a_number"}):
            assert _int_env("DC_TEST_INT", 100) == 100

    def test_parses_negative_int(self):
        from cogs.ai_core.api.dashboard_config import _int_env

        with patch.dict(os.environ, {"DC_TEST_INT": "-7"}):
            assert _int_env("DC_TEST_INT", 0) == -7

    def test_invalid_int_logs_warning(self, caplog):
        import logging

        from cogs.ai_core.api.dashboard_config import _int_env

        with patch.dict(os.environ, {"DC_TEST_INT": "abc"}):
            with caplog.at_level(logging.WARNING, logger=MODULE):
                assert _int_env("DC_TEST_INT", 5) == 5
        assert any("not a valid integer" in rec.message for rec in caplog.records)


class TestWebSocketDefaults:
    """Default values for the WebSocket configuration block."""

    def test_default_host_and_port(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.WS_HOST == "127.0.0.1"
        assert m.WS_PORT == 8765

    def test_default_require_tls_is_false(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.WS_REQUIRE_TLS is False

    def test_custom_port_parsed(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "WS_DASHBOARD_PORT": "9000"})
        assert m.WS_PORT == 9000

    def test_invalid_port_falls_back_to_default(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "WS_DASHBOARD_PORT": "abc"})
        assert m.WS_PORT == 8765

    @pytest.mark.parametrize("raw", ["true", "1", "yes", "TRUE", "Yes"])
    def test_require_tls_truthy_values(self, raw):
        m = _reload({"CLAUDE_BACKEND": "cli", "WS_REQUIRE_TLS": raw})
        assert m.WS_REQUIRE_TLS is True

    @pytest.mark.parametrize("raw", ["false", "0", "no", "", "anything"])
    def test_require_tls_falsey_values(self, raw):
        m = _reload({"CLAUDE_BACKEND": "cli", "WS_REQUIRE_TLS": raw})
        assert m.WS_REQUIRE_TLS is False


class TestWebSocketTlsSafety:
    """The plaintext-on-public-interface guard."""

    def test_localhost_hosts_are_allowed(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            m = _reload({"CLAUDE_BACKEND": "cli", "WS_DASHBOARD_HOST": host})
            assert m.WS_HOST == host

    def test_nonlocal_host_without_tls_falls_back(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "WS_DASHBOARD_HOST": "0.0.0.0"})
        assert m.WS_HOST == "127.0.0.1"

    def test_nonlocal_host_without_tls_logs_critical(self, caplog):
        import logging

        import cogs.ai_core.api.dashboard_config as dc

        with patch.dict(
            os.environ, {"CLAUDE_BACKEND": "cli", "WS_DASHBOARD_HOST": "0.0.0.0"}, clear=True
        ):
            with patch("cogs.ai_core.api.api_failover.api_failover.initialize"):
                with caplog.at_level(logging.CRITICAL, logger=MODULE):
                    importlib.reload(dc)
        assert any("without TLS" in rec.message for rec in caplog.records)

    def test_nonlocal_host_with_tls_is_kept(self):
        # A public bind is allowed only when TLS is both demanded
        # (WS_REQUIRE_TLS) AND configured (cert + key) — ws_dashboard only
        # builds the SSL context when WS_REQUIRE_TLS is true.
        m = _reload(
            {
                "CLAUDE_BACKEND": "cli",
                "WS_DASHBOARD_HOST": "0.0.0.0",
                "WS_REQUIRE_TLS": "true",
                "WS_TLS_CERT_PATH": "/path/cert.pem",
                "WS_TLS_KEY_PATH": "/path/key.pem",
            }
        )
        assert m.WS_HOST == "0.0.0.0"

    def test_nonlocal_host_with_certs_but_no_require_tls_falls_back(self):
        # Cert+key present but WS_REQUIRE_TLS unset: ws_dashboard would bind
        # PLAINTEXT ws:// on the public interface (it only applies TLS when
        # WS_REQUIRE_TLS is true), leaking the auth token. The guard must fall
        # back to localhost rather than trust cert-path presence alone.
        m = _reload(
            {
                "CLAUDE_BACKEND": "cli",
                "WS_DASHBOARD_HOST": "0.0.0.0",
                "WS_TLS_CERT_PATH": "/path/cert.pem",
                "WS_TLS_KEY_PATH": "/path/key.pem",
            }
        )
        assert m.WS_HOST == "127.0.0.1"

    def test_nonlocal_host_with_only_cert_falls_back(self):
        # Both cert AND key are required; only one is not enough.
        m = _reload(
            {
                "CLAUDE_BACKEND": "cli",
                "WS_DASHBOARD_HOST": "0.0.0.0",
                "WS_TLS_CERT_PATH": "/path/cert.pem",
            }
        )
        assert m.WS_HOST == "127.0.0.1"


class TestGeminiConfig:
    """Gemini configuration parsing."""

    def test_defaults(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.GEMINI_MODEL == "gemini-3.1-pro-preview"
        assert m.GEMINI_CONTEXT_WINDOW == 1000000
        assert m.GEMINI_API_KEY is None

    def test_api_key_stripped(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "GEMINI_API_KEY": "  abc123\n"})
        assert m.GEMINI_API_KEY == "abc123"

    def test_whitespace_only_key_becomes_none(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "GEMINI_API_KEY": "   "})
        assert m.GEMINI_API_KEY is None

    def test_custom_model_and_context(self):
        m = _reload(
            {"CLAUDE_BACKEND": "cli", "GEMINI_MODEL": "gemini-x", "GEMINI_CONTEXT_WINDOW": "2048"}
        )
        assert m.GEMINI_MODEL == "gemini-x"
        assert m.GEMINI_CONTEXT_WINDOW == 2048


class TestClaudeConfig:
    """Claude configuration parsing."""

    def test_defaults(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.CLAUDE_MODEL == "claude-opus-4-8"
        assert m.CLAUDE_MAX_TOKENS == 128000
        assert m.CLAUDE_CONTEXT_WINDOW == 1000000

    def test_api_key_stripped_and_optional(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.CLAUDE_API_KEY is None

        m = _reload({"CLAUDE_BACKEND": "cli", "ANTHROPIC_API_KEY": "  sk-key \n"})
        assert m.CLAUDE_API_KEY == "sk-key"

    def test_custom_model_and_tokens(self):
        m = _reload(
            {
                "CLAUDE_BACKEND": "cli",
                "CLAUDE_MODEL": "claude-opus-4-7",
                "CLAUDE_MAX_TOKENS": "64000",
                "CLAUDE_CONTEXT_WINDOW": "500000",
            }
        )
        assert m.CLAUDE_MODEL == "claude-opus-4-7"
        assert m.CLAUDE_MAX_TOKENS == 64000
        assert m.CLAUDE_CONTEXT_WINDOW == 500000


class TestClaudeEffort:
    """CLAUDE_EFFORT validation / fallback."""

    def test_default_is_xhigh(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.CLAUDE_EFFORT == "xhigh"

    @pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
    def test_valid_values_accepted(self, effort):
        m = _reload({"CLAUDE_BACKEND": "cli", "CLAUDE_EFFORT": effort})
        assert m.CLAUDE_EFFORT == effort

    def test_case_insensitive_and_stripped(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "CLAUDE_EFFORT": "  MAX  "})
        assert m.CLAUDE_EFFORT == "max"

    def test_invalid_value_becomes_none(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "CLAUDE_EFFORT": "ultra"})
        assert m.CLAUDE_EFFORT is None

    def test_allowed_set_shape(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert isinstance(m._CLAUDE_EFFORT_ALLOWED, frozenset)
        assert m._CLAUDE_EFFORT_ALLOWED == {"low", "medium", "high", "xhigh", "max"}


class TestBackendMode:
    """CLAUDE_BACKEND selection and the derived API_AI_DISABLED master switch."""

    def test_cli_mode_is_default(self):
        m = _reload({})
        assert m._CLAUDE_CLI_MODE_SELECTED is True
        assert m.API_AI_DISABLED is True

    def test_cli_mode_disables_failover(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.API_FAILOVER_AVAILABLE is False

    def test_api_mode_enables_api(self):
        m = _reload({"CLAUDE_BACKEND": "api", "ANTHROPIC_API_KEY": "k"})
        assert m._CLAUDE_CLI_MODE_SELECTED is False
        assert m.API_AI_DISABLED is False

    def test_backend_mode_case_insensitive(self):
        m = _reload({"CLAUDE_BACKEND": "  CLI  "})
        assert m._CLAUDE_CLI_MODE_SELECTED is True

    def test_unknown_backend_treated_as_non_cli(self):
        # Only the literal "cli" selects CLI mode; anything else enables API.
        m = _reload({"CLAUDE_BACKEND": "weird", "ANTHROPIC_API_KEY": "k"})
        assert m._CLAUDE_CLI_MODE_SELECTED is False
        assert m.API_AI_DISABLED is False


class TestProviders:
    """AVAILABLE_PROVIDERS / VALID_AI_PROVIDERS / DEFAULT_AI_PROVIDER logic."""

    def test_cli_mode_only_claude(self):
        m = _reload({"CLAUDE_BACKEND": "cli", "GEMINI_API_KEY": "g"})
        # Gemini is dropped in CLI mode even though the key is present.
        assert m.AVAILABLE_PROVIDERS == ["claude"]
        assert m.VALID_AI_PROVIDERS == frozenset({"claude"})

    def test_cli_mode_claude_available_without_key(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert "claude" in m.AVAILABLE_PROVIDERS

    def test_api_mode_both_providers(self):
        m = _reload({"CLAUDE_BACKEND": "api", "GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"})
        assert set(m.AVAILABLE_PROVIDERS) == {"gemini", "claude"}
        assert m.VALID_AI_PROVIDERS == frozenset({"gemini", "claude"})

    def test_api_mode_gemini_only_when_no_claude_key(self):
        m = _reload({"CLAUDE_BACKEND": "api", "GEMINI_API_KEY": "g"})
        assert m.AVAILABLE_PROVIDERS == ["gemini"]
        # VALID set still allows both names regardless of available keys.
        assert m.VALID_AI_PROVIDERS == frozenset({"gemini", "claude"})

    def test_api_mode_no_keys_yields_empty_available(self):
        m = _reload({"CLAUDE_BACKEND": "api"})
        assert m.AVAILABLE_PROVIDERS == []

    def test_valid_providers_is_frozenset(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert isinstance(m.VALID_AI_PROVIDERS, frozenset)


class TestDefaultProvider:
    """DEFAULT_AI_PROVIDER resolution order."""

    def test_default_prefers_claude_in_cli_mode(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.DEFAULT_AI_PROVIDER == "claude"

    def test_env_override_honored_when_available(self):
        m = _reload(
            {
                "CLAUDE_BACKEND": "api",
                "GEMINI_API_KEY": "g",
                "ANTHROPIC_API_KEY": "a",
                "DEFAULT_AI_PROVIDER": "gemini",
            }
        )
        assert m.DEFAULT_AI_PROVIDER == "gemini"

    def test_env_override_ignored_when_not_available(self):
        # gemini requested but unavailable in CLI mode -> falls back to claude.
        m = _reload({"CLAUDE_BACKEND": "cli", "DEFAULT_AI_PROVIDER": "gemini"})
        assert m.DEFAULT_AI_PROVIDER == "claude"

    def test_falls_back_to_first_available_when_claude_missing(self):
        # API mode, only gemini available, no explicit default -> gemini.
        m = _reload({"CLAUDE_BACKEND": "api", "GEMINI_API_KEY": "g"})
        assert m.DEFAULT_AI_PROVIDER == "gemini"

    def test_falls_back_to_claude_when_nothing_available(self):
        m = _reload({"CLAUDE_BACKEND": "api"})
        assert m.AVAILABLE_PROVIDERS == []
        assert m.DEFAULT_AI_PROVIDER == "claude"

    def test_env_override_case_insensitive_and_stripped(self):
        m = _reload(
            {
                "CLAUDE_BACKEND": "api",
                "GEMINI_API_KEY": "g",
                "ANTHROPIC_API_KEY": "a",
                "DEFAULT_AI_PROVIDER": "  GEMINI  ",
            }
        )
        assert m.DEFAULT_AI_PROVIDER == "gemini"


class TestUnrestrictedFraming:
    """The general-purpose unrestricted framing string."""

    def test_is_non_empty_string(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert isinstance(m.GENERAL_UNRESTRICTED_FRAMING, str)
        assert m.GENERAL_UNRESTRICTED_FRAMING.strip()

    def test_contains_creative_workspace_marker(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert "Private Creative Workspace" in m.GENERAL_UNRESTRICTED_FRAMING


class TestRolePresets:
    """Shape and required keys of DASHBOARD_ROLE_PRESETS."""

    REQUIRED_KEYS = {"name", "emoji", "system_instruction", "color", "unrestricted_framing"}

    def test_has_expected_presets(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert set(m.DASHBOARD_ROLE_PRESETS) == {"general", "faust"}

    def test_each_preset_has_required_keys(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        for name, preset in m.DASHBOARD_ROLE_PRESETS.items():
            assert self.REQUIRED_KEYS <= set(preset), f"{name} missing keys"

    def test_preset_value_types_and_nonempty(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        for preset in m.DASHBOARD_ROLE_PRESETS.values():
            for key in self.REQUIRED_KEYS:
                assert isinstance(preset[key], str)
            assert preset["name"].strip()
            assert preset["system_instruction"].strip()

    def test_colors_are_hex(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        for preset in m.DASHBOARD_ROLE_PRESETS.values():
            color = preset["color"]
            assert color.startswith("#")
            assert len(color) == 7
            int(color[1:], 16)  # raises ValueError if not valid hex

    def test_general_and_faust_names(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert m.DASHBOARD_ROLE_PRESETS["general"]["name"] == "General Assistant"
        assert m.DASHBOARD_ROLE_PRESETS["faust"]["name"] == "Faust"

    def test_faust_preset_includes_roleplay_addendum(self):
        """The dashboard faust preset carries the base persona AND, when the
        persona file defines a distinct FAUST_ROLEPLAY, its roleplay-format
        addendum (parity with the Discord guild surface)."""
        m = _reload({"CLAUDE_BACKEND": "cli"})
        from cogs.ai_core.data import FAUST_INSTRUCTION, FAUST_ROLEPLAY

        faust_si = m.DASHBOARD_ROLE_PRESETS["faust"]["system_instruction"]
        assert FAUST_INSTRUCTION in faust_si
        if FAUST_ROLEPLAY and FAUST_ROLEPLAY != FAUST_INSTRUCTION:
            assert FAUST_ROLEPLAY in faust_si


class TestPersonaFallbacks:
    """FAUST_AVAILABLE and the persona-related fallbacks."""

    def test_faust_available_is_bool(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert isinstance(m.FAUST_AVAILABLE, bool)

    def test_faust_instruction_is_nonempty_string(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert isinstance(m.FAUST_INSTRUCTION, str)
        assert m.FAUST_INSTRUCTION.strip()

    def test_db_available_is_bool(self):
        m = _reload({"CLAUDE_BACKEND": "cli"})
        assert isinstance(m.DB_AVAILABLE, bool)
