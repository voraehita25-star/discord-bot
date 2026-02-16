"""
Health API Module for Discord Bot
Provides HTTP endpoints for health checks and monitoring.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import platform
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any

import psutil

if TYPE_CHECKING:
    from discord.ext.commands import Bot

# Configuration
HEALTH_API_PORT = int(os.getenv("HEALTH_API_PORT", "8080"))
HEALTH_API_HOST = os.getenv("HEALTH_API_HOST", "127.0.0.1")
HEALTH_API_TOKEN = os.getenv("HEALTH_API_TOKEN", "")  # Optional Bearer token for sensitive endpoints

# Health check thresholds (configurable via env vars)
HEARTBEAT_MAX_AGE_SECONDS = int(os.getenv("HEALTH_HEARTBEAT_MAX_AGE", "60"))
MAX_LATENCY_MS = int(os.getenv("HEALTH_MAX_LATENCY_MS", "5000"))

# External service URLs to health-check
GO_HEALTH_API_URL = os.getenv("GO_HEALTH_API_URL", "http://127.0.0.1:8082/health")
GO_URL_FETCHER_URL = os.getenv("GO_URL_FETCHER_URL", "http://127.0.0.1:8081/health")

# Endpoints that require authentication (when HEALTH_API_TOKEN is set)
_PROTECTED_ENDPOINTS = {"/", "/metrics", "/health/deep", "/health/json", "/ai/stats", "/ai/stats/json"}


class BotHealthData:
    """Stores bot health metrics for the API."""

    def __init__(self) -> None:
        self.start_time: datetime = datetime.now()
        self.bot: Bot | None = None
        self.last_heartbeat: datetime = datetime.now()
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

    def update_from_bot(self, bot: Bot) -> None:
        """Update health data from bot instance (thread-safe)."""
        with self._data_lock:
            self.bot = bot
            self.last_heartbeat = datetime.now()
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
        return datetime.now() - self.start_time

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
        """Convert health data to dictionary (thread-safe)."""
        process = psutil.Process()

        with self._data_lock:
            is_ready = self.is_ready
            latency_ms = self.latency_ms
            guild_count = self.guild_count
            user_count = self.user_count
            cogs_loaded = self.cogs_loaded.copy()
            last_heartbeat = self.last_heartbeat

        with self._counter_lock:
            message_count = self.message_count
            command_count = self.command_count
            error_count = self.error_count

        return {
            "status": "healthy" if is_ready else "starting",
            "timestamp": datetime.now().isoformat(),
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
                "cpu_percent": process.cpu_percent(),
                "memory_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                "threads": process.num_threads(),
            },
            "heartbeat": {
                "last": last_heartbeat.isoformat(),
                "age_seconds": int((datetime.now() - last_heartbeat).total_seconds()),
            },
            "services": self.service_health,
            "features": self.feature_flags,
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

        heartbeat_age = (datetime.now() - last_heartbeat).total_seconds()
        if heartbeat_age > HEARTBEAT_MAX_AGE_SECONDS:
            return False

        return not latency_ms > MAX_LATENCY_MS

    def get_ai_performance_stats(self) -> dict:
        """Get AI performance statistics from chat manager.

        Thread-safe: uses _data_lock since this may be called from the
        HTTP server thread while the event loop thread mutates bot state.
        """
        try:
            with self._data_lock:
                if self.bot and hasattr(self.bot, "cogs"):
                    ai_cog = self.bot.cogs.get("AI")
                    if ai_cog and hasattr(ai_cog, "chat_manager"):
                        return ai_cog.chat_manager.get_performance_stats()
        except Exception as e:
            logging.debug("Failed to get AI performance stats: %s", e)
        return {"error": "AI cog not available or no stats collected"}


# Global health data instance
health_data = BotHealthData()


class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for health endpoints."""

    # Suppress default logging
    def log_message(self, format: str, *args) -> None:
        """Override to suppress logging."""
        pass

    def _send_json_response(self, data: dict, status: int = 200) -> None:
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_text_response(self, text: str, status: int = 200) -> None:
        """Send plain text response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode())

    def _send_html_response(self, html: str, status: int = 200) -> None:
        """Send HTML response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

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
        return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌸 Bot Health</title><style>{self._get_anime_theme_css()}</style></head><body>
