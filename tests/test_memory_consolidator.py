"""
Tests for cogs/ai_core/memory/memory_consolidator.py

Comprehensive tests for SummaryArchiver and ConversationSummary classes.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestConversationSummaryDataclass:
    """Tests for ConversationSummary dataclass."""

    def test_conversation_summary_defaults(self):
        """Test ConversationSummary default values."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary()

        assert summary.id is None
        assert summary.channel_id == 0
        assert summary.user_id is None
        assert summary.summary == ""
        assert summary.key_topics == []
        assert summary.key_decisions == []
        assert summary.start_time is None
        assert summary.end_time is None
        assert summary.message_count == 0
        assert summary.created_at is None

    def test_conversation_summary_with_values(self):
        """Test ConversationSummary with custom values."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        now = datetime.now()
        summary = ConversationSummary(
            id=1,
            channel_id=12345,
            user_id=67890,
            summary="Test summary",
            key_topics=["topic1", "topic2"],
            key_decisions=["decision1"],
            start_time=now,
            end_time=now,
            message_count=10,
            created_at=now,
        )

        assert summary.id == 1
        assert summary.channel_id == 12345
        assert summary.user_id == 67890
        assert summary.summary == "Test summary"
        assert len(summary.key_topics) == 2
        assert len(summary.key_decisions) == 1
        assert summary.message_count == 10

    def test_to_context_string_basic(self):
        """Test to_context_string with basic data."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(
            summary="This is a test summary",
            start_time=datetime(2024, 1, 15),
        )

        result = summary.to_context_string()

        assert "สรุปการสนทนา" in result
        assert "15/01/2024" in result
        assert "This is a test summary" in result

    def test_to_context_string_no_start_time(self):
        """Test to_context_string without start_time."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(summary="Test")
        result = summary.to_context_string()

        assert "N/A" in result
        assert "Test" in result

    def test_to_context_string_with_topics(self):
        """Test to_context_string with key topics."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(
            summary="Test",
            start_time=datetime.now(),
            key_topics=["Python", "AI", "Discord"],
        )

        result = summary.to_context_string()

        assert "หัวข้อ:" in result
        assert "Python" in result

    def test_to_context_string_limits_topics(self):
        """Test to_context_string limits topics to 3."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(
            summary="Test",
            start_time=datetime.now(),
            key_topics=["Topic1", "Topic2", "Topic3", "Topic4", "Topic5"],
        )

        result = summary.to_context_string()

        # Should only include first 3
        assert "Topic1" in result
        assert "Topic2" in result
        assert "Topic3" in result


class TestSummaryArchiverInit:
    """Tests for SummaryArchiver initialization."""

    def test_init(self):
        """Test SummaryArchiver init."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()

        assert consolidator._consolidation_task is None
        assert consolidator.MIN_MESSAGES_TO_SUMMARIZE == 20
        assert consolidator.SUMMARY_AGE_THRESHOLD_HOURS == 24
        assert consolidator.MAX_SUMMARY_LENGTH == 500

    def test_has_logger(self):
        """Test SummaryArchiver has logger."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        assert consolidator.logger is not None


class TestSummaryArchiverBackgroundTask:
    """Tests for background task methods."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_start_background_task(self):
        """Test start_background_task creates task."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()

        # Mock asyncio.create_task
        with patch("asyncio.create_task") as mock_create:
            mock_task = MagicMock()
            mock_create.return_value = mock_task

            consolidator.start_background_task(interval_hours=1.0)

            mock_create.assert_called_once()
            assert consolidator._consolidation_task is mock_task

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_start_background_task_already_running(self):
        """Test start_background_task does nothing if already running."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        consolidator._consolidation_task = mock_task

        with patch("asyncio.create_task") as mock_create:
            consolidator.start_background_task()

            mock_create.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_stop_background_task(self):
        """Test stop_background_task cancels task."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()

        # Create a real async task that we can cancel
        async def dummy_task():
            await asyncio.sleep(100)

        real_task = asyncio.create_task(dummy_task())
        consolidator._consolidation_task = real_task

        await consolidator.stop_background_task()

        assert real_task.cancelled() or real_task.done()
        assert consolidator._consolidation_task is None

    @pytest.mark.asyncio
    async def test_stop_background_task_no_task(self):
        """Test stop_background_task with no task."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        consolidator._consolidation_task = None

        # Should not raise
        await consolidator.stop_background_task()


