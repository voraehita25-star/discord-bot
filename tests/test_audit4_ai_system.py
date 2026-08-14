"""Regression tests for the AI-system audit (4th pass).

Each class pins ONE finding. The docstrings record the behaviour observed
BEFORE the fix, so a change that reintroduces it fails loudly instead of
quietly regressing.

Findings covered:
  1. ``_safe_split_message`` emitted an over-limit chunk once the 50-chunk
     ceiling was hit and ``limit`` was smaller than the truncation marker.
  2. The ``{{Name}}`` block cap sliced the split list to an EVEN length,
     which ends on a NAME whose message was cut off — the send loop then
     skipped it, delivering 29 blocks where the code promised 30.
  3. ``HistoryManager._get_message_content`` raised TypeError on a history
     row carrying ``parts: None``.
  4. ``CharacterState.from_dict`` / ``CharacterStateTracker.from_dict``
     raised on a malformed persistence blob, taking the whole channel
     restore down with it.
"""

from __future__ import annotations

import pytest

from cogs.ai_core.logic import MAX_CHARACTER_BLOCKS, PATTERN_CHARACTER_TAG
from cogs.ai_core.memory.history_manager import HistoryManager
from cogs.ai_core.memory.state_tracker import CharacterState, CharacterStateTracker
from cogs.ai_core.tools.tool_executor import _MAX_CHUNKS, _safe_split_message

# The exact marker _safe_split_message appends when it drops a tail. Pinned
# here (not imported) so a change to its wording is a deliberate edit in both
# places rather than a silently-passing test.
_CEILING_MARKER_LEN = len("\n\n*[ข้อความยาวเกินกำหนด จึงถูกตัดส่วนท้ายออก]*")


class TestSafeSplitCeilingRespectsLimit:
    """``_safe_split_message`` promises every chunk is ``<= limit``.

    Before the fix, the ceiling path built its final chunk as
    ``tail[: max(0, limit - len(marker))] + marker``. For any ``limit`` below
    the marker's own length that slice collapsed to empty and the emitted
    chunk WAS the marker — 46 chars regardless of the limit. Production
    callers pass >= 256 so it never bit in practice, but ``limit`` is a
    parameter and the bound has to hold for it.
    """

    @pytest.mark.parametrize("limit", [1, 5, 10, 45, 46, 47, 100, 256, 2000])
    def test_every_chunk_within_limit(self, limit: int) -> None:
        # Long enough to blow past the chunk ceiling at every limit tested.
        text = "z" * (limit * (_MAX_CHUNKS + 20))
        chunks = _safe_split_message(text, limit)
        assert chunks, "splitter returned nothing"
        oversized = [len(c) for c in chunks if len(c) > limit]
        assert not oversized, f"chunks exceeding limit={limit}: {oversized}"

    def test_marker_still_attached_when_it_fits(self) -> None:
        """The "content was dropped" notice must survive for real limits."""
        limit = 2000
        text = "z" * (limit * (_MAX_CHUNKS + 20))
        chunks = _safe_split_message(text, limit)
        assert len(chunks) == _MAX_CHUNKS + 1
        assert chunks[-1].endswith("]*"), "truncation notice was lost"
        assert len(chunks[-1]) <= limit

    def test_no_marker_when_it_cannot_fit(self) -> None:
        """Below the marker's length the tail is plain — never over-limit."""
        limit = _CEILING_MARKER_LEN - 1
        text = "z" * (limit * (_MAX_CHUNKS + 20))
        chunks = _safe_split_message(text, limit)
        assert len(chunks[-1]) <= limit


