"""
Health API Module for Discord Bot
Provides HTTP endpoints for health checks and monitoring.
"""

from __future__ import annotations

import asyncio
import hmac
import html
import json
import logging
import os
import platform
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any

import psutil

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from discord.ext.commands import Bot

# Configuration


def _env_int(name: str, default: int) -> int:
    """Read an int env var with a logged fallback on bad input.

    Previously ``int(os.getenv(...))`` would raise ``ValueError`` at
    module import time if an operator set ``HEALTH_API_PORT=foo``,
    bringing the whole bot down before any logging was visible.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "⚠️ %s=%r is not a valid integer; falling back to default %d",
            name,
            raw,
            default,
        )
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float env var with a logged fallback on bad input."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "⚠️ %s=%r is not a valid float; falling back to default %g",
            name,
            raw,
            default,
        )
        return default


HEALTH_API_PORT = _env_int("HEALTH_API_PORT", 8080)
_HEALTH_API_HOST_RAW = os.getenv("HEALTH_API_HOST", "127.0.0.1")
HEALTH_API_TOKEN = os.getenv("HEALTH_API_TOKEN", "")  # Bearer token for sensitive endpoints

# Security: If no auth token is set and host is not localhost, force localhost binding
_LOCALHOST_ADDRESSES = {"127.0.0.1", "localhost", "::1"}
if not HEALTH_API_TOKEN:
    # Auto-generate an ephemeral token rather than running with auth
    # disabled. Previously a missing token meant protected endpoints
    # served their data unauthenticated to any localhost listener — any
    # other process on the box (or a logged-in user) could scrape guild
    # names / latency / configured keys. Generate-once-per-process means
    # the operator MUST configure a real token if they want stable
    # access from a sidecar/Grafana, but the failure mode is now
    # "401 Unauthorized" instead of "silently exposed".
    import secrets

    HEALTH_API_TOKEN = secrets.token_urlsafe(32)
    # Don't log the generated token — it grants admin access to all
    # protected endpoints and the secret-redaction filter only matches
    # tokens with `key=`/`token=` style prefixes (not bare urlsafe).
    # Print enough to identify it (first 8 chars) so an operator can
    # discover it via stdout, but the full value lives only in memory.
    logger.warning(
        "⚠️ HEALTH_API_TOKEN not set; generated an ephemeral token "
        "(prefix=%s..., 32 bytes urlsafe). Set HEALTH_API_TOKEN in .env "
        "for a stable, persisted value.",
        HEALTH_API_TOKEN[:8],
    )

if _HEALTH_API_HOST_RAW not in _LOCALHOST_ADDRESSES and not os.getenv(
    "HEALTH_API_ALLOW_REMOTE", ""
):
    logger.warning(
        "⚠️ HEALTH_API_HOST=%s — forcing bind to 127.0.0.1. "
        "Set HEALTH_API_ALLOW_REMOTE=1 to opt into remote binding.",
        _HEALTH_API_HOST_RAW,
    )
    HEALTH_API_HOST = "127.0.0.1"
else:
    HEALTH_API_HOST = _HEALTH_API_HOST_RAW

# Health check thresholds (configurable via env vars)
HEARTBEAT_MAX_AGE_SECONDS = _env_int("HEALTH_HEARTBEAT_MAX_AGE", 60)
MAX_LATENCY_MS = _env_int("HEALTH_MAX_LATENCY_MS", 5000)


# External service URLs to health-check (validated to prevent SSRF)
def _validate_service_url(url: str, name: str) -> str:
    """Validate service URL is a safe localhost HTTP URL."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("Invalid scheme for %s: %s — falling back to default", name, url)
            return ""
        # Block userinfo injection (e.g. http://127.0.0.1@attacker.com/)
        if "@" in (parsed.netloc or ""):
            logger.warning("SSRF blocked: %s contains userinfo in URL", name)
            return ""
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            logger.warning("SSRF blocked: %s points to non-localhost: %s", name, url)
            return ""
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            logger.warning("Invalid port for %s", name)
            return ""
        return url
    except Exception:
        logger.warning("Failed to parse URL for %s — falling back to default", name)
        return ""


GO_HEALTH_API_URL = (
    _validate_service_url(
        os.getenv("GO_HEALTH_API_URL", "http://127.0.0.1:8082/health"), "GO_HEALTH_API_URL"
    )
    or "http://127.0.0.1:8082/health"
)
GO_URL_FETCHER_URL = (
    _validate_service_url(
        os.getenv("GO_URL_FETCHER_URL", "http://127.0.0.1:8081/health"), "GO_URL_FETCHER_URL"
    )
    or "http://127.0.0.1:8081/health"
)

# Endpoints that require authentication (when HEALTH_API_TOKEN is set).
# Anything that exposes guild names, user counts, cogs loaded, latency,
# or process state is information disclosure — gate them behind the
# token. The /health/live and /health/ready probes stay unauth'd because
# Kubernetes-style liveness/readiness probes need that.
_PROTECTED_ENDPOINTS = {
    "/",
    "/metrics",
    "/stats",
    "/stats/json",
    "/health",
    "/health/json",
    "/health/deep",
    "/health/status",
    "/ai/stats",
    "/ai/stats/json",
}


