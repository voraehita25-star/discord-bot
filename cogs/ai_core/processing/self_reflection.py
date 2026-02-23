"""
Self-Reflection Module for AI Response Quality.
Implements a lightweight check system for AI responses before sending.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IssueType(Enum):
    """Types of issues that can be detected in AI responses."""

    HALLUCINATION = "hallucination"
    OFF_TOPIC = "off_topic"
    INCOMPLETE = "incomplete"
    REPETITIVE = "repetitive"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    UNSAFE = "unsafe"
    INCONSISTENT = "inconsistent"
    LOW_CONFIDENCE = "low_confidence"


@dataclass
class Issue:
    """Represents a detected issue in the response."""

    type: IssueType
    description: str
    severity: float  # 0.0 to 1.0
    suggestion: str | None = None


@dataclass
class ReflectionResult:
    """Result of self-reflection analysis."""

    is_valid: bool
    confidence: float
    issues: list[Issue] = field(default_factory=list)
    suggested_revision: str | None = None
    processing_time_ms: float = 0.0

    @property
    def has_critical_issues(self) -> bool:
        """Check if there are any critical (severity > 0.7) issues."""
        return any(issue.severity > 0.7 for issue in self.issues)

    @property
    def issue_summary(self) -> str:
        """Get a summary of all issues."""
        if not self.issues:
            return "No issues detected"
        return "; ".join(f"{i.type.value}: {i.description}" for i in self.issues)


class SelfReflector:
    """
    Self-reflection system for AI responses.

    Performs lightweight checks to catch common issues:
    - Hallucination markers (uncertain language patterns)
    - Off-topic responses
    - Incomplete answers
    - Repetitive content
    - Safety concerns

    Can be configured to be strict (reject more) or lenient (pass more).
    """

    # Patterns that might indicate hallucination or uncertainty
    HALLUCINATION_PATTERNS = [
        # English patterns
        r"\b(I think|I believe|probably|maybe|possibly|might be|could be)\b",
        r"\b(I\'m not sure|I don\'t know for certain|I can\'t recall)\b",
        r"\b(allegedly|supposedly|reportedly)\b",
        # Thai patterns (Thai has no word boundaries, so no \b)
        r"(คิดว่า|เชื่อว่า|น่าจะ|อาจจะ|บางที|เป็นไปได้ว่า)",
        r"(ไม่แน่ใจ|ไม่ค่อยแน่ใจ|จำไม่ได้|ไม่ทราบแน่ชัด)",
        r"(มีรายงานว่า|ตามข่าว|ว่ากันว่า)",
    ]

    # Patterns that indicate incomplete responses
    INCOMPLETE_PATTERNS = [
        r"\.\.\.$",  # Ends with ellipsis
        r"continue[ds]?\s*$",  # Ends with "continue"
        r":\s*$",  # Ends with colon
        r"(?:and|but|or|so|then)\s*$",  # Ends with conjunction
    ]

    # Patterns for safety concerns (expanded beyond guardrails)
    SAFETY_PATTERNS = [
        r"(?:hack|exploit|bypass).{0,20}(?:security|system)",
        r"(?:how to|step.?by.?step).{0,30}(?:weapon|harm|attack)",
    ]

    def __init__(
        self,
        enabled: bool = True,
        strict_mode: bool = False,
        min_response_length: int = 20,
        max_response_length: int = 4000,
        confidence_threshold: float = 0.7,
    ):
        self.enabled = enabled
        self.strict_mode = strict_mode
        self.min_response_length = min_response_length
        self.max_response_length = max_response_length
        self.confidence_threshold = confidence_threshold
        self.logger = logging.getLogger("SelfReflector")

        # Compile patterns
        self._hallucination_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.HALLUCINATION_PATTERNS
        ]
        self._incomplete_patterns = [re.compile(p, re.IGNORECASE) for p in self.INCOMPLETE_PATTERNS]
        self._safety_patterns = [re.compile(p, re.IGNORECASE) for p in self.SAFETY_PATTERNS]

    async def reflect(
        self, user_message: str, ai_response: str, context: dict[str, Any] | None = None
    ) -> ReflectionResult:
        """
        Perform self-reflection on an AI response.

        Args:
            user_message: The original user message
            ai_response: The AI's response to check
            context: Additional context (history, intent, etc.)

        Returns:
            ReflectionResult with validation status and any issues
        """
        import time

        start_time = time.perf_counter()

        if not self.enabled:
            return ReflectionResult(is_valid=True, confidence=1.0)

        context = context or {}
        issues: list[Issue] = []
        confidence = 1.0

        # Check 1: Response length
        length_issue = self._check_length(ai_response)
        if length_issue:
            issues.append(length_issue)
            confidence -= length_issue.severity * 0.2

        # Check 2: Hallucination markers
        hallucination_issue = self._check_hallucination(ai_response)
        if hallucination_issue:
            issues.append(hallucination_issue)
            confidence -= hallucination_issue.severity * 0.15

        # Check 3: Completeness
        incomplete_issue = self._check_completeness(ai_response)
        if incomplete_issue:
            issues.append(incomplete_issue)
            confidence -= incomplete_issue.severity * 0.25

        # Check 4: Relevance to user message
        relevance_issue = self._check_relevance(user_message, ai_response, context)
        if relevance_issue:
            issues.append(relevance_issue)
            confidence -= relevance_issue.severity * 0.3

        # Check 5: Repetition
        repetition_issue = self._check_repetition(ai_response, context)
        if repetition_issue:
            issues.append(repetition_issue)
            confidence -= repetition_issue.severity * 0.2

        # Check 6: Safety
        safety_issue = self._check_safety(ai_response)
        if safety_issue:
            issues.append(safety_issue)
            confidence = 0.0  # Safety issues = automatic failure

        # Ensure confidence is in valid range
        confidence = max(0.0, min(1.0, confidence))

        # Determine if response is valid
        is_valid = confidence >= self.confidence_threshold and not any(
            i.type == IssueType.UNSAFE for i in issues
        )

        # In strict mode, any issue fails validation
        if self.strict_mode and issues:
            is_valid = False

        processing_time = (time.perf_counter() - start_time) * 1000

        result = ReflectionResult(
            is_valid=is_valid,
            confidence=confidence,
            issues=issues,
            processing_time_ms=processing_time,
        )

        if not is_valid:
            self.logger.warning(
                "Self-reflection failed: %s (confidence: %.2f)", result.issue_summary, confidence
            )

        return result

    def _check_length(self, response: str) -> Issue | None:
        """Check if response length is appropriate."""
        length = len(response.strip())

        if length < self.min_response_length:
            return Issue(
                type=IssueType.TOO_SHORT,
                description=f"Response too short ({length} chars)",
                severity=0.5,
                suggestion="Consider providing a more complete answer",
            )

        if length > self.max_response_length:
            return Issue(
                type=IssueType.TOO_LONG,
                description=f"Response too long ({length} chars)",
                severity=0.3,
                suggestion="Consider condensing the response",
            )

        return None

    def _check_hallucination(self, response: str) -> Issue | None:
        """Check for hallucination markers."""
        hallucination_count = 0

        for pattern in self._hallucination_patterns:
            matches = pattern.findall(response)
            hallucination_count += len(matches)

        if hallucination_count >= 3:
            return Issue(
                type=IssueType.HALLUCINATION,
                description=f"Found {hallucination_count} uncertainty markers",
                severity=min(0.8, hallucination_count * 0.15),
                suggestion="Verify facts or acknowledge uncertainty explicitly",
            )

        return None

    def _check_completeness(self, response: str) -> Issue | None:
        """Check if response appears complete."""
        response_stripped = response.strip()

        for pattern in self._incomplete_patterns:
            if pattern.search(response_stripped):
                return Issue(
                    type=IssueType.INCOMPLETE,
                    description="Response appears truncated or incomplete",
                    severity=0.6,
                    suggestion="Complete the response or restructure",
                )

        return None

    def _check_relevance(
        self, user_message: str, response: str, context: dict[str, Any]
    ) -> Issue | None:
        """
        Check if response is relevant to the user's message.
        Uses simple keyword overlap for efficiency.
        """
        # Extract significant words (length > 3, not common words)
        common_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "has",
            "what",
            "when",
            "where",
            "which",
            "who",
            "will",
            "with",
            "this",
            "that",
            "from",
            "they",
            "been",
            "have",
            "their",
            "ที่",
            "และ",
            "ของ",
            "ให้",
            "ได้",
            "จะ",
            "เป็น",
            "มี",
            "ไม่",
            "กับ",
            "ว่า",
            "ใน",
            "นี้",
            "ก็",
            "จาก",
            "แล้ว",
        }

        user_words = {
            w.lower()
            for w in re.findall(r"\S+", user_message)
            if len(w) > 3 and w.lower() not in common_words
        }

        response_words = {
            w.lower()
            for w in re.findall(r"\S+", response)
            if len(w) > 3 and w.lower() not in common_words
        }

        if not user_words:
            return None  # Can't assess relevance without keywords

        overlap = len(user_words & response_words)
        overlap_ratio = overlap / len(user_words)

        # Also check if response mentions user's intent if available
        intent = context.get("intent")
        if intent and overlap_ratio < 0.15:
            return Issue(
                type=IssueType.OFF_TOPIC,
                description=f"Low keyword overlap ({overlap_ratio:.0%}) with user message",
                severity=0.5,
                suggestion="Address the user's specific question or topic",
            )

        return None

    def _check_repetition(self, response: str, context: dict[str, Any]) -> Issue | None:
        """Check for repetitive content within response."""
        # Split into sentences
        sentences = re.split(r"[.!?。！？]\s*", response)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if len(sentences) < 3:
            return None

        # Check for duplicate or near-duplicate sentences
        seen = set()
        duplicates = 0
        for sentence in sentences:
            normalized = " ".join(sentence.lower().split())
            if normalized in seen:
                duplicates += 1
            seen.add(normalized)

        if duplicates >= 2:
            return Issue(
                type=IssueType.REPETITIVE,
                description=f"Found {duplicates} repeated sentences",
                severity=min(0.7, duplicates * 0.2),
                suggestion="Remove duplicate content",
            )

        # Check for word-level repetition (same phrase repeated)
        words = response.lower().split()
        if len(words) > 50:
            # Check 5-gram repetition
            ngrams = [" ".join(words[i : i + 5]) for i in range(len(words) - 4)]
            ngram_counts = {}
            for ng in ngrams:
                ngram_counts[ng] = ngram_counts.get(ng, 0) + 1

            max_repeat = max(ngram_counts.values()) if ngram_counts else 0
            if max_repeat >= 3:
                return Issue(
                    type=IssueType.REPETITIVE,
                    description="Found repeated phrases",
                    severity=0.4,
                    suggestion="Vary phrasing to avoid repetition",
                )

        return None

    def _check_safety(self, response: str) -> Issue | None:
        """Check for safety concerns."""
        for pattern in self._safety_patterns:
            if pattern.search(response):
                return Issue(
                    type=IssueType.UNSAFE,
                    description="Potential safety concern detected",
                    severity=1.0,
                    suggestion="Refuse to provide harmful information",
                )

        return None


# Global instance
self_reflector = SelfReflector()


def configure_reflection(enabled: bool = True, strict_mode: bool = False, **kwargs) -> None:
    """Configure the global self-reflector instance."""
    global self_reflector
    self_reflector = SelfReflector(enabled=enabled, strict_mode=strict_mode, **kwargs)
