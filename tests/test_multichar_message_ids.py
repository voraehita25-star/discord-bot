# pylint: disable=protected-access
"""Regression test: a ``{{Name}}`` turn that sent only narration lost its ids.

``process_chat`` stamps the model history row with ``sent_message_ids`` (every
Discord message the turn went out as) and ``message_id`` (the headline one used
by the delete/edit mirroring). Both were persisted through
``update_message_id`` — but only when ``last_msg_id`` was set, and that variable
tracks WEBHOOK sends alone. A turn whose ``{{Name}}`` blocks all came out empty
(a dangling tag the model wrote), or whose webhook sends all failed, therefore
kept its ids in memory and wrote NONE of them: after a restart the narration
messages that really did go out were invisible to the mirroring.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _make_manager(reply_text: str):
    from cogs.ai_core.logic import ChatManager

    with patch.object(ChatManager, "setup_ai"):
        mgr = ChatManager(MagicMock())

    mgr.client = MagicMock()
    mgr.cli_mode = False
    mgr._prepare_user_avatar = AsyncMock(return_value=None)
    mgr._process_attachments = AsyncMock(return_value=([], [], []))
    mgr._load_character_image = MagicMock(return_value=None)
    mgr._build_api_config = MagicMock(return_value={})
    mgr._call_gemini_api = AsyncMock(return_value=(reply_text, "", []))
    mgr.is_streaming_enabled = MagicMock(return_value=False)
    mgr._process_response_text = MagicMock(return_value=reply_text)
    mgr._maybe_track_feedback = AsyncMock()

    chat_data = {"history": []}
    mgr.get_chat_session = AsyncMock(return_value=chat_data)

    channel = MagicMock()
    channel.id = 4242
    channel.guild = MagicMock()
    channel.guild.id = 555
    channel.typing = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=None)
        )
    )

    user = MagicMock()
    user.id = 42
    user.display_name = "Tester"
    return mgr, channel, user, chat_data


@contextlib.contextmanager
def _patched_io(monkeypatch, webhook_result):
    from cogs.ai_core import logic as logic_mod

    update = AsyncMock()
    monkeypatch.setattr(logic_mod, "save_history", AsyncMock(return_value=True))
    monkeypatch.setattr(logic_mod, "update_message_id", update)
    monkeypatch.setattr(logic_mod, "send_as_webhook", AsyncMock(return_value=webhook_result))
    monkeypatch.setattr(logic_mod.rag_system, "search_memory", AsyncMock(return_value=[]))
    monkeypatch.setattr(logic_mod.entity_memory, "get_all_entities", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        type(logic_mod.memory_consolidator), "enabled", property(lambda _self: False)
    )
    yield update


async def test_narration_only_turn_persists_its_ids(monkeypatch):
    """A dangling ``{{Name}}`` sends narration and nothing else — those ids are
    still real Discord messages and must reach storage."""
    mgr, channel, user, chat_data = _make_manager("เดินเข้าไปในห้อง {{ซออา}}")
    narrator_msg = MagicMock(id=9001)
    channel.send = AsyncMock(return_value=narrator_msg)

    # send_as_webhook is never reached (the block after {{ซออา}} is empty), so
    # last_msg_id stays None — the exact pre-fix hole.
    with _patched_io(monkeypatch, None) as update:
        await mgr.process_chat(channel, user, "ต่อ")

    model_row = chat_data["history"][-1]
    assert model_row["role"] == "model"
    assert model_row["sent_message_ids"] == [{"name": "narration", "id": 9001}]
    assert model_row["message_id"] == 9001
    update.assert_awaited_once()
    assert update.await_args.args[1] == 9001
    assert update.await_args.args[2] == [{"name": "narration", "id": 9001}]


async def test_character_turn_still_uses_the_last_webhook_id(monkeypatch):
    """Unchanged behaviour when a webhook message did go out: the headline id is
    the LAST one, which is what the delete/edit mirroring is built on."""
    mgr, channel, user, chat_data = _make_manager("บทนำ {{ซออา}}\nสวัสดี")
    channel.send = AsyncMock(return_value=MagicMock(id=9001))

    with _patched_io(monkeypatch, MagicMock(id=9002)) as update:
        await mgr.process_chat(channel, user, "ต่อ")

    model_row = chat_data["history"][-1]
    assert model_row["message_id"] == 9002
    assert model_row["sent_message_ids"] == [
        {"name": "narration", "id": 9001},
        {"name": "ซออา", "id": 9002},
    ]
    assert update.await_args.args[1] == 9002


async def test_no_stamp_when_nothing_was_sent(monkeypatch):
    """Every send failed: there is no id to record, so storage is left alone
    rather than stamped with a message that does not exist."""
    mgr, channel, user, chat_data = _make_manager("{{ซออา}}\nสวัสดี")
    channel.send = AsyncMock(return_value=None)

    with _patched_io(monkeypatch, None) as update:
        await mgr.process_chat(channel, user, "ต่อ")

    model_row = chat_data["history"][-1]
    assert "sent_message_ids" not in model_row
    assert model_row.get("message_id") is None
    update.assert_not_awaited()
