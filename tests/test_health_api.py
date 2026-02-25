"""
Tests for utils.monitoring.health_api module.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

class TestHealthApiConstants:
    """Tests for health API constants."""

    def test_default_port(self):
        """Test default health API port."""
        with patch.dict("os.environ", {}, clear=True):
            # Re-import to get defaults
            import importlib

            import utils.monitoring.health_api
            importlib.reload(utils.monitoring.health_api)

            # Default port should be 8080
            assert utils.monitoring.health_api.HEALTH_API_PORT == 8080

    def test_default_host(self):
        """Test default health API host."""
        from utils.monitoring.health_api import HEALTH_API_HOST

        assert HEALTH_API_HOST == "127.0.0.1"


class TestBotHealthData:
    """Tests for BotHealthData class."""

    def test_init_sets_start_time(self):
        """Test initialization sets start time."""
        from utils.monitoring.health_api import BotHealthData

        before = datetime.now()
        health = BotHealthData()
        after = datetime.now()

        assert before <= health.start_time <= after

    def test_init_default_values(self):
        """Test initialization default values."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        assert health.bot is None
        assert health.message_count == 0
        assert health.command_count == 0
        assert health.error_count == 0
        assert health.is_ready is False
        assert health.latency_ms == 0.0
        assert health.guild_count == 0
        assert health.user_count == 0
        assert health.cogs_loaded == []

    def test_increment_message(self):
        """Test increment_message increases counter."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        assert health.message_count == 0

        health.increment_message()
        assert health.message_count == 1

        health.increment_message()
        health.increment_message()
        assert health.message_count == 3

    def test_increment_command(self):
        """Test increment_command increases counter."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        assert health.command_count == 0

        health.increment_command()
        assert health.command_count == 1

    def test_increment_error(self):
        """Test increment_error increases counter."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        assert health.error_count == 0

        health.increment_error()
        assert health.error_count == 1

    def test_get_uptime(self):
        """Test get_uptime returns timedelta."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        uptime = health.get_uptime()

        assert isinstance(uptime, timedelta)
        assert uptime.total_seconds() >= 0

    def test_get_uptime_str_seconds(self):
        """Test get_uptime_str formats seconds correctly."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(seconds=30)

        result = health.get_uptime_str()
        assert "s" in result

    def test_get_uptime_str_minutes(self):
        """Test get_uptime_str formats minutes correctly."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(minutes=5, seconds=30)

        result = health.get_uptime_str()
        assert "m" in result

    def test_get_uptime_str_hours(self):
        """Test get_uptime_str formats hours correctly."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(hours=2, minutes=30)

        result = health.get_uptime_str()
        assert "h" in result

    def test_get_uptime_str_days(self):
        """Test get_uptime_str formats days correctly."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(days=3, hours=5)

        result = health.get_uptime_str()
        assert "d" in result

    def test_update_from_bot_not_ready(self):
        """Test update_from_bot when bot is not ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False

        health.update_from_bot(mock_bot)

        assert health.bot is mock_bot
        assert health.is_ready is False

    def test_update_from_bot_ready(self):
        """Test update_from_bot when bot is ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05  # 50ms

        mock_guild1 = MagicMock()
        mock_guild1.member_count = 100
        mock_guild2 = MagicMock()
        mock_guild2.member_count = 200
        mock_bot.guilds = [mock_guild1, mock_guild2]

        mock_bot.cogs.keys.return_value = ["MusicCog", "AICog"]

        health.update_from_bot(mock_bot)

        assert health.is_ready is True
        assert health.latency_ms == 50.0
        assert health.guild_count == 2
        assert health.user_count == 300
        assert "MusicCog" in health.cogs_loaded
        assert "AICog" in health.cogs_loaded

    def test_to_dict_returns_dict(self):
        """Test to_dict returns dictionary with expected keys."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        result = health.to_dict()

        assert isinstance(result, dict)
        assert "status" in result
        assert "timestamp" in result
        assert "uptime" in result
        assert "uptime_seconds" in result
        assert "bot" in result

    def test_to_dict_status_starting_when_not_ready(self):
        """Test to_dict shows 'starting' status when not ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = False

        result = health.to_dict()
        assert result["status"] == "starting"

    def test_to_dict_status_healthy_when_ready(self):
        """Test to_dict shows 'healthy' status when ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True

        result = health.to_dict()
        assert result["status"] == "healthy"

    def test_to_dict_bot_section(self):
        """Test to_dict includes bot section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 45.5

        result = health.to_dict()

        assert "bot" in result
        assert result["bot"]["ready"] is True
        assert result["bot"]["latency_ms"] == 45.5


class TestHealthDataSingleton:
    """Tests for health_data global instance."""

    def test_health_data_exists(self):
        """Test that global health_data instance exists."""
        from utils.monitoring.health_api import health_data

        assert health_data is not None

    def test_health_data_is_bothealthdata(self):
        """Test that health_data is BotHealthData instance."""
        from utils.monitoring.health_api import BotHealthData, health_data

        assert isinstance(health_data, BotHealthData)


# ======================================================================
# Merged from test_health_api_extended.py
# ======================================================================

