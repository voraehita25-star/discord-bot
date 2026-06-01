"""
AI Core Package
Core AI functionality for the Discord Bot.

Reorganized into subdirectories (v3.3.7):
- api/       - Claude API handlers
- cache/     - Caching and analytics
- commands/  - Debug, memory, server commands
- core/      - Performance, message queue
- data/      - Constants and configuration
- memory/    - RAG, entity memory, history
- processing/ - Guardrails, intent detection
- response/  - Response sending, webhooks
- tools/     - Tool definitions and execution
"""

# Main AI Cog
from .ai_cog import AI

# New subdirectory modules
from .api import build_api_config, call_claude_api

# Backward compatibility re-exports from new locations
from .cache.ai_cache import AICache, ai_cache
from .cache.analytics import AIAnalytics, ai_analytics
from .commands import DebugCommands, MemoryCommands, ServerCommands
from .core import PERFORMANCE_SAMPLES_MAX

# Modular components (direct imports from subfolders)
from .core.message_queue import MessageQueue, PendingMessage, message_queue
from .core.performance import (
    PerformanceTracker,
    RequestDeduplicator,
    performance_tracker,
    request_deduplicator,
)
from .data import FAUST_INSTRUCTION, ROLEPLAY_ASSISTANT_INSTRUCTION, SERVER_AVATARS
from .data.constants import CREATOR_ID, GUILD_ID_MAIN, GUILD_ID_RESTRICTED
from .memory.history_manager import HistoryManager
from .memory.rag import rag_system
from .memory.summarizer import summarizer

# Optional processing modules — gracefully degrade if dependencies are missing
try:
    from .processing.guardrails import validate_response
except ImportError:
    validate_response = None  # type: ignore[assignment]

try:
    from .processing.intent_detector import detect_intent
except ImportError:
    detect_intent = None  # type: ignore[assignment]

from .response import ResponseMixin
from .tools import execute_tool_call, get_tool_definitions, send_as_webhook

__all__ = [
    "AI",
    "CREATOR_ID",
    "FAUST_INSTRUCTION",
    "GUILD_ID_MAIN",
    "GUILD_ID_RESTRICTED",
    "PERFORMANCE_SAMPLES_MAX",
    "ROLEPLAY_ASSISTANT_INSTRUCTION",
    "SERVER_AVATARS",
    "AIAnalytics",
    "AICache",
    # Modular components
    "DebugCommands",
    "HistoryManager",
    "MemoryCommands",
    "MessageQueue",
    "PendingMessage",
    "PerformanceTracker",
    "RequestDeduplicator",
    "ResponseMixin",
    "ServerCommands",
    "ai_analytics",
    "ai_cache",
    # New subdirectory exports
    "build_api_config",
    "call_claude_api",
    "detect_intent",
    "execute_tool_call",
    "get_tool_definitions",
    "message_queue",
    "performance_tracker",
    "request_deduplicator",
    "send_as_webhook",
    "summarizer",
    "validate_response",
]


async def setup(bot):
    """Setup function to add the AI cog to the bot.

    Delegate to ``ai_cog.setup`` so loading this package is equivalent to
    loading ``cogs.ai_core.ai_cog``. Without this, calling
    ``bot.load_extension("cogs.ai_core")`` silently skipped the
    ``AIDebug`` and ``MemoryCommands`` sub-cogs that ``ai_cog.setup``
    registers.
    """
    from .ai_cog import setup as _ai_cog_setup

    await _ai_cog_setup(bot)
