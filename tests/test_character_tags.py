"""
Tests for cogs.ai_core.character_tags module.

Covers the pure character-name -> ``{{Tag}}`` replacement helpers:
pattern compilation, the public ``replace_character_names`` entry point,
its guard branches (empty text / None guild / missing or empty char map),
case-insensitive standalone-line matching, longest-name-first precedence,
regex-special-char escaping, and the bounded LRU pattern cache.

The module imports ``SERVER_CHARACTER_NAMES`` into its own namespace, so
tests patch ``cogs.ai_core.character_tags.SERVER_CHARACTER_NAMES`` and clear
the module-level pattern cache to stay hermetic and order-independent.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def patch_char_names(monkeypatch: pytest.MonkeyPatch):
    """Patch SERVER_CHARACTER_NAMES and reset the pattern cache per test.

    Returns a setter that installs a fresh per-guild name map and clears the
    LRU cache so each test sees a clean, deterministic module state.
    """
    import cogs.ai_core.character_tags as ct

    def _set(mapping):
        monkeypatch.setattr(ct, "SERVER_CHARACTER_NAMES", mapping)
        ct._GUILD_TAG_PATTERN_CACHE.clear()

    # Ensure a clean cache before the test runs too.
    ct._GUILD_TAG_PATTERN_CACHE.clear()
    yield _set
    # Leave the shared cache empty for subsequent tests.
    ct._GUILD_TAG_PATTERN_CACHE.clear()


class TestModuleSurface:
    """Sanity checks on the module's exposed constants/structures."""

    def test_max_cache_constant_is_positive_int(self):
        import cogs.ai_core.character_tags as ct

        assert isinstance(ct._MAX_GUILD_PATTERN_CACHE, int)
        assert ct._MAX_GUILD_PATTERN_CACHE > 0

    def test_cache_is_ordered_dict(self):
        from collections import OrderedDict

        import cogs.ai_core.character_tags as ct

        assert isinstance(ct._GUILD_TAG_PATTERN_CACHE, OrderedDict)

    def test_server_character_names_is_dict(self):
        import cogs.ai_core.character_tags as ct

        assert isinstance(ct.SERVER_CHARACTER_NAMES, dict)


class TestCompileGuildPattern:
    """Tests for the _compile_guild_pattern helper."""

    def test_empty_names_returns_never_matching_pattern(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(())
        assert pattern.pattern == r"(?!)"
        assert pattern.search("anything at all") is None
        assert pattern.search("") is None

    def test_all_empty_string_names_returns_never_matching_pattern(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("", ""))
        # Empty entries are filtered out, leaving nothing -> never-match.
        assert pattern.search("anything") is None

    def test_empty_strings_filtered_but_real_names_kept(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("", "Alice", ""))
        assert pattern.search("Alice") is not None
        # The empty entry must NOT turn into a match-everything alternation.
        assert pattern.search("totally unrelated") is None

    def test_pattern_is_case_insensitive(self):
        import re

        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("Alice",))
        assert pattern.flags & re.IGNORECASE
        assert pattern.search("alice") is not None
        assert pattern.search("ALICE") is not None

    def test_pattern_is_multiline(self):
        import re

        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("Alice",))
        assert pattern.flags & re.MULTILINE

    def test_pattern_anchors_to_full_line(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("Alice",))
        # Standalone line matches.
        assert pattern.search("Alice") is not None
        # Inline occurrence does NOT match (anchored ^...$).
        assert pattern.search("hi Alice there") is None

    def test_pattern_allows_surrounding_space_and_tabs(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("Alice",))
        assert pattern.search("  Alice  ") is not None
        assert pattern.search("\tAlice\t") is not None

    def test_special_regex_chars_are_escaped(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("A.B+C",))
        # Matches the literal string only.
        assert pattern.search("A.B+C") is not None
        # The '.' / '+' must be literal, not regex metacharacters.
        assert pattern.search("AXBYC") is None

    def test_longer_name_precedes_shorter_in_alternation(self):
        import cogs.ai_core.character_tags as ct

        pattern = ct._compile_guild_pattern(("Alice", "Alice Smith"))
        m = pattern.search("Alice Smith")
        assert m is not None
        # Longest-first ordering means the full name wins the alternation.
        assert m.group(1) == "Alice Smith"


class TestReplacement:
    """Tests for the _replacement helper."""

    def test_wraps_group_in_double_braces(self):
        import re

        import cogs.ai_core.character_tags as ct

        match = re.match(r"(\w+)", "Hello")
        assert ct._replacement(match) == "{{Hello}}"

    def test_preserves_captured_casing(self):
        import re

        import cogs.ai_core.character_tags as ct

        match = re.match(r"(\w+)", "aLiCe")
        assert ct._replacement(match) == "{{aLiCe}}"


class TestReplaceCharacterNamesGuards:
    """Tests for the early-return guard branches."""

    def test_empty_text_returned_unchanged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        assert replace_character_names("", 7) == ""

    def test_none_guild_returned_unchanged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        # guild_id is None -> no replacement, even for a known name.
        assert replace_character_names("Alice", None) == "Alice"

    def test_guild_zero_is_valid_not_treated_as_no_guild(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        # guild_id == 0 must NOT be conflated with "no guild".
        patch_char_names({0: {"Bob": "b.png"}})
        assert replace_character_names("Bob", 0) == "{{Bob}}"

    def test_guild_not_in_map_returned_unchanged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        assert replace_character_names("Alice", 999) == "Alice"

    def test_empty_char_map_returned_unchanged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {}})
        assert replace_character_names("Alice", 7) == "Alice"

    def test_char_map_with_only_empty_keys_returned_unchanged(self, patch_char_names):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"": "x.png"}})
        # No usable names -> unchanged AND no cache entry created.
        assert replace_character_names("Alice", 7) == "Alice"
        assert 7 not in ct._GUILD_TAG_PATTERN_CACHE


