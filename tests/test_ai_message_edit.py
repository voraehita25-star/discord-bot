"""Tests for the AI correcting a message it already sent.

Three pieces have to line up for that to work, and each is covered here:

1. ``edit_message`` is a real tool — declared in the catalog the MCP bridge
   serves, and dispatched by ``execute_tool_call`` under a permission tier that
   matches ``cmd_edit_message``'s own ``manage_messages`` check.
2. The model can LEARN a message id — from the ``(msg …)`` annotation on its own
   past turns, and from ``read_channel``, which reports the id of every message
   it returns (the only route to a message older than the visible history).
3. The edit is mirrored back into stored history, because
   ``on_raw_message_edit`` deliberately ignores edits the bot authored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


def _bare_manager(chats):
    """A ChatManager with just the ``chats`` dict — bypasses heavy __init__."""
    from cogs.ai_core.logic import ChatManager

    cm = ChatManager.__new__(ChatManager)
    cm.chats = chats
    cm.bot = MagicMock()
    return cm


def _member(*, administrator=False, manage_messages=False, manage_guild=False):
    user = MagicMock(spec=discord.Member)
    user.display_name = "Mod"
    user.guild_permissions = MagicMock()
    user.guild_permissions.administrator = administrator
    user.guild_permissions.manage_messages = manage_messages
    user.guild_permissions.manage_guild = manage_guild
    return user


# ============================================================================
# 1. The tool exists
# ============================================================================


class TestEditMessageToolIsDeclared:
    def test_declared_in_catalog(self):
        """Without this the CLI backend has no edit_message to call at all —
        the MCP tool list is derived straight from get_tool_definitions()."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions

        decls = [fn for group in get_tool_definitions() for fn in group["function_declarations"]]
        edit = next((fn for fn in decls if fn["name"] == "edit_message"), None)
        assert edit is not None
        assert edit["parameters"]["required"] == ["message_id", "new_content"]

    def test_message_id_is_a_string_param(self):
        """Snowflakes exceed the range a JSON number round-trips exactly."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions

        decls = [fn for group in get_tool_definitions() for fn in group["function_declarations"]]
        edit = next(fn for fn in decls if fn["name"] == "edit_message")
        assert edit["parameters"]["properties"]["message_id"]["type"] == "STRING"

    def test_reaches_the_mcp_schema_list(self):
        from cogs.ai_core.api.ai_tools_ipc import _server_tool_schemas

        assert "edit_message" in {t["name"] for t in _server_tool_schemas()}


class TestEditMessageDispatch:
    """execute_tool_call must actually route edit_message to cmd_edit_message."""

    @staticmethod
    def _channel():
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = MagicMock(spec=discord.Guild)
        channel.send = AsyncMock()
        return channel

    @pytest.mark.asyncio
    async def test_routes_to_cmd_edit_message(self):
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        channel = self._channel()
        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": "140123", "new_content": "fixed line"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_edit_message", AsyncMock()) as mock_cmd:
            result = await execute_tool_call(
                MagicMock(), channel, _member(manage_messages=True), call
            )

        assert "140123" in result
        args = mock_cmd.await_args[0][3]
        assert args == ["140123", "fixed line"]

    @pytest.mark.asyncio
    async def test_accepts_an_integer_message_id(self):
        """A model that ignores the STRING type still sends a valid snowflake."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        channel = self._channel()
        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": 140123, "new_content": "fixed"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_edit_message", AsyncMock()) as mock_cmd:
            await execute_tool_call(MagicMock(), channel, _member(manage_messages=True), call)

        assert mock_cmd.await_args[0][3] == ["140123", "fixed"]

    @pytest.mark.asyncio
    async def test_rejects_missing_message_id(self):
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        call = MagicMock()
        call.name = "edit_message"
        call.input = {"new_content": "fixed"}

        result = await execute_tool_call(
            MagicMock(), self._channel(), _member(manage_messages=True), call
        )
        assert "message_id" in result and result.startswith("❌")

    @pytest.mark.asyncio
    async def test_rejects_blank_new_content(self):
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": "140123", "new_content": "   "}

        result = await execute_tool_call(
            MagicMock(), self._channel(), _member(manage_messages=True), call
        )
        assert "new_content" in result and result.startswith("❌")

    @pytest.mark.asyncio
    async def test_rejects_content_over_the_discord_limit(self):
        """An edit cannot be chunked, so >2000 chars is rejected up front
        instead of surfacing as an opaque 400 from the API."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": "140123", "new_content": "x" * 2001}

        with patch("cogs.ai_core.tools.tool_executor.cmd_edit_message", AsyncMock()) as mock_cmd:
            result = await execute_tool_call(
                MagicMock(), self._channel(), _member(manage_messages=True), call
            )

        assert "2000" in result and result.startswith("❌")
        mock_cmd.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manage_messages_is_enough_without_admin(self):
        """The executor tier must match the handler's own gate — requiring
        admin here would deny exactly the moderators cmd_edit_message allows."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": "140123", "new_content": "fixed"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_edit_message", AsyncMock()) as mock_cmd:
            result = await execute_tool_call(
                MagicMock(), self._channel(), _member(manage_messages=True), call
            )

        assert not result.startswith("⛔")
        mock_cmd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_denied_without_manage_messages(self):
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": "140123", "new_content": "fixed"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_edit_message", AsyncMock()) as mock_cmd:
            result = await execute_tool_call(MagicMock(), self._channel(), _member(), call)

        assert result.startswith("⛔")
        assert "manage_messages" in result
        mock_cmd.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handler_failure_is_surfaced_not_reported_as_success(self):
        """cmd_edit_message posts its errors to the channel and returns None;
        the tee is what stops that becoming a false 'Edited message …'."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        channel = self._channel()
        call = MagicMock()
        call.name = "edit_message"
        call.input = {"message_id": "140123", "new_content": "fixed"}

        async def _fail(_guild, origin, _name, _args, user=None):
            await origin.send("❌ แก้ไขไม่ได้: ข้อความไม่ใช่ของบอท")

        with patch("cogs.ai_core.tools.tool_executor.cmd_edit_message", _fail):
            result = await execute_tool_call(
                MagicMock(), channel, _member(manage_messages=True), call
            )

        assert result.startswith("❌")


# ============================================================================
# 2. The model can learn an id
# ============================================================================


class TestMessageIdAnnotation:
    def test_single_message_turn(self):
        from cogs.ai_core.logic import _format_message_id_prefix

        assert _format_message_id_prefix({"message_id": 140123}) == "(msg 140123) "

    def test_multi_message_turn_names_each_speaker(self):
        """One RP turn = one history row but several Discord messages; without
        the per-message list only the LAST character line is addressable."""
        from cogs.ai_core.logic import _format_message_id_prefix

        item = {
            "message_id": 3,
            "sent_message_ids": [
                {"name": "narration", "id": 1},
                {"name": "ซออา", "id": 2},
                {"name": "แชวอน", "id": 3},
            ],
        }
        assert _format_message_id_prefix(item) == "(msgs narration=1, ซออา=2, แชวอน=3) "

    def test_unlabelled_entries_fall_back_to_bare_ids(self):
        from cogs.ai_core.logic import _format_message_id_prefix

        item = {"sent_message_ids": [{"id": 1}, {"name": "", "id": 2}]}
        assert _format_message_id_prefix(item) == "(msgs 1, 2) "

    def test_long_lists_are_truncated_visibly(self):
        from cogs.ai_core.logic import _MAX_ANNOTATED_MESSAGE_IDS, _format_message_id_prefix

        item = {
            "sent_message_ids": [
                {"name": f"c{i}", "id": i} for i in range(_MAX_ANNOTATED_MESSAGE_IDS + 5)
            ]
        }
        out = _format_message_id_prefix(item)
        assert out.endswith(", …) ")
        assert "c0=0" in out

    def test_falls_back_to_row_id_when_list_is_unusable(self):
        from cogs.ai_core.logic import _format_message_id_prefix

        item = {"message_id": 9, "sent_message_ids": [{"name": "x"}]}
        assert _format_message_id_prefix(item) == "(msg 9) "

    def test_empty_when_nothing_was_recorded(self):
        """Older rows, and any row after a DB-backed restart — read_channel
        covers those, so the annotation must simply be absent, not wrong."""
        from cogs.ai_core.logic import _format_message_id_prefix

        assert _format_message_id_prefix({}) == ""
        assert _format_message_id_prefix({"sent_message_ids": []}) == ""


class TestStripLeadingMessageIds:
    """The annotation is shown on every past assistant turn, so the model
    imitates it — the same hazard the timestamp prefix already had."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("(msg 140123) hello", "hello"),
            ("(msgs narration=1, ซออา=2) hello", "hello"),
            ("  (msg 1)   hello", "hello"),
            ("(not an id) hello", "(not an id) hello"),
            ("hello (msg 1)", "hello (msg 1)"),
            ("", ""),
        ],
    )
    def test_strip(self, raw, expected):
        from cogs.ai_core.api.dashboard_common import strip_leading_message_ids

        assert strip_leading_message_ids(raw) == expected

    def test_only_one_annotation_is_removed(self):
        from cogs.ai_core.api.dashboard_common import strip_leading_message_ids

        assert strip_leading_message_ids("(msg 1) (msg 2) hi") == "(msg 2) hi"


