"""
Conversation Summarization Module
Summarizes long chat histories to save tokens while preserving context.
"""

from __future__ import annotations

import asyncio
import logging
logger = logging.getLogger(__name__)
import os
from typing import Any

import anthropic

from ..claude_payloads import build_single_user_text_messages
from ..data.constants import (
    ANTHROPIC_API_KEY,
    DEFAULT_MODEL,
    MIN_CONVERSATION_LENGTH,
    SUMMARIZATION_MAX_OUTPUT_TOKENS,
)

# Summarization Model (configurable via environment variable)
SUMMARIZATION_MODEL = os.getenv("CLAUDE_SUMMARIZATION_MODEL", DEFAULT_MODEL)


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
        self.client: anthropic.AsyncAnthropic | None = None
        self.model = SUMMARIZATION_MODEL

        if ANTHROPIC_API_KEY:
            try:
                self.client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            except Exception:
                logger.exception("Failed to init Anthropic Client for summarization")

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

            # Generate summary with retry logic
            prompt = SUMMARIZE_PROMPT.replace("{conversation}", conversation_text)

            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    response = await self.client.messages.create(
                        model=self.model,
                        max_tokens=SUMMARIZATION_MAX_OUTPUT_TOKENS,
                        messages=build_single_user_text_messages(prompt),
                    )

                    summary = None
                    for block in response.content:
                        if block.type == "text":
                            summary = block.text.strip()
                            break

                    if summary:
                        logger.info("📝 Generated conversation summary: %s...", summary[:50])

                    return summary

                except (TimeoutError, ValueError, TypeError, OSError, RuntimeError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        # Exponential backoff base 2 capped at 30s to respect Anthropic 429 retry guidance.
                        backoff = min(30.0, float(2 ** attempt))
                        await asyncio.sleep(backoff)
                        logger.warning("Summarization attempt %d failed: %s", attempt + 1, e)
                    continue
                except Exception as e:
                    last_error = e
                    logger.exception("Unexpected summarization error (no retry)")
                    break

            # All retries failed
            logger.error("Summarization failed after %d attempts: %s", max_retries, last_error)
            return None

        except (ValueError, TypeError) as e:
            logger.warning("Summarization parsing error: %s", e)
            return None
        except Exception:
            logger.exception("Summarization failed unexpectedly")
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

        logger.info("📦 Compressed history: %d → %d messages", len(history), len(compressed))

        return compressed


# Global instance
summarizer = ConversationSummarizer()
