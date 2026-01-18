"""
Smart History Management Module
Intelligent trimming and management of chat history.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

# Import summarizer for compression
try:
    from .summarizer import summarizer

    SUMMARIZER_AVAILABLE = True
except ImportError:
    SUMMARIZER_AVAILABLE = False


@dataclass
class HistoryStats:
    """Statistics about the history."""

    total_messages: int
    user_messages: int
    ai_messages: int
    important_count: int
    estimated_tokens: int


# Try to import tiktoken for accurate token counting
try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
    # Use cl100k_base encoding (closest to Gemini tokenization)
    _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    TIKTOKEN_AVAILABLE = False
    _TIKTOKEN_ENCODER = None


class HistoryManager:
    """
    Manages conversation history with intelligent trimming.

    Features:
    - Importance-based message retention
    - Smart summarization of old messages
    - User preference detection
    - Emotional significance detection
    - Token-aware context window management
    """

    # Patterns that indicate important messages
    IMPORTANCE_PATTERNS = [
        # User preferences and facts
        (r"(?:ชื่อ|name)\s*(?:ของ)?(?:ฉัน|ผม|ของฉัน|my|i\'m|im)\s*(?:คือ|is|เป็น)?", "user_name", 2.0),
        (r"(?:ฉัน|ผม|i)\s*(?:ชอบ|รัก|เกลียด|ไม่ชอบ|like|love|hate|dislike)", "preference", 1.5),
        (r"(?:วันเกิด|birthday|อายุ|age|ที่อยู่|address)", "personal_info", 1.8),
        # Emotional significance
        (r"(?:ขอบคุณ|thank|รัก|love|❤️|🙏)", "gratitude", 1.3),
        (r"(?:สำคัญ|important|จำ(?:ไว้)?|remember|อย่าลืม)", "explicit_important", 2.0),
        # Instructions and rules
        (r"(?:กฎ|rule|ต้อง|must|ห้าม|don\'t|never|always|เสมอ)", "rule", 1.5),
        # Context setters
        (r"(?:ตั้งแต่|since|เพราะ|because|เนื่องจาก)", "context", 1.2),
        # Roleplay character introductions
        (r"\{\{[^}]+\}\}", "character", 1.4),
    ]

    # Default settings - optimized for Gemini 2M context window
    DEFAULT_KEEP_RECENT = 200  # Always keep last N messages
    DEFAULT_MAX_HISTORY = 10000  # Max messages after trimming
    DEFAULT_COMPRESS_THRESHOLD = 2000  # Start compressing after this
    DEFAULT_MAX_TOKENS = 1200000  # 1.2M tokens for history (60% of 2M)
    TOKENS_PER_MESSAGE_ESTIMATE = 50  # Fallback rough estimate

    def __init__(
        self,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        max_history: int = DEFAULT_MAX_HISTORY,
        compress_threshold: int = DEFAULT_COMPRESS_THRESHOLD,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.keep_recent = keep_recent
        self.max_history = max_history
        self.compress_threshold = compress_threshold
        self.max_tokens = max_tokens
        self.logger = logging.getLogger("HistoryManager")

        # Pre-compile patterns
        self._importance_patterns = [
            (re.compile(pattern, re.IGNORECASE), name, weight)
            for pattern, name, weight in self.IMPORTANCE_PATTERNS
        ]

    def estimate_tokens(self, history: list[dict[str, Any]]) -> int:
        """
        Estimate token count for history using tiktoken.

        Uses cl100k_base encoding as approximation for Gemini tokenization.
        Falls back to character-based estimation if tiktoken unavailable.

        Args:
            history: Conversation history

        Returns:
            Estimated token count
        """
        total_tokens = 0

        for msg in history:
            content = self._get_message_content(msg)
            if not content:
                continue

            if TIKTOKEN_AVAILABLE and _TIKTOKEN_ENCODER:
                # Accurate token counting
                total_tokens += len(_TIKTOKEN_ENCODER.encode(content))
            else:
                # Fallback: ~4 characters per token (rough estimate)
                total_tokens += len(content) // 4

            # Add overhead for message structure (role, separators)
            total_tokens += 5

        return total_tokens

    def estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """Estimate tokens for a single message."""
        content = self._get_message_content(message)
        if not content:
            return 5  # Minimal overhead

        if TIKTOKEN_AVAILABLE and _TIKTOKEN_ENCODER:
            return len(_TIKTOKEN_ENCODER.encode(content)) + 5
        return len(content) // 4 + 5

    def get_stats(self, history: list[dict[str, Any]]) -> HistoryStats:
        """Get statistics about the history."""
        user_count = sum(1 for m in history if m.get("role") == "user")
        ai_count = len(history) - user_count

        important_count = 0
        for msg in history:
            if self._calculate_importance(msg)[0] >= 1.3:
                important_count += 1

        return HistoryStats(
            total_messages=len(history),
            user_messages=user_count,
            ai_messages=ai_count,
            important_count=important_count,
            estimated_tokens=self.estimate_tokens(history),
        )

    def _calculate_importance(self, message: dict[str, Any]) -> tuple[float, list[str]]:
        """
        Calculate importance score for a message.

        Returns:
            Tuple of (score, list of matched patterns)
        """
        content = self._get_message_content(message)
        if not content:
            return 1.0, []

        score = 1.0
        matched = []

        # Check importance patterns
        for pattern, name, weight in self._importance_patterns:
            if pattern.search(content):
                score = max(score, weight)
                matched.append(name)

        # Boost for longer messages (usually more substantive)
        if len(content) > 200:
            score *= 1.1

        # Boost for user messages (preserve user input)
        if message.get("role") == "user":
            score *= 1.1

        return score, matched

    def _get_message_content(self, message: dict[str, Any]) -> str:
        """Extract text content from message."""
        parts = message.get("parts", [])
        text_parts = []

        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(part["text"])

        return " ".join(text_parts)

    async def smart_trim(
        self, history: list[dict[str, Any]], max_messages: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Intelligently trim history while preserving important messages.

        Strategy:
        1. Always keep recent messages (last N)
        2. Keep messages with high importance scores
        3. Summarize the rest if possible
        4. Fall back to simple truncation

        Args:
            history: Full conversation history
            max_messages: Override for max history size

        Returns:
            Trimmed history list
        """
        max_messages = max_messages or self.max_history

        if len(history) <= max_messages:
            return history  # No trimming needed

        self.logger.info("📦 Smart trimming history: %d -> %d messages", len(history), max_messages)

        # 1. Split history into sections
        recent = history[-self.keep_recent :]
        older = history[: -self.keep_recent]

        # 2. Score all older messages
        scored_messages = []
        for i, msg in enumerate(older):
            importance, patterns = self._calculate_importance(msg)
            scored_messages.append((i, msg, importance, patterns))

        # 3. Sort by importance (descending)
        scored_messages.sort(key=lambda x: x[2], reverse=True)

        # 4. Calculate how many older messages we can keep
        available_slots = max_messages - len(recent)

        # Reserve some slots for a summary
        summary_slots = 1 if SUMMARIZER_AVAILABLE else 0
        message_slots = available_slots - summary_slots

        # 5. Select top important messages (preserving order)
        important_indices = {msg[0] for msg in scored_messages[:message_slots]}

        kept_older = [msg for i, msg in enumerate(older) if i in important_indices]

        # 6. Summarize discarded messages if possible
        discarded = [msg for i, msg in enumerate(older) if i not in important_indices]

        summary_entry = None
        if SUMMARIZER_AVAILABLE and len(discarded) >= 10:
            try:
                summary_text = await summarizer.summarize(discarded, max_messages=50)
                if summary_text:
                    summary_entry = {
                        "role": "user",
                        "parts": [
                            f"[📝 สรุปบทสนทนาก่อนหน้า ({len(discarded)} messages)]\n{summary_text}"
                        ],
                    }
                    self.logger.info(
                        "📝 Created summary from %d discarded messages", len(discarded)
                    )
            except Exception as e:
                self.logger.warning("Failed to create summary: %s", e)

        # 7. Combine: summary (if any) + kept older + recent
        result = []
        if summary_entry:
            result.append(summary_entry)
        result.extend(kept_older)
        result.extend(recent)

        self.logger.info(
            "📦 History trimmed: %d total (kept %d important, %d recent, 1 summary)",
            len(result),
            len(kept_older),
            len(recent),
        )

        return result

    def quick_trim(
        self, history: list[dict[str, Any]], max_messages: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Quick synchronous trim without summarization.
        For use when async is not available.
        """
        max_messages = max_messages or self.max_history

        if len(history) <= max_messages:
            return history

        # Simple approach: keep first few + last many
        keep_start = max_messages // 10
        keep_end = max_messages - keep_start

        return history[:keep_start] + history[-keep_end:]

    async def smart_trim_by_tokens(
        self,
        history: list[dict[str, Any]],
        max_tokens: int | None = None,
        reserve_tokens: int = 2000,
    ) -> list[dict[str, Any]]:
        """
        Trim history to fit within a token budget.

        Iteratively removes lowest-importance messages until
        the history fits within the token limit.

        Args:
            history: Conversation history
            max_tokens: Maximum token budget (default: self.max_tokens)
            reserve_tokens: Tokens to reserve for response (default: 2000)

        Returns:
            Trimmed history that fits within token budget
        """
        max_tokens = max_tokens or self.max_tokens
        target_tokens = max_tokens - reserve_tokens

        current_tokens = self.estimate_tokens(history)

        if current_tokens <= target_tokens:
            return history  # Already within budget

        self.logger.info("📊 Token trim needed: %d -> %d tokens", current_tokens, target_tokens)

        # Work with a copy
        working_history = list(history)

        # Always protect the most recent messages
        protected_count = min(self.keep_recent, len(working_history) // 2)

        while self.estimate_tokens(working_history) > target_tokens:
            if len(working_history) <= protected_count + 1:
                self.logger.warning("Cannot trim further without losing recent context")
                break

            # Find lowest importance message (excluding protected recent ones)
            trimmable = (
                working_history[:-protected_count] if protected_count > 0 else working_history
            )

            if not trimmable:
                break

            # Score all trimmable messages
            scored = [(i, self._calculate_importance(msg)[0]) for i, msg in enumerate(trimmable)]

            # Remove lowest importance message
            scored.sort(key=lambda x: x[1])
            remove_idx = scored[0][0]

            removed_msg = working_history.pop(remove_idx)
            removed_tokens = self.estimate_message_tokens(removed_msg)

            self.logger.debug(
                "Removed message at %d (importance: %.2f, tokens: %d)",
                remove_idx,
                scored[0][1],
                removed_tokens,
            )

        final_tokens = self.estimate_tokens(working_history)
        self.logger.info(
            "📦 Token trim complete: %d -> %d messages (%d tokens)",
            len(history),
            len(working_history),
            final_tokens,
        )

        return working_history

    def extract_user_facts(self, history: list[dict[str, Any]]) -> dict[str, list[str]]:
        """
        Extract user facts and preferences from history.
        Useful for building a user profile.
        """
        facts: dict[str, list[str]] = {
            "names": [],
            "preferences": [],
            "personal_info": [],
            "rules": [],
        }

        name_pattern = re.compile(
            r"(?:ชื่อ|name)\s*(?:ของ)?(?:ฉัน|ผม|my)?\s*(?:คือ|is|เป็น)?\s*[:\s]*([^\s,\.]+)",
            re.IGNORECASE,
        )

        pref_pattern = re.compile(
            r"(?:ฉัน|ผม|i)\s*(?:ชอบ|รัก|like|love)\s+(.+?)(?:[,\.]|$)", re.IGNORECASE
        )

        for msg in history:
            if msg.get("role") != "user":
                continue

            content = self._get_message_content(msg)

            # Extract names
            name_match = name_pattern.search(content)
            if name_match:
                name = name_match.group(1).strip()
                if name and name not in facts["names"]:
                    facts["names"].append(name)

            # Extract preferences
            pref_matches = pref_pattern.findall(content)
            for pref in pref_matches:
                pref = pref.strip()[:50]  # Limit length
                if pref and pref not in facts["preferences"]:
                    facts["preferences"].append(pref)

        return facts


# Global instance
history_manager = HistoryManager()


async def smart_trim_history(
    history: list[dict[str, Any]], max_messages: int = 500
) -> list[dict[str, Any]]:
    """Convenience function for smart trimming."""
    return await history_manager.smart_trim(history, max_messages)