class BotHealthData:
    """Stores bot health metrics for the API."""

    def __init__(self) -> None:
        self.start_time: datetime = datetime.now(timezone.utc)
        self.bot: Bot | None = None
        self.last_heartbeat: datetime = datetime.now(timezone.utc)
        self._counter_lock = threading.Lock()  # Thread-safe lock for counters
        self._data_lock = threading.Lock()  # Thread-safe lock for bot data updates
        self.message_count: int = 0
        self.command_count: int = 0
        self.error_count: int = 0
        self.is_ready: bool = False
        self.latency_ms: float = 0.0
        self.guild_count: int = 0
        self.user_count: int = 0
        self.cogs_loaded: list[str] = []
        # External service health status
        self.service_health: dict[str, dict[str, Any]] = {}
        # Feature flags (populated from config.feature_flags)
        self.feature_flags: dict[str, bool] = {}
        # Cached process handle so cpu_percent(interval=None) can compute a
        # real delta. A fresh psutil.Process() each call always reports 0.0
        # because the "previous sample" tracked inside the object dies with
        # the previous instance. None means "construct lazily on first read"
        # so tests that mock psutil.Process at patch-time still see the mock.
        self._process: psutil.Process | None = None

    def _get_process(self) -> psutil.Process:
        if self._process is None:
            self._process = psutil.Process()
        return self._process

    def update_from_bot(self, bot: Bot) -> None:
        """Update health data from bot instance (thread-safe)."""
        with self._data_lock:
            self.bot = bot
            self.last_heartbeat = datetime.now(timezone.utc)
            self.is_ready = bot.is_ready()

            if bot.is_ready():
                self.latency_ms = bot.latency * 1000
                self.guild_count = len(bot.guilds)
                self.user_count = sum(g.member_count or 0 for g in bot.guilds)
                self.cogs_loaded = list(bot.cogs.keys())

    def increment_message(self) -> None:
        """Increment message counter (thread-safe)."""
        with self._counter_lock:
            self.message_count += 1

    def increment_command(self) -> None:
        """Increment command counter (thread-safe)."""
        with self._counter_lock:
            self.command_count += 1

    def increment_error(self) -> None:
        """Increment error counter (thread-safe)."""
        with self._counter_lock:
            self.error_count += 1

    def get_uptime(self) -> timedelta:
        """Get bot uptime."""
        return datetime.now(timezone.utc) - self.start_time

    def get_uptime_str(self) -> str:
        """Get formatted uptime string."""
        delta = self.get_uptime()
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m {seconds}s"
        elif hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def to_dict(self) -> dict[str, Any]:
        """Convert health data to dictionary (thread-safe).

        Calls ``cpu_percent(interval=None)`` so the value reported is the
        delta since the last call (cheap), rather than blocking for the
        default measurement window. The first call after process start
        always reports 0.0 — that's fine because health endpoints get
        polled regularly enough that the second call onwards is accurate.
        """
        process = self._get_process()
        # Non-blocking read: returns the delta since the last call. Requires
        # the same psutil.Process() instance across calls — see _get_process.
        cpu_percent = process.cpu_percent(interval=None)

        with self._data_lock:
            is_ready = self.is_ready
            latency_ms = self.latency_ms
            guild_count = self.guild_count
            user_count = self.user_count
            cogs_loaded = self.cogs_loaded.copy()
            last_heartbeat = self.last_heartbeat
            # Copy these under the lock too: a worker thread's json.dumps would
            # otherwise iterate them while check_service mutates service_health
            # on the event-loop thread ("dictionary changed size during iteration").
            service_health = dict(self.service_health)
            feature_flags = dict(self.feature_flags)

        with self._counter_lock:
            message_count = self.message_count
            command_count = self.command_count
            error_count = self.error_count

        return {
            "status": "healthy" if is_ready else "starting",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime": self.get_uptime_str(),
            "uptime_seconds": int(self.get_uptime().total_seconds()),
            "bot": {
                "ready": is_ready,
                "latency_ms": round(latency_ms, 2),
                "guilds": guild_count,
                "users": user_count,
                "cogs_loaded": len(cogs_loaded),
                "cogs": cogs_loaded,
            },
            "stats": {
                "messages_processed": message_count,
                "commands_executed": command_count,
                "errors": error_count,
            },
            "system": {
                "platform": platform.system(),
                "python_version": platform.python_version(),
                "cpu_percent": cpu_percent,
                "memory_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                "threads": process.num_threads(),
            },
            "heartbeat": {
                "last": last_heartbeat.isoformat(),
                "age_seconds": int((datetime.now(timezone.utc) - last_heartbeat).total_seconds()),
            },
            "services": service_health,
            "features": feature_flags,
        }

    def is_healthy(self) -> bool:
        """Check if bot is healthy (thread-safe)."""
        # Bot is healthy if:
        # 1. It's ready
        # 2. Heartbeat is recent (within configured threshold)
        # 3. Latency is reasonable (under configured threshold)

        with self._data_lock:
            is_ready = self.is_ready
            last_heartbeat = self.last_heartbeat
            latency_ms = self.latency_ms

        if not is_ready:
            return False

        heartbeat_age = (datetime.now(timezone.utc) - last_heartbeat).total_seconds()
        if heartbeat_age > HEARTBEAT_MAX_AGE_SECONDS:
            return False

        return latency_ms <= MAX_LATENCY_MS

    def get_ai_performance_stats(self) -> dict:
        """Get AI performance statistics from chat manager.

        Thread-safe: reads bot reference under lock, but calls
        get_performance_stats outside the lock to avoid holding it
        during potentially slow operations.
        """
        try:
            with self._data_lock:
                bot = self.bot
            if bot and hasattr(bot, "cogs"):
                ai_cog = bot.cogs.get("AI")
                if ai_cog and hasattr(ai_cog, "chat_manager"):
                    return ai_cog.chat_manager.get_performance_stats()  # type: ignore[no-any-return]
        except Exception as e:
            logger.debug("Failed to get AI performance stats: %s", e)
        return {"error": "AI cog not available or no stats collected"}


# Global health data instance
health_data = BotHealthData()


