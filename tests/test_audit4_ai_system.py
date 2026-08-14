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
  5. ``logic.py`` carried a private mention-escape copy that had drifted from
     ``sanitization.escape_mentions``, reintroducing three bugs the canonical
     version documents as fixed.
  6. ``_safe_split_message`` claimed to mirror ``_split_for_discord`` but had
     neither its half-chunk boundary floor (an early newline produced a runt
     chunk — a whole extra webhook message on Thai RP text) nor its
     single-newline consumption (``lstrip("\\n")`` ate intentional blank lines).
  7. The CLI dashboard backend dropped over-size / unsupported attachments with
     only a server-side log, and persisted the REJECTED payload to the user
     row — so an image the user could still see in their own bubble had never
     reached the model, with nothing anywhere saying so.
"""

from __future__ import annotations

import base64
import inspect

import pytest

import cogs.ai_core.api.dashboard_chat_claude_cli as cli_mod
import cogs.ai_core.logic as logic_mod
from cogs.ai_core.logic import MAX_CHARACTER_BLOCKS, PATTERN_CHARACTER_TAG, _split_for_discord
from cogs.ai_core.memory.history_manager import HistoryManager
from cogs.ai_core.memory.state_tracker import CharacterState, CharacterStateTracker
from cogs.ai_core.sanitization import escape_mentions
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


class TestOneMentionEscaperOnly:
    """``logic.py`` must not carry its own mention-escape copy.

    It used to, and the copy had drifted from ``sanitization.escape_mentions``
    in three ways the canonical version's own comments document as fixed:
    ``@EVERYONE`` came back lowercased, ``<@!123>`` lost its legacy bang, and a
    full-width ``@`` (U+FF20) was not escaped at all. Since ``send_as_webhook``
    already used the canonical escaper, a single multi-character RP reply
    escaped its ``{{Name}}`` blocks by one set of rules and its narrator text
    by another.

    Zero-width space and full-width ``@`` are written as ``\\u`` escapes, not
    literals: ruff PLE2515 bans invisible characters in source, and a
    look-alike glyph in a test expectation is unreadable in a diff.
    """

    _Z = "\u200b"  # the ZWSP the escaper inserts
    _FW_AT = "＠"  # FULLWIDTH COMMERCIAL AT

    # (input, what the canonical escaper must produce)
    CASES = [
        ("@everyone hello", f"@{_Z}everyone hello"),
        # Casing survives — a fixed lowercase replacement under IGNORECASE
        # was the old bug.
        ("@EVERYONE hello", f"@{_Z}EVERYONE hello"),
        ("@Everyone hello", f"@{_Z}Everyone hello"),
        ("@HERE now", f"@{_Z}HERE now"),
        # The legacy-nickname bang survives the rewrite.
        ("<@!123456789012345678> hi", f"<@!{_Z}123456789012345678> hi"),
        ("<@123456789012345678> hi", f"<@{_Z}123456789012345678> hi"),
        ("<@&987654321098765432> yo", f"<@&{_Z}987654321098765432> yo"),
        # Full-width @ is NFKC-folded, then escaped.
        (f"{_FW_AT}everyone", f"@{_Z}everyone"),
        (f"{_FW_AT}here", f"@{_Z}here"),
        ("plain text", "plain text"),
    ]

    @pytest.mark.parametrize(("raw", "expected"), CASES)
    def test_canonical_escaper_behaviour(self, raw: str, expected: str) -> None:
        assert escape_mentions(raw) == expected

    @pytest.mark.parametrize(("raw", "_expected"), CASES)
    def test_canonical_escaper_is_idempotent(self, raw: str, _expected: str) -> None:
        once = escape_mentions(raw)
        assert escape_mentions(once) == once

    @pytest.mark.parametrize(
        "name",
        ["PATTERN_AT_EVERYONE", "PATTERN_AT_HERE", "PATTERN_USER_TAG", "PATTERN_ROLE_TAG"],
    )
    def test_logic_defines_no_private_escape_patterns(self, name: str) -> None:
        """A re-added local copy is exactly how the drift happened last time."""
        assert not hasattr(logic_mod, name), (
            f"logic.py re-declared {name}; use sanitization.escape_mentions instead"
        )

    def test_process_chat_calls_the_canonical_escaper(self) -> None:
        source = inspect.getsource(logic_mod.ChatManager.process_chat)
        assert "escape_mentions(response_text)" in source

    def test_webhook_send_uses_the_same_escaper(self) -> None:
        """Pins the shared-ness: both send paths route through one function."""
        from cogs.ai_core.tools import tool_executor

        assert tool_executor.escape_mentions is escape_mentions
        assert logic_mod.escape_mentions is escape_mentions


class TestTheTwoSplittersAgree:
    """``_safe_split_message``'s docstring says it mirrors ``_split_for_discord``.

    It didn't. Two of the boundary rules were missing:

    * No half-chunk floor on the newline/space boundary. Thai has no
      inter-word spaces, so a reply like ``"เขาพูดว่า\\n<2500 unbroken Thai
      chars>"`` split at index 18 and the RP webhook path posted an 18-char
      message of its own before the real paragraph.
    * ``lstrip("\\n")`` after EVERY split, so intentional blank lines
      straddling a hard cut (ASCII art, a code block inside a character's
      line) were eaten — the sibling fixed this by consuming exactly the one
      delimiter newline.
    """

    THAI_RP = "เขามองมาแล้วพูดว่า\n" + ("เสียงของเขาแผ่วเบาแต่หนักแน่นราวกับคำสาบาน" * 60)

    CORPUS = {
        "plain-long": "x" * 9000,
        "thai-long": "สวัสดีครับ" * 1500,
        "thai-rp-short-opener": THAI_RP,
        "marks-only": "ิ" * 9000,
        "base+mark": "กิ" * 4500,
        "newline-early": "a\n" + "x" * 9000,
        "newline-dense": "ab\n" * 4000,
        "spaces": "word " * 3000,
        "blank-lines": "line1\n\n\n" + "X" * 2500,
        "exactly2000": "y" * 2000,
        "exactly2001": "y" * 2001,
        "emoji": "\U0001f600" * 4000,
    }

    @pytest.mark.parametrize("name", sorted(CORPUS))
    def test_same_chunking_as_the_sibling(self, name: str) -> None:
        text = self.CORPUS[name]
        assert _safe_split_message(text, 2000) == _split_for_discord(text, 2000)

    def test_short_thai_opener_is_not_orphaned(self) -> None:
        """The regression that motivated the fix, stated directly."""
        chunks = _safe_split_message(self.THAI_RP, 2000)
        assert len(chunks[0]) > 1000, (
            f"opening line split into a {len(chunks[0])}-char runt chunk — "
            "the RP webhook path would post it as its own message"
        )

    def test_intentional_blank_lines_survive_a_hard_cut(self) -> None:
        text = "line1\n\n\n" + "X" * 2500
        joined = "".join(_safe_split_message(text, 2000))
        assert joined == text, "a hard cut ate a blank line"

    def test_one_delimiter_newline_is_consumed_on_a_newline_split(self) -> None:
        """Splitting ON a newline drops exactly that newline, nothing more.

        ``rfind`` picks the LAST newline inside the window, so with two
        adjacent newlines the first stays attached to the emitted chunk and
        only the second — the delimiter — is consumed. The old
        ``lstrip("\\n")`` swallowed both.
        """
        text = "A" * 1500 + "\n\n" + "B" * 1500
        chunks = _safe_split_message(text, 2000)
        assert chunks[0] == "A" * 1500 + "\n"
        assert chunks[1] == "B" * 1500
        # Exactly one newline lost, and it is the delimiter.
        assert "".join(chunks) == text.replace("\n\n", "\n", 1)


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


class TestDroppedAttachmentsAreReported:
    """A dropped attachment reached bot.log and nowhere else.

    The frontend's per-image ceiling is 20 MB and this backend's is 10 MB, so
    "attach a photo, get an answer that ignores it" was reachable with no
    explanation anywhere — the image still rendered in the user's own bubble
    because the REJECTED payload was what got persisted to the user row (the
    save ran before the decode). The SDK backend has always sent a per-image
    error frame and persisted only the accepted subset.
    """

    @pytest.fixture(autouse=True)
    def isolate_roots(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli_mod, "_TEMP_IMAGE_ROOT", tmp_path / "img")
        monkeypatch.setattr(cli_mod, "_TEMP_DOCS_ROOT", tmp_path / "doc")

    def test_oversized_image_reports_its_size_and_the_limit(self) -> None:
        url = _data_url("image/png", b"x" * 5000)
        skipped: list[dict] = []
        written = cli_mod._save_inline_images("conv-1", [url], 1024, skipped)
        assert written == []
        assert len(skipped) == 1
        assert skipped[0]["index"] == 0
        assert "limit" in skipped[0]["reason"]

    def test_unsupported_type_names_the_type(self) -> None:
        url = _data_url("image/heic", b"x" * 10)
        skipped: list[dict] = []
        assert cli_mod._save_inline_images("conv-1", [url], 1024, skipped) == []
        assert "image/heic" in skipped[0]["reason"]

    def test_accepted_image_is_not_reported(self) -> None:
        url = _data_url("image/png", b"x" * 10)
        skipped: list[dict] = []
        assert len(cli_mod._save_inline_images("conv-1", [url], 1024, skipped)) == 1
        assert skipped == []

    def test_index_identifies_which_image_of_a_batch(self) -> None:
        good = _data_url("image/png", b"x" * 10)
        bad = _data_url("image/png", b"x" * 5000)
        skipped: list[dict] = []
        written = cli_mod._save_inline_images("conv-1", [good, bad, good], 1024, skipped)
        assert len(written) == 2
        assert [s["index"] for s in skipped] == [1]

    def test_document_drop_names_the_file(self) -> None:
        skipped: list[dict] = []
        docs = [{"name": "secrets.exe", "kind": "text", "data": "x"}]
        assert cli_mod._save_inline_documents("conv-1", docs, 1024, skipped) == []
        assert skipped[0]["name"] == "secrets.exe"
        assert ".exe" in skipped[0]["reason"]

    def test_oversized_document_reports_the_limit(self) -> None:
        skipped: list[dict] = []
        docs = [{"name": "big.txt", "kind": "text", "data": "x" * 5000}]
        assert cli_mod._save_inline_documents("conv-1", docs, 1024, skipped) == []
        assert "limit" in skipped[0]["reason"]

    def test_out_param_is_optional(self) -> None:
        """Existing callers pass no list; the signature must stay compatible."""
        url = _data_url("image/png", b"x" * 5000)
        assert cli_mod._save_inline_images("conv-1", [url], 1024) == []
        assert (
            cli_mod._save_inline_documents("conv-1", [{"name": "a.exe", "data": "x"}], 1024) == []
        )

    def test_handler_persists_only_accepted_images(self) -> None:
        """The user row must not carry a payload the model never saw."""
        source = inspect.getsource(cli_mod.handle_chat_message_claude_cli)
        assert "images=accepted_images if accepted_images else None" in source, (
            "the user row is being saved with the raw (pre-decode) image list again"
        )
        # …and the decode has to run BEFORE that save, or there is nothing to
        # filter against.
        assert source.index("_save_inline_images") < source.index("save_dashboard_message")
