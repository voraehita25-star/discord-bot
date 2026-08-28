# pylint: disable=protected-access
"""Regression: ``!remember`` saved into a store the Discord reply path never read.

There are two long-term memory stores with near-identical names:

* ``long_term_memory`` — SQLite ``user_facts``. Written by the ``!remember``
  command and by the ``remember`` tool through the IPC bridge.
* ``rag_system`` — FAISS + ``rag_memories.json``. Written only by
  ``tool_executor``'s ``remember`` branch.

``process_chat``'s ``[Long-term Memory]`` prompt block read ONLY the second one.
So ``!remember`` replied "✅ จำแล้ว! … ข้อมูลนี้จะถูกจำอย่างถาวร" and the AI never
saw the fact — the only other readers being the ``recall_memory`` MCP tool
(withheld at the default ``CLI_TOOL_SCOPE=minimal``) and ``!memories``, which
only lists the facts back to the user who stored them.

Measured on the live database: 2 rows in ``user_facts``, 0 rows in the RAG store,
and no FAISS index on disk at all — the only populated long-term store was the
unreachable one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fact(content: str):
    from cogs.ai_core.memory.long_term_memory import Fact

    return Fact(user_id=42, content=content)


class TestFactsReachTheModel:
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
        mgr.is_streaming_enabled = MagicMock(return_value=False)
        mgr._process_response_text = MagicMock(return_value="reply")
        mgr._maybe_track_feedback = AsyncMock()
        mgr.get_chat_session = AsyncMock(return_value={"history": []})

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
        return mgr, channel, user

    async def _run(self, monkeypatch, *, facts, rag=None, message="จำอะไรเกี่ยวกับผมได้บ้าง"):
        from cogs.ai_core import logic as logic_mod
        from cogs.ai_core.memory import long_term_memory as ltm_mod

        mgr, channel, user = self._manager()
        seen = {}

        async def capture(contents, config_params, channel_id=None, **kwargs):
            seen["contents"] = contents
            return ("reply", "", [])

        mgr._call_gemini_api = capture
        monkeypatch.setattr(logic_mod, "save_history", AsyncMock(return_value=True))
        monkeypatch.setattr(logic_mod, "update_message_id", AsyncMock())
        monkeypatch.setattr(
            logic_mod.rag_system, "search_memory", AsyncMock(return_value=list(rag or []))
        )
        monkeypatch.setattr(logic_mod.entity_memory, "get_all_entities", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            type(logic_mod.memory_consolidator), "enabled", property(lambda _s: False)
        )
        monkeypatch.setattr(
            ltm_mod.long_term_memory, "get_user_facts", AsyncMock(return_value=facts)
        )
        await mgr.process_chat(channel, user, message)

        current = seen["contents"][-1]
        return " ".join(
            part["text"] for part in current["parts"] if isinstance(part, dict) and "text" in part
        )

    @pytest.mark.asyncio
    async def test_a_remembered_fact_is_in_the_prompt(self, monkeypatch):
        sent = await self._run(monkeypatch, facts=[_fact("ผมแพ้ถั่ว")])

        assert "[Long-term Memory]" in sent
        assert "ผมแพ้ถั่ว" in sent, (
            "!remember reported the fact as permanently stored, but the turn's "
            "prompt never carried it"
        )

    @pytest.mark.asyncio
    async def test_facts_and_rag_hits_share_one_block(self, monkeypatch):
        sent = await self._run(monkeypatch, facts=[_fact("ผมแพ้ถั่ว")], rag=["ผู้ใช้ชอบกาแฟ"])

        assert sent.count("[Long-term Memory]") == 1
        assert "ผมแพ้ถั่ว" in sent
        assert "ผู้ใช้ชอบกาแฟ" in sent

    @pytest.mark.asyncio
    async def test_no_block_when_there_is_nothing_to_say(self, monkeypatch):
        sent = await self._run(monkeypatch, facts=[])

        assert "[Long-term Memory]" not in sent

    @pytest.mark.asyncio
    async def test_the_count_is_bounded(self, monkeypatch):
        from cogs.ai_core.data.constants import RAG_TOP_K

        facts = [_fact(f"ข้อเท็จจริงที่ {i}") for i in range(RAG_TOP_K + 10)]
        sent = await self._run(monkeypatch, facts=facts)

        assert f"ข้อเท็จจริงที่ {RAG_TOP_K - 1}" in sent
        assert f"ข้อเท็จจริงที่ {RAG_TOP_K}" not in sent

    @pytest.mark.asyncio
    async def test_blank_facts_are_skipped(self, monkeypatch):
        sent = await self._run(monkeypatch, facts=[_fact("   "), _fact("ผมชื่อโจ")])

        assert "ผมชื่อโจ" in sent
        assert "- \n" not in sent

    @pytest.mark.asyncio
    async def test_facts_arrive_on_an_attachment_only_turn(self, monkeypatch):
        """Profile facts are about the speaker, not the query — an image-only
        turn needs them just as much, so retrieval is not gated on user text."""
        sent = await self._run(monkeypatch, facts=[_fact("ผมแพ้ถั่ว")], message="")

        assert "ผมแพ้ถั่ว" in sent

    @pytest.mark.asyncio
    async def test_a_backend_failure_degrades_to_no_facts(self, monkeypatch):
        """Same contract as the RAG block: never abort the turn."""
        from cogs.ai_core import logic as logic_mod
        from cogs.ai_core.memory import long_term_memory as ltm_mod

        mgr, channel, user = self._manager()
        seen = {}

        async def capture(contents, config_params, channel_id=None, **kwargs):
            seen["contents"] = contents
            return ("reply", "", [])

        mgr._call_gemini_api = capture
        monkeypatch.setattr(logic_mod, "save_history", AsyncMock(return_value=True))
        monkeypatch.setattr(logic_mod, "update_message_id", AsyncMock())
        monkeypatch.setattr(logic_mod.rag_system, "search_memory", AsyncMock(return_value=[]))
        monkeypatch.setattr(logic_mod.entity_memory, "get_all_entities", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            type(logic_mod.memory_consolidator), "enabled", property(lambda _s: False)
        )
        monkeypatch.setattr(
            ltm_mod.long_term_memory,
            "get_user_facts",
            AsyncMock(side_effect=RuntimeError("db down")),
        )

        await mgr.process_chat(channel, user, "สวัสดี")

        assert "contents" in seen, "a memory backend failure aborted the whole turn"