class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for health endpoints."""

    # Route stdlib's stdout-style access logs through our structured logger so
    # auth failures, scans, and other non-2xx responses leave a forensic trail.
    # The previous empty override silently dropped every access log line.
    def log_message(self, format: str, *args) -> None:
        try:
            msg = format % args
        except Exception:
            msg = " ".join(str(a) for a in args)
        # client_address is set by stdlib only when the handler is processing a
        # real connection. In unit tests / synthetic invocations it's missing —
        # fall back to "?" instead of crashing.
        client = "?"
        addr = getattr(self, "client_address", None)
        if isinstance(addr, tuple) and addr:
            client = str(addr[0])
        # Anything that isn't a 2xx is interesting (auth failures, scans, 4xx).
        # The first %args entry on stdlib's BaseHTTPRequestHandler is the
        # request line, the second is the status code as a string.
        status_str = args[1] if len(args) > 1 else ""
        if isinstance(status_str, str) and status_str.startswith(("4", "5")):
            logger.warning("health_api %s - %s", client, msg)
        else:
            logger.debug("health_api %s - %s", client, msg)

    def _send_json_response(
        self, data: dict, status: int = 200, *, allow_cors: bool = True
    ) -> None:
        """Send JSON response. Pass allow_cors=False for unauthenticated paths."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if allow_cors and status < 400:
            # Only attach the CORS header on successful, authenticated responses.
            # Dropping it for 4xx prevents cross-origin readers (any localhost
            # tab) from learning whether protected endpoints exist.
            self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.end_headers()
        # ensure_ascii=False: guild names / Discord usernames frequently
        # contain CJK / emoji / Thai characters; the default would
        # \u-escape them into garbage in the response body.
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def _send_text_response(self, text: str, status: int = 200) -> None:
        """Send plain text response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode())

    def _send_html_response(self, body: str, status: int = 200) -> None:
        """Send HTML response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if status < 400:
            self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _get_anime_theme_css(self) -> str:
        """Get shared anime theme CSS with sakura petals."""
        return """
        @import url('https://fonts.googleapis.com/css2?family=Zen+Maru+Gothic:wght@400;500;700&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Zen Maru Gothic', 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #2d1b4e 0%, #1a0a2e 50%, #0d0015 100%);
            min-height: 100vh; padding: 20px; color: #f8e8ff;
            overflow-x: hidden; position: relative;
        }
        /* Ambient sakura glow effects - corners */
        .ambient-glow {
            position: fixed; pointer-events: none; z-index: 0;
            border-radius: 50%; filter: blur(80px);
            animation: ambient-pulse 8s ease-in-out infinite alternate;
        }
        .glow-1 { width: 400px; height: 400px; top: -150px; left: -150px;
            background: radial-gradient(circle, rgba(255,182,193,0.4) 0%, rgba(255,105,180,0.1) 50%, transparent 70%); }
        .glow-2 { width: 350px; height: 350px; top: -100px; right: -100px;
            background: radial-gradient(circle, rgba(255,192,203,0.35) 0%, rgba(219,112,147,0.1) 50%, transparent 70%);
            animation-delay: 2s; }
        .glow-3 { width: 300px; height: 300px; bottom: -100px; left: -80px;
            background: radial-gradient(circle, rgba(255,105,180,0.3) 0%, rgba(199,21,133,0.1) 50%, transparent 70%);
            animation-delay: 4s; }
        .glow-4 { width: 320px; height: 320px; bottom: -120px; right: -100px;
            background: radial-gradient(circle, rgba(255,182,193,0.35) 0%, rgba(255,20,147,0.1) 50%, transparent 70%);
            animation-delay: 6s; }

        @keyframes ambient-pulse {
            0% { opacity: 0.6; transform: scale(1); }
            50% { opacity: 0.9; transform: scale(1.1); }
            100% { opacity: 0.7; transform: scale(1.05); }
        }

        .sakura-container { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; overflow: hidden; z-index: 0; }

        /* Multiple sakura petal types */
        .sakura { position: absolute; opacity: 0; animation: fall linear forwards; }
        .sakura-1 { width: 12px; height: 12px; background: linear-gradient(135deg, #ffd1dc 0%, #ffb7c5 100%);
            border-radius: 50% 0 50% 50%; box-shadow: 0 0 8px rgba(255,209,220,0.6); }
        .sakura-2 { width: 16px; height: 16px; background: linear-gradient(135deg, #ffb7c5 0%, #ff69b4 100%);
            border-radius: 50% 0 50% 50%; box-shadow: 0 0 12px rgba(255,105,180,0.5); }
        .sakura-3 { width: 10px; height: 10px; background: linear-gradient(135deg, #ffe4e9 0%, #ffc0cb 100%);
            border-radius: 50% 0 50% 50%; box-shadow: 0 0 6px rgba(255,192,203,0.4); }
        .sakura-4 { width: 18px; height: 18px; background: linear-gradient(135deg, #ff85a2 0%, #ff1493 100%);
            border-radius: 50% 0 50% 50%; box-shadow: 0 0 15px rgba(255,20,147,0.6); }
        .sakura-5 { width: 8px; height: 8px; background: radial-gradient(circle, #fff 0%, #ffb7c5 100%);
            border-radius: 50%; box-shadow: 0 0 10px rgba(255,255,255,0.8); } /* sparkle */

        @keyframes fall {
            0% { transform: translateY(-50px) translateX(0) rotate(0deg) scale(1); opacity: 0; }
            5% { opacity: 0.9; }
            25% { transform: translateY(25vh) translateX(30px) rotate(180deg) scale(0.95); }
            50% { transform: translateY(50vh) translateX(-20px) rotate(360deg) scale(0.9); }
            75% { transform: translateY(75vh) translateX(40px) rotate(540deg) scale(0.85); }
            95% { opacity: 0.7; }
            100% { transform: translateY(105vh) translateX(10px) rotate(720deg) scale(0.7); opacity: 0; }
        }
        @keyframes fall2 {
            0% { transform: translateY(-50px) translateX(0) rotate(45deg) scale(1); opacity: 0; }
            5% { opacity: 0.85; }
            30% { transform: translateY(30vh) translateX(-40px) rotate(225deg) scale(0.9); }
            60% { transform: translateY(60vh) translateX(25px) rotate(405deg) scale(0.8); }
            100% { transform: translateY(105vh) translateX(-15px) rotate(585deg) scale(0.6); opacity: 0; }
        }
        @keyframes fall3 {
            0% { transform: translateY(-30px) rotate(90deg) scale(0.8); opacity: 0; }
            10% { opacity: 1; }
            50% { transform: translateY(50vh) translateX(50px) rotate(450deg) scale(0.7); }
            100% { transform: translateY(110vh) translateX(-30px) rotate(810deg) scale(0.5); opacity: 0; }
        }
        .container { max-width: 900px; margin: 0 auto; position: relative; z-index: 1; }
        h1 { text-align: center; margin-bottom: 30px; font-size: 2.2em; font-weight: 700;
            background: linear-gradient(90deg, #ffb7c5, #ff69b4, #ffb7c5); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            text-shadow: 0 0 30px rgba(255,105,180,0.5); animation: glow 2s ease-in-out infinite alternate; }
        @keyframes glow { from { filter: drop-shadow(0 0 5px rgba(255,105,180,0.5)); } to { filter: drop-shadow(0 0 20px rgba(255,105,180,0.8)); } }
        .subtitle { text-align: center; color: #c9a0dc; margin-bottom: 25px; font-size: 0.95em; }
        .subtitle a { color: #ffb7c5; text-decoration: none; } .subtitle a:hover { color: #ff69b4; text-shadow: 0 0 10px #ff69b4; }
        .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; }
        .card { background: rgba(255,183,197,0.08); backdrop-filter: blur(15px); border: 1px solid rgba(255,183,197,0.2);
            border-radius: 16px; padding: 20px; transition: all 0.4s ease; }
        .card:hover { transform: translateY(-8px) scale(1.02); box-shadow: 0 15px 40px rgba(255,105,180,0.3); border-color: rgba(255,105,180,0.5); }
        .card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 15px; }
        .icon { font-size: 1.8em; } .name { font-size: 1.15em; font-weight: 600; color: #ffb7c5; }
        .stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .stats.four-cols { grid-template-columns: repeat(4, 1fr); }
        .stat { text-align: center; padding: 8px; background: rgba(0,0,0,0.2); border-radius: 8px; }
        .value { display: block; font-size: 1.5em; font-weight: 700; color: #fff; }
        .value.highlight { color: #ff69b4; }
        .label { font-size: 0.7em; color: #c9a0dc; text-transform: uppercase; }
        .status-badge { display: inline-block; padding: 6px 16px; border-radius: 20px; font-weight: 600; }
        .status-healthy { background: linear-gradient(90deg, #2ecc71, #27ae60); color: #fff; }
        .status-unhealthy { background: linear-gradient(90deg, #e74c3c, #c0392b); color: #fff; }
        .footer { text-align: center; margin-top: 35px; color: #8b6b9e; font-size: 0.85em; border-top: 1px solid rgba(255,183,197,0.1); padding-top: 15px; }
        .footer a { color: #ffb7c5; text-decoration: none; margin: 0 10px; } .footer a:hover { color: #ff69b4; }
        .nav-links { text-align: center; margin-bottom: 25px; }
        .nav-links a { display: inline-block; padding: 8px 20px; margin: 5px; background: rgba(255,183,197,0.15);
            border: 1px solid rgba(255,183,197,0.3); border-radius: 25px; color: #ffb7c5; text-decoration: none; font-size: 0.9em; transition: all 0.3s; }
        .nav-links a:hover, .nav-links a.active { background: rgba(255,105,180,0.3); border-color: #ff69b4; box-shadow: 0 0 15px rgba(255,105,180,0.4); }
        """

    def _get_sakura_js(self, json_endpoint: str | None = None, refresh_interval: int = 5000) -> str:
        """Get JavaScript for animated sakura petals and optional data refresh."""
        refresh_script = ""
        if json_endpoint:
            refresh_script = f"""
        // Auto-refresh data without page reload
        async function refreshData() {{
            try {{
                const resp = await fetch('{json_endpoint}');
                const data = await resp.json();
                // Update card values dynamically
                document.querySelectorAll('.stat .value').forEach((el, i) => {{
                    const keys = Object.keys(data);
                    // This is a simplified update - specific pages override this
                }});
            }} catch(e) {{ console.log('Refresh failed:', e); }}
        }}
        setInterval(refreshData, {refresh_interval});
        """

        return f"""<script>
        // Enhanced Sakura petals animation with variety
        const sakuraTypes = ['sakura-1', 'sakura-2', 'sakura-3', 'sakura-4', 'sakura-5'];
        const animations = ['fall', 'fall2', 'fall3'];

        function createSakura() {{
            const c = document.querySelector('.sakura-container'); if(!c) return;
            const p = document.createElement('div');
            const type = sakuraTypes[Math.floor(Math.random() * sakuraTypes.length)];
            const anim = animations[Math.floor(Math.random() * animations.length)];
            p.className = 'sakura ' + type;
            p.style.left = Math.random() * 100 + '%';
            p.style.animationName = anim;
            p.style.animationDuration = (Math.random() * 8 + 6) + 's';
            p.style.animationDelay = (Math.random() * 2) + 's';
            c.appendChild(p);
            setTimeout(() => p.remove(), 16000);
        }}

        // Create petals at varying intervals for natural effect
        setInterval(createSakura, 250);
        setInterval(() => {{ for(let i=0; i<2; i++) createSakura(); }}, 800);

        // Initial burst of petals
        for(let i = 0; i < 20; i++) setTimeout(createSakura, i * 150);
        {refresh_script}
        </script>"""

    def _generate_health_html(self, data: dict) -> str:
        """Generate anime-themed HTML for health check."""
        is_healthy = data.get("status") == "healthy"
        bot = data.get("bot", {})
        system = data.get("system", {})
        stats = data.get("stats", {})
        # Escape string values that could potentially contain user-influenced data
        uptime_escaped = html.escape(str(data.get("uptime", "N/A")))
        return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌸 Bot Health</title><style>{self._get_anime_theme_css()}</style></head><body>
