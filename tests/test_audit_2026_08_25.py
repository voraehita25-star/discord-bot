"""Regression tests for the 2026-08-25 full-repo audit.

Each class pins ONE confirmed finding. The docstrings state the behaviour
observed BEFORE the fix so a change that reintroduces it fails loudly instead
of quietly reverting the guarantee.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.ai_core.ai_cog as ai_cog_mod
from cogs.ai_core.api.dashboard_common import apply_search_replace
from cogs.ai_core.logic import MAX_CHARACTER_BLOCKS


class TestSearchReplaceTerminatorAnchoring:
    """A ``>>>`` inside a REPLACE body used to truncate the patch silently.

    The block terminators were unanchored (``\\n?>>>``), so the lazy body group
    ended at the FIRST ``>>>`` anywhere in the reply — including a markdown deep
    quote or a mid-line arrow. apply_search_replace then reported success and
    the truncated body was persisted over the user's message with no log line.
    """

    def test_deep_quote_in_replace_body_survives(self):
        result = apply_search_replace(
            "alpha\nbeta\ngamma",
            "<<<SEARCH\nbeta\n>>>\n<<<REPLACE\n>>> arrow\n>>>",
        )
        # Previously: 'alpha\n\ngamma' — the body was cut to "" and beta deleted.
        assert result == "alpha\n>>> arrow\ngamma"

    def test_multiline_body_with_blockquote_keeps_every_line(self):
        result = apply_search_replace(
            "quoted:\nplaceholder",
            "<<<SEARCH\nplaceholder\n>>>\n<<<REPLACE\nline one\n>>> deeper quote\nmore after\n>>>",
        )
        assert result == "quoted:\nline one\n>>> deeper quote\nmore after"

    def test_midline_arrow_is_not_a_terminator(self):
        result = apply_search_replace(
            "x\nold\ny",
            "<<<SEARCH\nold\n>>>\n<<<REPLACE\nabc >>> def\n>>>",
        )
        assert result == "x\nabc >>> def\ny"

    def test_wellformed_single_and_multi_patch_still_apply(self):
        assert (
            apply_search_replace(
                "alpha\nbeta\ngamma", "<<<SEARCH\nbeta\n>>>\n<<<REPLACE\nBETA\n>>>"
            )
            == "alpha\nBETA\ngamma"
        )
        assert (
            apply_search_replace(
                "one\ntwo\nthree",
                "<<<SEARCH\none\n>>>\n<<<REPLACE\n1\n>>>\n<<<SEARCH\nthree\n>>>\n<<<REPLACE\n3\n>>>",
            )
            == "1\ntwo\n3"
        )

    def test_no_blocks_is_still_a_full_rewrite(self):
        assert apply_search_replace("old text", "a clean full rewrite") == "a clean full rewrite"

    def test_unmatched_search_preserves_original(self):
        assert (
            apply_search_replace(
                "nothing useful here", "<<<SEARCH\nabsent\n>>>\n<<<REPLACE\nnew\n>>>"
            )
            == "nothing useful here"
        )

    def test_stray_terminator_outside_blocks_preserves_original(self):
        """An unparsed ``>>>`` line makes the block boundaries ambiguous.

        Applying a possibly-truncated body is worse than declining: keep the
        original, the same call the not-found path already makes.
        """
        reply = "<<<SEARCH\nbeta\n>>>\n<<<REPLACE\nBETA\n>>>\ntrailing note\n>>>\n"
        assert apply_search_replace("alpha\nbeta\ngamma", reply) == "alpha\nbeta\ngamma"


class TestResendCharacterBlockCap:
    """``!resend`` truncated {{Name}} splits at an EVEN element cap (60).

    ``re.split`` with one capture group returns ``1 + 2 * blocks`` elements, so
    an even cap ends the list on a NAME whose text was sliced off; the send loop
    skips that dangling name and one block silently never goes out. logic.py
    fixed exactly this on its own path with an odd cap.
    """

    def test_cap_is_odd_and_derived_from_the_shared_constant(self):
        source = Path("cogs/ai_core/ai_cog.py").read_text(encoding="utf-8")
        assert "_max_parts = 1 + 2 * MAX_CHARACTER_BLOCKS" in source
        assert "split_parts = split_parts[:_max_parts]" in source
        # The literal even cap must be gone from the resend path.
        assert "split_parts[:60]" not in source

    def test_thirty_blocks_survive_the_cap(self):
        pattern = ai_cog_mod.AI._RESEND_CHARACTER_PATTERN
        content = "".join(f"{{{{Char{i}}}}} line {i}\n" for i in range(1, 31))
        parts = pattern.split(content)
        max_parts = 1 + 2 * MAX_CHARACTER_BLOCKS
        capped = parts[:max_parts] if len(parts) > max_parts else parts

        sent = [
            capped[i]
            for i in range(1, len(capped), 2)
            if capped[i].strip() and i + 1 < len(capped) and capped[i + 1].strip()
        ]
        # Previously 29: "Char30" landed at index 59 with its text sliced off.
        assert len(sent) == 30
        assert sent[-1] == "Char30"


class TestOwnWebhookEditSkip:
    """The raw-edit mirror wholesale-overwrote multi-fragment RP turns.

    ``on_raw_message_edit`` skipped only messages authored by ``bot.user``, but
    an RP turn goes out through the bot's own webhook — whose author object is
    the webhook pseudo-user. The listener therefore re-mirrored the model's own
    ``edit_message`` tool call through ``edit_message_in_history``, whose
    whole-row swap erases every sibling character line from memory AND the DB.
    """

    @staticmethod
    def _cog() -> ai_cog_mod.AI:
        cog = ai_cog_mod.AI.__new__(ai_cog_mod.AI)
        cog.bot = MagicMock()
        cog.bot.user = MagicMock(id=999)
        cog._own_webhook_ids = {}
        return cog

    @pytest.mark.asyncio
    async def test_own_webhook_is_recognised_and_cached(self):
        cog = self._cog()
        webhook = MagicMock(id=555)
        webhook.user = MagicMock(id=999)  # created by the bot
        channel = MagicMock(spec=ai_cog_mod.discord.TextChannel)
        channel.webhooks = AsyncMock(return_value=[webhook])
        channel.parent = None
        cog.bot.get_channel = MagicMock(return_value=channel)

        assert await cog._edit_from_own_webhook(7, 555) is True
        assert cog._own_webhook_ids == {555: True}

        # Second call is served from cache — no extra REST round trip.
        assert await cog._edit_from_own_webhook(7, 555) is True
        channel.webhooks.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_foreign_proxy_webhook_still_mirrors(self):
        """Tupperbox/PluralKit proxied USER messages are stored as history rows
        and their edits must keep flowing — the skip is scoped to OUR webhooks."""
        cog = self._cog()
        webhook = MagicMock(id=556)
        webhook.user = MagicMock(id=12345)  # some proxy bot, not us
        channel = MagicMock(spec=ai_cog_mod.discord.TextChannel)
        channel.webhooks = AsyncMock(return_value=[webhook])
        channel.parent = None
        cog.bot.get_channel = MagicMock(return_value=channel)

        assert await cog._edit_from_own_webhook(7, 556) is False

    @pytest.mark.asyncio
    async def test_unresolvable_webhook_fails_open_to_mirroring(self):
        cog = self._cog()
        cog.bot.get_channel = MagicMock(return_value=None)
        assert await cog._edit_from_own_webhook(7, 557) is False
        assert await cog._edit_from_own_webhook(7, "not-an-id") is False

    @pytest.mark.asyncio
    async def test_listener_skips_history_swap_for_our_webhook_edit(self):
        cog = self._cog()
        cog.chat_manager = MagicMock()
        cog.chat_manager.edit_message_in_history = AsyncMock(return_value=True)
        payload = MagicMock()
        payload.channel_id = 7
        payload.message_id = 100
        payload.data = {"author": {"id": "555"}, "webhook_id": "555", "content": "edited"}

        with patch.object(cog, "_edit_from_own_webhook", AsyncMock(return_value=True)):
            await ai_cog_mod.AI.on_raw_message_edit(cog, payload)

        cog.chat_manager.edit_message_in_history.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listener_still_mirrors_a_plain_user_edit(self):
        cog = self._cog()
        cog.chat_manager = MagicMock()
        cog.chat_manager.edit_message_in_history = AsyncMock(return_value=True)
        payload = MagicMock()
        payload.channel_id = 7
        payload.message_id = 100
        payload.data = {"author": {"id": "1234"}, "content": "edited"}

        await ai_cog_mod.AI.on_raw_message_edit(cog, payload)

        cog.chat_manager.edit_message_in_history.assert_awaited_once_with(7, 100, "edited")


class TestCopyHistoryCarriesSentMessageIds:
    """copy_history dropped ``sent_message_ids`` on link/move.

    Every other ai_history writer persists the column; the copy built 7-column
    rows, so a moved multi-message turn landed with NULL — its individual RP
    lines stopped being addressable and the prompt annotation degraded from
    ``(msgs name=id, …)`` to ``(msg id)``.
    """

    @pytest.mark.asyncio
    async def test_sent_message_ids_survive_the_copy(self):
        from cogs.ai_core import storage

        captured: dict[str, object] = {}

        class _FakeCursor:
            async def fetchone(self):
                return (0,)

        class _FakeConn:
            async def execute(self, *args):
                return _FakeCursor()

            async def executemany(self, sql, rows):
                captured["sql"] = sql
                captured["rows"] = list(rows)

            async def commit(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        sent_ids = [{"name": "Aria", "id": 11}, {"name": "Bex", "id": 12}]
        with (
            patch.object(storage, "DATABASE_AVAILABLE", True),
            patch.object(storage, "db") as mock_db,
        ):
            mock_db.get_ai_history = AsyncMock(
                return_value=[
                    {
                        "role": "assistant",
                        "content": "{{Aria}} hi\n{{Bex}} yo",
                        "message_id": 12,
                        "user_id": 4242,
                        "sent_message_ids": sent_ids,
                        "timestamp": "2026-01-01T00:00:00",
                    }
                ]
            )
            mock_db.get_write_connection = MagicMock(return_value=_FakeConn())
            copied = await storage.copy_history(1, 2)

        assert copied == 1
        assert "sent_message_ids" in str(captured["sql"])
        row = captured["rows"][0]
        # (channel, user_id, role, content, message_id, sent_message_ids, ts, local_id)
        assert len(row) == 8
        assert row[5] is not None and "Aria" in str(row[5])


class TestDotenvReclaimAnchorsOnTheProjectEnv:
    """The CLAUDE_EFFORT pin silently no-opped when CWD != project root.

    bot.py loads env with a bare ``load_dotenv()`` (frame-anchored discovery)
    while the reclaim used ``find_dotenv(usecwd=True)`` — a different file, or
    none at all, so the inherited Claude Code session effort kept winning.
    """

    def test_reclaims_from_the_env_beside_config_regardless_of_cwd(self, tmp_path, monkeypatch):
        import config as config_mod

        monkeypatch.chdir(tmp_path)  # foreign CWD, no .env in its ancestry
        monkeypatch.setenv("CLAUDE_EFFORT", "low")  # inherited value

        project_env = Path(config_mod.__file__).with_name(".env")
        if not project_env.is_file():
            pytest.skip("no .env in the working tree to anchor on")

        from dotenv import dotenv_values

        pinned = dotenv_values(str(project_env)).get("CLAUDE_EFFORT")
        if not pinned:
            pytest.skip(".env does not pin CLAUDE_EFFORT")

        reclaimed = config_mod.reclaim_dotenv_overrides()
        assert reclaimed.get("CLAUDE_EFFORT") == pinned
        import os

        assert os.environ["CLAUDE_EFFORT"] == pinned

    def test_explicit_path_still_wins(self, tmp_path, monkeypatch):
        import config as config_mod

        env_file = tmp_path / ".env"
        env_file.write_text("CLAUDE_EFFORT=xhigh\n", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_EFFORT", "low")

        assert config_mod.reclaim_dotenv_overrides(env_file) == {"CLAUDE_EFFORT": "xhigh"}


class TestUrlFetcherBatchChunking:
    """The client posted unbounded URL lists; the Go service 400s over 20.

    The 400 carries a text/plain body, so ``resp.json()`` raised ContentTypeError
    and the broad except failed EVERY url in the batch and marked the service
    unavailable — over a limit the client can simply respect.
    """

    def test_cap_matches_the_go_service(self):
        from utils.web.url_fetcher_client import _SERVICE_MAX_BATCH

        go_source = Path("go_services/url_fetcher/main.go").read_text(encoding="utf-8")
        assert f"len(req.URLs) > {_SERVICE_MAX_BATCH}" in go_source

    @pytest.mark.asyncio
    async def test_batch_is_chunked_and_merged(self):
        from utils.web import url_fetcher_client as mod

        client = mod.URLFetcherClient.__new__(mod.URLFetcherClient)
        client.base_url = "http://127.0.0.1:8081"
        client._service_available = True
        client._service_check_time = 0

        posted: list[list[str]] = []

        class _Resp:
            def __init__(self, urls):
                self._urls = urls

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def json(self):
                return {
                    "results": [{"url": u, "content": "ok"} for u in self._urls],
                    "success_count": len(self._urls),
                    "error_count": 0,
                    "total_time_ms": 5,
                }

        class _Session:
            def post(self, _url, json):  # matches aiohttp ClientSession.post
                posted.append(list(json["urls"]))
                return _Resp(json["urls"])

        client._session = _Session()
        urls = [f"https://example.com/{i}" for i in range(45)]

        with patch("utils.web.url_fetcher._is_private_url", AsyncMock(return_value=False)):
            result = await client._fetch_batch_via_service(urls, None)

        assert [len(chunk) for chunk in posted] == [20, 20, 5]
        assert result["success_count"] == 45
        assert len(result["results"]) == 45
        assert result["total_time_ms"] == 15


class TestDatabaseBackupOffLoop:
    """The pre-migration backup copied and pruned synchronously on the loop.

    Whole-file IO on a production DB inside ``async def`` stalls every other
    coroutine; the rest of the module already offloads its file writes with
    ``asyncio.to_thread``.
    """

    def test_backup_helper_is_offloaded(self):
        source = Path("utils/database/database.py").read_text(encoding="utf-8")
        assert "await asyncio.to_thread(\n                        _backup_database_files" in source
        assert "def _backup_database_files(" in source
        # The blocking copy must no longer sit inline in the async method.
        migrate_block = source.split("backup_path = backup_dir / backup_name", 1)[1][:1200]
        assert "shutil.copy2(self.db_path" not in migrate_block

    def test_helper_copies_wal_siblings_and_prunes(self, tmp_path):
        import os
        import time

        from utils.database.database import _backup_database_files

        db = tmp_path / "bot_database.db"
        db.write_bytes(b"main")
        (tmp_path / "bot_database.db-wal").write_bytes(b"wal")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        # Stamp the existing backups as clearly older. shutil.copy2 carries the
        # SOURCE file's mtime onto the copy, so leaving these at "now" would tie
        # with the fresh backup and make the prune order undefined.
        now = time.time()
        for i in range(6):
            old = backup_dir / f"bot_database_v{i}_old.db"
            old.write_bytes(b"x")
            os.utime(old, (now - 3600 + i, now - 3600 + i))

        target = backup_dir / "bot_database_v9_new.db"
        _backup_database_files(db, target, backup_dir)

        assert target.read_bytes() == b"main"
        assert (backup_dir / "bot_database_v9_new.db-wal").read_bytes() == b"wal"
        # 6 pre-existing + the new one, pruned to the last 5 by mtime.
        remaining = sorted(p.name for p in backup_dir.glob("bot_database_v*.db"))
        assert len(remaining) == 5
        assert "bot_database_v9_new.db" in remaining
        # The two oldest were the ones dropped.
        assert "bot_database_v0_old.db" not in remaining
        assert "bot_database_v1_old.db" not in remaining
        # Pruned backups take their -wal/-shm sidecars with them.
        assert not (backup_dir / "bot_database_v0_old.db-wal").exists()


class TestEditMessageFailureIsMarked:
    """cmd_edit_message's HTTP failure path sent a bare status string.

    The AI-tool caller wraps the channel in _TeeChannel and decides the outcome
    by scanning captured lines for ❌/⛔ — so a failed edit was reported to the
    model as "Edited message <id>".
    """

    def test_failure_send_carries_the_failure_marker(self):
        source = Path("cogs/ai_core/commands/server_commands.py").read_text(encoding="utf-8")
        assert 'f"❌ แก้ไขข้อความไม่สำเร็จ {_fmt_http_error(err)}"' in source

    @pytest.mark.asyncio
    async def test_tee_sees_the_edit_failure(self):
        from cogs.ai_core.tools.tool_executor import _FAILURE_PREFIXES

        assert any("❌ แก้ไขข้อความไม่สำเร็จ (HTTP 404)".startswith(p) for p in _FAILURE_PREFIXES)


class TestAiEditPersistenceIsChecked:
    """Both dashboard backends discarded update_dashboard_message()'s bool.

    It returns False (no raise) when the UPDATE matches no row — the target was
    deleted mid-edit — and the handlers still wiped the CLI session and echoed
    the rewrite as full_response, desyncing the UI from the DB with no log line.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "cogs/ai_core/api/dashboard_chat_claude_cli.py",
            "cogs/ai_core/api/dashboard_chat_claude.py",
        ],
    )
    def test_backend_reads_the_update_result(self, path):
        source = Path(path).read_text(encoding="utf-8")
        assert "updated = await db.update_dashboard_message(" in source
        assert "if not updated:" in source
        assert "no longer matches conversation" in source
