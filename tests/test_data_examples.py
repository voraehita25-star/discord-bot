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
            FAUST_SANDBOX,
            UNRESTRICTED_MODE_INSTRUCTION,
        )

        assert isinstance(FAUST_INSTRUCTION, str)
        assert isinstance(FAUST_DM_INSTRUCTION, str)
        assert isinstance(FAUST_SANDBOX, str)
        assert isinstance(FAUST_CODE_OVERRIDE, str)
        assert isinstance(UNRESTRICTED_MODE_INSTRUCTION, str)

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
