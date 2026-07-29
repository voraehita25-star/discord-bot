"""
API Module - Claude API handler, streaming, and configuration.
"""

from .api_handler import (
    build_api_config,
    call_claude_api,
    call_claude_api_streaming,
)
from .ws_dashboard import (
    DASHBOARD_ROLE_PRESETS,
    DashboardWebSocketServer,
    get_dashboard_ws_server,
    start_dashboard_ws_server,
    stop_dashboard_ws_server,
)

__all__ = [
    "DASHBOARD_ROLE_PRESETS",
    "DashboardWebSocketServer",
    "build_api_config",
    "call_claude_api",
    "call_claude_api_streaming",
    "get_dashboard_ws_server",
    "start_dashboard_ws_server",
    "stop_dashboard_ws_server",
]