<div class="ambient-glow glow-1"></div><div class="ambient-glow glow-2"></div><div class="ambient-glow glow-3"></div><div class="ambient-glow glow-4"></div>
<div class="sakura-container"></div><div class="container">
<h1>🌸 Bot Health Check</h1>
<p class="subtitle"><span class="status-badge {"status-healthy" if is_healthy else "status-unhealthy"}">{"✨ Healthy" if is_healthy else "⚠️ Unhealthy"}</span></p>
<div class="nav-links"><a href="/ai/stats">🤖 AI Stats</a><a href="/health" class="active">💚 Health</a><a href="/stats">📊 Quick Stats</a></div>
<div class="cards">
<div class="card" style="border-left:4px solid #2ecc71;"><div class="card-header"><span class="icon">🤖</span><span class="name">Bot Info</span></div>
<div class="stats"><div class="stat"><span class="value">{data.get("uptime", "N/A")}</span><span class="label">Uptime</span></div>
<div class="stat"><span class="value highlight">{bot.get("latency_ms", 0):.0f}ms</span><span class="label">Latency</span></div></div></div>
<div class="card" style="border-left:4px solid #3498db;"><div class="card-header"><span class="icon">🌐</span><span class="name">Discord</span></div>
<div class="stats"><div class="stat"><span class="value">{bot.get("guilds", 0)}</span><span class="label">Guilds</span></div>
<div class="stat"><span class="value">{bot.get("users", 0)}</span><span class="label">Users</span></div></div></div>
<div class="card" style="border-left:4px solid #9b59b6;"><div class="card-header"><span class="icon">💻</span><span class="name">System</span></div>
<div class="stats"><div class="stat"><span class="value">{system.get("memory_mb", 0):.0f}MB</span><span class="label">Memory</span></div>
<div class="stat"><span class="value">{system.get("cpu_percent", 0):.1f}%</span><span class="label">CPU</span></div></div></div>
<div class="card" style="border-left:4px solid #e74c3c;"><div class="card-header"><span class="icon">📊</span><span class="name">Stats</span></div>
<div class="stats"><div class="stat"><span class="value">{stats.get("messages_processed", 0)}</span><span class="label">Messages</span></div>
<div class="stat"><span class="value">{stats.get("errors", 0)}</span><span class="label">Errors</span></div></div></div>
</div><p class="footer">🌸 Cogs: {html.escape(", ".join(bot.get("cogs", [])))} | <a href="/health/json">View JSON</a></p>
</div>{self._get_sakura_js()}</body></html>"""

    def _generate_stats_html(self, data: dict) -> str:
        """Generate anime-themed HTML for quick stats."""
        return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌸 Quick Stats</title><style>{self._get_anime_theme_css()}</style></head><body>
<div class="sakura-tree-left"><div class="tree-trunk"></div><div class="tree-branch tree-branch-1"></div><div class="tree-branch tree-branch-2"></div><div class="tree-branch tree-branch-3"></div><div class="tree-bloom bloom-1"></div><div class="tree-bloom bloom-2"></div><div class="tree-bloom bloom-3"></div><div class="tree-bloom bloom-4"></div><div class="tree-bloom bloom-5"></div></div>
<div class="sakura-tree-right"><div class="tree-trunk"></div><div class="tree-branch tree-branch-1"></div><div class="tree-branch tree-branch-2"></div><div class="tree-branch tree-branch-3"></div><div class="tree-bloom bloom-1"></div><div class="tree-bloom bloom-2"></div><div class="tree-bloom bloom-3"></div><div class="tree-bloom bloom-4"></div><div class="tree-bloom bloom-5"></div></div>
<div class="sakura-container"></div><div class="container">
<h1>🌸 Quick Stats</h1><p class="subtitle">✨ Auto-refresh every 5s</p>
<div class="nav-links"><a href="/ai/stats">🤖 AI Stats</a><a href="/health">💚 Health</a><a href="/stats" class="active">📊 Quick Stats</a></div>
<div class="cards">
<div class="card" style="border-left:4px solid #00d9ff;"><div class="card-header"><span class="icon">⏰</span><span class="name">Uptime</span></div>
<div class="stats"><div class="stat"><span class="value highlight">{data.get("uptime", "N/A")}</span><span class="label">Duration</span></div></div></div>
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
        if HEALTH_API_TOKEN and path in _PROTECTED_ENDPOINTS:
            auth_header = self.headers.get("Authorization", "")
            if auth_header != f"Bearer {HEALTH_API_TOKEN}":
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
            self._send_json_response({"status": "alive", "timestamp": datetime.now().isoformat()})

        elif path in {"/health/ready", "/readyz"}:
            # Kubernetes readiness probe - is the bot ready to serve?
            if health_data.is_ready:
                self._send_json_response(
                    {
                        "status": "ready",
                        "latency_ms": round(health_data.latency_ms, 2),
                        "guilds": health_data.guild_count,
                    }
                )
            else:
                self._send_json_response(
                    {"status": "not_ready", "message": "Bot is still starting up"}, 503
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
            # Quick stats (HTML dashboard)
            data = {
                "uptime": health_data.get_uptime_str(),
                "messages": health_data.message_count,
                "commands": health_data.command_count,
                "errors": health_data.error_count,
                "guilds": health_data.guild_count,
                "latency_ms": round(health_data.latency_ms, 2),
            }
            stats_html = self._generate_stats_html(data)
            self._send_html_response(stats_html)

        elif path == "/stats/json":
            # Quick stats (JSON)
            self._send_json_response(
                {
                    "uptime": health_data.get_uptime_str(),
                    "messages": health_data.message_count,
                    "commands": health_data.command_count,
                    "errors": health_data.error_count,
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
        process = psutil.Process()

        lines = [
            "# HELP discord_bot_up Bot is up and running",
            "# TYPE discord_bot_up gauge",
            f"discord_bot_up {1 if health_data.is_ready else 0}",
            "",
            "# HELP discord_bot_latency_ms Discord API latency in milliseconds",
            "# TYPE discord_bot_latency_ms gauge",
            f"discord_bot_latency_ms {health_data.latency_ms:.2f}",
            "",
            "# HELP discord_bot_guilds Number of guilds the bot is in",
            "# TYPE discord_bot_guilds gauge",
            f"discord_bot_guilds {health_data.guild_count}",
            "",
            "# HELP discord_bot_users Total users across all guilds",
            "# TYPE discord_bot_users gauge",
            f"discord_bot_users {health_data.user_count}",
            "",
            "# HELP discord_bot_messages_total Total messages processed",
            "# TYPE discord_bot_messages_total counter",
            f"discord_bot_messages_total {health_data.message_count}",
            "",
            "# HELP discord_bot_commands_total Total commands executed",
            "# TYPE discord_bot_commands_total counter",
            f"discord_bot_commands_total {health_data.command_count}",
            "",
            "# HELP discord_bot_errors_total Total errors",
            "# TYPE discord_bot_errors_total counter",
            f"discord_bot_errors_total {health_data.error_count}",
            "",
            "# HELP discord_bot_uptime_seconds Bot uptime in seconds",
            "# TYPE discord_bot_uptime_seconds counter",
            f"discord_bot_uptime_seconds {int(health_data.get_uptime().total_seconds())}",
            "",
            "# HELP process_cpu_percent CPU usage percentage",
            "# TYPE process_cpu_percent gauge",
            f"process_cpu_percent {process.cpu_percent()}",
            "",
            "# HELP process_memory_bytes Memory usage in bytes",
            "# TYPE process_memory_bytes gauge",
            f"process_memory_bytes {process.memory_info().rss}",
            "",
            "# HELP process_threads Number of threads",
            "# TYPE process_threads gauge",
            f"process_threads {process.num_threads()}",
        ]

        return "\n".join(lines) + "\n"

    def _perform_deep_health_check(self) -> dict[str, Any]:
        """Perform deep health check on all subsystems."""
        checks = {"timestamp": datetime.now().isoformat(), "healthy": True, "checks": {}}

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
            db_path = Path("data") / "bot_database.db"
            if db_path.exists():
                checks["checks"]["database"] = {"status": "ok", "type": "sqlite+aiosqlite"}
            else:
                checks["checks"]["database"] = {"status": "warning", "error": "DB file not found"}
        except Exception as e:
            checks["checks"]["database"] = {"status": "error", "error": str(e)[:100]}
            checks["healthy"] = False

        # 3. API Keys check (existence only, not validity)
        api_keys = {
            "DISCORD_TOKEN": bool(os.getenv("DISCORD_TOKEN")),
            "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
            "SPOTIFY_CLIENT_ID": bool(os.getenv("SPOTIFY_CLIENT_ID")),
            "SPOTIFY_CLIENT_SECRET": bool(os.getenv("SPOTIFY_CLIENT_SECRET")),
        }
        missing_keys = [k for k, v in api_keys.items() if not v]
        checks["checks"]["api_keys"] = {
            "status": "ok" if not missing_keys else "warning",
            "configured": [k for k, v in api_keys.items() if v],
            "missing": missing_keys,
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

        # 5. Memory check
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        checks["checks"]["memory"] = {
            "status": "ok" if memory_mb < 500 else "warning",
            "usage_mb": round(memory_mb, 2),
            "threshold_mb": 500,
        }

        return checks


class HealthAPIServer:
    """Health API Server that runs in a separate thread."""

    def __init__(self, host: str = HEALTH_API_HOST, port: int = HEALTH_API_PORT) -> None:
        self.host = host
        self.port = port
        self.server: HTTPServer | None = None
        self.thread: Thread | None = None
        self.running = False

    def start(self) -> bool:
        """Start the health API server."""
        if self.running:
            return True

        try:
            self.server = HTTPServer((self.host, self.port), HealthRequestHandler)
            self.thread = Thread(target=self._run_server, daemon=True)
            self.thread.start()
            self.running = True
            logging.info(
                "🏥 Health API started at http://%s:%d",
                self.host if self.host != "0.0.0.0" else "localhost",
                self.port,
            )
            return True
        except OSError as e:
            logging.error("❌ Failed to start Health API: %s", e)
            return False

    def _run_server(self) -> None:
        """Run the server (called in separate thread)."""
        if self.server:
            self.server.serve_forever()

    def stop(self) -> None:
        """Stop the health API server."""
        if self.server:
            self.server.shutdown()
            self.running = False
            logging.info("🏥 Health API stopped")


# Global server instance
_health_server: HealthAPIServer | None = None


def start_health_api(host: str = HEALTH_API_HOST, port: int = HEALTH_API_PORT) -> bool:
    """Start the health API server."""
    global _health_server

    if _health_server is None:
        _health_server = HealthAPIServer(host, port)

    return _health_server.start()


def stop_health_api() -> None:
    """Stop the health API server."""
    global _health_server

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
                health_data.service_health[name] = {
                    "status": "healthy" if healthy else "unhealthy",
                    "status_code": resp.status,
                    "last_check": datetime.now().isoformat(),
                }
                if healthy:
                    _service_failures[name] = 0
                else:
                    _service_failures[name] = _service_failures.get(name, 0) + 1
        except Exception:
            _service_failures[name] = _service_failures.get(name, 0) + 1
            health_data.service_health[name] = {
                "status": "unreachable",
                "last_check": datetime.now().isoformat(),
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
                
                # Check external Go services
                services = {
                    "go_health_api": GO_HEALTH_API_URL,
                    "go_url_fetcher": GO_URL_FETCHER_URL,
                }
                for svc_name, svc_url in services.items():
                    await check_service(session, svc_name, svc_url)
                    
                    # Alert on consecutive failures
                    if alerting_available and _service_failures.get(svc_name, 0) >= 3:
                        await alert_manager.alert_health_check_failed(
                            svc_name, _service_failures[svc_name]
                        )
                
                # Check memory threshold and alert
                if alerting_available:
                    try:
                        mem_mb = psutil.Process().memory_info().rss / 1024 / 1024
                        threshold = float(os.getenv("ALERT_MEMORY_THRESHOLD_MB", "2048"))
                        if mem_mb > threshold:
                            await alert_manager.alert_memory_threshold(mem_mb, threshold)
                    except Exception:
                        pass
                
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error("Error updating health data: %s", e)
                await asyncio.sleep(interval)


def setup_health_hooks(bot: Bot) -> None:
    """Setup event hooks to track bot health metrics."""

    @bot.listen("on_ready")
    async def health_on_ready():
        health_data.is_ready = True
        health_data.update_from_bot(bot)

    # Track messages (be careful not to override existing handlers)
    if hasattr(bot, "_health_on_message_set"):
        return

    bot._health_on_message_set = True

    @bot.listen("on_message")
    async def health_on_message(message):
        health_data.increment_message()

    @bot.listen("on_command")
    async def health_on_command(ctx):
        health_data.increment_command()

    @bot.listen("on_command_error")
    async def health_on_error(ctx, error):
        health_data.increment_error()
