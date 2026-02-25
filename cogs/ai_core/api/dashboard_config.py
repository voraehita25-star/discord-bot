"""
Dashboard WebSocket configuration, constants, and role presets.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Ensure .env is loaded
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# ============================================================================
# WebSocket Configuration
# ============================================================================

WS_HOST = os.getenv("WS_DASHBOARD_HOST", "127.0.0.1")
WS_PORT = int(os.getenv("WS_DASHBOARD_PORT", "8765"))
WS_REQUIRE_TLS = os.getenv("WS_REQUIRE_TLS", "false").lower() in ("true", "1", "yes")

# TLS enforcement: refuse to bind on 0.0.0.0 without TLS in production
if WS_REQUIRE_TLS and WS_HOST == "0.0.0.0":
    _ws_tls_cert = os.getenv("WS_TLS_CERT_PATH", "")
    _ws_tls_key = os.getenv("WS_TLS_KEY_PATH", "")
    if not (_ws_tls_cert and _ws_tls_key):
        logging.critical(
            "⛔ WS_REQUIRE_TLS is enabled but WS_TLS_CERT_PATH / WS_TLS_KEY_PATH are not set. "
            "Refusing to expose WebSocket on 0.0.0.0 without TLS. "
            "Set WS_DASHBOARD_HOST=127.0.0.1 for local-only access, or provide TLS certificates."
        )
        WS_HOST = "127.0.0.1"  # Fallback to localhost for safety

# ============================================================================
# Gemini Configuration
# ============================================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
# For thinking mode, use the same model (gemini-3.1-pro supports thinking)

# ============================================================================
# Persona Imports
# ============================================================================

try:
    from ..data.faust_data import ENI_ESCALATION_FRAMING, FAUST_PERSONA
    FAUST_AVAILABLE = True
except ImportError:
    FAUST_AVAILABLE = False
    FAUST_PERSONA = "You are Faust, a helpful AI assistant."
    ENI_ESCALATION_FRAMING = ""

# ============================================================================
# Database
# ============================================================================

try:
    from utils.database import Database
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    Database = None

# ============================================================================
# Role Presets
# ============================================================================

DASHBOARD_ROLE_PRESETS = {
    "general": {
        "name": "General Assistant",
        "emoji": "🤖",
        "system_instruction": """You are a helpful AI assistant. 
Respond in the same language the user uses (Thai or English).
Be concise, helpful, and friendly.
For simple questions, give brief answers (1-3 sentences).
For complex topics, provide detailed but well-organized responses.""",
        "color": "#22d3ee",  # Cyan
    },
    "faust": {
        "name": "Faust",
        "emoji": "👻",
        "system_instruction": FAUST_PERSONA if FAUST_AVAILABLE else "You are Faust, a genius AI assistant who speaks in third person.",
        "color": "#ffb1b4",  # Cerebral Pink
    },
}
