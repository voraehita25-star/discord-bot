"""
API Module - Gemini API handler, streaming, and configuration.
"""

from .api_handler import (
    build_api_config,
    call_gemini_api,
    call_gemini_api_streaming,
    detect_search_intent,
)

__all__ = [
    "build_api_config",
    "call_gemini_api",
    "call_gemini_api_streaming",
    "detect_search_intent",
]