class TestReplaceCharacterNamesBehavior:
    """Tests for the actual name->tag substitution behavior."""

    def test_standalone_name_is_tagged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        assert replace_character_names("Alice", 7) == "{{Alice}}"

    def test_surrounding_whitespace_stripped_in_replacement(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        # Leading/trailing spaces are consumed by the pattern; output is the bare tag.
        assert replace_character_names("  Alice  ", 7) == "{{Alice}}"

    def test_match_is_case_insensitive_and_preserves_input_casing(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        assert replace_character_names("alice", 7) == "{{alice}}"
        assert replace_character_names("ALICE", 7) == "{{ALICE}}"

    def test_inline_name_not_tagged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        # Name embedded in a sentence is not a standalone line -> untouched.
        assert replace_character_names("hello Alice there", 7) == "hello Alice there"

    def test_multiline_per_line_replacement(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        text = "line1\nAlice\nline3"
        assert replace_character_names(text, 7) == "line1\n{{Alice}}\nline3"

    def test_multiple_distinct_names_each_tagged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png", "Bob": "b.png"}})
        text = "Alice\nBob"
        assert replace_character_names(text, 7) == "{{Alice}}\n{{Bob}}"

    def test_longest_name_wins(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png", "Alice Smith": "as.png"}})
        assert replace_character_names("Alice Smith", 7) == "{{Alice Smith}}"

    def test_special_regex_char_name_matched_literally(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"A.B+C": "x.png"}})
        assert replace_character_names("A.B+C", 7) == "{{A.B+C}}"
        # No false match against a regex-style interpretation.
        assert replace_character_names("AXBYC", 7) == "AXBYC"

    def test_text_with_no_matching_name_unchanged(self, patch_char_names):
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        assert replace_character_names("nobody here", 7) == "nobody here"


class TestPatternCache:
    """Tests for the bounded LRU pattern cache behavior."""

    def test_pattern_cached_and_reused(self, patch_char_names):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        replace_character_names("Alice", 7)
        assert 7 in ct._GUILD_TAG_PATTERN_CACHE
        first_pattern = ct._GUILD_TAG_PATTERN_CACHE[7][1]

        # Second call with unchanged names reuses the same compiled pattern.
        replace_character_names("Alice", 7)
        assert ct._GUILD_TAG_PATTERN_CACHE[7][1] is first_pattern

    def test_cache_stores_names_tuple(self, patch_char_names):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        replace_character_names("Alice", 7)
        cached_names, _ = ct._GUILD_TAG_PATTERN_CACHE[7]
        assert cached_names == ("Alice",)

    def test_cache_invalidated_when_names_change(self, patch_char_names, monkeypatch):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({7: {"Alice": "a.png"}})
        replace_character_names("Alice", 7)
        old_pattern = ct._GUILD_TAG_PATTERN_CACHE[7][1]

        # Change the guild's names; cache must recompile for the new set.
        monkeypatch.setattr(ct, "SERVER_CHARACTER_NAMES", {7: {"Bob": "b.png"}})
        assert replace_character_names("Bob", 7) == "{{Bob}}"
        assert replace_character_names("Alice", 7) == "Alice"
        assert ct._GUILD_TAG_PATTERN_CACHE[7][1] is not old_pattern

    def test_cache_bounded_to_max_size(self, patch_char_names):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        n = ct._MAX_GUILD_PATTERN_CACHE
        mapping = {gid: {f"Name{gid}": "x.png"} for gid in range(n + 50)}
        patch_char_names(mapping)

        for gid in range(n + 50):
            replace_character_names(f"Name{gid}", gid)

        assert len(ct._GUILD_TAG_PATTERN_CACHE) == n

    def test_lru_eviction_drops_oldest_first(self, patch_char_names):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        n = ct._MAX_GUILD_PATTERN_CACHE
        total = n + 50
        mapping = {gid: {f"Name{gid}": "x.png"} for gid in range(total)}
        patch_char_names(mapping)

        for gid in range(total):
            replace_character_names(f"Name{gid}", gid)

        # The earliest-inserted guild ids are evicted.
        assert 0 not in ct._GUILD_TAG_PATTERN_CACHE
        # The most recently used guild id survives.
        assert (total - 1) in ct._GUILD_TAG_PATTERN_CACHE

    def test_cache_hit_moves_entry_to_end(self, patch_char_names):
        import cogs.ai_core.character_tags as ct
        from cogs.ai_core.character_tags import replace_character_names

        patch_char_names({1: {"One": "1.png"}, 2: {"Two": "2.png"}, 3: {"Three": "3.png"}})
        replace_character_names("One", 1)
        replace_character_names("Two", 2)
        replace_character_names("Three", 3)
        # Re-touch guild 1 (a cache hit) -> it should move to the most-recent end.
        replace_character_names("One", 1)
        assert list(ct._GUILD_TAG_PATTERN_CACHE.keys())[-1] == 1