<div class="ambient-glow glow-1"></div><div class="ambient-glow glow-2"></div><div class="ambient-glow glow-3"></div><div class="ambient-glow glow-4"></div>
<div class="sakura-container"></div><div class="container">
<h1>🌸 Bot Health Check</h1>
<p class="subtitle"><span class="status-badge {"status-healthy" if is_healthy else "status-unhealthy"}">{"✨ Healthy" if is_healthy else "⚠️ Unhealthy"}</span></p>
<div class="nav-links"><a href="/ai/stats">🤖 AI Stats</a><a href="/health" class="active">💚 Health</a><a href="/stats">📊 Quick Stats</a></div>
<div class="cards">
<div class="card" style="border-left:4px solid #2ecc71;"><div class="card-header"><span class="icon">🤖</span><span class="name">Bot Info</span></div>
<div class="stats"><div class="stat"><span class="value">{uptime_escaped}</span><span class="label">Uptime</span></div>
<div class="stat"><span class="value highlight">{bot.get("latency_ms", 0):.0f}ms</span><span class="label">Latency</span></div></div></div>
<div class="card" style="border-left:4px solid #3498db;"><div class="card-header"><span class="icon">🌐</span><span class="name">Discord</span></div>
<div class="stats"><div class="stat"><span class="value">{bot.get("guilds", 0)}</span><span class="label">Guilds</span></div>
<div class="stat"><span class="value">{bot.get("users", 0)}</span><span class="label">Users</span></div></div></div>
<div class="card" style="border-left:4px solid #9b59b6;"><div class="card-header"><span class="icon">💻</span><span class="name">System</span></div>
<div class="stats"><div class="stat"><span class="value">{(system.get("memory_mb") or 0):.0f}MB</span><span class="label">Memory</span></div>
<div class="stat"><span class="value">{system.get("cpu_percent", 0):.1f}%</span><span class="label">CPU</span></div></div></div>
<div class="card" style="border-left:4px solid #e74c3c;"><div class="card-header"><span class="icon">📊</span><span class="name">Stats</span></div>
<div class="stats"><div class="stat"><span class="value">{stats.get("messages_processed", 0)}</span><span class="label">Messages</span></div>
<div class="stat"><span class="value">{stats.get("errors", 0)}</span><span class="label">Errors</span></div></div></div>
</div><p class="footer">🌸 Cogs: {html.escape(", ".join(bot.get("cogs", [])))} | <a href="/health/json">View JSON</a></p>
</div>{self._get_sakura_js()}</body></html>"""

    def _generate_stats_html(self, data: dict) -> str:
        """Generate anime-themed HTML for quick stats."""
        uptime_escaped = html.escape(str(data.get("uptime", "N/A")))
        return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌸 Quick Stats</title><style>{self._get_anime_theme_css()}</style></head><body>
<div class="sakura-tree-left"><div class="tree-trunk"></div><div class="tree-branch tree-branch-1"></div><div class="tree-branch tree-branch-2"></div><div class="tree-branch tree-branch-3"></div><div class="tree-bloom bloom-1"></div><div class="tree-bloom bloom-2"></div><div class="tree-bloom bloom-3"></div><div class="tree-bloom bloom-4"></div><div class="tree-bloom bloom-5"></div></div>
<div class="sakura-tree-right"><div class="tree-trunk"></div><div class="tree-branch tree-branch-1"></div><div class="tree-branch tree-branch-2"></div><div class="tree-branch tree-branch-3"></div><div class="tree-bloom bloom-1"></div><div class="tree-bloom bloom-2"></div><div class="tree-bloom bloom-3"></div><div class="tree-bloom bloom-4"></div><div class="tree-bloom bloom-5"></div></div>
<div class="sakura-container"></div><div class="container">
<h1>🌸 Quick Stats</h1><p class="subtitle">✨ Auto-refresh every 5s</p>
<div class="nav-links"><a href="/ai/stats">🤖 AI Stats</a><a href="/health">💚 Health</a><a href="/stats" class="active">📊 Quick Stats</a></div>
<div class="cards">
<div class="card" style="border-left:4px solid #00d9ff;"><div class="card-header"><span class="icon">⏰</span><span class="name">Uptime</span></div>
<div class="stats"><div class="stat"><span class="value highlight">{uptime_escaped}</span><span class="label">Duration</span></div></div></div>
<div class="card" style="border-left:4px solid #2ecc71;"><div class="card-header"><span class="icon">💬</span><span class="name">Messages</span></div>
<div class="stats"><div class="stat"><span class="value">{data.get("messages", 0)}</span><span class="label">Processed</span></div></div></div>
<div class="card" style="border-left:4px solid #9b59b6;"><div class="card-header"><span class="icon">⚡</span><span class="name">Commands</span></div>
<div class="stats"><div class="stat"><span class="value">{data.get("commands", 0)}</span><span class="label">Executed</span></div></div></div>
<div class="card" style="border-left:4px solid #e74c3c;"><div class="card-header"><span class="icon">⚠️</span><span class="name">Errors</span></div>
<div class="stats"><div class="stat"><span class="value">{data.get("errors", 0)}</span><span class="label">Total</span></div></div></div>
<div class="card" style="border-left:4px solid #f39c12;"><div class="card-header"><span class="icon">🌐</span><span class="name">Guilds</span></div>
<div class="stats"><div class="stat"><span class="value">{data.get("guilds", 0)}</span><span class="label">Connected</span></div></div></div>
<div class="card" style="border-left:4px solid #ff69b4;"><div class="card-header"><span class="icon">📡</span><span class="name">Latency</span></div>
<div class="stats"><div class="stat"><span class="value highlight">{data.get("latency_ms", 0):.0f}ms</span><span class="label">Discord</span></div></div></div>
</div><p class="footer">🌸 Bot Health API | <a href="/stats/json">View JSON</a></p>
</div>{self._get_sakura_js()}</body></html>"""

    def _generate_ai_stats_html(self, stats: dict) -> str:
        """Generate anime-themed HTML dashboard for AI stats."""
        if "error" in stats:
            error_msg = html.escape(str(stats["error"]))  # Escape for XSS protection
            return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌸 AI Stats - Error</title><style>{self._get_anime_theme_css()}
