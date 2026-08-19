"""
Tests for cogs/ai_core/session_mixin.py

Comprehensive tests for SessionMixin class.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetChatSession:
    """Tests for get_chat_session method."""

    @pytest.mark.asyncio
    async def test_returns_none_without_client(self):
        """Test returns None when client is not initialized."""
        from cogs.ai_core.session_mixin import SessionMixin

        # Create a class that uses the mixin
        class TestClass(SessionMixin):
            def __init__(self):
                self.client = None
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

        instance = TestClass()
        result = await instance.get_chat_session(12345)
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_new_session(self):
        """Test creates new session if not exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000  # Required for _enforce_channel_limit

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                """Stub for LRU eviction."""
                return 0

        instance = TestClass()

        with patch(
            "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock
        ) as mock_load_history:
            with patch(
                "cogs.ai_core.session_mixin.load_metadata", new_callable=AsyncMock
            ) as mock_load_metadata:
                mock_load_history.return_value = []
                mock_load_metadata.return_value = {"thinking_enabled": True}

                result = await instance.get_chat_session(12345)

                assert result is not None
                assert "history" in result
                assert "system_instruction" in result
                assert 12345 in instance.chats

    @pytest.mark.asyncio
    async def test_returns_cached_session(self):
        """Test returns cached session if exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [{"role": "user", "parts": ["Hello"]}],
                        "system_instruction": "[Private Creative Session] Test",
                        "thinking_enabled": True,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                return 0

        instance = TestClass()
        result = await instance.get_chat_session(12345)

        assert result is not None
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_updates_last_accessed(self):
        """Test updates last_accessed timestamp."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [],
                        "system_instruction": "[Private Creative Session] Test",
                        "thinking_enabled": True,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                return 0

        instance = TestClass()
        before_time = time.time()
        await instance.get_chat_session(12345)
        after_time = time.time()

        assert 12345 in instance.last_accessed
        assert before_time <= instance.last_accessed[12345] <= after_time


class TestSaveAllSessions:
    """Tests for save_all_sessions method."""

    @pytest.mark.asyncio
    async def test_saves_all_sessions(self):
        """Test saves all sessions."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    111: {"history": [], "system_instruction": "Test"},
                    222: {"history": [], "system_instruction": "Test"},
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

        instance = TestClass()

        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock) as mock_save:
            await instance.save_all_sessions()

            assert mock_save.call_count == 2


class TestToggleThinking:
    """Tests for toggle_thinking method."""

    @pytest.mark.asyncio
    async def test_toggle_thinking_enabled(self):
        """Test enabling thinking mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [],
                        "system_instruction": "[Private Creative Session] Test",
                        "thinking_enabled": False,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                return 0

        instance = TestClass()

        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock):
            result = await instance.toggle_thinking(12345, True)

            assert result is True
            assert instance.chats[12345]["thinking_enabled"] is True

    @pytest.mark.asyncio
    async def test_toggle_thinking_disabled(self):
        """Test disabling thinking mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {
                    12345: {
                        "history": [],
                        "system_instruction": "[Private Creative Session] Test",
                        "thinking_enabled": True,
                    }
                }
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                return 0

        instance = TestClass()

        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock):
            result = await instance.toggle_thinking(12345, False)

            assert result is True
            assert instance.chats[12345]["thinking_enabled"] is False

    @pytest.mark.asyncio
    async def test_toggle_thinking_no_session(self):
        """Test toggle_thinking when no session exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.client = None  # No client
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

        instance = TestClass()

        result = await instance.toggle_thinking(12345, True)

        assert result is False


class TestToggleStreaming:
    """Tests for toggle_streaming method."""

    def test_toggle_streaming_enabled(self):
        """Test enabling streaming mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {}

        instance = TestClass()

        result = instance.toggle_streaming(12345, True)

        assert result is True
        assert instance.streaming_enabled[12345] is True

    def test_toggle_streaming_disabled(self):
        """Test disabling streaming mode."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {12345: True}

        instance = TestClass()

        result = instance.toggle_streaming(12345, False)

        assert result is True
        assert instance.streaming_enabled[12345] is False


