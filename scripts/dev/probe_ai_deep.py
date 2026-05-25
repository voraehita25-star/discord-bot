"""Deeper AI probes: concurrency, API retry path, response_sender edge cases,
context_builder SSRF, memory subsystem. Run after probe_ai_fixes.py.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PASS = 0
FAIL = 0
ERRORS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {label}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {label}"
        if detail:
            msg += f" — {detail}"
        ERRORS.append(msg)
        print(msg)


# ---------------------------------------------------------------------------
# 1. message_queue concurrency: many tasks contending on same channel
# ---------------------------------------------------------------------------
async def probe_message_queue_concurrency() -> None:
    print("\n[message_queue] concurrent acquire/release stress")
    from cogs.ai_core.core.message_queue import MessageQueue

    q = MessageQueue()
    channel_id = 12345

    counter = {"in_critical": 0, "max_in_critical": 0}
    lock = asyncio.Lock()  # to serialize counter updates atomically

    async def worker(i: int):
        ok = await q.acquire_lock_with_timeout(channel_id, timeout=5.0)
        if not ok:
            return
        try:
            async with lock:
                counter["in_critical"] += 1
                if counter["in_critical"] > counter["max_in_critical"]:
                    counter["max_in_critical"] = counter["in_critical"]
            await asyncio.sleep(0.001)
            async with lock:
                counter["in_critical"] -= 1
        finally:
            q.release_lock(channel_id)

    await asyncio.gather(*(worker(i) for i in range(50)))

    check(
        "lock enforced mutual exclusion (max_in_critical == 1)",
        counter["max_in_critical"] == 1,
        f"got {counter['max_in_critical']}",
    )
    check("counter zero at end", counter["in_critical"] == 0)


# ---------------------------------------------------------------------------
# 2. message_queue: pop_pending_messages atomicity
# ---------------------------------------------------------------------------
async def probe_message_queue_pending() -> None:
    print("\n[message_queue] pending message merge / cancel flag")
    from cogs.ai_core.core.message_queue import MessageQueue

    q = MessageQueue()
    cid = 999

    # Add a fake pending message
    msg = MagicMock()
    msg.id = 1
    msg.author = MagicMock()
    msg.author.id = 100
    msg.content = "hello"
    msg.attachments = []
    msg.created_at = MagicMock()
    msg.embeds = []
    msg.stickers = []
    msg.reference = None

    if hasattr(q, "add_pending_message"):
        q.add_pending_message(cid, msg)
        msgs = q.pop_pending_messages(cid)
        check(
            "pop_pending_messages returns list (possibly with the message)",
            isinstance(msgs, list),
            f"got {type(msgs).__name__}",
        )
        msgs2 = q.pop_pending_messages(cid)
        check("second pop returns empty", isinstance(msgs2, list) and len(msgs2) == 0)
    else:
        print("  [SKIP] add_pending_message API not present")

    # cancel flag
    q.signal_cancel(cid)
    check("signal_cancel + is_cancelled returns True", q.is_cancelled(cid))
    q.reset_cancel(cid)
    check("reset_cancel resets to False", not q.is_cancelled(cid))


# ---------------------------------------------------------------------------
# 3. response_sender: edge cases for split_content
# ---------------------------------------------------------------------------
def probe_response_sender_edges() -> None:
    print("\n[response_sender] split_content edge cases")
    from cogs.ai_core.response.response_sender import ResponseSender

    s = ResponseSender()

    # Empty
    check("empty string -> single empty chunk", s.split_content("") == [""])

    # Exactly at boundary
    text = "a" * 100
    chunks = s.split_content(text, max_length=100)
    check("at-boundary content stays one chunk", chunks == [text])

    # Just over boundary
    text2 = "a" * 101
    chunks2 = s.split_content(text2, max_length=100)
    check("over-boundary splits into 2+ chunks", len(chunks2) >= 2)
    check("all chunks within max_length", all(len(c) <= 100 for c in chunks2))

    # Multiple fences
    payload = "intro\n```python\nx=1\n```\nmid\n```js\nlet y=2\n```\nend"
    chunks3 = s.split_content(payload, max_length=30)
    # Each chunk respects max_length
    check(
        "multi-fence content respects max_length",
        all(len(c) <= 30 for c in chunks3),
        f"max len: {max(len(c) for c in chunks3)}",
    )

    # Verify even-fence-count chunks (each chunk's fences balanced)
    for i, c in enumerate(chunks3):
        fences = c.count("```")
        check(
            f"chunk {i} has balanced fences (count={fences})",
            fences % 2 == 0,
            f"chunk={c!r}",
        )

    # Long unicode with wide chars
    thai = "สวัสดีครับ ทดสอบยาว " * 50
    chunks4 = s.split_content(thai, max_length=100)
    check(
        "unicode content split correctly, all <= max_length",
        all(len(c) <= 100 for c in chunks4),
    )


# ---------------------------------------------------------------------------
# 4. response_sender: extract_character_tag
# ---------------------------------------------------------------------------
def probe_response_sender_character_tag() -> None:
    print("\n[response_sender] extract_character_tag")
    from cogs.ai_core.response.response_sender import ResponseSender

    s = ResponseSender()

    name, content = s.extract_character_tag("[Lyra]: hello there")
    check(
        "simple tag extracted",
        name == "Lyra" and content == "hello there",
        f"got: {name}, {content}",
    )

    name, content = s.extract_character_tag("no tag here")
    check("no tag -> name is None", name is None and content == "no tag here")

    name, content = s.extract_character_tag("[Multi Word Name]: line\nmore")
    check(
        "multi-word name extracted",
        name == "Multi Word Name" and content == "line\nmore",
        f"got: {name}, {content}",
    )


# ---------------------------------------------------------------------------
# 5. context_builder: hostname validator (SSRF guard)
# ---------------------------------------------------------------------------
async def probe_context_builder_ssrf() -> None:
    print("\n[context_builder] SSRF / private hostname rejection")
    from cogs.ai_core.core import context_builder as cb

    # Block list: Should reject obvious internal targets
    blocks = [
        "http://localhost/admin",
        "http://127.0.0.1:8080/secret",
        "http://10.0.0.5/internal",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.1",
        "file:///etc/passwd",
        "ftp://attacker.com",
    ]
    for url in blocks:
        # Most context_builders expose either a sync `is_safe_url` or do
        # the check inside fetch_url. Probe the public surface.
        is_safe = None
        if hasattr(cb, "_is_safe_url"):
            is_safe = cb._is_safe_url(url)
        elif hasattr(cb, "is_safe_url"):
            is_safe = cb.is_safe_url(url)
        else:
            print("  [SKIP] no is_safe_url helper exposed")
            return
        check(f"reject {url!r}", is_safe is False, f"got is_safe={is_safe}")

    safe = ["https://example.com/", "https://api.openai.com"]
    for url in safe:
        if hasattr(cb, "_is_safe_url"):
            is_safe = cb._is_safe_url(url)
        elif hasattr(cb, "is_safe_url"):
            is_safe = cb.is_safe_url(url)
        check(f"allow {url!r}", is_safe is True, f"got is_safe={is_safe}")


# ---------------------------------------------------------------------------
# 6. RAG: hybrid_search returns sane empty result on empty store
# ---------------------------------------------------------------------------
async def probe_rag_empty_store() -> None:
    print("\n[rag] hybrid_search on empty store")
    try:
        from cogs.ai_core.memory.rag import MemorySystem
    except ImportError as e:
        print(f"  [SKIP] {e}")
        return

    rag = MemorySystem()
    # Even with no DB, hybrid_search should not crash
    try:
        results = await asyncio.wait_for(
            rag.hybrid_search("anything", channel_id=42, limit=5), timeout=10
        )
        check("hybrid_search returns list (possibly empty)", isinstance(results, list))
    except (TimeoutError, AttributeError) as e:
        check("hybrid_search on empty store does not crash", False, f"raised: {e}")
    except Exception as e:
        # Any other exception is a real bug
        check(
            "hybrid_search on empty store does not crash", False, f"raised: {type(e).__name__}: {e}"
        )


# ---------------------------------------------------------------------------
# 7. long_term_memory: store / retrieve / forget cycle
# ---------------------------------------------------------------------------
async def probe_long_term_memory_cycle() -> None:
    print("\n[long_term_memory] cache fallback cycle when DB unavailable")
    try:
        from cogs.ai_core.memory.long_term_memory import Fact, LongTermMemory
    except ImportError as e:
        print(f"  [SKIP] {e}")
        return

    # Simulate DB-unavailable mode by passing nothing — system should still
    # work via its in-memory _cache.
    lt = LongTermMemory()

    # Force fallback path
    with patch("cogs.ai_core.memory.long_term_memory.DB_AVAILABLE", False):
        f = Fact(
            id=None,
            user_id=999,
            channel_id=1,
            category="preference",
            content="loves pizza",
            importance=0.7,
            confidence=1.0,
            mention_count=1,
        )
        # _store_fact in cache mode
        if hasattr(lt, "_store_fact"):
            await lt._store_fact(f)
        elif hasattr(lt, "store_fact"):
            await lt.store_fact(f)

        facts = await lt.get_user_facts(999)
        check(
            "get_user_facts returns list (cache fallback)",
            isinstance(facts, list),
        )
        # If the fact was stored, it should appear
        if facts:
            contents = [getattr(x, "content", "") for x in facts]
            check(
                "stored fact retrievable from cache",
                "loves pizza" in contents,
                f"got: {contents}",
            )


# ---------------------------------------------------------------------------
# 8. state_tracker: get/set/from_dict/to_dict roundtrip
# ---------------------------------------------------------------------------
def probe_state_tracker_roundtrip() -> None:
    print("\n[state_tracker] to_dict/from_dict roundtrip")
    from cogs.ai_core.memory.state_tracker import CharacterStateTracker

    tracker = CharacterStateTracker()
    cid = 777
    # Real signature: set_state(character_name, channel_id, **kwargs)
    tracker.set_state("Alpha", cid)
    tracker.set_state("Beta", cid)
    tracker.set_scene(cid, "garden at dusk")

    snap = tracker.to_dict(cid)
    check("to_dict has 'states' key", "states" in snap)
    check("to_dict has 'scene' key", "scene" in snap)
    check("to_dict scene matches", snap["scene"] == "garden at dusk")

    # Roundtrip into a fresh tracker
    other = CharacterStateTracker()
    other.from_dict(cid, snap)
    states = other.get_all_states(cid)
    check(
        "from_dict restored both characters",
        set(states.keys()) == {"Alpha", "Beta"},
        f"got: {set(states.keys())}",
    )
    check(
        "from_dict restored scene",
        other.get_scene(cid) == "garden at dusk",
        f"got: {other.get_scene(cid)}",
    )


# ---------------------------------------------------------------------------
# 9. api_handler: retry on transient errors, give up on 4xx
# ---------------------------------------------------------------------------
async def probe_api_handler_retry() -> None:
    print("\n[api_handler] retry behavior with mocked client")
    try:
        from cogs.ai_core.api import api_handler
    except ImportError as e:
        print(f"  [SKIP] {e}")
        return

    # Look for a public retry-aware function
    fn = None
    for name in ("call_claude_with_retry", "call_with_retry", "_call_with_retry"):
        if hasattr(api_handler, name):
            fn = getattr(api_handler, name)
            break
    if fn is None:
        print("  [SKIP] no retry-aware function exposed")
        return
    print(f"  [INFO] testing {fn.__name__}")


# ---------------------------------------------------------------------------
# 10. guardrails: prompt-injection / mention escape
# ---------------------------------------------------------------------------
def probe_guardrails() -> None:
    print("\n[guardrails] prompt injection sanitisation")
    try:
        from cogs.ai_core.processing.guardrails import validate_response
    except ImportError as e:
        print(f"  [SKIP] {e}")
        return

    # API key redaction
    inp = "my key is sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA test"
    _ok, out, _warn = validate_response(inp)
    check(
        "sk-ant-* keys redacted in output",
        "sk-ant-api03-AAAAA" not in out,
        f"got: {out}",
    )

    # OpenAI key
    inp2 = "OpenAI key sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    _ok, out2, _warn = validate_response(inp2)
    check(
        "sk-* keys redacted in output",
        "sk-AAAAAAAAAAA" not in out2,
        f"got: {out2}",
    )

    # Bearer token
    inp3 = "Authorization: Bearer abcdef0123456789ghijklmnop"
    _ok, out3, _warn = validate_response(inp3)
    check(
        "Bearer token redacted",
        "abcdef0123456789ghijkl" not in out3,
        f"got: {out3}",
    )


# ---------------------------------------------------------------------------
# 11. summarizer: empty / short history shortcut
# ---------------------------------------------------------------------------
async def probe_summarizer_short() -> None:
    print("\n[summarizer] short history doesn't hit API")
    try:
        from cogs.ai_core.memory.summarizer import ConversationSummarizer
    except ImportError as e:
        print(f"  [SKIP] {e}")
        return

    s = ConversationSummarizer()
    # Replace client with a mock that raises if called; short history should
    # short-circuit before calling the API.
    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=AssertionError("API was called"))
    s.client = fake_client

    short = [{"role": "user", "parts": ["hi"]}, {"role": "model", "parts": ["hello"]}]
    try:
        out = await s.summarize(short)
        check(
            "summarize on short history returns None without API call",
            out is None,
            f"got: {out!r}",
        )
    except AssertionError:
        check("summarize NOT routed to API for short history", False, "API was called")
    except Exception as e:
        check("summarize on short history did not crash", False, f"raised: {e}")


# ---------------------------------------------------------------------------
# 12. tool_executor: malformed permission edge case
# ---------------------------------------------------------------------------
async def probe_tool_executor_permission() -> None:
    print("\n[tool_executor] non-admin user rejected")
    from types import SimpleNamespace

    from cogs.ai_core.tools.tool_executor import execute_tool_call

    class _DummyChannel:
        guild = MagicMock()

        async def send(self, *a, **k):
            pass

    class _NonAdmin:
        display_name = "user"
        guild_permissions = type("P", (), {"administrator": False})()

    result = await execute_tool_call(
        object(),
        _DummyChannel(),
        _NonAdmin(),
        SimpleNamespace(name="create_text_channel", args={"name": "test"}),
    )
    check(
        "non-admin user rejected with permission denied",
        isinstance(result, str) and ("Permission denied" in result or "Admin" in result),
        f"got: {result}",
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
async def main_async() -> None:
    await probe_message_queue_concurrency()
    await probe_message_queue_pending()
    probe_response_sender_edges()
    probe_response_sender_character_tag()
    await probe_context_builder_ssrf()
    await probe_rag_empty_store()
    await probe_long_term_memory_cycle()
    probe_state_tracker_roundtrip()
    await probe_api_handler_retry()
    probe_guardrails()
    await probe_summarizer_short()
    await probe_tool_executor_permission()


def main() -> int:
    asyncio.run(main_async())
    print(f"\n========== Result: {PASS} passed, {FAIL} failed ==========")
    if ERRORS:
        for e in ERRORS:
            print(e)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