class TestCharacterBlockCapIsOdd:
    """``PATTERN_CHARACTER_TAG.split`` returns ``1 + 2 * blocks`` elements.

    The cap therefore has to be odd. The old ``parts[:60]`` was even: the
    list ended on a NAME whose message had been sliced away, and
    ``process_chat``'s ``if i + 1 < len(parts)`` guard skipped it. 29 blocks
    reached Discord while the comment (and the constant's intent) said 30.
    """

    @staticmethod
    def _blocks_delivered(parts: list[str]) -> int:
        """Replicate process_chat's send loop and count what actually goes out."""
        sent = 0
        for i in range(1, len(parts), 2):
            if not parts[i].strip():
                continue
            if i + 1 < len(parts) and parts[i + 1].strip():
                sent += 1
        return sent

    def test_split_length_is_always_odd(self) -> None:
        for n in (1, 2, 5, 40):
            body = "".join(f"{{{{C{i}}}}} line {i}\n" for i in range(n))
            assert len(PATTERN_CHARACTER_TAG.split(body)) % 2 == 1

    def test_cap_delivers_the_full_block_budget(self) -> None:
        body = "".join(f"{{{{C{i}}}}} line {i}\n" for i in range(MAX_CHARACTER_BLOCKS + 20))
        parts = PATTERN_CHARACTER_TAG.split(body)
        max_parts = 1 + 2 * MAX_CHARACTER_BLOCKS
        assert len(parts) > max_parts, "test input did not exceed the cap"
        assert self._blocks_delivered(parts[:max_parts]) == MAX_CHARACTER_BLOCKS

    def test_under_the_cap_nothing_is_dropped(self) -> None:
        n = MAX_CHARACTER_BLOCKS - 5
        body = "".join(f"{{{{C{i}}}}} line {i}\n" for i in range(n))
        parts = PATTERN_CHARACTER_TAG.split(body)
        assert len(parts) <= 1 + 2 * MAX_CHARACTER_BLOCKS
        assert self._blocks_delivered(parts) == n

    def test_dropped_block_count_matches_what_was_cut(self) -> None:
        """The count reported to the reader must equal the blocks removed."""
        extra = 13
        body = "".join(f"{{{{C{i}}}}} line {i}\n" for i in range(MAX_CHARACTER_BLOCKS + extra))
        parts = PATTERN_CHARACTER_TAG.split(body)
        max_parts = 1 + 2 * MAX_CHARACTER_BLOCKS
        dropped = (len(parts) - max_parts + 1) // 2
        assert dropped == extra


class TestHistoryContentToleratesNullParts:
    """``.get("parts", [])`` returns None when the key exists holding None.

    The loop then raised ``TypeError: 'NoneType' object is not iterable`` out
    of ``estimate_tokens`` — which ``!auto_summarize`` calls outside its
    try/except. ``is_summary_entry`` in the same module already used the safe
    ``or []`` form; this was the one place that didn't.
    """

    @pytest.fixture
    def hm(self) -> HistoryManager:
        return HistoryManager(keep_recent=5, max_history=10, max_tokens=1000)

    MALFORMED = [
        {"role": "user", "parts": None},
        {"role": "user"},
        {"role": "model", "parts": "not-a-list"},
        {"role": "model", "parts": 123},
        {"role": "model", "parts": {"text": "dict-not-list"}},
        {},
    ]

    @pytest.mark.parametrize("row", MALFORMED)
    def test_estimate_tokens_survives(self, hm: HistoryManager, row: dict) -> None:
        assert hm.estimate_tokens([row]) >= 0

    @pytest.mark.parametrize("row", MALFORMED)
    def test_estimate_message_tokens_survives(self, hm: HistoryManager, row: dict) -> None:
        assert hm.estimate_message_tokens(row) >= 0

    @pytest.mark.parametrize("row", MALFORMED)
    def test_importance_scoring_survives(self, hm: HistoryManager, row: dict) -> None:
        score, _patterns = hm._calculate_importance(row)
        assert score >= 1.0

    @pytest.mark.asyncio
    async def test_smart_trim_survives_malformed_history(self, hm: HistoryManager) -> None:
        history = self.MALFORMED * 4
        trimmed = await hm.smart_trim(history, 3)
        assert len(trimmed) <= 3

    @pytest.mark.asyncio
    async def test_token_trim_survives_malformed_history(self, hm: HistoryManager) -> None:
        history = self.MALFORMED * 4
        trimmed = await hm.smart_trim_by_tokens(history, max_tokens=50, reserve_tokens=10)
        assert isinstance(trimmed, list)

    def test_well_formed_rows_still_read(self, hm: HistoryManager) -> None:
        assert hm._get_message_content({"parts": ["a", {"text": "b"}]}) == "a b"