.error-box {{ text-align: center; padding: 60px 40px; }} .error-icon {{ font-size: 4em; margin-bottom: 20px; }}
</style></head><body><div class="sakura-container"></div><div class="container">
<div class="card error-box"><div class="error-icon">😿</div><h1>Oops!</h1><p style="color:#ff69b4;">{error_msg}</p></div>
<p class="footer"><a href="/">← Back to Home</a></p></div>{self._get_sakura_js()}</body></html>"""

        cards_html = ""
        colors = {
            "rag_search": "#00d9ff",
            "api_call": "#ff6b6b",
            "streaming": "#feca57",
            "post_process": "#c56cf0",
            "total": "#1dd1a1",
        }
        icons = {
            "rag_search": "🧠",
            "api_call": "🤖",
            "streaming": "📡",
            "post_process": "⚙️",
            "total": "📊",
        }
        names = {
            "rag_search": "RAG Search",
            "api_call": "API Call",
            "streaming": "Streaming",
            "post_process": "Post Process",
            "total": "Total",
        }

        for key, data in stats.items():
            color = colors.get(key, "#ff69b4")
            escaped_name = html.escape(names.get(key, key))
            cards_html += f"""
<div class="card" style="border-left:4px solid {color};"><div class="card-header"><span class="icon">{icons.get(key, "📈")}</span><span class="name">{escaped_name}</span></div>
<div class="stats four-cols"><div class="stat"><span class="value">{data.get("count", 0)}</span><span class="label">Calls</span></div>
<div class="stat"><span class="value highlight">{data.get("avg_ms", 0):.1f}</span><span class="label">Avg ms</span></div>
<div class="stat"><span class="value">{data.get("min_ms", 0):.1f}</span><span class="label">Min ms</span></div>
<div class="stat"><span class="value">{data.get("max_ms", 0):.1f}</span><span class="label">Max ms</span></div></div></div>"""

        return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌸 AI Performance Dashboard</title><style>{self._get_anime_theme_css()}</style></head><body>
<div class="sakura-tree-left"><div class="tree-trunk"></div><div class="tree-branch tree-branch-1"></div><div class="tree-branch tree-branch-2"></div><div class="tree-branch tree-branch-3"></div><div class="tree-bloom bloom-1"></div><div class="tree-bloom bloom-2"></div><div class="tree-bloom bloom-3"></div><div class="tree-bloom bloom-4"></div><div class="tree-bloom bloom-5"></div></div>
<div class="sakura-tree-right"><div class="tree-trunk"></div><div class="tree-branch tree-branch-1"></div><div class="tree-branch tree-branch-2"></div><div class="tree-branch tree-branch-3"></div><div class="tree-bloom bloom-1"></div><div class="tree-bloom bloom-2"></div><div class="tree-bloom bloom-3"></div><div class="tree-bloom bloom-4"></div><div class="tree-bloom bloom-5"></div></div>
<div class="sakura-container"></div><div class="container">
<h1>🌸 AI Performance Dashboard</h1>
<p class="subtitle">✨ Auto-refresh every 5s | <a href="/ai/stats/json">View JSON</a></p>
<div class="nav-links"><a href="/ai/stats" class="active">🤖 AI Stats</a><a href="/health">💚 Health</a><a href="/stats">📊 Quick Stats</a></div>
<div class="cards">{cards_html}</div>
<p class="footer">🌸 Bot Health API | Made with 💖</p>
</div>{self._get_sakura_js()}</body></html>"""

    def do_GET(self) -> None:
        """Handle GET requests."""
        path = self.path.split("?")[0]  # Remove query string

        # Check authentication for protected endpoints
        # When HEALTH_API_TOKEN is set, require it for sensitive endpoints.
        # When not set, only allow requests from localhost (enforced by binding).
        if path in _PROTECTED_ENDPOINTS:
            if HEALTH_API_TOKEN:
                auth_header = self.headers.get("Authorization", "")
                expected = f"Bearer {HEALTH_API_TOKEN}"
                if not hmac.compare_digest(auth_header, expected):
                    self._send_json_response(
                        {"error": "Unauthorized", "message": "Valid Bearer token required"},
                        401,
                    )
                    return

        if path == "/health":
            # Full health check (HTML dashboard)
            data = health_data.to_dict()
            health_html = self._generate_health_html(data)
            self._send_html_response(health_html)

        elif path in {"/", "/health/json"}:
            # Full health check (JSON)
            data = health_data.to_dict()
            status = 200 if health_data.is_healthy() else 503
            self._send_json_response(data, status)

        elif path in {"/health/live", "/livez"}:
            # Kubernetes liveness probe - is the process running?
            self._send_json_response(
                {"status": "alive", "timestamp": datetime.now(timezone.utc).isoformat()}
            )

        elif path in {"/health/ready", "/readyz"}:
            # Kubernetes readiness probe - is the bot fully healthy + ready?
            # Use the full is_healthy() rather than just is_ready so a bot
            # with a stuck heartbeat or runaway latency stops getting
            # traffic. is_healthy() also takes the data lock so we don't
            # race with update_from_bot.
            if health_data.is_healthy():
                self._send_json_response(
                    {
                        "status": "ready",
                        "latency_ms": round(health_data.latency_ms, 2),
                        "guilds": health_data.guild_count,
                    }
                )
            else:
                self._send_json_response(
                    {"status": "not_ready", "message": "Bot is still starting up or unhealthy"}, 503
                )

        elif path == "/health/status":
            # Simple status endpoint (for uptime monitors)
            if health_data.is_healthy():
                self._send_text_response("OK")
            else:
                self._send_text_response("UNHEALTHY", 503)

        elif path == "/health/deep":
            # Deep health check - tests all subsystems
            deep_result = self._perform_deep_health_check()
            status = 200 if deep_result["healthy"] else 503
            self._send_json_response(deep_result, status)

        elif path == "/metrics":
            # Prometheus-style metrics
            metrics = self._generate_prometheus_metrics()
            self._send_text_response(metrics)

        elif path == "/stats":
            # Quick stats (HTML dashboard). Snapshot the counters under
            # the lock so concurrent increments can't tear a multi-byte
            # int on platforms without atomic 64-bit ops.
            with health_data._counter_lock:
                msg_ct = health_data.message_count
                cmd_ct = health_data.command_count
                err_ct = health_data.error_count
            data = {
                "uptime": health_data.get_uptime_str(),
                "messages": msg_ct,
                "commands": cmd_ct,
                "errors": err_ct,
                "guilds": health_data.guild_count,
                "latency_ms": round(health_data.latency_ms, 2),
            }
            stats_html = self._generate_stats_html(data)
            self._send_html_response(stats_html)

        elif path == "/stats/json":
            # Quick stats (JSON) — same lock-protected snapshot as /stats.
            with health_data._counter_lock:
                msg_ct = health_data.message_count
                cmd_ct = health_data.command_count
                err_ct = health_data.error_count
            self._send_json_response(
                {
                    "uptime": health_data.get_uptime_str(),
                    "messages": msg_ct,
                    "commands": cmd_ct,
                    "errors": err_ct,
                    "guilds": health_data.guild_count,
                    "latency_ms": round(health_data.latency_ms, 2),
                }
            )

        elif path == "/ai/stats":
            # AI performance dashboard (HTML UI)
            ai_stats = health_data.get_ai_performance_stats()
            ai_html = self._generate_ai_stats_html(ai_stats)
            self._send_html_response(ai_html)

        elif path == "/ai/stats/json":
            # AI performance stats (raw JSON)
            ai_stats = health_data.get_ai_performance_stats()
            self._send_json_response(ai_stats)

        else:
            # 404 Not Found
            self._send_json_response(
                {
                    "error": "Not Found",
                    "available_endpoints": [
                        "/health - Full health check",
                        "/health/live - Liveness probe",
                        "/health/ready - Readiness probe",
                        "/health/status - Simple OK/UNHEALTHY",
                        "/health/deep - Deep health check (DB, APIs)",
                        "/metrics - Prometheus metrics",
                        "/stats - Quick statistics",
                        "/ai/stats - AI performance metrics",
                    ],
                },
                404,
            )

    def _generate_prometheus_metrics(self) -> str:
        """Generate Prometheus-compatible metrics."""
        process = health_data._get_process()

        # Snapshot every counter under the same locks to_dict() uses.
        # Without this, Prometheus scrapes can read torn state while
        # update_from_bot() is mid-write, producing inconsistent
        # adjacent gauges (e.g. is_ready=true with latency_ms still 0).
        with health_data._data_lock:
            is_ready = health_data.is_ready
            latency_ms = health_data.latency_ms
            guild_count = health_data.guild_count
            user_count = health_data.user_count
        with health_data._counter_lock:
            message_count = health_data.message_count
            command_count = health_data.command_count
            error_count = health_data.error_count
        uptime_seconds = int(health_data.get_uptime().total_seconds())

        # cpu_percent(interval=None) is delta-based and requires the
        # singleton process handle. cpu_percent() with no arg blocks 0.1s.
        cpu_percent = process.cpu_percent(interval=None)
        memory_rss = process.memory_info().rss
        num_threads = process.num_threads()

        lines = [
            "# HELP discord_bot_up Bot is up and running",
            "# TYPE discord_bot_up gauge",
            f"discord_bot_up {1 if is_ready else 0}",
            "",
            "# HELP discord_bot_latency_ms Discord API latency in milliseconds",
            "# TYPE discord_bot_latency_ms gauge",
            f"discord_bot_latency_ms {latency_ms:.2f}",
            "",
            "# HELP discord_bot_guilds Number of guilds the bot is in",
            "# TYPE discord_bot_guilds gauge",
            f"discord_bot_guilds {guild_count}",
            "",
            "# HELP discord_bot_users Total users across all guilds",
            "# TYPE discord_bot_users gauge",
            f"discord_bot_users {user_count}",
            "",
            "# HELP discord_bot_messages_total Total messages processed",
            "# TYPE discord_bot_messages_total counter",
            f"discord_bot_messages_total {message_count}",
            "",
            "# HELP discord_bot_commands_total Total commands executed",
            "# TYPE discord_bot_commands_total counter",
            f"discord_bot_commands_total {command_count}",
            "",
            "# HELP discord_bot_errors_total Total errors",
            "# TYPE discord_bot_errors_total counter",
            f"discord_bot_errors_total {error_count}",
            "",
            "# HELP discord_bot_uptime_seconds Bot uptime in seconds",
            "# TYPE discord_bot_uptime_seconds counter",
            f"discord_bot_uptime_seconds {uptime_seconds}",
            "",
            "# HELP process_cpu_percent CPU usage percentage",
            "# TYPE process_cpu_percent gauge",
            f"process_cpu_percent {cpu_percent}",
            "",
            "# HELP process_memory_bytes Memory usage in bytes",
            "# TYPE process_memory_bytes gauge",
            f"process_memory_bytes {memory_rss}",
            "",
            "# HELP process_threads Number of threads",
            "# TYPE process_threads gauge",
            f"process_threads {num_threads}",
        ]

        return "\n".join(lines) + "\n"

    def _perform_deep_health_check(self) -> dict[str, Any]:
        """Perform deep health check on all subsystems."""
        checks: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "healthy": True,
            "checks": {},
        }

        # 1. Bot status check
        checks["checks"]["bot"] = {
            "status": "ok" if health_data.is_ready else "not_ready",
            "latency_ms": round(health_data.latency_ms, 2),
            "guilds": health_data.guild_count,
        }
        if not health_data.is_ready:
            checks["healthy"] = False

        # 2. Database check
        try:
            from utils.database import db

            # Execute the async health check in the main event loop
            if (
                health_data.bot
                and hasattr(health_data.bot, "loop")
                and isinstance(health_data.bot.loop, asyncio.AbstractEventLoop)
                and db
            ):
                fut = asyncio.run_coroutine_threadsafe(db.health_check(), health_data.bot.loop)
                try:
                    is_healthy = fut.result(timeout=2.0)
                    if is_healthy:
                        checks["checks"]["database"] = {"status": "ok", "type": "sqlite+aiosqlite"}
                    else:
                        checks["checks"]["database"] = {"status": "error", "error": "Query failed"}
                        checks["healthy"] = False
                except TimeoutError:
                    fut.cancel()
                    checks["checks"]["database"] = {"status": "error", "error": "DB Check Timeout"}
                    checks["healthy"] = False
                except Exception as e:
                    fut.cancel()
                    checks["checks"]["database"] = {
                        "status": "error",
                        "error": f"DB Check Error: {e}",
                    }
                    checks["healthy"] = False
            else:
                # Fallback to file existence check if bot loop isn't ready
                db_path = Path("data") / "bot_database.db"
                if db_path.exists():
                    checks["checks"]["database"] = {"status": "ok", "type": "sqlite+aiosqlite"}
                else:
                    checks["checks"]["database"] = {
                        "status": "warning",
                        "error": "DB file not found",
                    }
        except Exception as e:
            checks["checks"]["database"] = {"status": "error", "error": str(e)[:100]}
            checks["healthy"] = False

        # 3. API Keys check (existence only, not validity).
        # Do NOT enumerate which keys are present/absent — that tells an
        # attacker exactly which integrations they can probe (e.g. a
        # missing GEMINI_API_KEY signals "Anthropic-only deployment, go
        # try a prompt injection on the Claude path"). Report aggregate
        # presence instead.
        spotify_client_id = os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
        spotify_client_secret = os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv(
            "SPOTIFY_CLIENT_SECRET"
        )
        api_keys = {
            "DISCORD_TOKEN": bool(os.getenv("DISCORD_TOKEN")),
            "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
            "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
            "SPOTIPY_CLIENT_ID": bool(spotify_client_id),
            "SPOTIPY_CLIENT_SECRET": bool(spotify_client_secret),
        }
        configured_count = sum(1 for v in api_keys.values() if v)
        total_count = len(api_keys)
        checks["checks"]["api_keys"] = {
            "status": "ok" if configured_count == total_count else "warning",
            "api_keys_configured": configured_count,
            "api_keys_total": total_count,
        }

        # 4. Filesystem check
        try:
            test_file = Path("temp") / ".health_check"
            test_file.parent.mkdir(exist_ok=True)
            test_file.write_text("test")
            test_file.unlink()
            checks["checks"]["filesystem"] = {"status": "ok", "writable": True}
        except Exception as e:
            checks["checks"]["filesystem"] = {"status": "error", "error": str(e)[:100]}

        # 5. Memory check. Use the configurable threshold from
        # ``MemoryMonitor`` defaults so this endpoint matches whatever the
        # cleanup loop is actually reacting to (was hardcoded 500 MB,
        # which was wildly out of sync with the 8 GB/16 GB reality).
        # Reuse the singleton process handle from the module-level
        # ``health_data`` so ``cpu_percent(interval=None)`` callers
        # downstream have a real "previous sample" to diff against
        # (a fresh `psutil.Process()` always reports 0.0% on first call).
        process = health_data._get_process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        try:
            # The actual threshold the cleanup loop uses lives on the
            # ``memory_monitor`` singleton, not as a class attribute —
            # the previous ``MemoryMonitor.DEFAULT_WARNING_MB`` lookup
            # never resolved and always fell back to the 8 GiB default,
            # while the real cleanup fires at 1 GiB.
            from utils.reliability.memory_manager import memory_monitor as _mm

            mem_warning = float(getattr(_mm, "warning_mb", 1024))
        except Exception:
            mem_warning = 1024.0
        checks["checks"]["memory"] = {
            "status": "ok" if memory_mb < mem_warning else "warning",
            "usage_mb": round(memory_mb, 2),
            "threshold_mb": mem_warning,
        }

        # 6. Circuit breaker status
        try:
            from utils.reliability.circuit_breaker import gemini_circuit

            if gemini_circuit:
                cb_status = gemini_circuit.get_status()
                cb_state = cb_status.get("state", "unknown")
                checks["checks"]["circuit_breaker"] = {
                    "status": "ok" if cb_state == "closed" else "warning",
                    "state": cb_state,
                    "failure_count": cb_status.get("failure_count", 0),
                }
                if cb_state == "open":
                    checks["healthy"] = False
        except ImportError:
            checks["checks"]["circuit_breaker"] = {"status": "not_available"}

        # 7. FFmpeg availability
        try:
            from utils.media import get_ffmpeg_executable, is_ffmpeg_available

            available = is_ffmpeg_available()
            checks["checks"]["ffmpeg"] = {
                "status": "ok" if available else "warning",
                "available": available,
                "path": get_ffmpeg_executable() if available else None,
            }
        except Exception:
            checks["checks"]["ffmpeg"] = {"status": "unknown"}

        return checks


