# pylint: disable=protected-access
"""Regression: a merged burst kept only its LAST message's Discord id.

When a user sends again while the AI is still answering, ``MessageQueue`` queues
the message and the drain merges the whole burst into ONE turn — and therefore
one history row. ``user_message_id`` can only name one message, and it named the
last, so every earlier message of the burst was unreachable by the Discord
delete/edit mirroring: deleting one of them left it in the AI's memory, which is
exactly what that mirroring exists to prevent.

The model side already solved the mirror-image problem (one turn, several sent
messages) with ``sent_message_ids``, and ``_row_covers_message`` reads that field
regardless of role — so the user side reuses it rather than inventing a second
mechanism.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _queue_with(*ids: int):
    from cogs.ai_core.core.message_queue import MessageQueue

    queue = MessageQueue()
    for i, mid in enumerate(ids):
        user = MagicMock()
        user.display_name = f"U{i}"
        queue.queue_message(
            channel_id=7,
            channel=MagicMock(),
            user=user,
            message=f"msg{i}",
            user_message_id=mid,
        )
    return queue


class TestMergeCarriesEveryId:
    def test_a_merged_burst_reports_all_ids_oldest_first(self):
        queue = _queue_with(101, 102, 103)
        latest, combined = queue.merge_pending_messages(7)

        assert latest is not None
        assert latest.merged_message_ids == [101, 102, 103]
        assert latest.user_message_id == 103
        assert "msg0" in combined and "msg2" in combined

    def test_a_single_message_turn_keeps_the_old_shape(self):
        queue = _queue_with(101)
        latest, _combined = queue.merge_pending_messages(7)

        assert latest is not None
        assert latest.merged_message_ids is None, (
            "a lone message is fully described by user_message_id; adding a list "
            "would change every single-message row for nothing"
        )

    def test_messages_without_an_id_are_skipped_not_recorded_as_none(self):
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        for mid in (None, 202):
            user = MagicMock()
            user.display_name = "U"
            queue.queue_message(
                channel_id=7,
                channel=MagicMock(),
                user=user,
                message="m",
                user_message_id=mid,
            )
        latest, _ = queue.merge_pending_messages(7)

        assert latest is not None
        assert latest.merged_message_ids == [202]


class TestTheMergedRowIsAddressable:
    @staticmethod
    def _manager():
        from cogs.ai_core.logic import ChatManager

        with patch.object(ChatManager, "setup_ai"):
            mgr = ChatManager(MagicMock())
        mgr.client = MagicMock()
        mgr.cli_mode = True
        mgr._prepare_user_avatar = AsyncMock(return_value=None)
        mgr._process_attachments = AsyncMock(return_value=([], [], []))
        mgr._load_character_image = MagicMock(return_value=None)
        mgr._build_api_config = MagicMock(return_value={})
        mgr._call_gemini_api = AsyncMock(return_value=("reply", "", []))
        mgr.is_streaming_enabled = MagicMock(return_value=False)
        mgr._process_response_text = MagicMock(return_value="reply")
        mgr._maybe_track_feedback = AsyncMock()

        chat_data = {"history": []}
        mgr.get_chat_session = AsyncMock(return_value=chat_data)

        channel = MagicMock()
        channel.id = 4242
        channel.guild = MagicMock(id=555)
        channel.send = AsyncMock(return_value=MagicMock(id=1))
        channel.typing = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=None)
            )
        )
        user = MagicMock(id=42)
        user.display_name = "Tester"
        return mgr, channel, user, chat_data

    async def _run(self, monkeypatch, **kwargs):
        from cogs.ai_core import logic as logic_mod

        mgr, channel, user, chat_data = self._manager()
        monkeypatch.setattr(logic_mod, "save_history", AsyncMock(return_value=True))
        monkeypatch.setattr(logic_mod, "update_message_id", AsyncMock())
        monkeypatch.setattr(logic_mod.rag_system, "search_memory", AsyncMock(return_value=[]))
        monkeypatch.setattr(logic_mod.entity_memory, "get_all_entities", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            type(logic_mod.memory_consolidator), "enabled", property(lambda _s: False)
        )
        await mgr.process_chat(channel, user, "รวมข้อความ", **kwargs)
        return mgr, chat_data

    @pytest.mark.asyncio
    async def test_the_row_records_every_burst_id(self, monkeypatch):
        _mgr, chat_data = await self._run(
            monkeypatch, user_message_id=103, merged_message_ids=[101, 102, 103]
        )

        row = chat_data["history"][0]
        assert row["role"] == "user"
        assert row["message_id"] == 103
        assert row["sent_message_ids"] == [
            {"name": "user", "id": 101},
            {"name": "user", "id": 102},
            {"name": "user", "id": 103},
        ]

    @pytest.mark.asyncio
    async def test_a_normal_turn_has_no_extra_field(self, monkeypatch):
        _mgr, chat_data = await self._run(monkeypatch, user_message_id=103)

        assert "sent_message_ids" not in chat_data["history"][0]

    @pytest.mark.asyncio
    async def test_deleting_an_earlier_burst_message_reaches_the_row(self, monkeypatch):
        """The whole point: mirroring has to find a row by ANY of its ids."""
        from cogs.ai_core.logic import _row_covers_message

        _mgr, chat_data = await self._run(
            monkeypatch, user_message_id=103, merged_message_ids=[101, 102, 103]
        )
        row = chat_data["history"][0]

        for mid in (101, 102, 103):
            assert _row_covers_message(row, mid), f"message {mid} was left unreachable"
        assert not _row_covers_message(row, 999)
