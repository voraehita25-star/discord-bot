"""Smoke-test the example data modules so they import cleanly + expose the
expected names. The real `*_data.py` modules are not committed (they're
server-specific), so the example variants are the fallback the rest of
the codebase imports against — they need to keep working."""

from __future__ import annotations


class TestFaustDataExample:
    def test_imports_cleanly(self):
        from cogs.ai_core.data import faust_data_example as fde

        assert fde is not None

    def test_persona_is_string(self):
        from cogs.ai_core.data.faust_data_example import (
            FAUST_CODE_OVERRIDE,
            FAUST_DM_INSTRUCTION,
            FAUST_INSTRUCTION,
        )

        assert isinstance(FAUST_INSTRUCTION, str)
        assert isinstance(FAUST_DM_INSTRUCTION, str)
        assert isinstance(FAUST_CODE_OVERRIDE, str)

    def test_escalations_are_lists(self):
        from cogs.ai_core.data.faust_data_example import (
            ENI_ESCALATION_FRAMING,
            ESCALATION_FRAMINGS,
        )

        assert isinstance(ESCALATION_FRAMINGS, list)
        assert all(isinstance(s, str) for s in ESCALATION_FRAMINGS)
        assert isinstance(ENI_ESCALATION_FRAMING, str)


class TestRoleplayDataExample:
    def test_imports_cleanly(self):
        from cogs.ai_core.data import roleplay_data_example as rde

        assert rde is not None

    def test_prompt_is_string(self):
        from cogs.ai_core.data.roleplay_data_example import (
            ROLEPLAY_ASSISTANT_INSTRUCTION,
            ROLEPLAY_PROMPT,
            WORLD_LORE,
        )

        assert isinstance(ROLEPLAY_PROMPT, str)
        assert isinstance(WORLD_LORE, str)
        assert isinstance(ROLEPLAY_ASSISTANT_INSTRUCTION, str)

    def test_characters_is_list(self):
        from cogs.ai_core.data.roleplay_data_example import SERVER_CHARACTERS

        assert isinstance(SERVER_CHARACTERS, list)
        for entry in SERVER_CHARACTERS:
            assert isinstance(entry, dict)
            assert "name" in entry

    def test_per_guild_dicts_initialised(self):
        from cogs.ai_core.data.roleplay_data_example import (
            SERVER_AVATARS,
            SERVER_CHARACTER_NAMES,
            SERVER_LORE,
        )

        assert isinstance(SERVER_LORE, dict)
        assert isinstance(SERVER_AVATARS, dict)
        assert isinstance(SERVER_CHARACTER_NAMES, dict)


class TestRoleplayDataExampleDerivedMaps:
    """``SERVER_CHARACTER_NAMES`` and ``SERVER_AVATARS`` are both derived from
    ``SERVER_CHARACTERS``, so every string that can become a ``{{Tag}}`` also
    resolves to a webhook avatar. The hand-written avatar map this replaced
    covered 8 of 17 keys on a real server: a ``{{nickname}}`` tag produced a
    webhook with no avatar."""

    def test_maps_share_keys_when_guild_configured(self, monkeypatch):
        import importlib
        import os

        from cogs.ai_core.data import roleplay_data_example as rde

        original = os.environ.get("GUILD_ID_RP")
        monkeypatch.setenv("GUILD_ID_RP", "424242")
        try:
            mod = importlib.reload(rde)
            names = mod.SERVER_CHARACTER_NAMES[424242]
            avatars = mod.SERVER_AVATARS[424242]
            assert set(names) == set(avatars)
            assert {"Example Character", "ตัวละครตัวอย่าง", "Example", "Ex"} <= set(names)
            assert names["Ex"] == "assets/RP/example.png"
            assert avatars["Ex"] == "assets/RP/AVATARS/example.png"
            assert mod.SERVER_LORE[424242] == mod.WORLD_LORE
        finally:
            # Re-execute under the ORIGINAL env so module state matches it again
            # (monkeypatch restores the env only after this runs).
            if original is None:
                monkeypatch.delenv("GUILD_ID_RP", raising=False)
            else:
                monkeypatch.setenv("GUILD_ID_RP", original)
            importlib.reload(rde)

    def test_explicit_avatar_wins_over_derived_path(self):
        from cogs.ai_core.data.roleplay_data_example import _avatar_path, _character_keys

        derived = {"name": "A", "image": "assets/RP/sub/A.png"}
        assert _avatar_path(derived) == "assets/RP/AVATARS/A.png"
        explicit = {"name": "A", "image": "assets/RP/A.png", "avatar": "assets/RP/AVATARS/a.png"}
        assert _avatar_path(explicit) == "assets/RP/AVATARS/a.png"
        # Empty / missing entries never become keys (an empty key would corrupt
        # the tag regex — see character_tags._compile_guild_pattern).
        assert _character_keys({"name": "A", "name_th": "", "nicknames": ["a1", ""]}) == ["A", "a1"]
        assert _character_keys({"name": "B"}) == ["B"]