class HealthAPIServer:
    """Health API Server that runs in a separate thread."""

    def __init__(self, host: str = HEALTH_API_HOST, port: int = HEALTH_API_PORT) -> None:
        self.host = host
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: Thread | None = None
        self.running = False

    def start(self) -> bool:
        """Start the health API server."""
        if self.running:
            return True

        try:
            # ThreadingHTTPServer so a slow request (DB liveness probe, deep
            # health) doesn't block other concurrent health checks.
            self.server = ThreadingHTTPServer((self.host, self.port), HealthRequestHandler)
            self.thread = Thread(target=self._run_server, daemon=True)
            self.thread.start()
            self.running = True
            logger.info(
                "🏥 Health API started at http://%s:%d",
                self.host if self.host != "0.0.0.0" else "localhost",  # nosec B104  # string compare, not bind
                self.port,
            )
            return True
        except Exception:
            # Broad catch: ThreadingHTTPServer construction can raise more than
            # OSError (e.g. ValueError on a bad host). Any failure here must
            # degrade to "health API unavailable", never crash the caller's
            # startup path.
            logger.exception("❌ Failed to start Health API")
            return False

    def _run_server(self) -> None:
        """Run the server (called in separate thread)."""
        if self.server:
            self.server.serve_forever()

    def stop(self) -> None:
        """Stop the health API server."""
        if self.server:
            self.server.shutdown()
            # Release the listen socket immediately — without server_close()
            # the FD lingers until the ThreadingHTTPServer object is GC'd,
            # which can leak across hot reloads.
            try:
                self.server.server_close()
            except Exception:
                logger.debug("Health server socket close failed", exc_info=True)
            self.running = False
            logger.info("🏥 Health API stopped")