class TestBotHealthData:
    """Tests for BotHealthData class."""

    def test_health_data_creation(self):
        """Test creating BotHealthData."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        assert health.bot is None
        assert health.message_count == 0
        assert health.command_count == 0
        assert health.error_count == 0
        assert health.is_ready is False

    def test_increment_message(self):
        """Test incrementing message counter."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.increment_message()
        health.increment_message()

        assert health.message_count == 2

    def test_increment_command(self):
        """Test incrementing command counter."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.increment_command()

        assert health.command_count == 1

    def test_increment_error(self):
        """Test incrementing error counter."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.increment_error()

        assert health.error_count == 1

    def test_get_uptime(self):
        """Test getting uptime."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        uptime = health.get_uptime()

        assert isinstance(uptime, timedelta)
        assert uptime.total_seconds() >= 0

    def test_get_uptime_str(self):
        """Test getting formatted uptime string."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        uptime_str = health.get_uptime_str()

        assert isinstance(uptime_str, str)
        # Should contain 's' for seconds at minimum
        assert "s" in uptime_str

    def test_to_dict_structure(self):
        """Test to_dict returns proper structure."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        data = health.to_dict()

        assert "status" in data
        assert "timestamp" in data
        assert "uptime" in data
        assert "bot" in data
        assert "stats" in data
        assert "system" in data
        assert "heartbeat" in data

    def test_to_dict_bot_section(self):
        """Test to_dict bot section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        data = health.to_dict()

        bot_data = data["bot"]
        assert "ready" in bot_data
        assert "latency_ms" in bot_data
        assert "guilds" in bot_data
        assert "users" in bot_data

    def test_to_dict_stats_section(self):
        """Test to_dict stats section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.increment_message()
        health.increment_command()

        data = health.to_dict()
        stats = data["stats"]

        assert stats["messages_processed"] == 1
        assert stats["commands_executed"] == 1

    def test_is_healthy_not_ready(self):
        """Test is_healthy when not ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = False

        assert health.is_healthy() is False

    def test_is_healthy_stale_heartbeat(self):
        """Test is_healthy with stale heartbeat."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.last_heartbeat = datetime.now() - timedelta(seconds=120)

        assert health.is_healthy() is False

    def test_is_healthy_high_latency(self):
        """Test is_healthy with high latency."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 6000  # Over 5 second threshold

        assert health.is_healthy() is False

    def test_is_healthy_good_state(self):
        """Test is_healthy in good state."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.last_heartbeat = datetime.now()
        health.latency_ms = 100

        assert health.is_healthy() is True

    def test_update_from_bot(self):
        """Test update_from_bot."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.1
        mock_bot.guilds = [MagicMock(member_count=100), MagicMock(member_count=50)]
        mock_bot.cogs = {"AI": MagicMock(), "Music": MagicMock()}

        health.update_from_bot(mock_bot)

        assert health.is_ready is True
        assert health.latency_ms == 100.0
        assert health.guild_count == 2
        assert health.user_count == 150

    def test_get_ai_performance_stats_no_bot(self):
        """Test get_ai_performance_stats with no bot."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.bot = None

        result = health.get_ai_performance_stats()

        assert "error" in result


class TestConstants:
    """Tests for module constants."""

    def test_health_api_port(self):
        """Test HEALTH_API_PORT default."""
        from utils.monitoring.health_api import HEALTH_API_PORT

        assert isinstance(HEALTH_API_PORT, int)
        assert HEALTH_API_PORT > 0

    def test_health_api_host(self):
        """Test HEALTH_API_HOST default."""
        from utils.monitoring.health_api import HEALTH_API_HOST

        assert isinstance(HEALTH_API_HOST, str)


class TestGlobalHealthData:
    """Tests for global health_data instance."""

    def test_health_data_exists(self):
        """Test health_data global exists."""
        from utils.monitoring.health_api import health_data

        assert health_data is not None

    def test_health_data_is_correct_type(self):
        """Test health_data is BotHealthData."""
        from utils.monitoring.health_api import BotHealthData, health_data

        assert isinstance(health_data, BotHealthData)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_bot_health_data(self):
        """Test importing BotHealthData."""
        from utils.monitoring.health_api import BotHealthData
        assert BotHealthData is not None

    def test_import_health_data(self):
        """Test importing health_data."""
        from utils.monitoring.health_api import health_data
        assert health_data is not None

    def test_import_setup_health_hooks(self):
        """Test importing setup_health_hooks."""
        from utils.monitoring.health_api import setup_health_hooks
        assert setup_health_hooks is not None

    def test_import_start_health_api(self):
        """Test importing start_health_api."""
        from utils.monitoring.health_api import start_health_api
        assert start_health_api is not None

    def test_import_stop_health_api(self):
        """Test importing stop_health_api."""
        from utils.monitoring.health_api import stop_health_api
        assert stop_health_api is not None

    def test_import_update_health_loop(self):
        """Test importing update_health_loop."""
        from utils.monitoring.health_api import update_health_loop
        assert update_health_loop is not None


class TestSetupHealthHooks:
    """Tests for setup_health_hooks function."""

    def test_setup_health_hooks_runs(self):
        """Test setup_health_hooks runs without error."""
        from utils.monitoring.health_api import setup_health_hooks

        mock_bot = MagicMock()

        # Should not raise
        setup_health_hooks(mock_bot)


class TestUptimeFormatting:
    """Tests for uptime formatting."""

    def test_uptime_format_seconds_only(self):
        """Test uptime formatting with seconds only."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        # Set start time to now for ~0 seconds uptime
        health.start_time = datetime.now()

        uptime_str = health.get_uptime_str()

        assert "s" in uptime_str

    def test_uptime_format_minutes(self):
        """Test uptime formatting with minutes."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(minutes=5, seconds=30)

        uptime_str = health.get_uptime_str()

        assert "m" in uptime_str

    def test_uptime_format_hours(self):
        """Test uptime formatting with hours."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(hours=2, minutes=30)

        uptime_str = health.get_uptime_str()

        assert "h" in uptime_str

    def test_uptime_format_days(self):
        """Test uptime formatting with days."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(days=3, hours=5)

        uptime_str = health.get_uptime_str()

        assert "d" in uptime_str


# ======================================================================
# Merged from test_health_api_handlers.py
# ======================================================================

def _make_handler(path: str = "/health", auth_header: str = ""):
    """Create a HealthRequestHandler with a fake request."""
    from utils.monitoring.health_api import HealthRequestHandler

    handler = object.__new__(HealthRequestHandler)
    handler.path = path
    handler.headers = {"Authorization": auth_header}
    handler.wfile = io.BytesIO()

    # Capture response status and headers
    handler._response_status = None
    handler._response_headers = {}

    def send_response(code):
        handler._response_status = code

    def send_header(k, v):
        handler._response_headers[k] = v

    def end_headers():
        pass

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers

    return handler


def _handler_body(handler) -> str:
    return handler.wfile.getvalue().decode("utf-8")


# ---------------------------------------------------------------------------
# HealthRequestHandler response helpers
# ---------------------------------------------------------------------------
class TestResponseHelpers:
    """Test _send_json_response, _send_text_response, _send_html_response."""

    def test_send_json_response(self):
        h = _make_handler()
        h._send_json_response({"hello": "world"}, 200)
        assert h._response_status == 200
        assert h._response_headers["Content-Type"] == "application/json"
        body = json.loads(_handler_body(h))
        assert body["hello"] == "world"

    def test_send_json_response_custom_status(self):
        h = _make_handler()
        h._send_json_response({"err": True}, 503)
        assert h._response_status == 503

    def test_send_text_response(self):
        h = _make_handler()
        h._send_text_response("OK", 200)
        assert h._response_status == 200
        assert h._response_headers["Content-Type"] == "text/plain"
        assert _handler_body(h) == "OK"

    def test_send_html_response(self):
        h = _make_handler()
        h._send_html_response("<h1>Hi</h1>", 200)
        assert h._response_status == 200
        assert "text/html" in h._response_headers["Content-Type"]
        assert "<h1>Hi</h1>" in _handler_body(h)


# ---------------------------------------------------------------------------
# do_GET route tests
# ---------------------------------------------------------------------------
class TestDoGETRoutes:
    """Test all do_GET route branches."""

    def test_health_html(self):
        h = _make_handler("/health")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status == 200
        assert "text/html" in h._response_headers.get("Content-Type", "")

    def test_health_json(self):
        h = _make_handler("/health/json")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status in (200, 503)
        body = json.loads(_handler_body(h))
        assert "status" in body

    def test_root_json(self):
        h = _make_handler("/")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert "status" in body

    def test_livez(self):
        h = _make_handler("/livez")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status == 200
        body = json.loads(_handler_body(h))
        assert body["status"] == "alive"

    def test_health_live(self):
        h = _make_handler("/health/live")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert body["status"] == "alive"

    def test_readyz_ready(self):
        from utils.monitoring.health_api import health_data
        old_ready = health_data.is_ready
        health_data.is_ready = True
        try:
            h = _make_handler("/readyz")
            with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
                h.do_GET()
            assert h._response_status == 200
            body = json.loads(_handler_body(h))
            assert body["status"] == "ready"
        finally:
            health_data.is_ready = old_ready

    def test_readyz_not_ready(self):
        from utils.monitoring.health_api import health_data
        old_ready = health_data.is_ready
        health_data.is_ready = False
        try:
            h = _make_handler("/readyz")
            with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
                h.do_GET()
            assert h._response_status == 503
            body = json.loads(_handler_body(h))
            assert body["status"] == "not_ready"
        finally:
            health_data.is_ready = old_ready

    def test_health_ready(self):
        from utils.monitoring.health_api import health_data
        old_ready = health_data.is_ready
        health_data.is_ready = True
        try:
            h = _make_handler("/health/ready")
            with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
                h.do_GET()
            assert h._response_status == 200
        finally:
            health_data.is_ready = old_ready

    def test_health_status_ok(self):
        from utils.monitoring.health_api import health_data
        old_ready = health_data.is_ready
        health_data.is_ready = True
        health_data.last_heartbeat = datetime.now()
        health_data.latency_ms = 50.0
        try:
            h = _make_handler("/health/status")
            with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
                h.do_GET()
            assert _handler_body(h) == "OK"
        finally:
            health_data.is_ready = old_ready

    def test_health_status_unhealthy(self):
        from utils.monitoring.health_api import health_data
        old_ready = health_data.is_ready
        health_data.is_ready = False
        try:
            h = _make_handler("/health/status")
            with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
                h.do_GET()
            assert h._response_status == 503
            assert _handler_body(h) == "UNHEALTHY"
        finally:
            health_data.is_ready = old_ready

    def test_health_deep(self):
        h = _make_handler("/health/deep")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert "checks" in body
        assert "healthy" in body

    def test_metrics(self):
        h = _make_handler("/metrics")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status == 200
        body = _handler_body(h)
        assert "discord_bot_up" in body
        assert "discord_bot_latency_ms" in body

    def test_stats_html(self):
        h = _make_handler("/stats")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status == 200
        assert "text/html" in h._response_headers.get("Content-Type", "")

    def test_stats_json(self):
        h = _make_handler("/stats/json")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert "uptime" in body
        assert "messages" in body

    def test_ai_stats_html(self):
        h = _make_handler("/ai/stats")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status == 200

    def test_ai_stats_json(self):
        h = _make_handler("/ai/stats/json")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""), \
             patch("utils.monitoring.health_api.health_data") as mock_hd:
            mock_hd.get_ai_performance_stats.return_value = {"error": "AI cog not available"}
            h.do_GET()
        body = json.loads(_handler_body(h))
        # Either has stats or error message
        assert isinstance(body, dict)

    def test_404(self):
        h = _make_handler("/nonexistent")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status == 404
        body = json.loads(_handler_body(h))
        assert body["error"] == "Not Found"

    def test_query_string_stripped(self):
        h = _make_handler("/health/live?foo=bar")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert body["status"] == "alive"


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------
class TestAuthentication:
    """Test auth enforcement on protected endpoints."""

    def test_protected_endpoint_no_token_configured(self):
        """When no token is configured, access is open."""
        h = _make_handler("/health/json")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
            h.do_GET()
        assert h._response_status in (200, 503)

    def test_protected_endpoint_with_valid_token(self):
        h = _make_handler("/health/json", auth_header="Bearer my-secret")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", "my-secret"):
            h.do_GET()
        assert h._response_status in (200, 503)

    def test_protected_endpoint_with_invalid_token(self):
        h = _make_handler("/health/json", auth_header="Bearer wrong")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", "my-secret"):
            h.do_GET()
        assert h._response_status == 401
        body = json.loads(_handler_body(h))
        assert body["error"] == "Unauthorized"

    def test_protected_endpoint_no_token_provided(self):
        h = _make_handler("/", auth_header="")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", "my-secret"):
            h.do_GET()
        assert h._response_status == 401

    def test_unprotected_endpoint_skips_auth(self):
        """Liveness probe should not require auth."""
        h = _make_handler("/livez", auth_header="")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", "my-secret"):
            h.do_GET()
        assert h._response_status == 200


# ---------------------------------------------------------------------------
# is_healthy tests
# ---------------------------------------------------------------------------
class TestIsHealthy:
    """Test BotHealthData.is_healthy method."""

    def test_healthy(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        hd.is_ready = True
        hd.last_heartbeat = datetime.now()
        hd.latency_ms = 50.0
        assert hd.is_healthy() is True

    def test_not_ready(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        hd.is_ready = False
        assert hd.is_healthy() is False

    def test_stale_heartbeat(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        hd.is_ready = True
        hd.last_heartbeat = datetime.now() - timedelta(seconds=120)
        hd.latency_ms = 50.0
        assert hd.is_healthy() is False

    def test_high_latency(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        hd.is_ready = True
        hd.last_heartbeat = datetime.now()
        hd.latency_ms = 10000.0  # Over threshold
        assert hd.is_healthy() is False


# ---------------------------------------------------------------------------
# get_ai_performance_stats tests
# ---------------------------------------------------------------------------
class TestAIPerformanceStats:
    """Test get_ai_performance_stats."""

    def test_no_bot(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        result = hd.get_ai_performance_stats()
        assert "error" in result

    def test_with_ai_cog(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.cogs = {"AI": MagicMock()}
        mock_bot.cogs["AI"].chat_manager.get_performance_stats.return_value = {"total": {"count": 5}}
        hd.bot = mock_bot
        result = hd.get_ai_performance_stats()
        assert result["total"]["count"] == 5

    def test_with_exception(self):
        from utils.monitoring.health_api import BotHealthData
        hd = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.cogs = {"AI": MagicMock()}
        mock_bot.cogs["AI"].chat_manager.get_performance_stats.side_effect = RuntimeError("fail")
        hd.bot = mock_bot
        result = hd.get_ai_performance_stats()
        assert "error" in result


# ---------------------------------------------------------------------------
# Deep health check tests
# ---------------------------------------------------------------------------
class TestDeepHealthCheck:
    """Test _perform_deep_health_check."""

    def test_deep_check_with_db(self):
        h = _make_handler("/health/deep")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""), \
             patch.object(Path, "exists", return_value=True):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert body["checks"]["database"]["status"] == "ok"

    def test_deep_check_no_db(self):
        h = _make_handler("/health/deep")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""), \
             patch.object(Path, "exists", return_value=False):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert body["checks"]["database"]["status"] == "warning"

    def test_deep_check_bot_not_ready(self):
        from utils.monitoring.health_api import health_data
        old = health_data.is_ready
        health_data.is_ready = False
        try:
            h = _make_handler("/health/deep")
            with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""):
                h.do_GET()
            body = json.loads(_handler_body(h))
            assert body["healthy"] is False
        finally:
            health_data.is_ready = old


# ---------------------------------------------------------------------------
# HTML generator tests
# ---------------------------------------------------------------------------
class TestHTMLGenerators:
    """Test HTML generation methods."""

    def test_health_html_contains_status(self):
        h = _make_handler()
        from utils.monitoring.health_api import health_data
        data = health_data.to_dict()
        html_str = h._generate_health_html(data)
        assert "Bot Health" in html_str

    def test_stats_html(self):
        h = _make_handler()
        data = {"uptime": "1h 5m", "messages": 10, "commands": 3,
                "errors": 0, "guilds": 2, "latency_ms": 50.0}
        html_str = h._generate_stats_html(data)
        assert "Quick Stats" in html_str

    def test_ai_stats_html_with_error(self):
        h = _make_handler()
        html_str = h._generate_ai_stats_html({"error": "No AI <cog>"})
        assert "Oops" in html_str
        # XSS should be escaped
        assert "&lt;cog&gt;" in html_str

    def test_ai_stats_html_with_data(self):
        h = _make_handler()
        stats = {
            "total": {"count": 10, "avg_ms": 500.0, "min_ms": 100.0, "max_ms": 900.0},
            "api_call": {"count": 5, "avg_ms": 300.0, "min_ms": 50.0, "max_ms": 600.0},
        }
        html_str = h._generate_ai_stats_html(stats)
        assert "AI Performance" in html_str
        assert "Total" in html_str

    def test_anime_theme_css(self):
        h = _make_handler()
        css = h._get_anime_theme_css()
        assert "sakura" in css

    def test_sakura_js_without_refresh(self):
        h = _make_handler()
        js = h._get_sakura_js()
        assert "createSakura" in js

    def test_sakura_js_with_refresh(self):
        h = _make_handler()
        js = h._get_sakura_js(json_endpoint="/health/json", refresh_interval=3000)
        assert "refreshData" in js
        assert "/health/json" in js

    def test_log_message_suppressed(self):
        h = _make_handler()
        # Should not raise
        h.log_message("test %s", "value")


# ---------------------------------------------------------------------------
# HealthAPIServer lifecycle tests
# ---------------------------------------------------------------------------
class TestHealthAPIServer:
    """Test HealthAPIServer start/stop."""

    def test_init(self):
        from utils.monitoring.health_api import HealthAPIServer
        srv = HealthAPIServer("127.0.0.1", 0)
        assert srv.host == "127.0.0.1"
        assert srv.running is False

    def test_start_already_running(self):
        from utils.monitoring.health_api import HealthAPIServer
        srv = HealthAPIServer("127.0.0.1", 0)
        srv.running = True
        assert srv.start() is True

    def test_start_and_stop(self):
        from utils.monitoring.health_api import HealthAPIServer
        srv = HealthAPIServer("127.0.0.1", 0)  # port 0 = random available
        assert srv.start() is True
        assert srv.running is True
        srv.stop()
        assert srv.running is False

    def test_start_port_in_use(self):
        from utils.monitoring.health_api import HealthAPIServer
        # Bind a port first
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)
        try:
            srv = HealthAPIServer("127.0.0.1", port)
            assert srv.start() is False
        finally:
            sock.close()

    def test_stop_when_no_server(self):
        from utils.monitoring.health_api import HealthAPIServer
        srv = HealthAPIServer("127.0.0.1", 0)
        # Should not raise
        srv.stop()

    def test_run_server_with_none(self):
        from utils.monitoring.health_api import HealthAPIServer
        srv = HealthAPIServer("127.0.0.1", 0)
        srv.server = None
        # Should not raise
        srv._run_server()


# ---------------------------------------------------------------------------
# Module-level start/stop functions
# ---------------------------------------------------------------------------
class TestModuleFunctions:
    """Test start_health_api and stop_health_api."""

    def test_start_health_api(self):
        import utils.monitoring.health_api as mod
        old = mod._health_server
        mod._health_server = None
        try:
            with patch.object(mod.HealthAPIServer, "start", return_value=True):
                result = mod.start_health_api("127.0.0.1", 0)
                assert result is True
                assert mod._health_server is not None
        finally:
            mod._health_server = old

    def test_stop_health_api(self):
        import utils.monitoring.health_api as mod
        mock_server = MagicMock()
        old = mod._health_server
        mod._health_server = mock_server
        try:
            mod.stop_health_api()
            mock_server.stop.assert_called_once()
            assert mod._health_server is None
        finally:
            mod._health_server = old

    def test_stop_health_api_when_none(self):
        import utils.monitoring.health_api as mod
        old = mod._health_server
        mod._health_server = None
        try:
            mod.stop_health_api()  # Should not raise
        finally:
            mod._health_server = old


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
class TestPrometheusMetrics:
    """Test Prometheus metrics generation."""

    def test_metrics_format(self):
        h = _make_handler("/metrics")
        metrics = h._generate_prometheus_metrics()
        assert "# HELP discord_bot_up" in metrics
        assert "# TYPE discord_bot_up gauge" in metrics
        assert "discord_bot_messages_total" in metrics
        assert "process_memory_bytes" in metrics
        assert metrics.endswith("\n")


# ---------------------------------------------------------------------------
# update_health_loop tests
# ---------------------------------------------------------------------------
class TestUpdateHealthLoop:
    """Test update_health_loop async function."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_loop_updates_bot_data(self):
        from utils.monitoring.health_api import update_health_loop, health_data

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = []
        mock_bot.cogs.keys.return_value = []

        call_count = 0
        original_sleep = asyncio.sleep

        async def limited_sleep(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()
            await original_sleep(0)

        with patch("asyncio.sleep", side_effect=limited_sleep), \
             patch("utils.monitoring.health_api.GO_HEALTH_API_URL", "http://127.0.0.1:1/h"), \
             patch("utils.monitoring.health_api.GO_URL_FETCHER_URL", "http://127.0.0.1:1/h"):
            await update_health_loop(mock_bot, interval=0)

    @pytest.mark.asyncio
    async def test_loop_handles_general_exception(self):
        from utils.monitoring.health_api import update_health_loop

        mock_bot = MagicMock()
        mock_bot.is_ready.side_effect = RuntimeError("boom")

        call_count = 0

        async def limited_sleep(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        # CancelledError from the error-branch sleep propagates out
        with patch("asyncio.sleep", side_effect=limited_sleep):
            try:
                await update_health_loop(mock_bot, interval=0)
            except asyncio.CancelledError:
                pass

        assert call_count >= 1  # Loop ran and hit the error branch


# ---------------------------------------------------------------------------
# setup_health_hooks tests
# ---------------------------------------------------------------------------
class TestSetupHealthHooks:
    """Test setup_health_hooks."""

    def test_registers_listeners(self):
        from utils.monitoring.health_api import setup_health_hooks

        mock_bot = MagicMock()
        mock_bot._health_on_message_set = False
        del mock_bot._health_on_message_set  # hasattr will be False

        setup_health_hooks(mock_bot)

        # Should have registered listeners
        assert mock_bot.listen.call_count >= 3  # on_ready, on_message, on_command, on_command_error

    def test_skips_duplicate_registration(self):
        from utils.monitoring.health_api import setup_health_hooks

        mock_bot = MagicMock()
        mock_bot._health_on_message_set = True

        setup_health_hooks(mock_bot)

        # Only on_ready listener should be registered (message/command skipped)
        assert mock_bot.listen.call_count == 1

    @pytest.mark.asyncio
    async def test_on_ready_callback(self):
        """Test the on_ready listener callback updates health_data."""
        from utils.monitoring.health_api import setup_health_hooks, health_data

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.01
        mock_bot.guilds = []
        mock_bot.cogs.keys.return_value = []
        del mock_bot._health_on_message_set  # ensure hasattr is False

        callbacks = {}

        def capture_listen(event_name):
            def decorator(func):
                callbacks[event_name] = func
                return func
            return decorator

        mock_bot.listen = capture_listen
        setup_health_hooks(mock_bot)

        # Call the on_ready callback
        assert "on_ready" in callbacks
        await callbacks["on_ready"]()
        assert health_data.is_ready is True

    @pytest.mark.asyncio
    async def test_on_message_callback(self):
        """Test the on_message listener increments message count."""
        from utils.monitoring.health_api import setup_health_hooks, health_data

        mock_bot = MagicMock()
        del mock_bot._health_on_message_set

        callbacks = {}

        def capture_listen(event_name):
            def decorator(func):
                callbacks[event_name] = func
                return func
            return decorator

        mock_bot.listen = capture_listen
        setup_health_hooks(mock_bot)

        old_count = health_data.message_count
        await callbacks["on_message"](MagicMock())
        assert health_data.message_count == old_count + 1

    @pytest.mark.asyncio
    async def test_on_command_callback(self):
        """Test the on_command listener increments command count."""
        from utils.monitoring.health_api import setup_health_hooks, health_data

        mock_bot = MagicMock()
        del mock_bot._health_on_message_set

        callbacks = {}

        def capture_listen(event_name):
            def decorator(func):
                callbacks[event_name] = func
                return func
            return decorator

        mock_bot.listen = capture_listen
        setup_health_hooks(mock_bot)

        old_count = health_data.command_count
        await callbacks["on_command"](MagicMock())
        assert health_data.command_count == old_count + 1

    @pytest.mark.asyncio
    async def test_on_command_error_callback(self):
        """Test the on_command_error listener increments error count."""
        from utils.monitoring.health_api import setup_health_hooks, health_data

        mock_bot = MagicMock()
        del mock_bot._health_on_message_set

        callbacks = {}

        def capture_listen(event_name):
            def decorator(func):
                callbacks[event_name] = func
                return func
            return decorator

        mock_bot.listen = capture_listen
        setup_health_hooks(mock_bot)

        old_count = health_data.error_count
        await callbacks["on_command_error"](MagicMock(), RuntimeError("test"))
        assert health_data.error_count == old_count + 1


# ---------------------------------------------------------------------------
# Service health check + alerting branch tests
# ---------------------------------------------------------------------------
class TestServiceHealthChecks:
    """Test check_service inner function and alerting in update_health_loop."""

    @pytest.mark.asyncio
    async def test_loop_service_healthy(self):
        """Test loop marks service as healthy when HTTP 200."""
        from utils.monitoring.health_api import update_health_loop, health_data

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = []
        mock_bot.cogs.keys.return_value = []

        # Proper async context manager for aiohttp response
        mock_resp = MagicMock()
        mock_resp.status = 200

        class FakeCtx:
            async def __aenter__(self):
                return mock_resp
            async def __aexit__(self, *args):
                return False

        class FakeSession:
            def get(self, url, **kw):
                return FakeCtx()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False

        call_count = 0

        async def limited_sleep(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=limited_sleep), \
             patch("aiohttp.ClientSession", return_value=FakeSession()):
            await update_health_loop(mock_bot, interval=0)

        # Service should be marked healthy
        for svc in health_data.service_health.values():
            assert svc["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_loop_service_unhealthy(self):
        """Test loop marks service as unhealthy when HTTP 500."""
        from utils.monitoring.health_api import update_health_loop, health_data

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = []
        mock_bot.cogs.keys.return_value = []

        mock_resp = MagicMock()
        mock_resp.status = 500

        class FakeCtx:
            async def __aenter__(self):
                return mock_resp
            async def __aexit__(self, *args):
                return False

        class FakeSession:
            def get(self, url, **kw):
                return FakeCtx()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False

        call_count = 0

        async def limited_sleep(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=limited_sleep), \
             patch("aiohttp.ClientSession", return_value=FakeSession()):
            await update_health_loop(mock_bot, interval=0)

        for svc in health_data.service_health.values():
            assert svc["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# Deep health check - DB exception path
# ---------------------------------------------------------------------------
class TestDeepHealthCheckEdge:
    """Test edge cases in deep health check."""

    def test_deep_check_db_exception(self):
        """Test database check exception path (lines 687-689)."""
        from utils.monitoring.health_api import HealthRequestHandler
        h = _make_handler("/health/deep")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""), \
             patch("pathlib.Path.exists", side_effect=PermissionError("no access")):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert body["checks"]["database"]["status"] == "error"

    def test_deep_check_filesystem_error(self):
        """Test filesystem check exception path (lines 712-713)."""
        from utils.monitoring.health_api import HealthRequestHandler
        h = _make_handler("/health/deep")
        with patch("utils.monitoring.health_api.HEALTH_API_TOKEN", ""), \
             patch("pathlib.Path.mkdir", side_effect=PermissionError("read-only")):
            h.do_GET()
        body = json.loads(_handler_body(h))
        assert body["checks"]["filesystem"]["status"] == "error"


# ======================================================================
# Merged from test_health_api_module.py
# ======================================================================

class TestHealthApiConstants:
    """Test module constants."""

    def test_health_api_port_default(self):
        """Test default health API port."""
        with patch.dict('os.environ', {}, clear=True):
            # Force reimport with cleared env
            import importlib

            import utils.monitoring.health_api as health_api_module
            importlib.reload(health_api_module)

            # Default should be 8080
            assert health_api_module.HEALTH_API_PORT == 8080

    def test_health_api_host_default(self):
        """Test default health API host."""
        with patch.dict('os.environ', {}, clear=True):
            import importlib

            import utils.monitoring.health_api as health_api_module
            importlib.reload(health_api_module)

            # Default should be 127.0.0.1 (localhost only for security)
            assert health_api_module.HEALTH_API_HOST == "127.0.0.1"


# ==================== TestBotHealthDataInit ====================


class TestBotHealthDataInit:
    """Test BotHealthData initialization."""

    def test_init_defaults(self):
        """Test BotHealthData default values."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        assert health.bot is None
        assert health.message_count == 0
        assert health.command_count == 0
        assert health.error_count == 0
        assert health.is_ready is False
        assert health.latency_ms == 0.0
        assert health.guild_count == 0
        assert health.user_count == 0
        assert health.cogs_loaded == []

    def test_init_has_start_time(self):
        """Test BotHealthData has start time."""
        from utils.monitoring.health_api import BotHealthData

        before = datetime.now()
        health = BotHealthData()
        after = datetime.now()

        assert before <= health.start_time <= after

    def test_init_has_last_heartbeat(self):
        """Test BotHealthData has last heartbeat."""
        from utils.monitoring.health_api import BotHealthData

        before = datetime.now()
        health = BotHealthData()
        after = datetime.now()

        assert before <= health.last_heartbeat <= after


# ==================== TestBotHealthDataUpdateFromBot ====================


class TestBotHealthDataUpdateFromBot:
    """Test BotHealthData update from bot."""

    def test_update_from_bot_stores_bot(self):
        """Test update stores bot reference."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False

        health.update_from_bot(mock_bot)

        assert health.bot == mock_bot

    def test_update_from_bot_updates_heartbeat(self):
        """Test update updates heartbeat."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        old_heartbeat = health.last_heartbeat

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False

        import time
        time.sleep(0.01)
        health.update_from_bot(mock_bot)

        assert health.last_heartbeat >= old_heartbeat

    def test_update_from_bot_when_ready(self):
        """Test update when bot is ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        mock_guild1 = MagicMock()
        mock_guild1.member_count = 100
        mock_guild2 = MagicMock()
        mock_guild2.member_count = 50

        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05  # 50ms
        mock_bot.guilds = [mock_guild1, mock_guild2]
        mock_bot.cogs = {"AI": MagicMock(), "Music": MagicMock()}

        health.update_from_bot(mock_bot)

        assert health.is_ready is True
        assert health.latency_ms == 50.0
        assert health.guild_count == 2
        assert health.user_count == 150
        assert health.cogs_loaded == ["AI", "Music"]


# ==================== TestBotHealthDataIncrementers ====================


class TestBotHealthDataIncrementers:
    """Test BotHealthData counter incrementers."""

    def test_increment_message(self):
        """Test incrementing message count."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        assert health.message_count == 0

        health.increment_message()
        assert health.message_count == 1

        health.increment_message()
        assert health.message_count == 2

    def test_increment_command(self):
        """Test incrementing command count."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        assert health.command_count == 0

        health.increment_command()
        assert health.command_count == 1

    def test_increment_error(self):
        """Test incrementing error count."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        assert health.error_count == 0

        health.increment_error()
        assert health.error_count == 1


# ==================== TestBotHealthDataUptime ====================


class TestBotHealthDataUptime:
    """Test BotHealthData uptime methods."""

    def test_get_uptime_returns_timedelta(self):
        """Test get_uptime returns timedelta."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        uptime = health.get_uptime()

        assert isinstance(uptime, timedelta)

    def test_get_uptime_str_format_seconds(self):
        """Test uptime string format for seconds."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(seconds=30)

        uptime_str = health.get_uptime_str()

        assert "s" in uptime_str
        assert "30" in uptime_str or "29" in uptime_str or "31" in uptime_str

    def test_get_uptime_str_format_minutes(self):
        """Test uptime string format for minutes."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(minutes=5, seconds=30)

        uptime_str = health.get_uptime_str()

        assert "m" in uptime_str
        assert "5" in uptime_str

    def test_get_uptime_str_format_hours(self):
        """Test uptime string format for hours."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(hours=2, minutes=30)

        uptime_str = health.get_uptime_str()

        assert "h" in uptime_str
        assert "2" in uptime_str

    def test_get_uptime_str_format_days(self):
        """Test uptime string format for days."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.start_time = datetime.now() - timedelta(days=3, hours=5)

        uptime_str = health.get_uptime_str()

        assert "d" in uptime_str
        assert "3" in uptime_str


# ==================== TestBotHealthDataToDict ====================


class TestBotHealthDataToDict:
    """Test BotHealthData to_dict method."""

    def test_to_dict_returns_dict(self):
        """Test to_dict returns dictionary."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 10.5
            mock_proc.return_value.memory_info.return_value.rss = 100 * 1024 * 1024
            mock_proc.return_value.num_threads.return_value = 4

            data = health.to_dict()

        assert isinstance(data, dict)

    def test_to_dict_has_status(self):
        """Test to_dict includes status."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert "status" in data
        assert data["status"] == "starting"  # is_ready is False by default

    def test_to_dict_has_bot_section(self):
        """Test to_dict includes bot section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert "bot" in data
        assert "ready" in data["bot"]
        assert "latency_ms" in data["bot"]
        assert "guilds" in data["bot"]

    def test_to_dict_has_stats_section(self):
        """Test to_dict includes stats section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.message_count = 100
        health.command_count = 50
        health.error_count = 5

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert "stats" in data
        assert data["stats"]["messages_processed"] == 100
        assert data["stats"]["commands_executed"] == 50
        assert data["stats"]["errors"] == 5

    def test_to_dict_has_system_section(self):
        """Test to_dict includes system section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 25.5
            mock_proc.return_value.memory_info.return_value.rss = 512 * 1024 * 1024
            mock_proc.return_value.num_threads.return_value = 8

            data = health.to_dict()

        assert "system" in data
        assert data["system"]["cpu_percent"] == 25.5
        assert data["system"]["memory_mb"] == 512.0
        assert data["system"]["threads"] == 8


# ==================== TestBotHealthDataIsHealthy ====================


class TestBotHealthDataIsHealthy:
    """Test BotHealthData is_healthy method."""

    def test_is_healthy_false_when_not_ready(self):
        """Test is_healthy returns false when not ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = False

        assert health.is_healthy() is False

    def test_is_healthy_false_when_heartbeat_stale(self):
        """Test is_healthy returns false when heartbeat is stale."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 50
        health.last_heartbeat = datetime.now() - timedelta(seconds=120)

        assert health.is_healthy() is False

    def test_is_healthy_false_when_high_latency(self):
        """Test is_healthy returns false when latency is too high."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 6000  # 6 seconds
        health.last_heartbeat = datetime.now()

        assert health.is_healthy() is False

    def test_is_healthy_true_when_all_good(self):
        """Test is_healthy returns true when all checks pass."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True
        health.latency_ms = 50
        health.last_heartbeat = datetime.now()

        assert health.is_healthy() is True


# ==================== TestBotHealthDataGetAiPerformanceStats ====================


class TestBotHealthDataGetAiPerformanceStats:
    """Test BotHealthData AI performance stats."""

    def test_get_ai_performance_stats_no_bot(self):
        """Test getting AI stats with no bot."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        stats = health.get_ai_performance_stats()

        assert "error" in stats

    def test_get_ai_performance_stats_no_ai_cog(self):
        """Test getting AI stats with no AI cog."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.bot = MagicMock()
        health.bot.cogs = {}

        stats = health.get_ai_performance_stats()

        assert "error" in stats

    def test_get_ai_performance_stats_with_ai_cog(self):
        """Test getting AI stats with AI cog."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_ai_cog = MagicMock()
        mock_ai_cog.chat_manager.get_performance_stats.return_value = {
            "total_requests": 100,
            "avg_response_time": 1.5
        }
        mock_bot.cogs = {"AI": mock_ai_cog}
        health.bot = mock_bot

        stats = health.get_ai_performance_stats()

        assert stats["total_requests"] == 100
        assert stats["avg_response_time"] == 1.5


# ==================== TestGlobalHealthData ====================


class TestGlobalHealthData:
    """Test global health_data instance."""

    def test_health_data_exists(self):
        """Test global health_data instance exists."""
        from utils.monitoring.health_api import health_data

        assert health_data is not None

    def test_health_data_is_bot_health_data(self):
        """Test global health_data is BotHealthData instance."""
        from utils.monitoring.health_api import BotHealthData, health_data

        assert isinstance(health_data, BotHealthData)


# ==================== TestHealthRequestHandler ====================


class TestHealthRequestHandler:
    """Test HealthRequestHandler class."""

    def test_handler_class_exists(self):
        """Test HealthRequestHandler class exists."""
        from utils.monitoring.health_api import HealthRequestHandler

        assert HealthRequestHandler is not None

    def test_handler_log_message_suppressed(self):
        """Test log_message is suppressed."""
        from utils.monitoring.health_api import HealthRequestHandler

        # log_message should do nothing (suppressed)
        handler = MagicMock(spec=HealthRequestHandler)
        HealthRequestHandler.log_message(handler, "test %s", "arg")
        # No assertion needed - just verify no exception


# ==================== TestModuleImports ====================


class TestModuleImports:
    """Test module imports."""

    def test_import_health_api(self):
        """Test importing health_api module."""
        import utils.monitoring.health_api

        assert utils.monitoring.health_api is not None

    def test_import_bot_health_data(self):
        """Test importing BotHealthData class."""
        from utils.monitoring.health_api import BotHealthData

        assert BotHealthData is not None

    def test_import_health_request_handler(self):
        """Test importing HealthRequestHandler class."""
        from utils.monitoring.health_api import HealthRequestHandler

        assert HealthRequestHandler is not None

    def test_import_health_data(self):
        """Test importing global health_data."""
        from utils.monitoring.health_api import health_data

        assert health_data is not None


# ==================== TestHealthyStatus ====================


class TestHealthyStatus:
    """Test healthy status variations."""

    def test_status_starting_when_not_ready(self):
        """Test status is 'starting' when not ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = False

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert data["status"] == "starting"

    def test_status_healthy_when_ready(self):
        """Test status is 'healthy' when ready."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.is_ready = True

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert data["status"] == "healthy"


# ==================== TestTimestamp ====================


class TestTimestamp:
    """Test timestamp functionality."""

    def test_to_dict_has_timestamp(self):
        """Test to_dict includes timestamp."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert "timestamp" in data
        # Should be ISO format
        assert "T" in data["timestamp"]

    def test_to_dict_has_uptime(self):
        """Test to_dict includes uptime."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert "uptime" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)


# ==================== TestHeartbeat ====================


class TestHeartbeat:
    """Test heartbeat functionality."""

    def test_to_dict_has_heartbeat(self):
        """Test to_dict includes heartbeat section."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        assert "heartbeat" in data
        assert "last" in data["heartbeat"]
        assert "age_seconds" in data["heartbeat"]

    def test_heartbeat_age_calculation(self):
        """Test heartbeat age is calculated correctly."""
        from utils.monitoring.health_api import BotHealthData

        health = BotHealthData()
        health.last_heartbeat = datetime.now() - timedelta(seconds=30)

        with patch('utils.monitoring.health_api.psutil.Process') as mock_proc:
            mock_proc.return_value.cpu_percent.return_value = 0
            mock_proc.return_value.memory_info.return_value.rss = 0
            mock_proc.return_value.num_threads.return_value = 1

            data = health.to_dict()

        # Age should be approximately 30 seconds
        assert 28 <= data["heartbeat"]["age_seconds"] <= 32


# ======================================================================
# Merged from test_health_api_more.py
# ======================================================================

class TestBotHealthDataCounters:
    """Additional tests for BotHealthData counters."""

    def test_counters_independent(self):
        """Test counters are independent of each other."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        health.increment_message()
        health.increment_message()
        health.increment_command()
        health.increment_error()

        assert health.message_count == 2
        assert health.command_count == 1
        assert health.error_count == 1

    def test_counters_large_values(self):
        """Test counters can handle large values."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        health.message_count = 1000000
        health.increment_message()

        assert health.message_count == 1000001


class TestBotHealthDataBotAttribute:
    """Tests for bot attribute management."""

    def test_bot_none_initially(self):
        """Test bot is None initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        assert health.bot is None

    def test_bot_set_after_update(self):
        """Test bot is set after update_from_bot."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = False

        health.update_from_bot(mock_bot)

        assert health.bot is mock_bot


class TestBotHealthDataCogsLoaded:
    """Tests for cogs_loaded attribute."""

    def test_cogs_loaded_empty_initially(self):
        """Test cogs_loaded is empty initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        assert health.cogs_loaded == []

    def test_cogs_loaded_populated_when_ready(self):
        """Test cogs_loaded is populated when bot is ready."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = []
        mock_bot.cogs = {"Music": MagicMock(), "AI": MagicMock()}

        health.update_from_bot(mock_bot)

        assert "Music" in health.cogs_loaded
        assert "AI" in health.cogs_loaded


class TestBotHealthDataLatency:
    """Tests for latency attribute."""

    def test_latency_zero_initially(self):
        """Test latency is zero initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        assert health.latency_ms == 0.0

    def test_latency_converted_from_seconds(self):
        """Test latency is converted from seconds to ms."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.1  # 100ms
        mock_bot.guilds = []
        mock_bot.cogs = {}

        health.update_from_bot(mock_bot)

        assert health.latency_ms == 100.0


class TestBotHealthDataGuilds:
    """Tests for guild-related attributes."""

    def test_guild_count_zero_initially(self):
        """Test guild_count is zero initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        assert health.guild_count == 0

    def test_user_count_zero_initially(self):
        """Test user_count is zero initially."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        assert health.user_count == 0

    def test_guild_count_calculated(self):
        """Test guild_count is calculated from guilds."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = [MagicMock(member_count=50), MagicMock(member_count=100), MagicMock(member_count=25)]
        mock_bot.cogs = {}

        health.update_from_bot(mock_bot)

        assert health.guild_count == 3
        assert health.user_count == 175


class TestBotHealthDataUptimeEdgeCases:
    """Edge case tests for uptime methods."""

    def test_uptime_str_zero_seconds(self):
        """Test uptime_str with zero seconds."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        health.start_time = datetime.now()

        uptime_str = health.get_uptime_str()

        assert "s" in uptime_str

    def test_uptime_seconds_returns_int(self):
        """Test uptime_seconds in to_dict is int."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()

        result = health.to_dict()

        assert isinstance(result["uptime_seconds"], int)


class TestBotHealthDataNullMemberCount:
    """Tests for handling None member_count."""

    def test_handles_null_member_count(self):
        """Test handles guild with None member_count."""
        try:
            from utils.monitoring.health_api import BotHealthData
        except ImportError:
            pytest.skip("health_api not available")
            return

        health = BotHealthData()
        mock_bot = MagicMock()
        mock_bot.is_ready.return_value = True
        mock_bot.latency = 0.05
        mock_bot.guilds = [MagicMock(member_count=None), MagicMock(member_count=100)]
        mock_bot.cogs = {}

        health.update_from_bot(mock_bot)

        # Should handle None gracefully (treated as 0)
        assert health.user_count == 100
