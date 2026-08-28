# pylint: disable=protected-access
"""Regression tests: the Discord CLI backend cannot carry inline images.

``discord_chat_claude_cli._flatten_contents_to_prompt`` turns the whole turn
into one text prompt and replaces every ``inline_data`` part with
``[attachment omitted: …]``. Everything that produced those parts was still
running on every turn — the avatar download + PIL decode, custom-emoji image
fetches, the character-reference decode, each attachment's download/decode, an
animated GIF's ffmpeg encode, then a PNG encode + base64 in
``pil_to_inline_data`` — all for bytes the prompt discards.

Worse, the plain-text LABELS that introduce those images survive the flattening,
so the model was told to look at a profile picture that never arrived.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestFlattenerReallyDropsInlineImages:
    """The premise the gate is built on — asserted, not assumed."""

    def test_inline_data_becomes_a_placeholder(self):
        from cogs.ai_core.api.discord_chat_claude_cli import _flatten_contents_to_prompt

        prompt = _flatten_contents_to_prompt(
            [
                {
                    "role": "user",
                    "parts": [
                        {"text": "[System Notice: profile picture follows]"},
                        {"inline_data": {"mime_type": "image/png", "data": "AAAA"}},
                    ],
                }
            ],
            "persona",
        )
        assert "[attachment omitted: image/png]" in prompt
        assert "AAAA" not in prompt


class TestProcessAttachmentsImageGate:
    @staticmethod
    def _image_attachment():
        att = MagicMock()
        att.content_type = "image/png"
        att.filename = "photo.png"
        att.size = 1024
        att.read = AsyncMock(return_value=b"not-really-png")
        return att

    @pytest.mark.asyncio
    async def test_image_is_not_downloaded_when_the_backend_drops_it(self):
        from cogs.ai_core.media_processor import process_attachments

        att = self._image_attachment()
        image_parts, video_parts, text_parts = await process_attachments(
            [att], "TestUser", include_images=False
        )

        att.read.assert_not_awaited()
        assert image_parts == []
        assert video_parts == []
        assert len(text_parts) == 1
        assert "photo.png" in text_parts[0]
        assert "cannot view images" in text_parts[0]

    @pytest.mark.asyncio
    async def test_default_still_processes_images(self):
        """Backends that DO carry images must be untouched by the gate."""
        import io

        from PIL import Image

        from cogs.ai_core.media_processor import process_attachments

        buf = io.BytesIO()
        Image.new("RGB", (4, 4), color="red").save(buf, format="PNG")
        att = self._image_attachment()
        att.read = AsyncMock(return_value=buf.getvalue())

        image_parts, _video_parts, text_parts = await process_attachments([att], "TestUser")

        att.read.assert_awaited()
        assert len(image_parts) == 1
        assert text_parts == []
        for img in image_parts:
            img.close()

    @pytest.mark.asyncio
    async def test_text_attachments_are_unaffected_by_the_gate(self):
        """Text files flatten into the prompt fine — only pixels are dropped."""
        from cogs.ai_core.media_processor import process_attachments

        att = MagicMock()
        att.content_type = "text/plain"
        att.filename = "notes.txt"
        att.size = 5
        att.read = AsyncMock(return_value=b"hello")

        _images, _videos, text_parts = await process_attachments(
            [att], "TestUser", include_images=False
        )

        assert len(text_parts) == 1
        assert "hello" in text_parts[0]


class TestChatManagerCapability:
    @staticmethod
    def _manager():
        from cogs.ai_core.logic import ChatManager

        return ChatManager(MagicMock())

    def test_cli_backend_does_not_accept_inline_images(self):
        cm = self._manager()
        cm.cli_mode = True
        assert cm.accepts_inline_images() is False

    def test_sdk_backend_accepts_inline_images(self):
        cm = self._manager()
        cm.cli_mode = False
        assert cm.accepts_inline_images() is True

    @pytest.mark.asyncio
    async def test_wrapper_forwards_the_capability(self):
        from unittest.mock import patch

        cm = self._manager()
        cm.cli_mode = True
        with patch(
            "cogs.ai_core.logic.process_attachments", new=AsyncMock(return_value=([], [], []))
        ) as proc:
            await cm._process_attachments([MagicMock()], "TestUser")
        assert proc.await_args.kwargs["include_images"] is False


class TestProcessChatSkipsImageWorkOnTheCliBackend:
    """End-to-end: the whole image pipeline is skipped, labels included."""

    @staticmethod
    def _manager(cli_mode: bool):
        from unittest.mock import patch

        from cogs.ai_core.logic import ChatManager

        with patch.object(ChatManager, "setup_ai"):
            mgr = ChatManager(MagicMock())
        mgr.client = MagicMock()
        mgr.cli_mode = cli_mode
        mgr.get_chat_session = AsyncMock(return_value={"history": []})
        mgr._build_api_config = MagicMock(return_value={})
        mgr._call_gemini_api = AsyncMock(return_value=("reply", "", []))
        mgr.is_streaming_enabled = MagicMock(return_value=False)
        mgr._process_response_text = MagicMock(return_value="reply")
        mgr._maybe_track_feedback = AsyncMock()

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

    async def _run(self, monkeypatch, *, cli_mode: bool):
        from unittest.mock import patch

        from cogs.ai_core import logic as logic_mod

        mgr, channel, user = self._manager(cli_mode)
        avatar = AsyncMock(return_value=None)
        char_image = MagicMock(return_value=None)
        emoji_fetch = AsyncMock(return_value=[])

        monkeypatch.setattr(logic_mod, "save_history", AsyncMock(return_value=True))
        monkeypatch.setattr(logic_mod, "update_message_id", AsyncMock())
        monkeypatch.setattr(logic_mod.rag_system, "search_memory", AsyncMock(return_value=[]))
        monkeypatch.setattr(logic_mod.entity_memory, "get_all_entities", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            type(logic_mod.memory_consolidator), "enabled", property(lambda _self: False)
        )
        monkeypatch.setattr(logic_mod, "fetch_emoji_images", emoji_fetch)

        with (
            patch.object(type(mgr), "_prepare_user_avatar", avatar),
            patch.object(type(mgr), "_load_character_image", char_image),
        ):
            await mgr.process_chat(channel, user, "ดูอันนี้สิ <:smile:123>")
        return avatar, char_image, emoji_fetch

    @pytest.mark.asyncio
    async def test_cli_backend_skips_avatar_character_and_emoji_images(self, monkeypatch):
        avatar, char_image, emoji_fetch = await self._run(monkeypatch, cli_mode=True)
        avatar.assert_not_awaited()
        char_image.assert_not_called()
        emoji_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sdk_backend_still_does_all_of_it(self, monkeypatch):
        avatar, char_image, emoji_fetch = await self._run(monkeypatch, cli_mode=False)
        avatar.assert_awaited()
        char_image.assert_called()
        emoji_fetch.assert_awaited()
