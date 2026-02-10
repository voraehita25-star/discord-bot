"""
AI Core Package
Core AI functionality for the Discord Bot.

Reorganized into subdirectories (v3.3.7):
- api/       - Gemini API handlers
- cache/     - Caching and analytics
- commands/  - Debug, memory, server commands
- core/      - Performance, message queue, context building
- data/      - Constants and configuration
- memory/    - RAG, entity memory, history
- processing/ - Guardrails, intent detection
- prompts/   - System prompts
- response/  - Response sending, webhooks
- tools/     - Tool definitions and execution
"""

# Main AI Cog
from .ai_cog import AI

# New subdirectory modules
from .api import build_api_config, call_gemini_api

# Backward compatibility re-exports from new locations
from .cache.ai_cache import AICache, ai_cache
from .cache.analytics import AIAnalytics, ai_analytics
from .commands import DebugCommands, MemoryCommands, ServerCommands

# Modular components (via backward compatible re-exports)
from .context_builder import AIContext, ContextBuilder, context_builder
from .core import PERFORMANCE_SAMPLES_MAX
from .data.constants import CREATOR_ID, GUILD_ID_MAIN, GUILD_ID_RESTRICTED
from .data import FAUST_INSTRUCTION
from .data import ROLEPLAY_ASSISTANT_INSTRUCTION, SERVER_AVATARS
from .memory.conversation_branch import branch_manager
from .memory.history_manager import HistoryManager
from .memory.rag import rag_system
from .memory.summarizer import summarizer
from .message_queue import MessageQueue, PendingMessage, message_queue
from .performance import (
    PerformanceTracker,
    RequestDeduplicator,
    performance_tracker,
    request_deduplicator,
)
from .processing.guardrails import validate_response
from .processing.intent_detector import detect_intent
from .processing.prompt_manager import prompt_manager
from .response import ResponseMixin
from .response_sender import ResponseSender, SendResult, response_sender
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
    "AIContext",
    "ContextBuilder",
    "DebugCommands",
    "HistoryManager",
    "MemoryCommands",
    "MessageQueue",
    "PendingMessage",
    "PerformanceTracker",
    "RequestDeduplicator",
    "ResponseMixin",
    "ResponseSender",
    "SendResult",
    "ServerCommands",
    "ai_analytics",
    "ai_cache",
    "branch_manager",
    # New subdirectory exports
    "build_api_config",
    "call_gemini_api",
    "context_builder",
    "detect_intent",
    "execute_tool_call",
    "get_tool_definitions",
    "message_queue",
    "performance_tracker",
    "prompt_manager",
    "rag_system",
    "request_deduplicator",
    "response_sender",
    "send_as_webhook",
    "summarizer",
    "validate_response",
]


async def setup(bot):
    """Setup function to add the AI cog to the bot."""
    await bot.add_cog(AI(bot))