class TestSummaryArchiverInitSchema:
    """Tests for init_schema method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_init_schema_no_db(self):
        """Test init_schema when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()

        # Should not raise, just return early
        await consolidator.init_schema()


class TestSummaryArchiverConsolidateChannel:
    """Tests for consolidate_channel method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_consolidate_channel_no_db(self):
        """Test consolidate_channel when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        result = await consolidator.consolidate_channel(12345)

        assert result is None


class TestSummaryArchiverConsolidateAllChannels:
    """Tests for consolidate_all_channels method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_consolidate_all_channels_no_db(self):
        """Test consolidate_all_channels when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        result = await consolidator.consolidate_all_channels()

        assert result == 0


class TestSummaryArchiverGetChannelSummaries:
    """Tests for get_channel_summaries method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_get_channel_summaries_no_db(self):
        """Test get_channel_summaries when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        result = await consolidator.get_channel_summaries(12345)

        assert result == []


class TestSummaryArchiverGetContextSummaries:
    """Tests for get_context_summaries method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_get_context_summaries_no_db(self):
        """Test get_context_summaries when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        result = await consolidator.get_context_summaries(12345)

        assert result == ""


class TestSummaryArchiverGenerateSummary:
    """Tests for _generate_summary method."""

    @pytest.mark.asyncio
    async def test_generate_summary_empty_messages(self):
        """Test _generate_summary with empty messages."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        result = await consolidator._generate_summary([])

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_summary_with_messages(self):
        """Test _generate_summary with messages."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        consolidator = SummaryArchiver()
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "model", "content": "I'm fine, thank you!"},
            {"role": "user", "content": "Tell me about Python"},
            {"role": "model", "content": "Python is a programming language"},
        ]

        result = await consolidator._generate_summary(messages)

        assert result is not None
        assert "text" in result


class TestModuleImports:
    """Tests for module imports."""

    def test_import_conversation_summary(self):
        """Test ConversationSummary can be imported."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        assert ConversationSummary is not None

    def test_import_summary_archiver(self):
        """Test SummaryArchiver can be imported."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        assert SummaryArchiver is not None

    def test_import_summary_archiver_singleton(self):
        """The module-level ``summary_archiver`` instance is the public hook."""
        from cogs.ai_core.memory.memory_consolidator import (
            SummaryArchiver,
            summary_archiver,
        )

        assert isinstance(summary_archiver, SummaryArchiver)

    def test_db_available_flag_exists(self):
        """Test DB_AVAILABLE flag exists."""
        from cogs.ai_core.memory.memory_consolidator import DB_AVAILABLE

        assert isinstance(DB_AVAILABLE, bool)


# ======================================================================
# Appended deeper-coverage tests (DB/LLM mocked, hermetic, deterministic)
# ======================================================================

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock


class _FakeCursor:
    """Minimal stand-in for an aiosqlite cursor.

    ``fetchall`` returns the pre-seeded rows (list of dicts, which support
    ``row["col"]`` access exactly like sqlite3.Row). ``lastrowid`` mirrors
    the value the fake connection was told to hand back from INSERTs.
    """

    def __init__(self, rows=None, lastrowid=None):
        self._rows = rows if rows is not None else []
        self.lastrowid = lastrowid

    async def fetchall(self):
        return self._rows


class _FakeConn:
    """Records executed SQL and returns scripted cursors.

    ``cursors`` is consumed FIFO: each ``execute`` pops the next scripted
    cursor (or a default empty one). ``executed`` keeps (sql, params) so
    tests can assert which statements ran (e.g. DELETE vs UPDATE).
    """

    def __init__(self, cursors=None, lastrowid=None, raise_on=None):
        self._cursors = list(cursors) if cursors else []
        self._lastrowid = lastrowid
        self._raise_on = raise_on  # substring -> raise when SQL contains it
        self.executed = []
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("boom: " + self._raise_on)
        # Only SELECTs consume a scripted cursor; DDL (CREATE TABLE/INDEX from
        # lazy init_schema) and writes get a default cursor so they don't eat
        # the row data a test seeded for the real query.
        if self._cursors and sql.lstrip().upper().startswith("SELECT"):
            return self._cursors.pop(0)
        return _FakeCursor(rows=[], lastrowid=self._lastrowid)

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


