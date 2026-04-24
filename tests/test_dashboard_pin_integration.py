"""Integration test for message pinning (#20).

Exercises the full write-path end-to-end against a real SQLite DB:

    save message -> update_dashboard_message_pin(True) -> read back is_pinned=True
                 -> update_dashboard_message_pin(False) -> read back is_pinned=False

This catches regressions in:
  - migration 013 (column + index)
  - init_schema ALTER TABLE fallback
  - is_pinned deserialization in get_dashboard_messages
  - update_dashboard_message_pin affecting exactly one row

The fixture uses a fresh, NON-singleton Database. It bypasses the
`Database.__new__` singleton entirely via `object.__new__(Database)` so later
tests that import the module-level `db` singleton are unaffected by this
test's state — no `_instance` reset, no shared connection pool.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def fresh_db():
    """Build an isolated Database instance without touching the singleton."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    tmp = tempfile.mkdtemp(prefix="pin-test-")
    data_dir = Path(tmp) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "bot_database.db"

    # init_schema creates `data/backups/` relative to CWD — chdir for isolation.
    original_cwd = Path.cwd()
    os.chdir(tmp)
    try:
        from utils.database import database as db_module

        # Bypass __new__ singleton — we want a standalone Database that doesn't
        # mutate any class-level state.
        instance = object.__new__(db_module.Database)
        # Manually initialize the attributes that __init__ normally sets.
        instance._initialized = True  # Prevent __init__ body from running again if called.
        instance.db_path = str(db_file)
        instance._schema_initialized = False
        instance._export_pending = False
        instance._export_delay = 3
        instance._export_tasks = set()
        instance._pool_semaphore = None
        instance._connection_count = 0
        instance._conn_pool = None
        instance._pool_initialized = False
        instance._checkpoint_task = None
        instance._export_pending_keys = set()
        instance._dashboard_export_pending = set()
        import asyncio
        instance._export_lock = asyncio.Lock()
        instance._write_lock = None

        await instance.init_schema()
        try:
            yield instance
        finally:
            await instance.close_pool()
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_pin_and_unpin_message_persists(fresh_db):
    db = fresh_db

    # Create a conversation + one message.
    conv_id = "conv-pin-test"
    await db.create_dashboard_conversation(
        conv_id,
        title="Pin test",
        role_preset="general",
        system_instruction="",
        thinking_enabled=False,
    )
    msg_id = await db.save_dashboard_message(conv_id, "user", "hello")
    assert msg_id > 0

    # Initially not pinned.
    msgs = await db.get_dashboard_messages(conv_id)
    assert len(msgs) == 1
    assert msgs[0]["is_pinned"] is False

    # Pin it.
    assert await db.update_dashboard_message_pin(msg_id, True) is True
    msgs = await db.get_dashboard_messages(conv_id)
    assert msgs[0]["is_pinned"] is True

    # Unpin it.
    assert await db.update_dashboard_message_pin(msg_id, False) is True
    msgs = await db.get_dashboard_messages(conv_id)
    assert msgs[0]["is_pinned"] is False


@pytest.mark.asyncio
async def test_pin_missing_message_returns_false(fresh_db):
    db = fresh_db
    # Pinning a non-existent message must return False and not raise.
    result = await db.update_dashboard_message_pin(9_999_999, True)
    assert result is False


@pytest.mark.asyncio
async def test_pinned_partial_index_present(fresh_db):
    """Migration 013 + init_schema should have created the partial index."""
    import sqlite3

    conn = sqlite3.connect(fresh_db.db_path)
    try:
        cur = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_dashboard_messages_pinned",),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None, "partial index idx_dashboard_messages_pinned should exist"
    # Confirm it really is a partial index on is_pinned=1 (not a plain one).
    assert "WHERE is_pinned = 1" in row[0] or "WHERE is_pinned=1" in row[0]


# ============================================================================
# Integration tests for #20b (liked) and #22 (conversation tags)
# ============================================================================