class TestPromptExplainsTheAnnotation:
    def test_formatting_rules_mention_edit_message_and_read_channel(self):
        """With the tools resolved as present, the prompt says how to use the ids."""
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            [{"role": "user", "parts": ["hi"]}],
            "persona",
            include_history=True,
            can_edit_messages=True,
            can_read_channel=True,
        )
        assert "edit_message" in prompt
        assert "read_channel" in prompt
        assert "(msg " in prompt

    def test_annotation_is_still_explained_without_the_tools(self):
        """The ids are always explained as metadata to ignore — that is what
        keeps the model from mimicking the prefix into its own reply."""
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            [{"role": "user", "parts": ["hi"]}], "persona", include_history=True
        )
        assert "(msg " in prompt
        assert "never reproduce" in prompt

    def test_no_tool_is_promised_when_the_argv_withholds_it(self):
        """The default (CLI_TOOL_SCOPE=minimal) turn carries no MCP tool at all,
        so the prompt must not offer edit_message / read_channel — a promise the
        model would act on and fail."""
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            [{"role": "user", "parts": ["hi"]}], "persona", include_history=True
        )
        assert "edit_message" not in prompt
        assert "read_channel" not in prompt

    def test_each_tool_is_announced_independently(self):
        """DASHBOARD_CLI_SERVER_ACTIONS can expose one without the other."""
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        only_edit = _flatten_contents_to_prompt(
            [{"role": "user", "parts": ["hi"]}], "persona", can_edit_messages=True
        )
        assert "edit_message" in only_edit
        assert "read_channel" not in only_edit

    def test_message_id_tools_reads_the_resolved_toolset(self):
        from cogs.ai_core.api.discord_chat_claude_cli import _message_id_tools

        assert _message_id_tools(None) == (False, False)
        assert _message_id_tools([]) == (False, False)
        # What effective_ai_tool_names() returns at minimal scope on this path.
        assert _message_id_tools(["WebSearch", "WebFetch"]) == (False, False)
        assert _message_id_tools(
            ["mcp__bottools__edit_message", "mcp__bottools__read_channel"]
        ) == (True, True)
        assert _message_id_tools(["mcp__bottools__remember"]) == (False, False)


