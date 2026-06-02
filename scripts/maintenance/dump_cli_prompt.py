"""Dump exactly what the CLI handler would send to Claude for a given conversation.

Reads the conversation from SQLite, calls build_user_context(), and shows the
final prompt assembly so we can verify no foreign chat data is leaking in.

By default this script prints only metadata (sizes, section counts) — passing
``--full`` additionally prints the full prompt text. Be careful with --full:
the prompt embeds persona and full message history, which is generally
sensitive data that you do not want to paste into an issue tracker or share
unredacted.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Avoid the dashboard-CLI module pulling its full dep graph at import time
# we just want build_user_context + the prompt builder.
from cogs.ai_core.api.dashboard_chat_claude_cli import _build_full_prompt
from cogs.ai_core.api.dashboard_common import build_user_context
from cogs.ai_core.api.dashboard_config import DASHBOARD_ROLE_PRESETS


async def main(title_substr: str = "", show_full: bool = False) -> None:
    db_path = ROOT / "data" / "bot_database.db"
    # SQLite LIKE treats ``%`` and ``_`` as wildcards. Without escaping,
    # a CLI arg containing ``%`` would match every conversation in the DB.
    _esc_substr = title_substr.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with sqlite3.connect(db_path) as raw:
        raw.row_factory = sqlite3.Row
        row = raw.execute(
            "SELECT id, title, role_preset FROM dashboard_conversations "
            "WHERE title LIKE ? ESCAPE '\\'",
            (f"%{_esc_substr}%",),
        ).fetchone()
        if not row:
            print(f"No conversation matching {title_substr!r}")
            return
        conv_id = row["id"]
        print(f"Conversation : {row['title']}  ({conv_id})")
        print(f"Preset       : {row['role_preset']}")

        msgs = raw.execute(
            "SELECT id, role, content, created_at FROM dashboard_messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
        print(f"DB messages  : {len(msgs)}")

    # build_user_context relies on the bot's get_db() singleton.
    user_context, _ = await build_user_context(
        "User",
        False,
        conversation_id=conv_id,
    )

    history = [
        {"role": m["role"], "content": m["content"], "created_at": m["created_at"]} for m in msgs
    ]
    preset = DASHBOARD_ROLE_PRESETS.get(row["role_preset"], DASHBOARD_ROLE_PRESETS["general"])
    persona = str(preset.get("system_instruction", ""))

    prompt = _build_full_prompt(
        persona=persona,
        user_context=user_context,
        history=history,
        history_limit=100,
        current_message="<<<NEXT TURN HERE>>>",
        image_paths=[],
        doc_paths=[],
        is_resumed_session=False,
    )

    print()
    print("=" * 72)
    print(f"PROMPT (length: {len(prompt):,} chars)")
    print("=" * 72)
    if show_full:
        print(prompt)
        print("=" * 72)
        print()
    else:
        print("(redacted — pass --full to print the prompt body)")
        print()

    # Sections breakdown — always shown, contains no message bodies.
    parts = prompt.split("\n# ")
    print(f"Top-level sections: {len(parts)}")
    for p in parts:
        first_line = p.splitlines()[0] if p.splitlines() else ""
        size = len(p)
        print(f"  # {first_line[:60]:60s}  ({size:,} chars)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--full"]
    full_flag = "--full" in sys.argv[1:]
    arg = args[0] if args else "ไงงงงงง"
    asyncio.run(main(arg, show_full=full_flag))
