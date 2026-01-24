"""
API Module - Gemini API handler, streaming, and configuration.
"""

from .api_handler import (
    build_api_config,
    call_gemini_api,
    call_gemini_api_streaming,
    detect_search_intent,
)
from .ws_dashboard import (
    DashboardWebSocketServer,
    get_dashboard_ws_server,
    start_dashboard_ws_server,
    stop_dashboard_ws_server,
    DASHBOARD_ROLE_PRESETS,
)

__all__ = [
    "build_api_config",
    "call_gemini_api",
    "call_gemini_api_streaming",
    "detect_search_intent",
    # Dashboard WebSocket
    "DashboardWebSocketServer",
    "get_dashboard_ws_server",
    "start_dashboard_ws_server",
    "stop_dashboard_ws_server",
    "DASHBOARD_ROLE_PRESETS",
]