class _FakeDB:
    """Fake ``db`` exposing async-context-manager connection getters.

    Both ``get_connection`` and ``get_write_connection`` yield the SAME
    underlying connection so a test can inspect everything that ran across
    read and write paths on one object.
    """

    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def get_connection(self):
        yield self._conn

    @asynccontextmanager
    async def get_write_connection(self):
        yield self._conn


def _patch_db(monkeypatch, conn):
    """Wire a fake db + DB_AVAILABLE=True into the module under test."""
    from cogs.ai_core.memory import memory_consolidator as mc

    fake_db = _FakeDB(conn)
    monkeypatch.setattr(mc, "db", fake_db)
    monkeypatch.setattr(mc, "DB_AVAILABLE", True)
    return fake_db


class TestConsolidationLoop:
    """Tests for the _consolidation_loop background loop (159-176)."""

    @pytest.mark.asyncio
    async def test_loop_runs_then_cancels(self, monkeypatch):
        """Happy path: sleep -> consolidate_all_channels -> cancelled exits cleanly."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()

        calls = {"consolidate": 0}

        async def fake_consolidate_all():
            calls["consolidate"] += 1

        archiver.consolidate_all_channels = fake_consolidate_all  # type: ignore[method-assign]

        # First sleep returns immediately; second sleep raises CancelledError
        # to break the otherwise-infinite loop deterministically.
        sleeps = []

        async def fake_sleep(secs):
            sleeps.append(secs)
            if len(sleeps) >= 2:
                raise asyncio.CancelledError

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await archiver._consolidation_loop(interval_hours=6.0)

        # consolidate ran once, the interval sleep was interval_hours*3600
        assert calls["consolidate"] == 1
        assert sleeps[0] == 6.0 * 3600

    @pytest.mark.asyncio
    async def test_loop_backoff_on_error(self, monkeypatch):
        """Error branch: an exception triggers exponential backoff sleep then exits.

        The backoff sleep lives inside the ``except Exception`` handler, so we
        let it complete normally and instead cancel on the *next* iteration's
        interval sleep (inside the top-level try, where CancelledError breaks).
        """
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()

        async def boom():
            raise ValueError("db down")

        archiver.consolidate_all_channels = boom  # type: ignore[method-assign]

        sleeps = []

        async def fake_sleep(secs):
            sleeps.append(secs)
            # sleep #1 = interval (returns ok -> reach boom)
            # sleep #2 = backoff (returns ok)
            # sleep #3 = next interval -> cancel to exit cleanly
            if len(sleeps) >= 3:
                raise asyncio.CancelledError

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await archiver._consolidation_loop(interval_hours=0.001)

        interval_secs = 0.001 * 3600
        assert sleeps[0] == interval_secs  # first interval sleep
        # backoff for the first error = min(interval_secs, 60 * 2**1)
        expected_backoff = min(interval_secs, 60 * (2**1))
        assert sleeps[1] == expected_backoff

    @pytest.mark.asyncio
    async def test_loop_backoff_capped(self, monkeypatch):
        """Backoff never exceeds interval_secs (the min() cap)."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()

        async def boom():
            raise ValueError("persistent")

        archiver.consolidate_all_channels = boom  # type: ignore[method-assign]

        interval_secs = 0.5 * 3600  # 1800s
        sleeps = []

        async def fake_sleep(secs):
            sleeps.append(secs)
            # Let two full error cycles (interval+backoff) run, then cancel.
            if len(sleeps) >= 5:
                raise asyncio.CancelledError

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await archiver._consolidation_loop(interval_hours=0.5)

        # Backoff sleeps are the even-indexed ones (1, 3, ...).
        backoff_sleeps = sleeps[1::2]
        assert backoff_sleeps  # at least one backoff happened
        for b in backoff_sleeps:
            assert b <= interval_secs


