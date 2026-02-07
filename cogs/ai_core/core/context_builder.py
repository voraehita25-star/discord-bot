"""
Context Builder Module
Handles building context for AI responses including RAG, entity memory, state tracker.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

# Import constants
try:
    from ..data.constants import (
        MAX_ENTITY_ITEMS,
        MAX_RAG_RESULTS,
        RAG_MIN_SIMILARITY,
    )
except ImportError:
    MAX_RAG_RESULTS = 5
    RAG_MIN_SIMILARITY = 0.4
    MAX_ENTITY_ITEMS = 3


@dataclass
class AIContext:
    """Context data for AI response generation."""

    avatar_name: str | None = None
    avatar_personality: str | None = None
    avatar_image_url: str | None = None
    rag_context: str = ""
    entity_memory: str = ""
    state_tracker: str = ""
    url_content: str = ""
    recent_history: list[dict[str, str]] | None = None
    instructions: str = ""

    @property
    def has_avatar(self) -> bool:
        """Check if avatar context is available."""
        return self.avatar_name is not None

    def build_system_context(self) -> str:
        """Build the combined system context string.

        Returns:
            Combined system context string
        """
        parts = []

        if self.instructions:
            parts.append(f"## Instructions\n{self.instructions}")

        if self.rag_context:
            parts.append(f"## Relevant Knowledge\n{self.rag_context}")

        if self.entity_memory:
            parts.append(f"## Entity Memory\n{self.entity_memory}")

        if self.state_tracker:
            parts.append(f"## State Tracker\n{self.state_tracker}")

        if self.url_content:
            parts.append(f"## URL Content\n{self.url_content}")

        return "\n\n".join(parts)


class ContextBuilder:
    """Builds context for AI responses."""

    def __init__(
        self,
        memory_manager: Any = None,
        entity_memory: Any = None,
        state_tracker: Any = None,
        avatar_manager: Any = None,
    ) -> None:
        """Initialize the context builder.

        Args:
            memory_manager: Memory manager for RAG operations
            entity_memory: Entity memory for user/channel data
            state_tracker: State tracker for conversation state
            avatar_manager: Avatar manager for persona data
        """
        self.memory_manager = memory_manager
        self.entity_memory = entity_memory
        self.state_tracker = state_tracker
        self.avatar_manager = avatar_manager

    async def build_context(
        self,
        channel_id: int,
        user_id: int,
        message: str,
        guild: Any = None,
        include_rag: bool = True,
        include_entity: bool = True,
        include_state: bool = True,
        include_avatar: bool = True,
    ) -> AIContext:
        """Build the complete AI context.

        Args:
            channel_id: Channel ID
            user_id: User ID
            message: User message
            guild: Discord guild
            include_rag: Whether to include RAG context
            include_entity: Whether to include entity memory
            include_state: Whether to include state tracker
            include_avatar: Whether to include avatar context

        Returns:
            AIContext with all context data
        """
        context = AIContext()

        # Build context parts in parallel where possible
        tasks = []
        task_names = []

        if include_rag and self.memory_manager:
            tasks.append(self._get_rag_context(channel_id, message))
            task_names.append("rag")

        if include_entity and self.entity_memory:
            tasks.append(self._get_entity_memory(channel_id, user_id, message))
            task_names.append("entity")

        if include_state and self.state_tracker:
            tasks.append(self._get_state_tracker(channel_id))
            task_names.append("state")

        if include_avatar and self.avatar_manager and guild:
            tasks.append(self._get_avatar_context(channel_id, guild))
            task_names.append("avatar")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for name, result in zip(task_names, results, strict=False):
                if isinstance(result, Exception):
                    logging.error("Context build error for %s: %s", name, result)
                    continue

                if name == "rag":
                    context.rag_context = result or ""
                elif name == "entity":
                    context.entity_memory = result or ""
                elif name == "state":
                    context.state_tracker = result or ""
                elif name == "avatar":
                    if result:
                        context.avatar_name = result.get("name")
                        context.avatar_personality = result.get("personality")
                        context.avatar_image_url = result.get("image_url")

        return context

    async def _get_rag_context(self, channel_id: int, query: str) -> str:
        """Get RAG-based context for a query.

        Args:
            channel_id: Channel ID
            query: Search query

        Returns:
            RAG context string
        """
        if not self.memory_manager:
            return ""

        try:
            start_time = time.time()

            # Use semantic search if available
            if hasattr(self.memory_manager, "semantic_search"):
                results = await self.memory_manager.semantic_search(
                    channel_id,
                    query,
                    max_results=MAX_RAG_RESULTS,
                    min_similarity=RAG_MIN_SIMILARITY,
                )
            elif hasattr(self.memory_manager, "search"):
                results = await self.memory_manager.search(channel_id, query, limit=MAX_RAG_RESULTS)
            else:
                return ""

            if not results:
                return ""

            # Format results
            context_parts = []
            for i, result in enumerate(results, 1):
                if isinstance(result, dict):
                    text = result.get("text", result.get("content", ""))
                    # Score is available but not displayed in context
                    # score = result.get("score", result.get("similarity", 0))
                else:
                    text = str(result)

                if text:
                    context_parts.append(f"[{i}] {text}")

            elapsed = time.time() - start_time
            logging.debug(
                "RAG search completed in %.2fs, found %d results",
                elapsed,
                len(context_parts),
            )

            return "\n".join(context_parts)

        except Exception as e:
            logging.error("RAG context error: %s", e)
            return ""

    async def _get_entity_memory(self, channel_id: int, user_id: int, message: str) -> str:
        """Get entity memory context.

        Args:
            channel_id: Channel ID
            user_id: User ID
            message: User message

        Returns:
            Entity memory string
        """
        if not self.entity_memory:
            return ""

        try:
            start_time = time.time()

            # Get relevant entities
            if hasattr(self.entity_memory, "get_relevant"):
                entities = await self.entity_memory.get_relevant(
                    channel_id=channel_id,
                    user_id=user_id,
                    query=message,
                    max_items=MAX_ENTITY_ITEMS,
                )
            elif hasattr(self.entity_memory, "get_entities"):
                entities = await self.entity_memory.get_entities(channel_id, limit=MAX_ENTITY_ITEMS)
            else:
                return ""

            if not entities:
                return ""

            # Format entities
            entity_parts = []
            for entity in entities:
                if isinstance(entity, dict):
                    name = entity.get("name", entity.get("entity", "Unknown"))
                    info = entity.get("info", entity.get("data", ""))
                    entity_parts.append(f"- {name}: {info}")
                else:
                    entity_parts.append(f"- {entity}")

            elapsed = time.time() - start_time
            logging.debug(
                "Entity memory retrieved in %.2fs, found %d entities",
                elapsed,
                len(entity_parts),
            )

            return "\n".join(entity_parts)

        except Exception as e:
            logging.error("Entity memory error: %s", e)
            return ""

    async def _get_state_tracker(self, channel_id: int) -> str:
        """Get state tracker context.

        Args:
            channel_id: Channel ID

        Returns:
            State tracker string
        """
        if not self.state_tracker:
            return ""

        try:
            start_time = time.time()

            # Get state
            if hasattr(self.state_tracker, "get_state_summary"):
                state = await self.state_tracker.get_state_summary(channel_id)
            elif hasattr(self.state_tracker, "get_state"):
                state = await self.state_tracker.get_state(channel_id)
            else:
                return ""

            elapsed = time.time() - start_time
            logging.debug("State tracker retrieved in %.2fs", elapsed)

            return state or ""

        except Exception as e:
            logging.error("State tracker error: %s", e)
            return ""

    async def _get_avatar_context(self, channel_id: int, guild: Any) -> dict[str, Any] | None:
        """Get avatar context for a channel.

        Args:
            channel_id: Channel ID
            guild: Discord guild

        Returns:
            Avatar data dict or None
        """
        if not self.avatar_manager:
            return None

        try:
            start_time = time.time()

            # Get avatar for channel
            if hasattr(self.avatar_manager, "get_avatar"):
                avatar = await self.avatar_manager.get_avatar(channel_id, guild)
            elif hasattr(self.avatar_manager, "get_channel_avatar"):
                avatar = await self.avatar_manager.get_channel_avatar(channel_id)
            else:
                return None

            if not avatar:
                return None

            elapsed = time.time() - start_time
            logging.debug("Avatar retrieved in %.2fs", elapsed)

            if isinstance(avatar, dict):
                return avatar

            # Convert avatar object to dict
            return {
                "name": getattr(avatar, "name", None),
                "personality": getattr(avatar, "personality", None),
                "image_url": getattr(avatar, "image_url", getattr(avatar, "avatar_url", None)),
            }

        except Exception as e:
            logging.error("Avatar context error: %s", e)
            return None

    async def fetch_url_content(self, urls: list[str], max_content_length: int = 2000) -> str:
        """Fetch content from URLs.

        Args:
            urls: List of URLs to fetch
            max_content_length: Maximum content length per URL

        Returns:
            Combined URL content string
        """
        if not urls:
            return ""

        try:
            # Import URL fetcher from utils
            from utils.web.url_fetcher import fetch_url_content as fetch_url

            contents = []
            for url in urls[:3]:  # Limit to 3 URLs
                try:
                    content = await fetch_url(url)
                    if content:
                        # Truncate if too long
                        if len(content) > max_content_length:
                            content = content[:max_content_length] + "..."
                        contents.append(f"[{url}]\n{content}")
                except Exception as e:
                    logging.warning("URL fetch error for %s: %s", url, e)

            return "\n\n".join(contents)

        except Exception as e:
            logging.error("URL content fetch error: %s", e)
            return ""


# Module-level instance for easy access
context_builder = ContextBuilder()