# Global server instance
_health_server: HealthAPIServer | None = None
_health_server_lock = threading.Lock()


def start_health_api(host: str = HEALTH_API_HOST, port: int = HEALTH_API_PORT) -> bool:
    """Start the health API server."""
    global _health_server

    with _health_server_lock:
        if _health_server is None:
            _health_server = HealthAPIServer(host, port)

        return _health_server.start()


def stop_health_api() -> None:
    """Stop the health API server."""
    global _health_server

    with _health_server_lock:
        if _health_server:
            _health_server.stop()
            _health_server = None


async def update_health_loop(bot: Bot, interval: float = 10.0) -> None:
    """Background task to update health data periodically.

    Also checks external service health and sends alerts on failures.
    """
    import aiohttp

    # Track consecutive failures for alerting
    _service_failures: dict[str, int] = {}

    # Import alert manager (optional)
    try:
        from utils.monitoring.alerting import alert_manager

        alerting_available = True
    except ImportError:
        alerting_available = False

    # Import feature flags
    try:
        from config import feature_flags as _ff

        health_data.feature_flags = _ff.get_all()
    except ImportError:
        pass

    async def check_service(session: aiohttp.ClientSession, name: str, url: str) -> None:
        """Check a single external service health."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                healthy = resp.status == 200
                # Mutate service_health under the same data lock to_dict()
                # uses, so concurrent reads can't observe a half-updated row.
                with health_data._data_lock:
                    health_data.service_health[name] = {
                        "status": "healthy" if healthy else "unhealthy",
                        "status_code": resp.status,
                        "last_check": datetime.now(timezone.utc).isoformat(),
                    }
                if healthy:
                    _service_failures[name] = 0
                else:
                    _service_failures[name] = _service_failures.get(name, 0) + 1
        except Exception:
            _service_failures[name] = _service_failures.get(name, 0) + 1
            with health_data._data_lock:
                health_data.service_health[name] = {
                    "status": "unreachable",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                health_data.update_from_bot(bot)

                # Update feature flags
                try:
                    from config import feature_flags as _ff

                    health_data.feature_flags = _ff.get_all()
                except ImportError:
                    pass

                # Check external Go services. Run them concurrently — the
                # previous sequential loop waited the full per-service
                # timeout end-to-end (5s × N), so adding a third service
                # would have made the health update visibly slow.
                services = {
                    "go_health_api": GO_HEALTH_API_URL,
                    "go_url_fetcher": GO_URL_FETCHER_URL,
                }
                await asyncio.gather(
                    *(
                        check_service(session, svc_name, svc_url)
                        for svc_name, svc_url in services.items()
                    ),
                    return_exceptions=True,
                )

                # Alert on consecutive failures
                if alerting_available:
                    for svc_name in services:
                        if _service_failures.get(svc_name, 0) >= 3:
                            await alert_manager.alert_health_check_failed(
                                svc_name, _service_failures[svc_name]
                            )

                # Check memory threshold and alert
                if alerting_available:
                    try:
                        mem_mb = psutil.Process().memory_info().rss / 1024 / 1024
                        threshold = _env_float("ALERT_MEMORY_THRESHOLD_MB", 2048.0)
                        if mem_mb > threshold:
                            await alert_manager.alert_memory_threshold(mem_mb, threshold)
                    except Exception:
                        pass

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error updating health data")
                await asyncio.sleep(interval)


def setup_health_hooks(bot: Bot) -> None:
    """Setup event hooks to track bot health metrics.

    Idempotent: re-calling on the same bot instance won't double-register
    any of the four listeners. Previously the guard sat AFTER the
    on_ready registration, so on_ready could double-fire if
    setup_health_hooks ran twice.
    """
    if getattr(bot, "_health_hooks_registered", False):
        return
    bot._health_hooks_registered = True  # type: ignore[attr-defined]

    @bot.listen("on_ready")
    async def health_on_ready():
        health_data.is_ready = True
        health_data.update_from_bot(bot)

    @bot.listen("on_message")
    async def health_on_message(message):
        health_data.increment_message()

    @bot.listen("on_command")
    async def health_on_command(ctx):
        health_data.increment_command()

    @bot.listen("on_command_error")
    async def health_on_error(ctx, error):
        health_data.increment_error()