class TestResumedSessionIdRecap:
    """On the default cli backend a resumed turn does not re-send the history,
    which would also withhold every id annotation — leaving the model unable to
    correct its own recent messages from turn two onward."""

    @staticmethod
    def _contents():
        return [
            {"role": "user", "parts": ["[2026-08-02T13:00:00+07:00] เล่นต่อ"]},
            {
                "role": "model",
                "parts": ["[2026-08-02T13:00:01+07:00] (msgs ซออา=11, แชวอน=12) บทที่หนึ่ง"],
            },
            {"role": "user", "parts": ["ต่อ"]},
        ]

    def test_recap_survives_a_resumed_turn(self):
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            self._contents(), "persona", include_history=False, can_edit_messages=True
        )
        assert "# Conversation history" not in prompt
        assert "(msgs ซออา=11, แชวอน=12)" in prompt
        assert "ids for edit_message" in prompt

    def test_no_recap_without_the_edit_tool(self):
        """The block exists only to feed edit_message; without that tool it is
        prompt weight that reads as an invitation to call something absent."""
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(self._contents(), "persona", include_history=False)
        assert "# Conversation history" not in prompt
        assert "ids for edit_message" not in prompt

    def test_full_history_path_is_unchanged(self):
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            self._contents(), "persona", include_history=True, can_edit_messages=True
        )
        assert "# Conversation history" in prompt
        assert "ids for edit_message" not in prompt

    def test_recap_is_bounded(self):
        from cogs.ai_core.api.discord_chat_claude_cli import (
            _RESUMED_ID_RECAP_TURNS,
            _recent_message_id_lines,
        )

        history = [
            {"role": "model", "parts": [f"(msg {i}) line {i}"]}
            for i in range(_RESUMED_ID_RECAP_TURNS + 4)
        ]
        lines = _recent_message_id_lines(history)
        assert len(lines) == _RESUMED_ID_RECAP_TURNS
        # Oldest-first, and it kept the MOST RECENT turns.
        assert lines[-1].startswith(f"(msg {_RESUMED_ID_RECAP_TURNS + 3})")

    def test_long_turns_are_snipped(self):
        from cogs.ai_core.api.discord_chat_claude_cli import (
            _RESUMED_ID_RECAP_SNIPPET,
            _recent_message_id_lines,
        )

        history = [{"role": "model", "parts": ["(msg 1) " + "ก" * 500]}]
        (line,) = _recent_message_id_lines(history)
        assert line.endswith("…")
        assert len(line) < _RESUMED_ID_RECAP_SNIPPET + 40

    def test_turns_without_an_annotation_are_skipped(self):
        """Naming a turn without giving its id would only invite a guess."""
        from cogs.ai_core.api.discord_chat_claude_cli import _recent_message_id_lines

        history = [
            {"role": "model", "parts": ["no annotation here"]},
            {"role": "user", "parts": ["(msg 1) not the assistant"]},
        ]
        assert _recent_message_id_lines(history) == []

    def test_no_recap_block_when_nothing_is_annotated(self):
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            [{"role": "model", "parts": ["plain"]}, {"role": "user", "parts": ["hi"]}],
            "persona",
            include_history=False,
            can_edit_messages=True,
        )
        assert "ids for edit_message" not in prompt