class TestConsolidateChannelFull:
    """Tests for consolidate_channel happy/edge paths (204-335)."""

    def _rows(self, n):
        base = datetime(2024, 1, 1, 12, 0, 0)
        rows = []
        for i in range(n):
            ts = (base + timedelta(minutes=i)).isoformat()
            role = "user" if i % 2 == 0 else "model"
            rows.append({"id": i + 1, "role": role, "content": f"message {i}", "timestamp": ts})
        return rows

    @pytest.mark.asyncio
    async def test_below_threshold_returns_none(self, monkeypatch):
        """Too few unsummarized rows and force=False -> None, no save."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = self._rows(3)
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        result = await archiver.consolidate_channel(555, force=False)

        assert result is None

    @pytest.mark.asyncio
    async def test_force_below_threshold_consolidates(self, monkeypatch):
        """force=True summarizes even below MIN_MESSAGES_TO_SUMMARIZE."""
        from cogs.ai_core.memory.memory_consolidator import (
            ConversationSummary,
            SummaryArchiver,
        )

        rows = self._rows(4)
        # SELECT cursor for the history query; subsequent writes use the
        # default empty cursor with a lastrowid so _save_summary returns an id.
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)], lastrowid=42)
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        # CONSOLIDATOR_DELETE_ORIGINALS unset -> default mark-only path
        monkeypatch.delenv("CONSOLIDATOR_DELETE_ORIGINALS", raising=False)

        result = await archiver.consolidate_channel(555, force=True)

        assert isinstance(result, ConversationSummary)
        assert result.channel_id == 555
        assert result.message_count == 4
        assert result.summary  # extractive summary text present
        assert result.start_time == datetime.fromisoformat(rows[0]["timestamp"])
        assert result.end_time == datetime.fromisoformat(rows[-1]["timestamp"])
        # Default path: an UPDATE (mark) ran, no DELETE.
        sql_blob = " ".join(sql for sql, _ in conn.executed)
        assert "UPDATE ai_history SET summarized_at" in sql_blob
        assert "DELETE FROM ai_history" not in sql_blob

    @pytest.mark.asyncio
    async def test_delete_originals_env_triggers_delete(self, monkeypatch):
        """CONSOLIDATOR_DELETE_ORIGINALS=1 marks AND hard-deletes originals."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = self._rows(4)
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)], lastrowid=7)
        _patch_db(monkeypatch, conn)
        monkeypatch.setenv("CONSOLIDATOR_DELETE_ORIGINALS", "1")

        archiver = SummaryArchiver()
        result = await archiver.consolidate_channel(900, force=True)

        assert result is not None
        sql_blob = " ".join(sql for sql, _ in conn.executed)
        assert "UPDATE ai_history SET summarized_at" in sql_blob
        assert "DELETE FROM ai_history" in sql_blob

    @pytest.mark.asyncio
    async def test_empty_summary_returns_none_no_writes(self, monkeypatch):
        """All non-user rows -> _generate_summary None -> bail before any write."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        base = datetime(2024, 1, 1, 12, 0, 0)
        rows = [
            {
                "id": i + 1,
                "role": "model",
                "content": f"assistant {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            }
            for i in range(5)
        ]
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        result = await archiver.consolidate_channel(123, force=True)

        assert result is None
        sql_blob = " ".join(sql for sql, _ in conn.executed)
        assert "UPDATE ai_history" not in sql_blob
        assert "DELETE FROM ai_history" not in sql_blob

    @pytest.mark.asyncio
    async def test_malformed_timestamp_tolerated(self, monkeypatch):
        """A bad first/last timestamp is parsed to None, summary still produced."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = self._rows(4)
        rows[0]["timestamp"] = "not-a-timestamp"
        rows[-1]["timestamp"] = None
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)], lastrowid=5)
        _patch_db(monkeypatch, conn)
        monkeypatch.delenv("CONSOLIDATOR_DELETE_ORIGINALS", raising=False)

        archiver = SummaryArchiver()
        result = await archiver.consolidate_channel(321, force=True)

        assert result is not None
        assert result.start_time is None
        assert result.end_time is None

    @pytest.mark.asyncio
    async def test_save_fail_keeps_originals(self, monkeypatch):
        """_save_summary returning None -> warning branch, no mark/delete."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = self._rows(4)
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        # Force _save_summary to report failure (None id)
        archiver._save_summary = AsyncMock(return_value=None)  # type: ignore[method-assign]
        archiver._mark_consolidated_messages = AsyncMock()  # type: ignore[method-assign]

        result = await archiver.consolidate_channel(777, force=True)

        # Failed save now reports failure (None) — callers previously counted
        # the un-persisted summary as success ("✅ สำเร็จ" in !consolidate).
        # Originals stay untouched either way.
        assert result is None
        archiver._mark_consolidated_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_mark_failure_logged_not_raised(self, monkeypatch):
        """If marking raises after save, the error is logged (not raised), no delete
        runs, and consolidate_channel returns None to signal no progress — the source
        rows are still summarized_at IS NULL, so returning None makes the per-channel
        pass loop stop instead of re-summarising them into duplicate summary rows."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = self._rows(4)
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)
        monkeypatch.setenv("CONSOLIDATOR_DELETE_ORIGINALS", "1")

        archiver = SummaryArchiver()
        archiver._save_summary = AsyncMock(return_value=99)  # type: ignore[method-assign]
        archiver._mark_consolidated_messages = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("mark failed")
        )
        delete_mock = AsyncMock()
        archiver._delete_consolidated_messages = delete_mock  # type: ignore[method-assign]

        result = await archiver.consolidate_channel(888, force=True)

        # mark-summarized failed -> no real progress -> None (so the pass loop stops)
        assert result is None
        # Mark failed -> delete must NOT run (else block skipped)
        delete_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_failure_logged_not_raised(self, monkeypatch):
        """Hard-delete failure after a successful mark is logged, not raised."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = self._rows(4)
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)
        monkeypatch.setenv("CONSOLIDATOR_DELETE_ORIGINALS", "1")

        archiver = SummaryArchiver()
        archiver._save_summary = AsyncMock(return_value=50)  # type: ignore[method-assign]
        archiver._mark_consolidated_messages = AsyncMock()  # type: ignore[method-assign]
        archiver._delete_consolidated_messages = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("delete failed")
        )

        # Should not raise despite delete failing
        result = await archiver.consolidate_channel(999, force=True)
        assert result is not None


class TestConsolidateAllChannelsFull:
    """Tests for consolidate_all_channels with DB present (337-368)."""

    @pytest.mark.asyncio
    async def test_iterates_channels_and_counts(self, monkeypatch):
        """Each channel is DRAINED across capped passes until consolidate_channel
        returns None (below-threshold/drained); every truthy pass is counted."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        channels = [{"channel_id": 1, "count": 30}, {"channel_id": 2, "count": 25}]
        conn = _FakeConn(cursors=[_FakeCursor(rows=channels)])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()

        # Channel 1 drains over two successful passes then None; channel 2 has
        # nothing eligible (None on the first pass).
        per_channel = {1: iter([object(), object(), None]), 2: iter([None])}
        archiver.consolidate_channel = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda cid: next(per_channel[cid])
        )

        count = await archiver.consolidate_all_channels()

        # 2 successful passes on channel 1; channel 2 contributes 0.
        assert count == 2
        # ch1: 3 calls (2 results + 1 drained None), ch2: 1 call.
        assert archiver.consolidate_channel.await_count == 4

    @pytest.mark.asyncio
    async def test_no_channels_returns_zero(self, monkeypatch):
        """Empty channel set -> 0 consolidations, consolidate_channel never called."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn(cursors=[_FakeCursor(rows=[])])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        archiver.consolidate_channel = AsyncMock()  # type: ignore[method-assign]

        count = await archiver.consolidate_all_channels()

        assert count == 0
        archiver.consolidate_channel.assert_not_called()


class TestGetChannelSummariesFull:
    """Tests for get_channel_summaries with DB present (370-419)."""

    @pytest.mark.asyncio
    async def test_maps_rows_to_summaries(self, monkeypatch):
        """DB rows are mapped into ConversationSummary objects with parsed fields."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = [
            {
                "id": 10,
                "channel_id": 42,
                "summary": "did stuff",
                "key_topics": '["python", "discord"]',
                "key_decisions": "[]",
                "start_time": "2024-01-01T10:00:00",
                "end_time": "2024-01-01T11:00:00",
                "message_count": 25,
                "created_at": "2024-01-01T11:05:00",
            }
        ]
        # init_schema runs first (DDL on write conn), then the SELECT.
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        summaries = await archiver.get_channel_summaries(42, limit=5)

        assert len(summaries) == 1
        s = summaries[0]
        assert s.id == 10
        assert s.channel_id == 42
        assert s.summary == "did stuff"
        assert s.key_topics == ["python", "discord"]
        assert s.key_decisions == []
        assert s.start_time == datetime(2024, 1, 1, 10, 0, 0)
        assert s.message_count == 25

    @pytest.mark.asyncio
    async def test_safe_dt_handles_bad_timestamps(self, monkeypatch):
        """Malformed/blank stored timestamps parse to None instead of raising."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        rows = [
            {
                "id": 1,
                "channel_id": 7,
                "summary": "x",
                "key_topics": None,
                "key_decisions": None,
                "start_time": "garbage",
                "end_time": "",
                "message_count": 20,
                "created_at": None,
            }
        ]
        conn = _FakeConn(cursors=[_FakeCursor(rows=rows)])
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        summaries = await archiver.get_channel_summaries(7)

        assert len(summaries) == 1
        s = summaries[0]
        assert s.start_time is None
        assert s.end_time is None
        assert s.created_at is None
        assert s.key_topics == []


class TestGetContextSummariesFull:
    """Tests for get_context_summaries with summaries present (421-433)."""

    @pytest.mark.asyncio
    async def test_formats_existing_summaries(self, monkeypatch):
        """Existing summaries are rendered into the Thai context header block."""
        from cogs.ai_core.memory.memory_consolidator import (
            ConversationSummary,
            SummaryArchiver,
        )

        archiver = SummaryArchiver()
        fake_summaries = [
            ConversationSummary(
                summary="we talked about cats",
                start_time=datetime(2024, 2, 2),
                key_topics=["cats"],
            )
        ]
        archiver.get_channel_summaries = AsyncMock(  # type: ignore[method-assign]
            return_value=fake_summaries
        )

        text = await archiver.get_context_summaries(500)

        assert "ประวัติการสนทนาก่อนหน้า" in text
        assert "we talked about cats" in text
        archiver.get_channel_summaries.assert_awaited_once_with(500, limit=3)

    @pytest.mark.asyncio
    async def test_no_summaries_returns_empty(self, monkeypatch):
        """No summaries -> empty string (early return)."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        archiver.get_channel_summaries = AsyncMock(return_value=[])  # type: ignore[method-assign]

        text = await archiver.get_context_summaries(500)
        assert text == ""


