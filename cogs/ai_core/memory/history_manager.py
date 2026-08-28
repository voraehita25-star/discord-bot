"""
Smart History Management Module
Intelligent trimming and management of chat history.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

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
    _TIKTOKEN_ENCODER = None  # type: ignore[assignment]


# Prefix on the synthetic history row that stands in for messages a trim
# discarded. Exposed (with :func:`is_summary_entry`) so callers can tell
# "trimmed AND summarised" apart from "trimmed, old turns are simply gone" and
# say which one happened — the over-limit prompt and ``!auto_summarize`` both
# used to promise a summary unconditionally while the summarizer is disabled on
# the default CLI backend, so the honest answer was usually the second one.
SUMMARY_ENTRY_PREFIX = "[📝 สรุปบทสนทนาก่อนหน้า"


def is_summary_entry(item: Any) -> bool:
    """True when ``item`` is a trim-generated summary row."""
    if not isinstance(item, dict):
        return False
    parts = item.get("parts") or []
    first = parts[0] if parts else ""
    if isinstance(first, dict):
        first = first.get("text", "")
    return isinstance(first, str) and first.startswith(SUMMARY_ENTRY_PREFIX)


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
    IMPORTANCE_PATTERNS: ClassVar[list[tuple[str, str, float]]] = [
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

    # Default settings — sized for the smaller of Claude/Gemini current context
    # windows (1M each). Reserve ~40% for system prompt, response, and tool
    # outputs so a default trim never blows past either provider's limit. If
    # you want a tighter target, pass max_tokens explicitly to smart_trim_by_tokens.
    DEFAULT_KEEP_RECENT = 200  # Always keep last N messages
    DEFAULT_MAX_HISTORY = 10000  # Max messages after trimming
    DEFAULT_MAX_TOKENS = 600_000  # ~60% of 1M context window
    # เมื่อ history ใหญ่กว่านี้ การ encode ด้วย tiktoken แบบ synchronous จะ
    # block event loop / discord.py heartbeat นานเกินไป จึง offload ไป worker
    # thread ผ่าน asyncio.to_thread (ดู smart_trim_by_tokens). ต่ำกว่า threshold
    # นี้คำนวณ inline เพื่อเลี่ยง overhead ของ thread-pool บน history เล็ก ๆ
    TOKEN_ESTIMATE_OFFLOAD_THRESHOLD = 500  # messages
    # (DEFAULT_COMPRESS_THRESHOLD / TOKENS_PER_MESSAGE_ESTIMATE removed —
    # they were stored but nothing ever read them.)

    def __init__(
        self,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        max_history: int = DEFAULT_MAX_HISTORY,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.keep_recent = keep_recent
        self.max_history = max_history
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
        if not history:
            return 0

        total_tokens = 0

        for msg in history:
            content = self._get_message_content(msg)
            # Structural overhead (role, separators) for EVERY message — matches
            # estimate_message_tokens(), which returns 5 even for empty content,
            # so the two baselines in smart_trim_by_tokens stay consistent.
            total_tokens += 5
            if not content:
                continue

            if TIKTOKEN_AVAILABLE and _TIKTOKEN_ENCODER:
                # Accurate token counting
                total_tokens += len(_TIKTOKEN_ENCODER.encode(content))
            else:
                # Fallback: Smart character-based estimation
                # Thai/Unicode text typically has ~2-3 chars per token
                # ASCII text typically has ~4 chars per token
                total_tokens += self._estimate_tokens_fallback(content)

        return total_tokens

    # Characters per token, per script. Measured with cl100k_base against this
    # bot's own stored history (267,614 chars of Thai RP), not assumed:
    #
    #   non-ASCII alone : 229,304 chars -> 219,187 tokens = 1.046 chars/token
    #   ASCII alone     :  38,310 chars ->  15,050 tokens = 2.546 chars/token
    #   English prose   :     900 chars ->     201 tokens = 4.48  chars/token
    #
    # The old non-ASCII divisor was 2.5, which the docstring called "more
    # conservative". It was the opposite: against the real 1.046 it UNDER-counted
    # Thai by ~58%. That matters because ``smart_trim_by_tokens`` is what the
    # over-limit "📝 ย่อประวัติแชท" button runs — a history that is over the
    # window looked like it already fit, so the trim removed nothing, reported
    # "✅ ย่อประวัติเรียบร้อย", and the next turn was over the limit again.
    #
    # Aim for ACCURACY rather than a safety direction. Both errors cost
    # something here: under-counting wedges the channel in that loop, while
    # over-counting makes a trim that force-saves (i.e. permanently deletes)
    # drop more than it needed to. ``smart_trim_by_tokens``'s own
    # ``reserve_tokens`` is where the margin belongs. Re-measured on the same
    # corpus these values land within 0.4% of tiktoken, down from 58%.
    #
    # ASCII stays at 4: that is right for English prose (4.48 measured). The
    # 2.546 above is ASCII extracted OUT of Thai text — punctuation, digits and
    # markers — which the estimator never sees in isolation.
    _ASCII_CHARS_PER_TOKEN = 4.0
    _NON_ASCII_CHARS_PER_TOKEN = 1.0

    def _estimate_tokens_fallback(self, content: str) -> int:
        """
        Smart fallback token estimation for mixed Thai/English text.

        Only reached when tiktoken is unavailable. See the class constants above
        for the measured per-script rates and why they err toward over-counting.
        """
        if not content:
            return 0

        # Count ASCII vs non-ASCII characters
        ascii_count = sum(1 for c in content if ord(c) < 128)
        non_ascii_count = len(content) - ascii_count

        ascii_tokens = ascii_count / self._ASCII_CHARS_PER_TOKEN
        non_ascii_tokens = non_ascii_count / self._NON_ASCII_CHARS_PER_TOKEN

        return max(1, int(ascii_tokens + non_ascii_tokens))

    def estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """Estimate tokens for a single message."""
        content = self._get_message_content(message)
        if not content:
            return 5  # Minimal overhead

        if TIKTOKEN_AVAILABLE and _TIKTOKEN_ENCODER:
            return len(_TIKTOKEN_ENCODER.encode(content)) + 5
        return self._estimate_tokens_fallback(content) + 5

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
        # ``or []`` (not ``.get("parts", [])``): a row that carries the key with
        # an explicit ``None`` returns None from the two-arg get, and the loop
        # below then raises ``TypeError: 'NoneType' object is not iterable`` —
        # out of ``estimate_tokens``, which ``!auto_summarize`` calls OUTSIDE its
        # try (see ai_cog) and ``debug_commands`` already documents as a runtime
        # hazard. ``is_summary_entry`` at the top of this module uses the safe
        # form; this was the one place in the file that didn't. The non-list
        # guard mirrors ``storage._parts_to_text`` / the JSON loader, which both
        # normalise the field for exactly this reason.
        parts = message.get("parts") or []
        if not isinstance(parts, list):
            return ""
        text_parts = []

        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text = str(part.get("text", ""))
                if text:
                    text_parts.append(text)

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
            return list(history)  # Return a copy to prevent caller mutation

        self.logger.info("📦 Smart trimming history: %d -> %d messages", len(history), max_messages)

        # 1. Split history into sections. Clamp the "recent" tail to max_messages
        # so the result can never exceed the requested cap: with the raw
        # keep_recent slice, a caller passing max_messages < keep_recent would
        # get back more than max_messages items (recent alone already exceeds the
        # cap). When max_messages >= keep_recent (the normal case) this is a
        # no-op. CRITICAL: `older` must use the SAME clamp so older + recent ==
        # history; slicing older with the raw keep_recent while recent uses the
        # clamped value would drop the middle band (between -keep_recent and
        # -clamp) into NEITHER list, silently discarding it without summarizing.
        clamp = min(self.keep_recent, max_messages)
        recent = history[-clamp:] if clamp else []
        older = history[:-clamp] if clamp else list(history)

        # 2. Score all older messages. _calculate_importance does a content-join
        # + 8 compiled-regex .search() calls per message — real CPU work. On
        # large histories offload the whole scan to a worker thread (mirroring
        # smart_trim_by_tokens) so the regex pass doesn't block the event loop /
        # heartbeat. Small histories compute inline to avoid thread overhead.
        def _score_older() -> list[tuple[int, dict[str, Any], float, list[str]]]:
            scored: list[tuple[int, dict[str, Any], float, list[str]]] = []
            for i, msg in enumerate(older):
                importance, patterns = self._calculate_importance(msg)
                scored.append((i, msg, importance, patterns))
            return scored

        if len(older) > self.TOKEN_ESTIMATE_OFFLOAD_THRESHOLD:
            scored_messages = await asyncio.to_thread(_score_older)
        else:
            scored_messages = _score_older()

        # 3. Sort by importance (descending)
        scored_messages.sort(key=lambda x: x[2], reverse=True)

        # 4. Calculate how many older messages we can keep
        available_slots = max_messages - len(recent)

        # Reserve some slots for a summary — only when a slot actually
        # exists. With max_messages <= keep_recent there are zero available
        # slots, and appending a summary anyway exceeded the caller's cap by
        # one (and wasted a summarizer API call).
        summary_slots = 1 if (SUMMARIZER_AVAILABLE and available_slots > 0) else 0
        message_slots = max(0, available_slots - summary_slots)

        # 5. Select top important messages (preserving order)
        important_indices = {msg[0] for msg in scored_messages[:message_slots]}

        kept_older = [msg for i, msg in enumerate(older) if i in important_indices]

        # 6. Summarize discarded messages if possible
        discarded = [msg for i, msg in enumerate(older) if i not in important_indices]

        summary_entry = await self._build_summary_entry(discarded) if summary_slots else None

        # 7. Combine: summary (if any) + kept older + recent
        result = []
        if summary_entry:
            result.append(summary_entry)
        result.extend(kept_older)
        result.extend(recent)

        self.logger.info(
            "📦 History trimmed: %d total (kept %d important, %d recent, %d summary)",
            len(result),
            len(kept_older),
            len(recent),
            1 if summary_entry else 0,
        )

        return result

    async def _build_summary_entry(self, discarded: list[dict[str, Any]]) -> dict[str, Any] | None:
        """One history row standing in for ``discarded``, or None.

        Returns None when no summary can be produced: the summarizer module is
        absent, its SDK client is unset (which is the case under
        CLAUDE_BACKEND=cli — the DEFAULT — so this is the common outcome, not an
        edge case), the set is too small to be worth summarising, or the API
        call failed. Callers MUST treat None as "the discarded turns are simply
        gone" and report it as such rather than claiming a summary was written.

        Shared by :meth:`smart_trim` and :meth:`smart_trim_by_tokens` so the two
        trims can't drift on how (or whether) they preserve what they drop.
        """
        if not SUMMARIZER_AVAILABLE or len(discarded) < 10:
            return None
        try:
            # max_messages must cover the WHOLE discarded set: summarize()
            # slices history[-max_messages:], so the old max_messages=50
            # silently summarized only the newest 50 discarded messages while
            # the stored entry below claims coverage of all len(discarded) —
            # the model then treated lost context as summarized.
            # compress_history fixed this identical trap the same way.
            summary_text = await summarizer.summarize(discarded, max_messages=len(discarded))
        except Exception as e:
            self.logger.warning("Failed to create summary: %s", e)
            return None
        if not summary_text:
            return None
        self.logger.info("📝 Created summary from %d discarded messages", len(discarded))
        return {
            "role": "user",
            "parts": [f"{SUMMARY_ENTRY_PREFIX} ({len(discarded)} messages)]\n{summary_text}"],
            # Timestamp matters downstream: storage force-replace must not
            # insert NULL (bypasses the column default), and the
            # SummaryArchiver's `WHERE timestamp < ?` would never see a
            # NULL-timestamp row.
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def quick_trim(
        self, history: list[dict[str, Any]], max_messages: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Quick synchronous trim without summarization.
        For use when async is not available.
        """
        max_messages = max_messages or self.max_history

        if len(history) <= max_messages:
            # Return a copy, not the original object — every other trim path
            # (smart_trim, smart_trim_by_tokens) returns a fresh list, so a
            # caller that mutates the result must not corrupt the live history.
            return list(history)

        # Simple approach: keep first few + last many
        keep_start = max_messages // 10
        keep_end = max_messages - keep_start

        return history[:keep_start] + history[-keep_end:]

    async def smart_trim_by_tokens(
        self,
        history: list[dict[str, Any]],
        max_tokens: int | None = None,
        reserve_tokens: int = 2000,
        summarize: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Trim history to fit within a token budget.

        Iteratively removes lowest-importance messages until
        the history fits within the token limit.

        Args:
            history: Conversation history
            max_tokens: Maximum token budget (default: self.max_tokens)
            reserve_tokens: Tokens to reserve for response (default: 2000)
            summarize: roll the removed messages into a single leading summary
                row when one can be produced (see :meth:`_build_summary_entry`).
                Off by default so the prompt-shaping callers keep their exact
                previous behaviour; the two USER-FACING callers — the over-limit
                "condense this chat" button and ``!auto_summarize`` — pass True,
                because both persist their result with ``force=True`` and the
                removed rows are gone for good afterwards. Check
                :func:`is_summary_entry` on the result to find out whether a
                summary actually materialised.

        Returns:
            Trimmed history that fits within token budget
        """
        max_tokens = max_tokens or self.max_tokens
        target_tokens = max_tokens - reserve_tokens

        # tiktoken encode เป็น CPU-bound และ synchronous การรันบน history ใหญ่
        # จะ block event loop / heartbeat จึง offload ทั้ง estimate_tokens และ
        # per-message estimation ไป worker thread เมื่อ history ใหญ่กว่า threshold
        # ส่วน history เล็กคำนวณ inline เพื่อเลี่ยง overhead ของ thread-pool
        offload = len(history) > self.TOKEN_ESTIMATE_OFFLOAD_THRESHOLD

        if offload:
            current_tokens = await asyncio.to_thread(self.estimate_tokens, history)
        else:
            current_tokens = self.estimate_tokens(history)

        if current_tokens <= target_tokens:
            return list(history)  # Already within budget; return a copy so the
            # caller can mutate it without surprising
            # other callers that share the input list.

        self.logger.info("📊 Token trim needed: %d -> %d tokens", current_tokens, target_tokens)

        # Work with a copy
        working_history = list(history)

        # Pre-calculate per-message tokens to avoid O(n²) recalculation
        if offload:
            message_tokens = await asyncio.to_thread(
                lambda: [self.estimate_message_tokens(msg) for msg in working_history]
            )
        else:
            message_tokens = [self.estimate_message_tokens(msg) for msg in working_history]
        running_total = sum(message_tokens)

        # Always protect the most recent messages
        protected_count = min(self.keep_recent, len(working_history) // 2)

        # Pre-compute importance scores and build a min-heap for O(n log n) trimming
        trim_end = (
            len(working_history) - protected_count if protected_count > 0 else len(working_history)
        )
        if trim_end > 0:
            # Build heap of (importance, original_index) for trimmable messages.
            # _calculate_importance does a content-join + 8 compiled-regex
            # .search() calls per message — real CPU work. On large histories
            # offload the whole scan to a worker thread (mirroring the
            # per-message token estimation above) so the regex pass doesn't
            # block the event loop / heartbeat; heapify is cheap and stays on
            # the loop. Small histories compute inline to avoid thread overhead.
            trimmable = working_history[:trim_end]
            if offload:
                importance_heap = await asyncio.to_thread(
                    lambda: [
                        (self._calculate_importance(msg)[0], i) for i, msg in enumerate(trimmable)
                    ]
                )
            else:
                importance_heap = [
                    (self._calculate_importance(msg)[0], i) for i, msg in enumerate(trimmable)
                ]
            heapq.heapify(importance_heap)
        else:
            importance_heap = []

        removed_indices: set[int] = set()

        while running_total > target_tokens and importance_heap:
            if len(working_history) - len(removed_indices) <= protected_count + 1:
                self.logger.warning("Cannot trim further without losing recent context")
                break

            importance, remove_idx = heapq.heappop(importance_heap)
            if remove_idx in removed_indices:
                # Already removed by an earlier iteration; skip without
                # double-subtracting from running_total.
                continue

            removed_indices.add(remove_idx)
            running_total -= message_tokens[remove_idx]

            self.logger.debug(
                "Removed message at %d (importance: %.2f, tokens: %d)",
                remove_idx,
                importance,
                message_tokens[remove_idx],
            )

        # If the heap is exhausted but we still exceed the budget, the protected
        # recent tail alone is over budget. Warn instead of silently returning an
        # over-budget history; do not hard-truncate protected messages.
        if running_total > target_tokens:
            self.logger.warning(
                "Token budget could not be met: %d > %d tokens "
                "(protected recent tail exceeds budget)",
                running_total,
                target_tokens,
            )

        # Build result excluding removed indices
        discarded = [msg for i, msg in enumerate(working_history) if i in removed_indices]
        working_history = [msg for i, msg in enumerate(working_history) if i not in removed_indices]

        # Roll the dropped turns into one summary row when asked and possible.
        # Prepended (not appended) so it reads as the oldest context, matching
        # smart_trim's layout. The extra row is a few hundred tokens against a
        # budget measured in hundreds of thousands, so it does not reopen the
        # over-budget condition in any realistic configuration.
        if summarize and discarded:
            summary_entry = await self._build_summary_entry(discarded)
            if summary_entry is not None:
                working_history.insert(0, summary_entry)

        final_tokens = running_total
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

        # Cap the captured name at 50 chars so adversarial input with no
        # punctuation can't blow up cache size by appending a 10 KB
        # "name" to facts["names"].
        name_pattern = re.compile(
            r"(?:ชื่อ|name)\s*(?:ของ)?(?:ฉัน|ผม|my)?\s*(?:คือ|is|เป็น)?\s*[:\s]*([^\s,\.]{1,50})",
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