class TestSdkBackendParity:
    """CLAUDE_BACKEND=api must not be a silent downgrade: the SDK path gets the
    same prompt note and the same output cleaning as the cli path."""

    def test_system_prompt_explains_the_injected_prefixes(self):
        from cogs.ai_core.api.api_handler import with_prefix_note

        system = with_prefix_note("persona")
        assert system.startswith("persona")
        assert "(msg " in system
        assert "never write one into a reply" in system

    def test_sdk_note_promises_no_tool(self):
        """This path sends no ``tools`` argument at all, so naming edit_message /
        read_channel was an unconditional lie that the model would act on."""
        from cogs.ai_core.api.api_handler import with_prefix_note

        system = with_prefix_note("persona")
        assert "edit_message" not in system
        assert "read_channel" not in system

    def test_empty_system_prompt_stays_empty(self):
        """An empty instruction means 'no persona' — appending a lone rules
        block would turn that into a prompt."""
        from cogs.ai_core.api.api_handler import with_prefix_note

        assert with_prefix_note("") == ""

    def test_build_api_config_still_passes_the_instruction_through(self):
        """The note is added at the wire, not in the config — the config
        builder's pass-through contract is what its own tests assert."""
        from cogs.ai_core.api.api_handler import build_api_config

        config = build_api_config({"system_instruction": "persona", "thinking_enabled": False})
        assert config["system_instruction"] == "persona"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("[2026-05-20T13:18:47+07:00] hi", "hi"),
            ("(msgs a=1, b=2) hi", "hi"),
            ("[2026-05-20T13:18:47+07:00] (msg 1) hi", "hi"),
            ("hi", "hi"),
            ("", ""),
        ],
    )
    def test_output_cleaning(self, raw, expected):
        from cogs.ai_core.api.api_handler import clean_model_text

        assert clean_model_text(raw) == expected


