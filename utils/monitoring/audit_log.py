"""
Audit Logging Module
Tracks administrative actions for security and accountability.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


logger = logging.getLogger(__name__)

# Fallback JSONL file used when the DB layer is unavailable. We append-only
# so audit history isn't silently lost when sqlite is broken at import time.
_FALLBACK_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "audit_fallback.jsonl"
# Lazy-init lock so the binding to a running event loop happens at first
# call rather than import time — constructing an asyncio.Lock at import
# time has historically tripped tests that load this module before
# starting the loop, and any future Python that tightens loop-policy
# behaviour at import time would break it again.
_FALLBACK_LOCK: asyncio.Lock | None = None


def _get_fallback_lock() -> asyncio.Lock:
    global _FALLBACK_LOCK
    if _FALLBACK_LOCK is None:
        _FALLBACK_LOCK = asyncio.Lock()
    return _FALLBACK_LOCK


def _scrub_str(v: Any) -> Any:
    if isinstance(v, str):
        return v.replace("\r", " ").replace("\n", " ")[:500]
    return v


# Tamper-evidence chain. Each audit row stores entry_hash = HMAC(key, prev_hash
# + fields). With AUDIT_LOG_HMAC_KEY set (a secret NOT stored in the DB), an
# attacker who edits/deletes a row can't recompute the chain without the key;
# without the key it degrades to a plain SHA-256 chain that still catches naive
# edits. The append-only triggers (database.py) block in-place edits outright;
# the chain makes deletions / out-of-band writes detectable via verify_chain().
_AUDIT_HMAC_KEY = os.getenv("AUDIT_LOG_HMAC_KEY", "")
_jsonl_prev_hash = ""  # running prev_hash for the JSONL-fallback chain (per process)


def _compute_entry_hash(
    prev_hash: str,
    action_type: Any,
    guild_id: Any,
    user_id: Any,
    target_id: Any,
    details: Any,
    created_at: Any,
) -> str:
    """HMAC-SHA256 (keyed) or SHA-256 (unkeyed) over prev_hash + the row fields."""
    canonical = "\x1f".join(
        str(x) for x in (prev_hash, action_type, guild_id, user_id, target_id, details, created_at)
    )
    data = canonical.encode("utf-8", errors="replace")
    if _AUDIT_HMAC_KEY:
        return hmac.new(_AUDIT_HMAC_KEY.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


def _add_jsonl_chain(entry: dict[str, Any]) -> dict[str, Any]:
    """Attach prev_hash/entry_hash to a JSONL-fallback entry.

    Uses a per-process running hash (resets on restart — the JSONL fallback is
    a degraded DB-down path; the DB chain is the authoritative one).

    NOTE: this computes the chain links but does NOT advance the running head —
    that is committed by ``_write_fallback_chained`` only after the entry is
    actually persisted, so a failed write can't leave the next entry chained
    off a record that never reached disk (a false tamper signal on replay).
    """
    prev = _jsonl_prev_hash
    h = _compute_entry_hash(
        prev,
        entry.get("action"),
        entry.get("guild_id"),
        entry.get("user_id"),
        entry.get("target_id"),
        entry.get("details"),
        entry.get("ts"),
    )
    entry["prev_hash"] = prev
    entry["entry_hash"] = h
    return entry


async def _write_fallback_chained(entry: dict[str, Any]) -> bool:
    """Chain + write one fallback entry, advancing the running hash only on a
    confirmed write.

    The whole read-chain -> write -> head-commit critical section runs under a
    single hold of ``_get_fallback_lock()`` so two concurrent fallback writers
    can't both read the same stale ``_jsonl_prev_hash`` before either advances
    it (which would fork the tamper-evidence chain with two entries sharing one
    ``prev_hash``). asyncio.Lock is not re-entrant, so the inner writer below
    must NOT re-acquire it.
    """
    global _jsonl_prev_hash
    async with _get_fallback_lock():
        chained = _add_jsonl_chain(entry)  # reads _jsonl_prev_hash under lock
        ok = await _write_fallback_entry_locked(chained)
        if ok:
            _jsonl_prev_hash = chained["entry_hash"]  # commit head under same lock
        return ok


async def _write_fallback_entry_locked(entry: dict[str, Any]) -> bool:
    """Append one audit row to the JSONL fallback file.

    Caller MUST already hold ``_get_fallback_lock()`` (see
    ``_write_fallback_chained``); this function does not acquire it, so the
    read-chain/write/commit stays one atomic critical section.

    The file handle is opened inside a ``with`` so close is deterministic — on
    Windows a leaked handle could collide with a rotating-logs sweeper's Path
    lock on the next write.
    """

    def _do_write(line: str) -> None:
        with _FALLBACK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)

    try:
        _FALLBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        await asyncio.to_thread(_do_write, line)
        return True
    except Exception:
        logger.exception("Audit fallback write failed; entry lost")
        return False


class AuditLogger:
    """Async-compatible logger for tracking administrative actions."""

    async def log_action(
        self,
        user_id: int,
        action: str,
        guild_id: int | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        details: str | None = None,
    ) -> bool:
        """Log an administrative action.

        Args:
            user_id: ID of the user performing the action
            action: Type of action (e.g., 'channel_create', 'role_assign', 'ban')
            guild_id: Guild where action occurred
            target_type: Type of target (e.g., 'channel', 'role', 'user')
            target_id: ID of the target
            details: Additional details as JSON string

        Returns:
            True if logged successfully
        """
        if not DB_AVAILABLE:
            # Strip newlines / control chars from string fields so a
            # crafted action / details string can't inject extra log
            # lines. The %s formatter does NOT escape these by default.
            logger.info(
                "📋 AUDIT: [%s] %s (target: %s:%s) - %s",
                guild_id,
                _scrub_str(action),
                _scrub_str(target_type),
                target_id,
                _scrub_str(details),
            )
            # Persist to JSONL so an audit trail survives DB outages. Logger
            # output alone is not durable — log files rotate and are not a
            # tamper-resistant audit substrate.
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "ts_epoch": time.time(),
                "user_id": user_id,
                "action": _scrub_str(action),
                "guild_id": guild_id,
                "target_type": _scrub_str(target_type),
                "target_id": target_id,
                "details": _scrub_str(details),
                "fallback_reason": "db_unavailable",
            }
            return await _write_fallback_chained(entry)

        try:
            # Embed target_type into details JSON if provided
            full_details = details or "{}"
            if target_type:
                try:
                    d = json.loads(full_details) if full_details != "{}" else {}
                    d["target_type"] = target_type
                    full_details = json.dumps(d, ensure_ascii=False)
                except json.JSONDecodeError:
                    # If details is not valid JSON, wrap it
                    full_details = json.dumps({"original": details, "target_type": target_type})

            # Set created_at explicitly (not via the column DEFAULT) so the
            # exact value is part of the hash and stays verifiable later.
            created_at = datetime.now(timezone.utc).isoformat()
            async with db.get_write_connection() as conn:
                # Read the tail hash and insert under the same write lock so the
                # chain can't interleave with a concurrent audit write.
                cur = await conn.execute(
                    "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
                )
                last = await cur.fetchone()
                prev_hash = (last[0] if last and last[0] else "") or ""
                entry_hash = _compute_entry_hash(
                    prev_hash, action, guild_id, user_id, target_id, full_details, created_at
                )
                await conn.execute(
                    """
                    INSERT INTO audit_log
                        (guild_id, user_id, action_type, target_id, details,
                         created_at, prev_hash, entry_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        guild_id,
                        user_id,
                        action,
                        target_id,
                        full_details,
                        created_at,
                        prev_hash,
                        entry_hash,
                    ),
                )
                await conn.commit()

            logger.debug("📋 Logged audit action: %s by user %s", action, user_id)
            return True

        except Exception:
            logger.exception("Failed to log audit action; falling back to JSONL")
            # DB write failed at runtime (disk full, lock timeout, …).
            # Drop the entry into the JSONL fallback so the audit trail
            # isn't lost. Previously this returned False and the entry
            # vanished, defeating the whole point of an audit log.
            try:
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "ts_epoch": time.time(),
                    "user_id": user_id,
                    "action": _scrub_str(action),
                    "guild_id": guild_id,
                    "target_type": _scrub_str(target_type),
                    "target_id": target_id,
                    "details": _scrub_str(details),
                    "fallback_reason": "db_write_failed",
                }
                return await _write_fallback_chained(entry)
            except Exception:
                logger.exception("Audit JSONL fallback also failed")
                return False

    async def get_recent_actions(self, guild_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent actions for a guild.

        Args:
            guild_id: Guild ID to query
            limit: Maximum number of entries to return

        Returns:
            List of audit log entries
        """
        if not DB_AVAILABLE:
            return []

        try:
            async with db.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT id, user_id, action_type, target_id, details, created_at
                    FROM audit_log
                    WHERE guild_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (guild_id, limit),
                )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

        except Exception:
            logger.exception("Failed to get audit log")
            return []

    async def verify_chain(self) -> tuple[bool, int | None]:
        """Verify the audit hash chain. Returns ``(ok, first_bad_id)``.

        Walks rows oldest→newest, recomputing each ``entry_hash`` from the
        running prev_hash + fields. A mismatch (or a broken prev_hash link)
        means a row was edited or one was deleted. Legacy rows written before
        chaining have NULL hashes and are skipped (the chain starts at the
        first hashed row).
        """
        if not DB_AVAILABLE or db is None:
            return True, None
        try:
            async with db.get_connection() as conn:
                cur = await conn.execute(
                    "SELECT id, action_type, guild_id, user_id, target_id, details, "
                    "created_at, prev_hash, entry_hash FROM audit_log ORDER BY id ASC"
                )
                rows = await cur.fetchall()
        except Exception:
            logger.exception("verify_chain: query failed")
            return False, None
        prev = ""
        for r in rows:
            entry_hash = r["entry_hash"]
            if entry_hash is None:
                continue  # legacy pre-chain row — skip, chain starts later
            if (r["prev_hash"] or "") != prev:
                return False, r["id"]
            expect = _compute_entry_hash(
                prev,
                r["action_type"],
                r["guild_id"],
                r["user_id"],
                r["target_id"],
                r["details"],
                r["created_at"],
            )
            if expect != entry_hash:
                return False, r["id"]
            prev = entry_hash
        return True, None


# Global audit logger instance
audit = AuditLogger()


# Convenience async functions
async def log_admin_action(
    user_id: int, action: str, guild_id: int | None = None, **kwargs
) -> bool:
    """Log an administrative action (convenience function)."""
    return await audit.log_action(user_id, action, guild_id, **kwargs)


async def log_channel_change(
    user_id: int, guild_id: int, action: str, channel_id: int, channel_name: str
) -> bool:
    """Log a channel-related action."""
    return await audit.log_action(
        user_id=user_id,
        action=f"channel_{action}",
        guild_id=guild_id,
        target_type="channel",
        target_id=channel_id,
        details=json.dumps({"name": channel_name}, ensure_ascii=False),
    )


async def log_role_change(
    user_id: int,
    guild_id: int,
    action: str,
    role_id: int,
    role_name: str,
    target_user_id: int | None = None,
) -> bool:
    """Log a role-related action."""
    details_dict: dict[str, str | int] = {"name": role_name}
    if target_user_id:
        details_dict["target_user"] = target_user_id

    return await audit.log_action(
        user_id=user_id,
        action=f"role_{action}",
        guild_id=guild_id,
        target_type="role",
        target_id=role_id,
        details=json.dumps(details_dict, ensure_ascii=False),
    )
