# pylint: disable=protected-access
"""Regression: wiping a channel's history left its RP character states behind.

``state_tracker`` holds the "[สถานะปัจจุบันของตัวละคร]" block — every
character's current location / activity / emotion / last action — derived
entirely from the messages of that channel's conversation, and ``process_chat``
injects it into every RP-guild prompt labelled as CURRENT.

Nothing cleared it. The turn right after ``!reset_ai`` still carried each
character's pre-wipe emotional state and last action, presented as current,
while the owner had just been told "🧹 ล้างความจำ AI ในห้องนี้เรียบร้อยแล้ว".
``CharacterStateTracker.clear_channel`` existed for exactly this and had no
caller anywhere in the tree.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

CHANNEL = 4242


def _make_cog():
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        cm.cli_mode = False
        cm.chats = {}
        cm.seen_users = {}
        cm.last_accessed = {}
        cm.processing_locks = {}
        cm.streaming_enabled = {}
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


def _seed_states(channel_id: int = CHANNEL):
    from cogs.ai_core.memory.state_tracker import state_tracker

    state_tracker.clear_channel(channel_id)
    state_tracker.set_state(
        "Min Chae-won", channel_id, emotion="embarrassed", last_action="ทั้งตัวแข็งค้างอยู่ตรงนั้น"
    )
    state_tracker.set_state("Han Seo-ah", channel_id, emotion="happy")
    assert state_tracker.get_states_for_prompt(channel_id) != ""
    return state_tracker


class TestForgetCharacterStates:
    def test_helper_clears_the_block(self):
        tracker = _seed_states()
        cog = _make_cog()
        try:
            cog._forget_character_states(CHANNEL)
            assert tracker.get_states_for_prompt(CHANNEL) == ""
        finally:
            tracker.clear_channel(CHANNEL)

    def test_other_channels_are_untouched(self):
        tracker = _seed_states(CHANNEL)
        _seed_states(CHANNEL + 1)
        cog = _make_cog()
        try:
            cog._forget_character_states(CHANNEL)
            assert tracker.get_states_for_prompt(CHANNEL) == ""
            assert tracker.get_states_for_prompt(CHANNEL + 1) != ""
        finally:
            tracker.clear_channel(CHANNEL)
            tracker.clear_channel(CHANNEL + 1)

    def test_a_tracker_failure_cannot_abort_the_wipe(self):
        """The rows are already deleted by the time this runs."""
        cog = _make_cog()
        broken = MagicMock()
        broken.clear_channel.side_effect = RuntimeError("boom")
        with patch.dict(
            "sys.modules",
            {"cogs.ai_core.memory.state_tracker": MagicMock(state_tracker=broken)},
        ):
            cog._forget_character_states(CHANNEL)  # must not raise


class TestWipePathsCallIt:
    @pytest.mark.asyncio
    async def test_reset_ai_clears_the_states(self):
        tracker = _seed_states()
        cog = _make_cog()
        ctx = MagicMock()
        ctx.guild = None
        ctx.channel.id = CHANNEL
        ctx.interaction = None
        ctx.send = AsyncMock()
        try:
            with patch("cogs.ai_core.ai_cog.delete_history", AsyncMock(return_value=True)):
                await cog.reset_ai.callback(cog, ctx)
            assert tracker.get_states_for_prompt(CHANNEL) == "", (
                "the turn after !reset_ai would still assert every character's "
                "pre-wipe state as CURRENT"
            )
            ctx.send.assert_awaited()
        finally:
            tracker.clear_channel(CHANNEL)

    @pytest.mark.asyncio
    async def test_channel_delete_clears_the_states(self):
        tracker = _seed_states()
        cog = _make_cog()
        channel = MagicMock()
        channel.id = CHANNEL
        try:
            with patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete"):
                await cog.on_guild_channel_delete(channel)
            assert tracker.get_states_for_prompt(CHANNEL) == ""
        finally:
            tracker.clear_channel(CHANNEL)


class TestTrackerDocumentsWhatItActuallyDoes:
    def test_persistence_is_not_claimed(self):
        """``to_dict`` / ``from_dict`` work but have no caller, so every restart
        starts with no states. The docstring used to advertise persistence."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        doc = CharacterStateTracker.__doc__ or ""
        assert "State persistence between sessions" not in doc
        assert "NOT persisted" in doc