class TestReadChannelReportsIds:
    @pytest.mark.asyncio
    async def test_each_line_carries_its_message_id(self):
        """The only way to reach a message older than the loaded history."""
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        msg = MagicMock()
        msg.id = 140987
        msg.content = "คาบนี้ยาวเป็นชาติเลยนะน้อง"
        msg.author.display_name = "ซออา"
        msg.created_at.strftime.return_value = "13:05"

        async def _history(limit=10):
            yield msg

        target = MagicMock(spec=discord.TextChannel)
        target.name = "rp"
        target.id = 555
        target.history = _history
        target.permissions_for.return_value = MagicMock(
            read_messages=True, read_message_history=True
        )

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel.return_value = target
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        origin.guild = guild

        with patch(
            "cogs.ai_core.commands.server_commands.send_long_message", AsyncMock()
        ) as mock_send:
            await cmd_read_channel(guild, origin, None, ["555"], user=_member(administrator=True))

        lines = mock_send.await_args[0][2]
        assert lines == ["[13:05] (id: 140987) ซออา: คาบนี้ยาวเป็นชาติเลยนะน้อง"]


# ============================================================================
# 3. The edit reaches stored memory
# ============================================================================


class TestReplaceMessageTextInHistory:
    @pytest.mark.asyncio
    async def test_id_keyed_row_uses_a_targeted_update(self):
        cm = _bare_manager(
            {7: {"history": [{"role": "model", "parts": ["hello there"], "message_id": 10}]}}
        )
        with patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=1)) as mock_edit:
            result = await cm.replace_message_text_in_history(7, 10, "hello there", "hi there")

        assert result is True
        assert cm.chats[7]["history"][0]["parts"] == ["hi there"]
        mock_edit.assert_awaited_once_with(7, 10, "hi there")

    @pytest.mark.asyncio
    async def test_rp_turn_patches_only_the_edited_fragment(self):
        """A multi-character turn is ONE row. Swapping the row wholesale (what
        edit_message_in_history does) would delete every other character's
        line, so only the edited message's text may change."""
        cm = _bare_manager(
            {
                7: {
                    "history": [
                        {
                            "role": "model",
                            "parts": ["{{ซออา}} คาบนี้ยาวชิบหายเลยนะน้อง\n{{แชวอน}} เย็นจัง"],
                            "message_id": 99,
                        }
                    ]
                }
            }
        )
        with patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=1)):
            result = await cm.replace_message_text_in_history(
                7, 55, "คาบนี้ยาวชิบหายเลยนะน้อง", "คาบนี้ยาวเป็นชาติเลยนะน้อง"
            )

        assert result is True
        text = cm.chats[7]["history"][0]["parts"][0]
        assert "ชิบหาย" not in text
        assert "คาบนี้ยาวเป็นชาติเลยนะน้อง" in text
        assert "{{แชวอน}} เย็นจัง" in text

    @pytest.mark.asyncio
    async def test_row_without_an_id_is_persisted_by_force_replace(self):
        """No id to key a targeted UPDATE on — an intermediate webhook message
        never had one recorded — so the in-memory view is committed wholesale."""
        cm = _bare_manager({7: {"history": [{"role": "model", "parts": ["swear word here"]}]}})
        with (
            patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock()) as mock_edit,
            patch("cogs.ai_core.logic.save_history", AsyncMock(return_value=True)) as mock_save,
        ):
            result = await cm.replace_message_text_in_history(7, 55, "swear word", "nice word")

        assert result is True
        assert cm.chats[7]["history"][0]["parts"] == ["nice word here"]
        mock_edit.assert_not_awaited()
        assert mock_save.await_args.kwargs["force"] is True

    @pytest.mark.asyncio
    async def test_patches_the_most_recent_occurrence(self):
        cm = _bare_manager(
            {
                7: {
                    "history": [
                        {"role": "model", "parts": ["same line"]},
                        {"role": "user", "parts": ["ok"]},
                        {"role": "model", "parts": ["same line"]},
                    ]
                }
            }
        )
        with patch("cogs.ai_core.logic.save_history", AsyncMock(return_value=True)):
            await cm.replace_message_text_in_history(7, 55, "same line", "fixed line")

        assert cm.chats[7]["history"][0]["parts"] == ["same line"]
        assert cm.chats[7]["history"][2]["parts"] == ["fixed line"]

    @pytest.mark.asyncio
    async def test_never_patches_a_user_turn(self):
        cm = _bare_manager({7: {"history": [{"role": "user", "parts": ["swear word"]}]}})
        with patch("cogs.ai_core.logic.save_history", AsyncMock()) as mock_save:
            result = await cm.replace_message_text_in_history(7, 55, "swear word", "nice word")

        assert result is False
        assert cm.chats[7]["history"][0]["parts"] == ["swear word"]
        mock_save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_dict_parts(self):
        cm = _bare_manager(
            {7: {"history": [{"role": "model", "parts": [{"text": "bad word"}], "message_id": 10}]}}
        )
        with patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=1)):
            await cm.replace_message_text_in_history(7, 10, "bad word", "good word")

        assert cm.chats[7]["history"][0]["parts"] == [{"text": "good word"}]

    @pytest.mark.asyncio
    async def test_drops_the_compress_cache(self):
        """An in-place edit leaves the history LENGTH unchanged, so the
        length-keyed cache would keep serving the pre-edit compression."""
        cm = _bare_manager(
            {
                7: {
                    "history": [{"role": "model", "parts": ["old"], "message_id": 10}],
                    "_compress_cache": {"src_len": 1, "history": []},
                }
            }
        )
        with patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=1)):
            await cm.replace_message_text_in_history(7, 10, "old", "new")

        assert "_compress_cache" not in cm.chats[7]

    @pytest.mark.asyncio
    async def test_drops_the_cli_session(self):
        """On the default cli backend a resumed turn sends only the new message,
        so the server-side session keeps the pre-edit text unless dropped."""
        cm = _bare_manager(
            {7: {"history": [{"role": "model", "parts": ["old"], "message_id": 10}]}}
        )
        with (
            patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=1)),
            patch.object(cm, "_drop_cli_session_after_history_mutation") as mock_drop,
        ):
            await cm.replace_message_text_in_history(7, 10, "old", "new")

        mock_drop.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_no_match_changes_nothing(self):
        cm = _bare_manager({7: {"history": [{"role": "model", "parts": ["hello"]}]}})
        with patch("cogs.ai_core.logic.save_history", AsyncMock()) as mock_save:
            result = await cm.replace_message_text_in_history(7, 55, "absent", "x")

        assert result is False
        mock_save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_when_text_is_unchanged(self):
        cm = _bare_manager({7: {"history": [{"role": "model", "parts": ["same"]}]}})
        assert await cm.replace_message_text_in_history(7, 55, "same", "same") is False

    @pytest.mark.asyncio
    async def test_session_not_loaded(self):
        cm = _bare_manager({})
        assert await cm.replace_message_text_in_history(7, 55, "old", "new") is False