@pytest.mark.asyncio
async def test_like_and_unlike_message_persists(fresh_db):
    db = fresh_db
    conv_id = "conv-like-test"
    await db.create_dashboard_conversation(
        conv_id, title="Like test", role_preset="general",
        system_instruction="", thinking_enabled=False,
    )
    msg_id = await db.save_dashboard_message(conv_id, "assistant", "a response")

    msgs = await db.get_dashboard_messages(conv_id)
    assert msgs[0]["liked"] is False

    assert await db.update_dashboard_message_liked(msg_id, True) is True
    msgs = await db.get_dashboard_messages(conv_id)
    assert msgs[0]["liked"] is True

    assert await db.update_dashboard_message_liked(msg_id, False) is True
    msgs = await db.get_dashboard_messages(conv_id)
    assert msgs[0]["liked"] is False


@pytest.mark.asyncio
async def test_conversation_tags_roundtrip(fresh_db):
    db = fresh_db
    conv_id = "conv-tag-test"
    await db.create_dashboard_conversation(
        conv_id, title="Tag test", role_preset="general",
        system_instruction="", thinking_enabled=False,
    )

    # Starts with no tags.
    assert await db.get_conversation_tags(conv_id) == []

    # Add 3 tags.
    assert await db.add_conversation_tag(conv_id, "important") is True
    assert await db.add_conversation_tag(conv_id, "work") is True
    assert await db.add_conversation_tag(conv_id, "brainstorm") is True

    # Sorted alphabetically on read.
    assert await db.get_conversation_tags(conv_id) == ["brainstorm", "important", "work"]

    # Duplicate add is idempotent (returns False, doesn't raise).
    assert await db.add_conversation_tag(conv_id, "important") is False

    # Remove one.
    assert await db.remove_conversation_tag(conv_id, "work") is True
    assert await db.get_conversation_tags(conv_id) == ["brainstorm", "important"]

    # Remove missing tag returns False.
    assert await db.remove_conversation_tag(conv_id, "not-there") is False


@pytest.mark.asyncio
async def test_tag_normalization_and_validation(fresh_db):
    db = fresh_db
    conv_id = "conv-tag-validate"
    await db.create_dashboard_conversation(
        conv_id, title="x", role_preset="general",
        system_instruction="", thinking_enabled=False,
    )

    # Whitespace stripped, case lowercased.
    assert await db.add_conversation_tag(conv_id, "  IMPORTANT  ") is True
    assert await db.get_conversation_tags(conv_id) == ["important"]

    # Empty / too-long rejected.
    assert await db.add_conversation_tag(conv_id, "") is False
    assert await db.add_conversation_tag(conv_id, "x" * 65) is False


@pytest.mark.asyncio
async def test_list_all_conversation_tags_counts(fresh_db):
    db = fresh_db
    # Two conversations sharing one tag, one unique tag each.
    for cid, tags in [("c1", ["a", "b"]), ("c2", ["a", "c"])]:
        await db.create_dashboard_conversation(
            cid, title=cid, role_preset="general",
            system_instruction="", thinking_enabled=False,
        )
        for t in tags:
            await db.add_conversation_tag(cid, t)

    all_tags = await db.list_all_conversation_tags()
    tag_map = {row["tag"]: row["count"] for row in all_tags}
    assert tag_map == {"a": 2, "b": 1, "c": 1}
    # Sort: higher count first, then tag asc — "a" must come first.
    assert all_tags[0]["tag"] == "a"


@pytest.mark.asyncio
async def test_tags_cascade_delete_on_conversation_delete(fresh_db):
    db = fresh_db
    await db.create_dashboard_conversation(
        "temp-conv", title="x", role_preset="general",
        system_instruction="", thinking_enabled=False,
    )
    await db.add_conversation_tag("temp-conv", "cascades")
    assert await db.get_conversation_tags("temp-conv") == ["cascades"]

    await db.delete_dashboard_conversation("temp-conv")
    # FK ON DELETE CASCADE should have wiped the tag too.
    assert await db.get_conversation_tags("temp-conv") == []