class TestStateRestoreToleratesMalformedBlob:
    """The persistence restore consumed its blob without shape guards.

    ``CharacterState.from_dict({"location": "x"})`` raised TypeError (``name``
    has no default) and ``CharacterStateTracker.from_dict(cid, {"states":
    "junk"})`` raised AttributeError — either one aborted the whole channel
    restore rather than skipping the bad row.
    """

    def test_missing_name_uses_the_default(self) -> None:
        state = CharacterState.from_dict({"location": "Library"}, default_name="Faust")
        assert state.name == "Faust"
        assert state.location == "Library"

    def test_missing_name_with_no_default_is_empty_not_a_crash(self) -> None:
        assert CharacterState.from_dict({"location": "x"}).name == ""

    @pytest.mark.parametrize("payload", ["junk", 123, None, [], ("a",)])
    def test_non_dict_payload_is_tolerated(self, payload: object) -> None:
        state = CharacterState.from_dict(payload, default_name="A")  # type: ignore[arg-type]
        assert state.name == "A"

    def test_scalar_list_fields_are_coerced(self) -> None:
        state = CharacterState.from_dict({"name": "A", "nearby_characters": "Bob"})
        assert state.nearby_characters == ["Bob"]

    @pytest.mark.parametrize(
        "data",
        [
            {"states": "junk"},
            {"states": None},
            {"states": ["a", "b"]},
            {"states": {"A": "junk"}},
            {"states": {"A": None}},
            {"states": {5: {"name": "x"}}},
            {"scene": None},
            {"scene": 123},
            {},
            "not-a-dict",
            None,
        ],
    )
    def test_tracker_restore_never_raises(self, data: object) -> None:
        tracker = CharacterStateTracker()
        tracker.from_dict(4242, data)  # type: ignore[arg-type]

    def test_one_bad_row_does_not_discard_the_good_ones(self) -> None:
        tracker = CharacterStateTracker()
        tracker.from_dict(
            4243,
            {
                "states": {
                    "Bad": "junk",
                    "Good": {"name": "Good", "location": "Library"},
                },
                "scene": "Night",
            },
        )
        good = tracker.get_state("Good", 4243)
        assert good is not None
        assert good.location == "Library"
        assert tracker.get_state("Bad", 4243) is None
        assert tracker.get_scene(4243) == "Night"

    def test_name_falls_back_to_the_mapping_key(self) -> None:
        """The tracker is keyed BY name, so the key is the authoritative one."""
        tracker = CharacterStateTracker()
        tracker.from_dict(4244, {"states": {"Faust": {"location": "Library"}}})
        state = tracker.get_state("Faust", 4244)
        assert state is not None
        assert state.name == "Faust"

    def test_round_trip_still_works(self) -> None:
        source = CharacterStateTracker()
        source.set_state("Faust", 1, location="Library", emotion="calm")
        source.set_scene(1, "Night time")

        target = CharacterStateTracker()
        target.from_dict(2, source.to_dict(1))

        restored = target.get_state("Faust", 2)
        assert restored is not None
        assert restored.location == "Library"
        assert restored.emotion == "calm"
        assert target.get_scene(2) == "Night time"

    def test_round_trip_with_no_scene_set(self) -> None:
        """``to_dict`` emits ``scene: None`` for a channel that never set one."""
        source = CharacterStateTracker()
        source.set_state("A", 1, location="x")

        target = CharacterStateTracker()
        target.from_dict(2, source.to_dict(1))
        assert target.get_scene(2) is None