class TestDeleteMirroringAcrossMultiMessageTurns:
    """A turn that went out as several Discord messages must lose only the
    deleted one — dropping the whole row would forget lines still on screen,
    and doing nothing (the old behaviour) leaves the model quoting a message
    that no longer exists."""

    @staticmethod
    def _rp_session():
        return {
            7: {
                "history": [
                    {
                        "role": "model",
                        "parts": ["{{ซออา}} บทหนึ่ง\n{{แชวอน}} บทสอง"],
                        "message_id": 12,
                        "sent_message_ids": [
                            {"name": "ซออา", "id": 11},
                            {"name": "แชวอน", "id": 12},
                        ],
                    }
                ]
            }
        }

    @pytest.mark.asyncio
    async def test_row_survives_when_other_messages_remain(self):
        cm = _bare_manager(self._rp_session())
        with (
            patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=0)),
            patch("cogs.ai_core.logic.save_history", AsyncMock(return_value=True)) as mock_save,
        ):
            result = await cm.remove_message_from_history(7, 11, "บทหนึ่ง")

        assert result is True
        (row,) = cm.chats[7]["history"]
        assert "บทหนึ่ง" not in row["parts"][0]
        assert "{{ซออา}}" not in row["parts"][0]  # the label went with its line
        assert "{{แชวอน}} บทสอง" in row["parts"][0]
        assert row["sent_message_ids"] == [{"name": "แชวอน", "id": 12}]
        assert mock_save.await_args.kwargs["force"] is True

    @pytest.mark.asyncio
    async def test_dead_id_leaves_the_list_even_without_cached_text(self):
        """MESSAGE_DELETE carries no content. With nothing cached we still stop
        advertising an id that now 404s, rather than guessing which line to cut."""
        cm = _bare_manager(self._rp_session())
        with (
            patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=0)),
            patch("cogs.ai_core.logic.save_history", AsyncMock(return_value=True)),
        ):
            assert await cm.remove_message_from_history(7, 11) is True

        (row,) = cm.chats[7]["history"]
        assert row["sent_message_ids"] == [{"name": "แชวอน", "id": 12}]
        assert "บทหนึ่ง" in row["parts"][0]  # untouched — we could not identify it

    @pytest.mark.asyncio
    async def test_headline_id_repoints_at_a_surviving_message(self):
        """message_id is what the DB column and the mirroring paths key on; if
        the deleted message owned it, it has to move or the row goes dark."""
        cm = _bare_manager(self._rp_session())
        with (
            patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=0)),
            patch("cogs.ai_core.logic.save_history", AsyncMock(return_value=True)),
        ):
            await cm.remove_message_from_history(7, 12, "บทสอง")

        (row,) = cm.chats[7]["history"]
        assert row["message_id"] == 11

    @pytest.mark.asyncio
    async def test_last_remaining_message_drops_the_row(self):
        cm = _bare_manager(
            {
                7: {
                    "history": [
                        {
                            "role": "model",
                            "parts": ["only line"],
                            "message_id": 11,
                            "sent_message_ids": [{"name": "ซออา", "id": 11}],
                        }
                    ]
                }
            }
        )
        with patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=1)):
            assert await cm.remove_message_from_history(7, 11) is True

        assert cm.chats[7]["history"] == []

    @pytest.mark.asyncio
    async def test_plain_row_still_drops_whole(self):
        """Unchanged behaviour for the ordinary one-message-per-row case."""
        cm = _bare_manager(
            {
                7: {
                    "history": [
                        {"role": "user", "parts": ["hi"], "message_id": 10},
                        {"role": "model", "parts": ["hello"], "message_id": 11},
                    ]
                }
            }
        )
        with patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=1)):
            assert await cm.remove_message_from_history(7, 10) is True

        assert [i["message_id"] for i in cm.chats[7]["history"]] == [11]

    @pytest.mark.asyncio
    async def test_patch_drops_the_compress_cache(self):
        cm = _bare_manager(self._rp_session())
        cm.chats[7]["_compress_cache"] = {"src_len": 1, "history": []}
        with (
            patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=0)),
            patch("cogs.ai_core.logic.save_history", AsyncMock(return_value=True)),
        ):
            await cm.remove_message_from_history(7, 11, "บทหนึ่ง")

        assert "_compress_cache" not in cm.chats[7]

    @pytest.mark.asyncio
    async def test_unrelated_delete_touches_nothing(self):
        cm = _bare_manager(self._rp_session())
        with (
            patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=0)),
            patch("cogs.ai_core.logic.save_history", AsyncMock()) as mock_save,
        ):
            assert await cm.remove_message_from_history(7, 999, "nope") is False

        assert len(cm.chats[7]["history"]) == 1
        mock_save.assert_not_awaited()


