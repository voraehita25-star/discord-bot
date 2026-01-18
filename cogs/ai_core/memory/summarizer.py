"""
Conversation Summarization Module
Summarizes long chat histories to save tokens while preserving context.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google import genai
from google.genai import types

from ..data.constants import GEMINI_API_KEY

# Summarization Model (configurable via environment variable)
# Default to gemini-3-flash-preview for cost-effective summarization
SUMMARIZATION_MODEL = os.getenv("GEMINI_SUMMARIZATION_MODEL", "gemini-3-flash-preview")

# Conversation length thresholds
MIN_CONVERSATION_LENGTH = 200  # Minimum characters to summarize


# Summarization prompt template
SUMMARIZE_PROMPT = """สรุปบทสนทนาต่อไปนี้ให้กระชับและครบถ้วน ใน 2-3 ประโยค:
- เก็บประเด็นสำคัญ ชื่อ และข้อมูลที่ต้องจำ
- เขียนเป็นมุมมองบุคคลที่สาม
- ใช้ภาษาเดียวกับบทสนทนา

บทสนทนา:
{conversation}

สรุป:"""


class ConversationSummarizer:
    """Handles summarization of long conversations."""

    def __init__(self):
        self.client = None
        self.model = SUMMARIZATION_MODEL  # Configurable model for summarization

        if GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
            except Exception as e:
                logging.error("Failed to init Gemini Client for summarization: %s", e)

    async def summarize(self, history: list[dict[str, Any]], max_messages: int = 50) -> str | None:
        """Summarize conversation history.

        Args:
            history: List of message dicts with 'role' and 'parts'.
            max_messages: Max recent messages to summarize.

        Returns:
            Summary string or None if failed.
        """
        if not self.client or len(history) < 10:
            return None

        try:
            # Convert history to text
            conversation_text = self._history_to_text(history[-max_messages:])

            if len(conversation_text) < MIN_CONVERSATION_LENGTH:
                return None  # Too short to summarize

            # Generate summary
            prompt = SUMMARIZE_PROMPT.format(conversation=conversation_text)

            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=300,
                    temperature=0.3,  # Low temp for consistent summaries
                ),
            )

            summary = response.text.strip() if response.text else None

            if summary:
                logging.info("📝 Generated conversation summary: %s...", summary[:50])

            return summary

        except Exception as e:
            logging.error("Summarization failed: %s", e)
            return None

    def _history_to_text(self, history: list[dict[str, Any]]) -> str:
        """Convert history list to readable text."""
        lines = []
        for msg in history:
            role = "User" if msg.get("role") == "user" else "AI"
            parts = msg.get("parts", [])

            for part in parts:
                if isinstance(part, str):
                    # Truncate long messages
                    text = part[:500] + "..." if len(part) > 500 else part
                    lines.append(f"{role}: {text}")
                elif isinstance(part, dict) and "text" in part:
                    text = part["text"][:500] + "..." if len(part["text"]) > 500 else part["text"]
                    lines.append(f"{role}: {text}")

        return "\n".join(lines)

    async def should_summarize(self, history: list[dict[str, Any]], threshold: int = 100) -> bool:
        """Check if history should be summarized.

        Args:
            history: Current chat history.
            threshold: Number of messages before summarization.

        Returns:
            True if summarization is recommended.
        """
        return len(history) >= threshold

    async def compress_history(
        self, history: list[dict[str, Any]], keep_recent: int = 20
    ) -> list[dict[str, Any]]:
        """Compress history by summarizing old messages.

        Args:
            history: Full chat history.
            keep_recent: Number of recent messages to keep intact.

        Returns:
            Compressed history with summary + recent messages.
        """
        if len(history) <= keep_recent + 10:
            return history  # Not enough to compress

        # Split history
        old_history = history[:-keep_recent]
        recent_history = history[-keep_recent:]

        # Summarize old history
        summary = await self.summarize(old_history)

        if not summary:
            return history  # Keep original if summarization failed

        # Create compressed history
        summary_entry = {"role": "user", "parts": [f"[บทสรุปการสนทนาก่อนหน้า]\n{summary}"]}

        compressed = [summary_entry, *recent_history]

        logging.info("📦 Compressed history: %d → %d messages", len(history), len(compressed))

        return compressed


# Global instance
summarizer = ConversationSummarizer()
