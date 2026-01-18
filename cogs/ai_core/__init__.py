"""
AI Core Package
Core AI functionality for the Discord Bot.
Reorganized into subdirectories for better organization.
"""

# Main AI Cog
from .ai_cog import AI

# Backward compatibility re-exports from new locations
from .cache.ai_cache import AICache, ai_cache
from .cache.analytics import AIAnalytics, ai_analytics
from .data.constants import CREATOR_ID, GUILD_ID_MAIN, GUILD_ID_RESTRICTED
from .data.faust_data import FAUST_INSTRUCTION
from .data.roleplay_data import ROLEPLAY_ASSISTANT_INSTRUCTION, SERVER_AVATARS
from .memory.conversation_branch import branch_manager
from .memory.history_manager import HistoryManager
from .memory.rag import rag_system
from .memory.summarizer import summarizer
from .processing.guardrails import validate_response
from .processing.intent_detector import detect_intent
from .processing.prompt_manager import prompt_manager

__all__ = [
    "AI",
    "CREATOR_ID",
    "FAUST_INSTRUCTION",
    "GUILD_ID_MAIN",
    "GUILD_ID_RESTRICTED",
    "ROLEPLAY_ASSISTANT_INSTRUCTION",
    "SERVER_AVATARS",
    "AIAnalytics",
    "AICache",
    "HistoryManager",
    "ai_analytics",
    "ai_cache",
    "branch_manager",
    "detect_intent",
    "prompt_manager",
    "rag_system",
    "summarizer",
    "validate_response",
]


async def setup(bot):
    """Setup function to add the AI cog to the bot."""
    await bot.add_cog(AI(bot))