class TestIsStreamingEnabled:
    """Tests for is_streaming_enabled method."""

    def test_is_streaming_enabled_true(self):
        """Test returns True when streaming is enabled."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {12345: True}

        instance = TestClass()

        result = instance.is_streaming_enabled(12345)

        assert result is True

    def test_is_streaming_enabled_false(self):
        """Test returns False when streaming is disabled."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {12345: False}

        instance = TestClass()

        result = instance.is_streaming_enabled(12345)

        assert result is False

    def test_is_streaming_enabled_default(self):
        """Test returns False by default when not set."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.streaming_enabled = {}

        instance = TestClass()

        result = instance.is_streaming_enabled(99999)

        assert result is False


class TestCleanupInactiveSessions:
    """Tests for cleanup_inactive_sessions method."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_sessions(self):
        """Test cleanup removes old sessions."""
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.bot.is_closed = MagicMock(return_value=True)  # Stop loop immediately
                # Inactive session (old timestamp)
                old_time = time.time() - 7200  # 2 hours ago
                self.chats = {
                    12345: {"history": [], "system_instruction": "Test"},
                }
                self.last_accessed = {12345: old_time}
                self.seen_users = {12345: set()}
                self.processing_locks = {12345: asyncio.Lock()}
                self.pending_messages = {12345: []}
                self.cancel_flags = {12345: False}
                self.streaming_enabled = {}

        instance = TestClass()

        # The method runs in a loop, so we need to mock it to run once
        # Since bot.is_closed() returns True, it should exit immediately
        with patch("cogs.ai_core.session_mixin.save_history", new_callable=AsyncMock):
            # Just verify the method exists and runs
            await instance.cleanup_inactive_sessions()


