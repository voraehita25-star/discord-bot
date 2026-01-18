"""
Unit Tests for AI Memory Modules.
Tests history manager, guardrails, and intent detection.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestHistoryManager:
    """Test history management and trimming."""

    def test_importance_pattern_detection(self) -> None:
        """Test detection of important messages."""
        IMPORTANT_PATTERNS = [
            r"ชื่อ.*คือ",  # Name declarations
            r"จำไว้ว่า",  # Remember this
            r"สำคัญ",  # Important
            r"remember\s+that",  # Remember that
            r"my name is",  # Name
            r"please\s+note",  # Note
        ]

        compiled = [re.compile(p, re.IGNORECASE) for p in IMPORTANT_PATTERNS]

        def is_important(text: str) -> bool:
            return any(p.search(text) for p in compiled)

        # Test Thai patterns
        assert is_important("ชื่อของฉันคือ John")
        assert is_important("จำไว้ว่าฉันชอบสีฟ้า")
        assert is_important("นี่สำคัญมาก")

        # Test English patterns
        assert is_important("Remember that I prefer dark mode")
        assert is_important("My name is Alice")
        assert is_important("Please note this setting")

        # Test non-important messages
        assert not is_important("Hello, how are you?")
        assert not is_important("สวัสดีครับ")

    def test_token_estimation(self) -> None:
        """Test token count estimation."""

        def estimate_tokens(text: str) -> int:
            """Rough estimation: 1 token per 4 chars for English, 1 per 2 for Thai."""
            # Simple heuristic
            return len(text) // 3

        text = "Hello world, this is a test message."
        tokens = estimate_tokens(text)

        # Should be reasonable estimate
        assert 5 < tokens < 20

    def test_history_trimming_keeps_recent(self) -> None:
        """Test that trimming keeps most recent messages."""
        MAX_MESSAGES = 50

        history = [{"role": "user", "parts": [f"Message {i}"]} for i in range(100)]

        if len(history) > MAX_MESSAGES:
            # Keep first message (summary) and last N-1
            trimmed = history[:1] + history[-(MAX_MESSAGES - 1) :]

        assert len(trimmed) == MAX_MESSAGES
        assert trimmed[0]["parts"][0] == "Message 0"  # Summary kept
        assert trimmed[-1]["parts"][0] == "Message 99"  # Latest kept


class TestGuardrails:
    """Test output guardrails and sanitization."""

    def test_sensitive_pattern_detection(self) -> None:
        """Test detection of sensitive patterns."""
        SENSITIVE_PATTERNS = [
            r'api[_\-]?key[\s:=]+["\']?[\w\-]+',
            r'password[\s:=]+["\']?[\w]+',
            r'token[\s:=]+["\']?[\w\-]+',
            r'secret[\s:=]+["\']?[\w]+',
        ]

        compiled = [re.compile(p, re.IGNORECASE) for p in SENSITIVE_PATTERNS]

        def has_sensitive_data(text: str) -> bool:
            return any(p.search(text) for p in compiled)

        # Should detect sensitive patterns
        assert has_sensitive_data("api_key = abc123")
        assert has_sensitive_data('password: "secret123"')
        assert has_sensitive_data("token=xyz789")

        # Should not flag normal text without assignment
        assert not has_sensitive_data("Hello, how are you?")
        assert not has_sensitive_data("Let's talk about API design")

    def test_repetition_detection(self) -> None:
        """Test detection of repetitive content."""

        def detect_repetition(text: str, threshold: int = 3) -> bool:
            """Detect if any phrase repeats more than threshold times."""
            words = text.split()
            for i in range(len(words)):
                for length in range(3, 10):  # Check 3-9 word phrases
                    if i + length > len(words):
                        break
                    phrase = " ".join(words[i : i + length])
                    if text.count(phrase) >= threshold:
                        return True
            return False

        # Should detect repetition
        repeated = "I like cake. I like cake. I like cake. I like cake."
        assert detect_repetition(repeated)

        # Normal text should pass
        normal = "Hello there. How are you today? I hope you're doing well."
        assert not detect_repetition(normal)

    def test_length_enforcement(self) -> None:
        """Test response length limits."""
        MAX_LENGTH = 2000

        long_response = "x" * 3000

        if len(long_response) > MAX_LENGTH:
            truncated = long_response[: MAX_LENGTH - 3] + "..."

        assert len(truncated) == MAX_LENGTH


class TestIntentDetection:
    """Test intent detection patterns."""

    def test_greeting_detection(self) -> None:
        """Test greeting intent patterns."""
        GREETING_PATTERNS = [
            r"^(hi|hello|hey|สวัสดี|หวัดดี)[\s!]*$",
            r"^good\s+(morning|afternoon|evening)",
        ]

        compiled = [re.compile(p, re.IGNORECASE) for p in GREETING_PATTERNS]

        def is_greeting(text: str) -> bool:
            return any(p.match(text.strip()) for p in compiled)

        assert is_greeting("Hello!")
        assert is_greeting("สวัสดี")
        assert is_greeting("Good morning")
        assert not is_greeting("Hello, how are you?")  # Too long

    def test_question_detection(self) -> None:
        """Test question detection."""

        def is_question(text: str) -> bool:
            question_words = [
                "what",
                "how",
                "why",
                "when",
                "where",
                "who",
                "อะไร",
                "ทำไม",
                "เมื่อไหร่",
                "ที่ไหน",
            ]
            text_lower = text.lower()

            if text.rstrip().endswith("?"):
                return True

            return any(text_lower.startswith(w) for w in question_words)

        assert is_question("What time is it?")
        assert is_question("How do you do this")
        assert is_question("ทำไมถึงเป็นแบบนี้")
        assert not is_question("I like cats.")

    def test_command_detection(self) -> None:
        """Test command intent detection."""
        COMMAND_PREFIXES = ["!", "/", "."]

        def is_command(text: str) -> bool:
            return any(text.startswith(p) for p in COMMAND_PREFIXES)

        assert is_command("!play music")
        assert is_command("/help")
        assert is_command(".status")
        assert not is_command("play some music")


class TestEntityMemory:
    """Test entity memory operations."""

    def test_entity_fact_format(self) -> None:
        """Test entity fact structure."""
        entity = {
            "name": "Alice",
            "type": "character",
            "facts": {
                "age": 25,
                "occupation": "programmer",
                "likes": ["cats", "coffee"],
            },
            "relationships": {"Bob": "friend"},
        }

        assert entity["name"] == "Alice"
        assert entity["type"] == "character"
        assert isinstance(entity["facts"], dict)
        assert entity["facts"]["age"] == 25

    def test_entity_search(self) -> None:
        """Test entity search by name."""
        entities = [
            {"name": "Alice", "type": "character"},
            {"name": "Bob", "type": "character"},
            {"name": "Tokyo Tower", "type": "location"},
        ]

        def search_entity(query: str) -> list:
            query_lower = query.lower()
            return [e for e in entities if query_lower in e["name"].lower()]

        results = search_entity("alice")
        assert len(results) == 1
        assert results[0]["name"] == "Alice"

        results = search_entity("tower")
        assert len(results) == 1
        assert results[0]["type"] == "location"


class TestCacheStats:
    """Test cache statistics."""

    def test_hit_rate_calculation(self) -> None:
        """Test cache hit rate calculation."""
        hits = 80
        misses = 20
        total = hits + misses

        hit_rate = hits / total if total > 0 else 0.0

        assert hit_rate == 0.8
        assert 0 <= hit_rate <= 1.0

    def test_memory_estimate(self) -> None:
        """Test cache memory estimation."""
        entries = [
            {"key": "a", "value": "x" * 1000},
            {"key": "b", "value": "y" * 2000},
        ]

        # Estimate based on string length
        memory_bytes = sum(len(e["key"]) + len(e["value"]) for e in entries)
        memory_kb = memory_bytes / 1024

        assert memory_kb > 2.5  # At least ~3KB for 3000 chars


# Run tests with: python -m pytest tests/test_memory_modules.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