class TestGenerateSummaryDetails:
    """Tests for _generate_summary content/edge branches (446-482)."""

    @pytest.mark.asyncio
    async def test_first_and_last_user_lines(self):
        """Both a first and last user line are captured in the summary text."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        messages = [
            {"role": "user", "content": "first question about widgets"},
            {"role": "model", "content": "answer"},
            {"role": "user", "content": "last question about gadgets"},
        ]
        result = await archiver._generate_summary(messages)

        assert result is not None
        assert "ผู้ใช้ถาม:" in result["text"]
        assert "หัวข้อล่าสุด:" in result["text"]
        assert "first question about widgets" in result["text"]
        assert "last question about gadgets" in result["text"]

    @pytest.mark.asyncio
    async def test_single_user_line_no_last(self):
        """A single user line yields only the 'first' sentence, no 'latest' line."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        messages = [
            {"role": "user", "content": "only one user message"},
            {"role": "model", "content": "reply"},
        ]
        result = await archiver._generate_summary(messages)

        assert result is not None
        assert "ผู้ใช้ถาม:" in result["text"]
        assert "หัวข้อล่าสุด:" not in result["text"]

    @pytest.mark.asyncio
    async def test_only_assistant_returns_none(self):
        """No user content -> empty summary text -> None."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        messages = [
            {"role": "model", "content": "a"},
            {"role": "model", "content": "b"},
        ]
        result = await archiver._generate_summary(messages)

        assert result is None

    @pytest.mark.asyncio
    async def test_summary_truncated_to_max_length(self, monkeypatch):
        """Overlong summary text is truncated and suffixed with '...'."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        # Shrink the cap so the assertion is robust and fast.
        monkeypatch.setattr(archiver, "MAX_SUMMARY_LENGTH", 30)
        messages = [
            {"role": "user", "content": "x" * 400},
            {"role": "user", "content": "y" * 400},
        ]
        result = await archiver._generate_summary(messages)

        assert result is not None
        assert result["text"].endswith("...")
        # Truncated to MAX_SUMMARY_LENGTH chars + the "..." suffix
        assert len(result["text"]) == 30 + 3

    @pytest.mark.asyncio
    async def test_topics_capped_at_five(self):
        """The returned topics list never exceeds 5 entries."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        # Build text where many distinct 4+ char words each appear twice
        words = [f"alpha{i}word" for i in range(8)]
        content = " ".join(words + words)  # each appears exactly twice
        messages = [{"role": "user", "content": content}]
        result = await archiver._generate_summary(messages)

        assert result is not None
        assert len(result["topics"]) <= 5


class TestExtractTopics:
    """Tests for _extract_topics heuristic (484-543)."""

    def test_filters_common_and_short_words(self):
        """Common stopwords and <4-char words are excluded; freq>=2 required."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        # "python" appears 3x, "the"/"and" are stopwords, "cat" too short.
        text = "the python and python cat python the and"
        topics = archiver._extract_topics(text)

        assert "python" in topics
        assert "the" not in topics
        assert "and" not in topics
        assert "cat" not in topics

    def test_singletons_excluded(self):
        """Words appearing only once are dropped (count >= 2 gate)."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        topics = archiver._extract_topics("unique words appearing single times only here")
        # Nothing repeats twice -> no topics
        assert topics == []

    def test_empty_text_returns_empty(self):
        """Empty input yields no topics."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        archiver = SummaryArchiver()
        assert archiver._extract_topics("") == []