class TestRemoveMessageFragment:
    @pytest.mark.parametrize(
        ("text", "fragment", "expected"),
        [
            ("{{A}} one\n{{B}} two", "one", "{{B}} two"),
            ("{{A}} one\n{{B}} two", "two", "{{A}} one"),
            ("narration\n{{A}} one\n{{B}} two", "one", "narration\n{{B}} two"),
            ("plain reply", "plain reply", ""),
            ("{{A}} one", "absent", "{{A}} one"),
        ],
    )
    def test_cuts_the_line_and_its_label(self, text, fragment, expected):
        from cogs.ai_core.logic import _remove_message_fragment

        assert _remove_message_fragment(text, fragment) == expected


class TestCmdEditMessageMirrorsIntoHistory:
    """on_raw_message_edit skips anything the bot authored, so without this the
    AI would fix the text in Discord and keep the original in its memory."""

    @staticmethod
    def _origin(guild):
        origin = MagicMock(spec=discord.TextChannel)
        origin.id = 4242
        origin.guild = guild
        origin.send = AsyncMock()
        return origin

    @pytest.mark.asyncio
    async def test_bot_owned_edit_is_mirrored(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        msg = MagicMock()
        msg.author = bot
        msg.content = "old text"
        msg.edit = AsyncMock()
        origin = self._origin(guild)
        origin.fetch_message = AsyncMock(return_value=msg)

        manager = MagicMock()
        manager.replace_message_text_in_history = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.chat_manager_registry.get_chat_manager", return_value=manager):
            await cmd_edit_message(None, origin, None, ["123", "new text"])

        msg.edit.assert_awaited_once_with(content="new text")
        manager.replace_message_text_in_history.assert_awaited_once_with(
            4242, 123, "old text", "new text"
        )

    @pytest.mark.asyncio
    async def test_webhook_edit_is_mirrored(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        bot.id = 7
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        msg = MagicMock()
        msg.author = MagicMock()
        msg.webhook_id = 55
        msg.content = "ยาวชิบหาย"
        webhook = MagicMock()
        webhook.id = 55
        webhook.user.id = 7
        webhook.edit_message = AsyncMock()
        origin = self._origin(guild)
        origin.fetch_message = AsyncMock(return_value=msg)
        origin.webhooks = AsyncMock(return_value=[webhook])

        manager = MagicMock()
        manager.replace_message_text_in_history = AsyncMock(return_value=True)
        with patch("cogs.ai_core.api.chat_manager_registry.get_chat_manager", return_value=manager):
            await cmd_edit_message(None, origin, None, ["123", "ยาวเป็นชาติ"])

        webhook.edit_message.assert_awaited_once_with(123, content="ยาวเป็นชาติ")
        manager.replace_message_text_in_history.assert_awaited_once_with(
            4242, 123, "ยาวชิบหาย", "ยาวเป็นชาติ"
        )

    @pytest.mark.asyncio
    async def test_a_rejected_edit_is_not_mirrored(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        bot.id = 7
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        msg = MagicMock()
        msg.author = MagicMock()
        msg.webhook_id = None
        msg.content = "someone else's message"
        origin = self._origin(guild)
        origin.fetch_message = AsyncMock(return_value=msg)

        manager = MagicMock()
        manager.replace_message_text_in_history = AsyncMock()
        with patch("cogs.ai_core.api.chat_manager_registry.get_chat_manager", return_value=manager):
            await cmd_edit_message(None, origin, None, ["123", "new"])

        manager.replace_message_text_in_history.assert_not_awaited()
        assert "ไม่ใช่ของบอท" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_mirror_failure_does_not_fail_the_edit(self):
        """The Discord edit has already committed — an unavailable session or a
        trimmed history must not be reported to the user as a failed edit."""
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        msg = MagicMock()
        msg.author = bot
        msg.content = "old"
        msg.edit = AsyncMock()
        origin = self._origin(guild)
        origin.fetch_message = AsyncMock(return_value=msg)

        manager = MagicMock()
        manager.replace_message_text_in_history = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("cogs.ai_core.api.chat_manager_registry.get_chat_manager", return_value=manager):
            await cmd_edit_message(None, origin, None, ["123", "new"])

        msg.edit.assert_awaited_once()
        # Nothing failure-shaped posted to the channel.
        assert origin.send.await_count == 0

    @pytest.mark.asyncio
    async def test_no_live_cog_is_tolerated(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        msg = MagicMock()
        msg.author = bot
        msg.content = "old"
        msg.edit = AsyncMock()
        origin = self._origin(guild)
        origin.fetch_message = AsyncMock(return_value=msg)

        with patch("cogs.ai_core.api.chat_manager_registry.get_chat_manager", return_value=None):
            await cmd_edit_message(None, origin, None, ["123", "new"])

        msg.edit.assert_awaited_once()
