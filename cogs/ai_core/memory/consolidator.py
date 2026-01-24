"""
Memory Consolidation Module
Background task that extracts facts from conversation history
and updates entity memory to prevent hallucinations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

try:
    from google import genai
    from google.genai import types

    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from ..data.constants import (
    CONSOLIDATE_EVERY_N_MESSAGES,
    CONSOLIDATE_INTERVAL_SECONDS,
    CONSOLIDATOR_CLEANUP_MAX_AGE_SECONDS,
    CONSOLIDATOR_CLEANUP_MAX_CHANNELS,
    GEMINI_MODEL,
    MAX_RECENT_MESSAGES_FOR_EXTRACTION,
    MIN_CONVERSATION_LENGTH,
)
from .entity_memory import EntityFacts, entity_memory

# Fact extraction prompt
FACT_EXTRACTION_PROMPT = """วิเคราะห์บทสนทนาต่อไปนี้และดึงข้อมูลสำคัญเกี่ยวกับตัวละครออกมา

กรุณาตอบเป็น JSON format ดังนี้:
{
    "entities": [
        {
            "name": "ชื่อตัวละคร",
            "type": "character/location/item",
            "facts": {
                "age": 19,
                "occupation": "นักศึกษา",
                "personality": "ขี้อาย",
                "relationships": {"ชื่อคนอื่น": "ความสัมพันธ์"}
            }
        }
    ]
}

บทสนทนา:
{conversation}

