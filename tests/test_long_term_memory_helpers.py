"""Tests for the pure-logic helpers in cogs.ai_core.memory.long_term_memory.

Targets:
  - Fact dataclass round-trip (to_dict / from_dict)
  - Fact.decay_confidence math
  - FactExtractor pattern matching
  - FactCategory / ImportanceLevel enum values

The async LongTermMemory class wraps a SQLite DB and is exercised by
test_long_term_memory.py — the helpers here are pure-Python and don't
need the DB fixture.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cogs.ai_core.memory.long_term_memory import (
    Fact,
    FactCategory,
    FactExtractor,
    ImportanceLevel,
)


class TestFactRoundTrip:
    def test_minimal_to_dict(self):
        fact = Fact(user_id=42, content="hi")
        data = fact.to_dict()
        assert data["user_id"] == 42
        assert data["content"] == "hi"
        # Default category / importance should serialise as their .value strings/ints.
        assert data["category"] == FactCategory.CUSTOM.value
        assert data["importance"] == ImportanceLevel.MEDIUM.value

    def test_datetime_serialises_to_iso(self):
        ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        fact = Fact(user_id=1, first_mentioned=ts, last_confirmed=ts)
        data = fact.to_dict()
        assert data["first_mentioned"] == ts.isoformat()
        assert data["last_confirmed"] == ts.isoformat()

    def test_from_dict_parses_iso_dates(self):
        data = {
            "user_id": 7,
            "content": "x",
            "first_mentioned": "2026-01-02T03:04:05+00:00",
        }
        fact = Fact.from_dict(data)
        assert fact.user_id == 7
        assert isinstance(fact.first_mentioned, datetime)

    def test_from_dict_handles_invalid_iso(self):
        # Bad ISO string falls back to None rather than raising.
        data = {"user_id": 1, "content": "x", "first_mentioned": "not-a-date"}
        fact = Fact.from_dict(data)
        assert fact.first_mentioned is None

    def test_from_dict_filters_unknown_keys(self):
        # Keys not on the dataclass shouldn't blow up __init__.
        data = {"user_id": 1, "content": "x", "extraneous_field": 999}
        fact = Fact.from_dict(data)
        assert fact.user_id == 1

    def test_from_dict_does_not_mutate_input(self):
        data = {"user_id": 1, "content": "x", "first_mentioned": "2026-01-01T00:00:00+00:00"}
        original = dict(data)
        Fact.from_dict(data)
        assert data == original


class TestDecayConfidence:
    def test_no_decay_at_zero_days(self):
        fact = Fact(user_id=1, content="x")
        assert fact.decay_confidence(0) == pytest.approx(1.0)

    def test_decay_after_30_days(self):
        fact = Fact(user_id=1, content="x")
        # 30 days = 1 decay period @ 10% = 0.9
        assert fact.decay_confidence(30) == pytest.approx(0.9)

    def test_decay_floors_at_0_1(self):
        fact = Fact(user_id=1, content="x")
        # 1000 days far below 0.1 in raw math, but clamped.
        assert fact.decay_confidence(10000) == pytest.approx(0.1)

    def test_negative_days_treated_as_zero(self):
        fact = Fact(user_id=1, content="x")
        # Clock skew shouldn't allow > 1.0.
        assert fact.decay_confidence(-365) == pytest.approx(1.0)

    def test_pure_function_does_not_mutate(self):
        fact = Fact(user_id=1, content="x", confidence=0.5)
        result = fact.decay_confidence(30)
        # Method returns the new value but doesn't mutate self.confidence.
        assert fact.confidence == 0.5
        assert result < 1.0


class TestFactExtractor:
    def test_extract_no_match_returns_empty(self):
        ex = FactExtractor()
        assert ex.extract_facts("just a regular message", user_id=1) == []

    def test_extract_remember_command(self):
        ex = FactExtractor()
        facts = ex.extract_facts("Please remember that I love coffee", user_id=42)
        # The CUSTOM category should pick this up via the "remember that" pattern.
        assert any(f.category == FactCategory.CUSTOM.value for f in facts)

    def test_extracted_fact_carries_user_id(self):
        ex = FactExtractor()
        facts = ex.extract_facts("My name is Alice", user_id=99)
        if facts:
            assert facts[0].user_id == 99

    def test_extracted_fact_carries_channel_id(self):
        ex = FactExtractor()
        facts = ex.extract_facts("Remember I work at NASA", user_id=1, channel_id=555)
        if facts:
            assert facts[0].channel_id == 555

    def test_extracted_fact_includes_source_truncated(self):
        ex = FactExtractor()
        long_message = "Remember that " + "x" * 500
        facts = ex.extract_facts(long_message, user_id=1)
        if facts:
            assert facts[0].source_message is not None
            # source_message is truncated to 200 chars.
            assert len(facts[0].source_message) <= 200

    def test_extractor_compiles_patterns_at_init(self):
        ex = FactExtractor()
        # Compiled patterns should be a list of (compiled_re, category, importance) tuples.
        assert len(ex._compiled_patterns) > 0

    def test_too_short_content_skipped(self):
        ex = FactExtractor()
        # Single-char captures (after the 2-char minimum guard) should be filtered.
        # Use a message that would trigger pattern but capture only 1 char.
        facts = ex.extract_facts("My name is X", user_id=1)
        # X (1 char) is below the min length, so nothing is added.
        # Some patterns might still capture longer content — just verify length floor.
        for f in facts:
            assert len(f.content) >= 2


class TestEnums:
    def test_fact_category_values_unique(self):
        values = [c.value for c in FactCategory]
        assert len(values) == len(set(values))

    def test_importance_levels_ordered(self):
        # LOW < MEDIUM < HIGH for sorting/comparison sanity.
        assert ImportanceLevel.LOW.value < ImportanceLevel.MEDIUM.value
        assert ImportanceLevel.MEDIUM.value < ImportanceLevel.HIGH.value