class TestSessionMixinClass:
    """Tests for SessionMixin class structure."""

    def test_class_exists(self):
        """Test SessionMixin class exists."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert SessionMixin is not None

    def test_has_get_chat_session(self):
        """Test has get_chat_session method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "get_chat_session")

    def test_has_save_all_sessions(self):
        """Test has save_all_sessions method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "save_all_sessions")

    def test_has_cleanup_inactive_sessions(self):
        """Test has cleanup_inactive_sessions method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "cleanup_inactive_sessions")

    def test_has_toggle_thinking(self):
        """Test has toggle_thinking method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "toggle_thinking")

    def test_has_toggle_streaming(self):
        """Test has toggle_streaming method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "toggle_streaming")

    def test_has_is_streaming_enabled(self):
        """Test has is_streaming_enabled method."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert hasattr(SessionMixin, "is_streaming_enabled")


class TestModuleImports:
    """Tests for module imports."""

    def test_import_session_mixin(self):
        """Test SessionMixin can be imported."""
        from cogs.ai_core.session_mixin import SessionMixin

        assert SessionMixin is not None


class TestRoleplayAndUnrestrictedWiring:
    """FAUST_ROLEPLAY (Discord-guild-only) and CLAUDE2.md (Discord !unrestricted) wiring."""

    def _make_instance(self):
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                return 0

        return TestClass()

    @pytest.mark.asyncio
    async def test_guild_channel_appends_faust_roleplay(self):
        """A non-RP Discord guild channel gets FAUST_ROLEPLAY appended to the persona."""
        instance = self._make_instance()
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.GUILD_ID_RP", 1),
            patch("cogs.ai_core.session_mixin.FAUST_INSTRUCTION", "FAUST_BASE"),
            patch("cogs.ai_core.session_mixin.FAUST_ROLEPLAY", "RP_FORMAT_RULES"),
        ):
            result = await instance.get_chat_session(100, guild_id=2)  # non-RP guild
        assert "FAUST_BASE" in result["system_instruction"]
        assert "RP_FORMAT_RULES" in result["system_instruction"]

    @pytest.mark.asyncio
    async def test_dm_does_not_append_faust_roleplay(self):
        """A DM (guild_id None) keeps plain FAUST_INSTRUCTION — no roleplay actions."""
        instance = self._make_instance()
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.GUILD_ID_RP", 1),
            patch("cogs.ai_core.session_mixin.FAUST_INSTRUCTION", "FAUST_BASE"),
            patch("cogs.ai_core.session_mixin.FAUST_ROLEPLAY", "RP_FORMAT_RULES"),
        ):
            result = await instance.get_chat_session(101)  # DM: guild_id defaults to None
        assert "FAUST_BASE" in result["system_instruction"]
        assert "RP_FORMAT_RULES" not in result["system_instruction"]

    @pytest.mark.asyncio
    async def test_rp_server_uses_roleplay_world_not_faust_roleplay(self):
        """The RP server still uses ROLEPLAY_ASSISTANT_INSTRUCTION, not FAUST_ROLEPLAY."""
        instance = self._make_instance()
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.GUILD_ID_RP", 1),
            patch("cogs.ai_core.session_mixin.ROLEPLAY_ASSISTANT_INSTRUCTION", "RP_WORLD"),
            patch("cogs.ai_core.session_mixin.FAUST_ROLEPLAY", "RP_FORMAT_RULES"),
        ):
            result = await instance.get_chat_session(102, guild_id=1)  # RP server
        assert "RP_WORLD" in result["system_instruction"]
        assert "RP_FORMAT_RULES" not in result["system_instruction"]

    @pytest.mark.asyncio
    async def test_unrestricted_injects_discord_sandbox_text(self):
        """When a channel is unrestricted, the CLAUDE2.md override is prepended."""
        instance = self._make_instance()
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.FAUST_INSTRUCTION", "FAUST_BASE"),
            patch(
                "cogs.ai_core.api.dashboard_config.resolve_unrestricted_system_text",
                return_value="SANDBOX_TEXT",
            ),
            patch("cogs.ai_core.session_mixin.is_unrestricted", return_value=True),
        ):
            result = await instance.get_chat_session(103)
        # The override is now wrapped in stable sentinel markers (so a live
        # CLAUDE2.md edit can be detected/removed as a whole block) and prepended
        # ahead of the base persona.
        instruction = result["system_instruction"]
        assert "SANDBOX_TEXT" in instruction
        assert "FAUST_BASE" in instruction
        assert instruction.index("SANDBOX_TEXT") < instruction.index("FAUST_BASE")

    @pytest.mark.asyncio
    async def test_cli_mode_skips_unrestricted_body_injection(self):
        """Under CLAUDE_BACKEND=cli the body injection is skipped — the CLI path
        applies CLAUDE2.md via --system-prompt-file instead, so injecting it
        into the body too would duplicate the whole override every turn."""
        instance = self._make_instance()
        instance.cli_mode = True
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.FAUST_INSTRUCTION", "FAUST_BASE"),
            patch(
                "cogs.ai_core.api.dashboard_config.resolve_unrestricted_system_text",
                return_value="SANDBOX_TEXT",
            ),
            patch("cogs.ai_core.session_mixin.is_unrestricted", return_value=True),
        ):
            result = await instance.get_chat_session(104)
        assert "SANDBOX_TEXT" not in result["system_instruction"]
        assert "FAUST_BASE" in result["system_instruction"]

    @pytest.mark.asyncio
    async def test_unrestricted_disable_strips_stale_block_after_claude2_edit(self):
        """Disabling unrestricted mode strips the whole injected block even if
        CLAUDE2.md was edited (resolved text changed) since it was injected.

        Regression: injection used to key on the CURRENT resolved text, so if
        CLAUDE2.md changed between enable (text A) and disable (text B), the
        disable path checked "B in instruction" -> False and stripped nothing,
        leaving stale text A wedged in the system prompt (and persisted) forever.
        """
        instance = self._make_instance()
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.FAUST_INSTRUCTION", "FAUST_BASE"),
            patch(
                "cogs.ai_core.api.dashboard_config.resolve_unrestricted_system_text"
            ) as mock_resolve,
            patch("cogs.ai_core.session_mixin.is_unrestricted") as mock_unrestricted,
        ):
            # Enable with text A.
            mock_resolve.return_value = "OVERRIDE_TEXT_A"
            mock_unrestricted.return_value = True
            result = await instance.get_chat_session(200)
            assert "OVERRIDE_TEXT_A" in result["system_instruction"]

            # CLAUDE2.md edited between inject and remove -> resolver returns text B.
            mock_resolve.return_value = "OVERRIDE_TEXT_B"
            mock_unrestricted.return_value = False
            result = await instance.get_chat_session(200)

        instruction = result["system_instruction"]
        assert "OVERRIDE_TEXT_A" not in instruction  # stale block fully removed
        assert "OVERRIDE_TEXT_B" not in instruction
        assert "FAUST_BASE" in instruction

    @pytest.mark.asyncio
    async def test_unrestricted_reinject_after_edit_does_not_stack(self):
        """A live CLAUDE2.md edit while unrestricted stays ON refreshes the block
        in place instead of stacking a second copy.

        Regression: keying on the current text meant "B in instruction" -> False
        while an older A block was present, so B was prepended too and BOTH the
        stale and the new override ended up in the system prompt.
        """
        instance = self._make_instance()
        with (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
            patch("cogs.ai_core.session_mixin.FAUST_INSTRUCTION", "FAUST_BASE"),
            patch(
                "cogs.ai_core.api.dashboard_config.resolve_unrestricted_system_text"
            ) as mock_resolve,
            patch("cogs.ai_core.session_mixin.is_unrestricted", return_value=True),
        ):
            mock_resolve.return_value = "OVERRIDE_TEXT_A"
            await instance.get_chat_session(201)
            mock_resolve.return_value = "OVERRIDE_TEXT_B"
            result = await instance.get_chat_session(201)

        instruction = result["system_instruction"]
        assert "OVERRIDE_TEXT_A" not in instruction  # old text refreshed out
        assert instruction.count("OVERRIDE_TEXT_B") == 1  # exactly one block, no stacking
        assert "FAUST_BASE" in instruction


class TestServerLoreCap:
    """MAX_SERVER_LORE_CHARS — the env knob that replaced a hard-coded 20000.

    The old constant was cutting a real 50,723-char RP lore down by 60%,
    mid-sentence, on every session creation, and announcing it only as a log
    WARNING. Both injection sites (cache-miss and RP cache-fixup) now share
    one helper so they cannot drift apart on the ceiling again.
    """

    def _make_instance(self):
        from cogs.ai_core.session_mixin import SessionMixin

        class TestClass(SessionMixin):
            MAX_CHANNELS = 1000

            def __init__(self):
                self.client = MagicMock()
                self.bot = MagicMock()
                self.chats = {}
                self.last_accessed = {}
                self.seen_users = {}
                self.processing_locks = {}
                self.pending_messages = {}
                self.cancel_flags = {}
                self.streaming_enabled = {}

            def _enforce_channel_limit(self):
                return 0

        return TestClass()

    def _storage_patches(self):
        return (
            patch(
                "cogs.ai_core.session_mixin.load_history", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "cogs.ai_core.session_mixin.load_metadata",
                new_callable=AsyncMock,
                return_value={"thinking_enabled": True},
            ),
        )

    # ---------- the env knob itself ----------

    def test_default_is_raised_above_the_old_hardcoded_20000(self):
        """Env-isolated: env.example invites operators to SET this, and a suite
        that fails on a legal configuration trains people to ignore it."""
        import os

        from cogs.ai_core import session_mixin as sm

        env = {k: v for k, v in os.environ.items() if k != "MAX_SERVER_LORE_CHARS"}
        with patch.dict(os.environ, env, clear=True):
            assert sm._max_lore_chars_from_env() == 60_000

    def test_env_override(self):
        import os

        from cogs.ai_core import session_mixin as sm

        with patch.dict(os.environ, {"MAX_SERVER_LORE_CHARS": "125000"}):
            assert sm._max_lore_chars_from_env() == 125_000

    def test_zero_means_no_cap(self):
        import os

        from cogs.ai_core import session_mixin as sm

        with patch.dict(os.environ, {"MAX_SERVER_LORE_CHARS": "0"}):
            assert sm._max_lore_chars_from_env() == 0

    def test_negative_clamps_to_zero(self):
        import os

        from cogs.ai_core import session_mixin as sm

        with patch.dict(os.environ, {"MAX_SERVER_LORE_CHARS": "-5"}):
            assert sm._max_lore_chars_from_env() == 0

    def test_garbage_falls_back_to_default(self):
        import os

        from cogs.ai_core import session_mixin as sm

        with patch.dict(os.environ, {"MAX_SERVER_LORE_CHARS": "twenty"}):
            assert sm._max_lore_chars_from_env() == 60_000
        with patch.dict(os.environ, {"MAX_SERVER_LORE_CHARS": "   "}):
            assert sm._max_lore_chars_from_env() == 60_000

    # ---------- the resolver ----------

    def test_missing_guild_and_dm_resolve_empty(self):
        from cogs.ai_core import session_mixin as sm

        with patch.object(sm, "SERVER_LORE", {7: "LORE"}):
            assert sm._resolve_server_lore(None) == ""
            assert sm._resolve_server_lore(0) == ""
            assert sm._resolve_server_lore(999) == ""

    def test_lore_under_cap_passes_through_whole(self):
        from cogs.ai_core import session_mixin as sm

        lore = "L" * 5_000
        with (
            patch.object(sm, "SERVER_LORE", {7: lore}),
            patch.object(sm, "_MAX_LORE_CHARS", 60_000),
        ):
            assert sm._resolve_server_lore(7) == lore

    def test_lore_over_cap_is_truncated_and_warned(self, caplog):
        from cogs.ai_core import session_mixin as sm

        lore = "L" * 5_000
        with (
            patch.object(sm, "SERVER_LORE", {7: lore}),
            patch.object(sm, "_MAX_LORE_CHARS", 100),
            caplog.at_level("WARNING"),
        ):
            out = sm._resolve_server_lore(7)
        assert out.startswith("L" * 100)
        assert "[... lore truncated ...]" in out
        assert "Truncated server lore for guild 7" in caplog.text
        assert "MAX_SERVER_LORE_CHARS" in caplog.text  # tells the operator the fix

    def test_zero_cap_sends_lore_whole(self):
        from cogs.ai_core import session_mixin as sm

        lore = "L" * 300_000
        with (
            patch.object(sm, "SERVER_LORE", {7: lore}),
            patch.object(sm, "_MAX_LORE_CHARS", 0),
        ):
            assert sm._resolve_server_lore(7) == lore

    def test_context_label_names_the_path(self, caplog):
        from cogs.ai_core import session_mixin as sm

        with (
            patch.object(sm, "SERVER_LORE", {7: "L" * 500}),
            patch.object(sm, "_MAX_LORE_CHARS", 10),
            caplog.at_level("WARNING"),
        ):
            sm._resolve_server_lore(7, context=" on cache fixup")
        assert "guild 7 on cache fixup" in caplog.text

    # ---------- both injection sites ----------

    @pytest.mark.asyncio
    async def test_cache_miss_path_injects_capped_lore(self):
        from cogs.ai_core import session_mixin as sm

        instance = self._make_instance()
        hist, meta = self._storage_patches()
        with (
            hist,
            meta,
            patch.object(sm, "GUILD_ID_RP", 1),
            patch.object(sm, "FAUST_INSTRUCTION", "FAUST_BASE"),
            patch.object(sm, "FAUST_ROLEPLAY", "FAUST_BASE"),
            patch.object(sm, "SERVER_LORE", {2: "WORLD" * 100}),
            patch.object(sm, "_MAX_LORE_CHARS", 50),
        ):
            result = await instance.get_chat_session(900, guild_id=2)
        instruction = result["system_instruction"]
        assert "FAUST_BASE" in instruction
        assert "[... lore truncated ...]" in instruction

    @pytest.mark.asyncio
    async def test_dm_gets_no_lore(self):
        from cogs.ai_core import session_mixin as sm

        instance = self._make_instance()
        hist, meta = self._storage_patches()
        with (
            hist,
            meta,
            patch.object(sm, "GUILD_ID_RP", 1),
            patch.object(sm, "FAUST_INSTRUCTION", "FAUST_BASE"),
            patch.object(sm, "SERVER_LORE", {2: "WORLD_LORE_TEXT"}),
            patch.object(sm, "is_unrestricted", return_value=False),
        ):
            result = await instance.get_chat_session(901)  # DM
        assert "WORLD_LORE_TEXT" not in result["system_instruction"]

    @pytest.mark.asyncio
    async def test_rp_cache_fixup_path_uses_the_same_cap(self):
        """A cached RP session corrected in place gets the same capped lore."""
        from cogs.ai_core import session_mixin as sm

        instance = self._make_instance()
        # Pre-seed a cached session missing the RP instruction so the
        # correction branch fires.
        instance.chats[902] = {
            "history": [],
            "system_instruction": "STALE_NON_RP_PERSONA",
            "thinking_enabled": True,
            "_db_loaded": False,
        }
        hist, meta = self._storage_patches()
        with (
            hist,
            meta,
            patch.object(sm, "GUILD_ID_RP", 1),
            patch.object(sm, "ROLEPLAY_ASSISTANT_INSTRUCTION", "RP_WORLD"),
            patch.object(sm, "SERVER_LORE", {1: "WORLD" * 100}),
            patch.object(sm, "_MAX_LORE_CHARS", 50),
            patch.object(sm, "is_unrestricted", return_value=False),
        ):
            result = await instance.get_chat_session(902, guild_id=1)
        instruction = result["system_instruction"]
        assert "RP_WORLD" in instruction
        assert "[... lore truncated ...]" in instruction
        # capped, not the full 500-char lore
        assert instruction.count("WORLD") <= 11

    @pytest.mark.asyncio
    async def test_session_keeps_the_lore_text_separately(self):
        """``server_lore`` lets the CLI path drop the block from resumed turns."""
        from cogs.ai_core import session_mixin as sm

        instance = self._make_instance()
        hist, meta = self._storage_patches()
        with (
            hist,
            meta,
            patch.object(sm, "GUILD_ID_RP", 1),
            patch.object(sm, "FAUST_INSTRUCTION", "FAUST_BASE"),
            patch.object(sm, "FAUST_ROLEPLAY", "FAUST_BASE"),
            patch.object(sm, "SERVER_LORE", {2: "WORLD_LORE_TEXT"}),
        ):
            result = await instance.get_chat_session(903, guild_id=2)
        assert result["server_lore"] == "WORLD_LORE_TEXT"
        # and it is exactly the tail of the instruction, so the CLI's exact-match
        # strip cannot drift from what was appended
        assert result["system_instruction"].endswith("\n\n" + "WORLD_LORE_TEXT")

    @pytest.mark.asyncio
    async def test_dm_session_has_empty_server_lore(self):
        from cogs.ai_core import session_mixin as sm

        instance = self._make_instance()
        hist, meta = self._storage_patches()
        with (
            hist,
            meta,
            patch.object(sm, "GUILD_ID_RP", 1),
            patch.object(sm, "FAUST_INSTRUCTION", "FAUST_BASE"),
            patch.object(sm, "SERVER_LORE", {2: "WORLD_LORE_TEXT"}),
            patch.object(sm, "is_unrestricted", return_value=False),
        ):
            result = await instance.get_chat_session(904)
        assert result["server_lore"] == ""