JSON:"""


class MemoryConsolidator:
    """
    Background task that consolidates conversation history into entity memory.

    Features:
    - Automatic fact extraction from conversations
    - Periodic consolidation runs
    - Conflict detection and resolution
    """

    def __init__(self):
        self._client = None
        self._task: asyncio.Task | None = None
        self._message_counts: dict[int, int] = {}  # channel_id: message_count
        self._last_consolidation: dict[int, float] = {}  # channel_id: timestamp

        # Settings (from constants for consistency)
        self.consolidate_every_n_messages = CONSOLIDATE_EVERY_N_MESSAGES
        self.consolidate_interval_seconds = CONSOLIDATE_INTERVAL_SECONDS
        self.model = GEMINI_MODEL  # Use same model as main AI
        self.min_conversation_length = MIN_CONVERSATION_LENGTH
        self.max_recent_messages = MAX_RECENT_MESSAGES_FOR_EXTRACTION

    def initialize(self, api_key: str) -> bool:
        """Initialize the Gemini client."""
        if not GENAI_AVAILABLE:
            logging.warning("google-genai not available for memory consolidation")
            return False

        try:
            self._client = genai.Client(api_key=api_key)
            logging.info("🧠 Memory Consolidator initialized")
            return True
        except Exception as e:
            logging.error("Failed to initialize Memory Consolidator: %s", e)
            return False

    def record_message(self, channel_id: int) -> None:
        """Record that a message was processed for this channel."""
        self._message_counts[channel_id] = self._message_counts.get(channel_id, 0) + 1

    def cleanup_old_channels(
        self,
        max_age_seconds: int = CONSOLIDATOR_CLEANUP_MAX_AGE_SECONDS,
        max_channels: int = CONSOLIDATOR_CLEANUP_MAX_CHANNELS,
    ) -> int:
        """
        Remove tracking data for channels inactive longer than max_age_seconds.
        Also enforces max channel limit to prevent memory growth.
        Returns number of channels cleaned up.

        Should be called periodically to prevent memory leaks.
        """
        removed = 0
        now = time.time()

        # Remove old channels
        for channel_id in list(self._last_consolidation.keys()):
            if now - self._last_consolidation[channel_id] > max_age_seconds:
                self._message_counts.pop(channel_id, None)
                self._last_consolidation.pop(channel_id, None)
                removed += 1

        # Enforce max channel limit if still over
        if len(self._last_consolidation) > max_channels:
            # Sort by oldest timestamp and remove excess
            sorted_channels = sorted(
                self._last_consolidation.keys(),
                key=lambda cid: self._last_consolidation[cid],
            )
            excess = len(self._last_consolidation) - max_channels
            for channel_id in sorted_channels[:excess]:
                self._message_counts.pop(channel_id, None)
                self._last_consolidation.pop(channel_id, None)
                removed += 1

        return removed

    def should_consolidate(self, channel_id: int) -> bool:
        """Check if consolidation should run for this channel."""
        msg_count = self._message_counts.get(channel_id, 0)
        last_time = self._last_consolidation.get(channel_id, 0)

        # Consolidate every N messages or every hour
        if msg_count >= self.consolidate_every_n_messages:
            return True
        return time.time() - last_time > self.consolidate_interval_seconds

    async def consolidate(
        self, channel_id: int, history: list[dict[str, Any]], guild_id: int | None = None
    ) -> int:
        """
        Extract facts from history and update entity memory.
        Returns number of entities updated.
        """
        if not self._client or not history:
            return 0

        try:
            # Get recent history for extraction
            recent = (
                history[-self.max_recent_messages :]
                if len(history) > self.max_recent_messages
                else history
            )
            conversation_text = self._history_to_text(recent)

            if len(conversation_text) < self.min_conversation_length:
                return 0  # Too short

            # Extract facts using AI
            prompt = FACT_EXTRACTION_PROMPT.format(conversation=conversation_text)

            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=1000,
                    temperature=0.1,  # Low temp for consistent extraction
                    response_mime_type="application/json",
                ),
            )

            if not response.text:
                return 0

            # Parse JSON response
            extracted = self._parse_extraction(response.text)

            if not extracted:
                return 0

            # Update entity memory
            updated = 0
            for entity_data in extracted.get("entities", []):
                success = await self._update_entity_from_extraction(
                    entity_data, channel_id, guild_id
                )
                if success:
                    updated += 1

            # Reset counters
            self._message_counts[channel_id] = 0
            self._last_consolidation[channel_id] = time.time()

            if updated > 0:
                logging.info("🧠 Consolidated %d entities for channel %s", updated, channel_id)

            return updated

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logging.warning("Memory consolidation parsing failed: %s", e)
            return 0
        except Exception as e:
            # Log with traceback for unexpected errors
            logging.error("Memory consolidation failed unexpectedly: %s", e, exc_info=True)
            return 0

    def _history_to_text(self, history: list[dict[str, Any]]) -> str:
        """Convert history to text for extraction."""
        lines = []
        for msg in history:
            role = "User" if msg.get("role") == "user" else "AI"
            parts = msg.get("parts", [])

            for part in parts:
                if isinstance(part, str):
                    text = part[:500] if len(part) > 500 else part
                    lines.append(f"{role}: {text}")
                elif isinstance(part, dict) and "text" in part:
                    text = part["text"][:500] if len(part["text"]) > 500 else part["text"]
                    lines.append(f"{role}: {text}")

        return "\n".join(lines[-100:])  # Last 100 lines max

    def _parse_extraction(self, response_text: str) -> dict | None:
        """Parse JSON extraction response."""
        try:
            # Clean up response
            text = response_text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            return json.loads(text)

        except (json.JSONDecodeError, ValueError) as e:
            logging.debug("JSON parse failed, trying fallback: %s", e)
            # Try to find JSON in response
            try:
                match = re.search(r"\{[\s\S]*\}", response_text)
                if match:
                    return json.loads(match.group())
            except (json.JSONDecodeError, ValueError) as fallback_error:
                logging.debug("JSON fallback parse also failed: %s", fallback_error)

        return None

    async def _update_entity_from_extraction(
        self, entity_data: dict, channel_id: int, guild_id: int | None
    ) -> bool:
        """Update entity memory from extracted data."""
        name = entity_data.get("name")
        entity_type = entity_data.get("type", "character")
        facts_data = entity_data.get("facts", {})

        if not name or not facts_data:
            return False

        # Calculate importance score based on fact richness
        importance_score = min(1.0, 0.3 + len(facts_data) * 0.1)

        # Boost for certain valuable facts
        if "age" in facts_data:
            importance_score += 0.15
        if facts_data.get("relationships"):
            importance_score += 0.2
        if "personality" in facts_data:
            importance_score += 0.1

        importance_score = min(1.0, importance_score)

        try:
            # Check for existing entity
            existing = await entity_memory.get_entity(name, channel_id, guild_id)

            if existing:
                # Merge with existing facts
                return await entity_memory.update_entity_facts(
                    name=name,
                    new_facts=facts_data,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    merge=True,
                )
            else:
                # Create new entity
                facts = EntityFacts.from_dict(facts_data)
                entity_id = await entity_memory.add_entity(
                    name=name,
                    entity_type=entity_type,
                    facts=facts,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    confidence=0.7 + importance_score * 0.2,  # 0.7-0.9 range
                    source="ai_extracted",
                )
                return entity_id is not None

        except Exception as e:
            logging.error("Failed to update entity %s: %s", name, e)
            return False

    async def detect_contradictions(
        self, new_text: str, channel_id: int, guild_id: int | None = None
    ) -> list[dict[str, str]]:
        """
        Detect contradictions between new text and stored entity facts.
        Returns list of contradictions found.
        """
        contradictions = []

        # Extract entity names from text
        name_patterns = re.findall(r"\{\{([^}]+)\}\}", new_text)

        for name in set(name_patterns):
            entity = await entity_memory.get_entity(name.strip(), channel_id, guild_id)
            if not entity:
                continue

            facts = entity.facts.to_dict()

            # Check for age contradictions
            if facts.get("age"):
                age_match = re.search(
                    rf"{name}.*?(\d+)\s*(?:ปี|years?|ขวบ)", new_text, re.IGNORECASE
                )
                if age_match:
                    mentioned_age = int(age_match.group(1))
                    if mentioned_age != facts["age"]:
                        contradictions.append(
                            {
                                "entity": name,
                                "field": "age",
                                "stored": str(facts["age"]),
                                "mentioned": str(mentioned_age),
                            }
                        )

            # Check for relationship contradictions
            if facts.get("relationships"):
                for related_name, relation in facts["relationships"].items():
                    # Check if text mentions a different relationship
                    rel_pattern = rf"{name}.*?{related_name}.*?(พี่|น้อง|แฟน|เพื่อน|ศัตรู|แม่|พ่อ)"
                    rel_match = re.search(rel_pattern, new_text, re.IGNORECASE)
                    if rel_match:
                        mentioned_rel = rel_match.group(1)
                        if mentioned_rel not in relation:
                            contradictions.append(
                                {
                                    "entity": name,
                                    "field": f"relationship with {related_name}",
                                    "stored": relation,
                                    "mentioned": mentioned_rel,
                                }
                            )

        return contradictions

    def format_contradictions_warning(self, contradictions: list[dict[str, str]]) -> str:
        """Format contradictions as a warning message for the prompt."""
        if not contradictions:
            return ""

        lines = ["[⚠️ คำเตือน: ตรวจพบข้อมูลที่อาจขัดแย้ง]"]
        for c in contradictions:
            lines.append(
                f"- {c['entity']}: {c['field']} ที่บันทึกไว้คือ '{c['stored']}' "
                f"แต่พบ '{c['mentioned']}' ในข้อความ"
            )
        lines.append("[กรุณาใช้ข้อมูลที่บันทึกไว้เป็นหลัก]")

        return "\n".join(lines)


# Global instance
memory_consolidator = MemoryConsolidator()