class TestLoadJsonList:
    """Tests for _load_json_list (545-557)."""

    def test_valid_json_list(self):
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        assert SummaryArchiver._load_json_list('["a", "b"]') == ["a", "b"]

    def test_none_and_empty(self):
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        assert SummaryArchiver._load_json_list(None) == []
        assert SummaryArchiver._load_json_list("") == []

    def test_legacy_comma_separated_fallback(self):
        """Non-JSON comma-separated legacy data falls back to split-on-comma."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        assert SummaryArchiver._load_json_list("a, b ,c") == ["a", "b", "c"]

    def test_json_non_list_falls_back(self):
        """Valid JSON that is not a list (e.g. an object) hits the fallback path."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        # '{"x":1}' parses but isn't a list -> fallback splits on comma.
        result = SummaryArchiver._load_json_list('{"x":1}')
        assert isinstance(result, list)
        assert result  # non-empty: legacy split produced tokens


class TestSaveSummary:
    """Tests for _save_summary (559-588)."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_no_db_returns_none(self):
        from cogs.ai_core.memory.memory_consolidator import (
            ConversationSummary,
            SummaryArchiver,
        )

        archiver = SummaryArchiver()
        result = await archiver._save_summary(ConversationSummary(channel_id=1))
        assert result is None

    @pytest.mark.asyncio
    async def test_inserts_and_returns_lastrowid(self, monkeypatch):
        """A populated summary INSERTs once, commits, returns lastrowid."""
        from cogs.ai_core.memory.memory_consolidator import (
            ConversationSummary,
            SummaryArchiver,
        )

        conn = _FakeConn(lastrowid=314)
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        summary = ConversationSummary(
            channel_id=11,
            user_id=22,
            summary="text",
            key_topics=["t1"],
            key_decisions=["d1"],
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 2),
            message_count=20,
        )
        result = await archiver._save_summary(summary)

        assert result == 314
        assert conn.committed == 1
        sql, params = conn.executed[0]
        assert "INSERT INTO conversation_summaries" in sql
        # key_topics/decisions serialized to JSON strings
        assert params[3] == '["t1"]'
        assert params[4] == '["d1"]'
        assert params[5] == datetime(2024, 1, 1).isoformat()

    @pytest.mark.asyncio
    async def test_empty_lists_serialize_to_empty_json(self, monkeypatch):
        """Empty topics/decisions persist as '[]', not 'null'."""
        from cogs.ai_core.memory.memory_consolidator import (
            ConversationSummary,
            SummaryArchiver,
        )

        conn = _FakeConn(lastrowid=1)
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        await archiver._save_summary(
            ConversationSummary(channel_id=1, summary="s", message_count=20)
        )
        _, params = conn.executed[0]
        assert params[3] == "[]"
        assert params[4] == "[]"
        # No times -> None placeholders
        assert params[5] is None
        assert params[6] is None


class TestDeleteConsolidatedMessages:
    """Tests for _delete_consolidated_messages (590-613)."""

    @pytest.mark.asyncio
    async def test_empty_ids_noop(self, monkeypatch):
        """No ids -> early return, no DB touched."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn()
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        await archiver._delete_consolidated_messages([])
        assert conn.executed == []

    @pytest.mark.asyncio
    async def test_batches_over_900(self, monkeypatch):
        """More than 900 ids are split into multiple DELETE batches, one commit."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn()
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        ids = list(range(1, 950))  # 949 -> 2 batches (900 + 49)
        await archiver._delete_consolidated_messages(ids)

        deletes = [sql for sql, _ in conn.executed if "DELETE FROM ai_history" in sql]
        assert len(deletes) == 2
        assert conn.committed == 1

    @pytest.mark.asyncio
    async def test_failure_rolls_back_and_raises(self, monkeypatch):
        """A failing DELETE rolls back the transaction and re-raises."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn(raise_on="DELETE FROM ai_history")
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        with pytest.raises(RuntimeError):
            await archiver._delete_consolidated_messages([1, 2, 3])

        assert conn.rolled_back == 1
        assert conn.committed == 0


class TestMarkConsolidatedMessages:
    """Tests for _mark_consolidated_messages (615-648)."""

    @pytest.mark.asyncio
    async def test_empty_ids_noop(self, monkeypatch):
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn()
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        await archiver._mark_consolidated_messages([])
        assert conn.executed == []

    @pytest.mark.asyncio
    async def test_updates_with_summarized_at_filter(self, monkeypatch):
        """UPDATE stamps summarized_at and only touches IS NULL rows."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn()
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        await archiver._mark_consolidated_messages([1, 2, 3])

        assert conn.committed == 1
        sql, params = conn.executed[0]
        assert "UPDATE ai_history SET summarized_at" in sql
        assert "summarized_at IS NULL" in sql
        # First param is the marked_at timestamp, rest are the ids
        assert params[1:] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_batches_over_900(self, monkeypatch):
        """More than 900 ids split into multiple UPDATE batches, single commit."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn()
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        ids = list(range(1, 902))  # 901 -> 2 batches
        await archiver._mark_consolidated_messages(ids)

        updates = [sql for sql, _ in conn.executed if "UPDATE ai_history" in sql]
        assert len(updates) == 2
        assert conn.committed == 1

    @pytest.mark.asyncio
    async def test_failure_rolls_back_and_raises(self, monkeypatch):
        """A failing UPDATE rolls back and re-raises."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn(raise_on="UPDATE ai_history")
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        with pytest.raises(RuntimeError):
            await archiver._mark_consolidated_messages([1, 2, 3])

        assert conn.rolled_back == 1
        assert conn.committed == 0


class TestInitSchemaWithDB:
    """Tests for init_schema DDL path (108-139)."""

    @pytest.mark.asyncio
    async def test_creates_table_and_index(self, monkeypatch):
        """init_schema issues CREATE TABLE + CREATE INDEX and commits."""
        from cogs.ai_core.memory.memory_consolidator import SummaryArchiver

        conn = _FakeConn()
        _patch_db(monkeypatch, conn)

        archiver = SummaryArchiver()
        await archiver.init_schema()

        sql_blob = " ".join(sql for sql, _ in conn.executed)
        assert "CREATE TABLE IF NOT EXISTS conversation_summaries" in sql_blob
        assert "CREATE INDEX IF NOT EXISTS idx_summaries_channel" in sql_blob
        assert conn.committed == 1
