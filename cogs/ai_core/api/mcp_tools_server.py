"""Standalone MCP (stdio) server that proxies the AI's tool calls to the bot.

``claude -p`` (subscription mode) only accepts CUSTOM tools through an MCP
server it spawns as a child process. This script IS that server: a thin
stdio JSON-RPC proxy. It owns no tool logic — on ``tools/list`` and
``tools/call`` it forwards to the running bot's localhost IPC endpoint
(``cogs/ai_core/api/ai_tools_ipc.py``), which executes the tool in-process
with the live bot/guild state, permission checks, and memory manager.

CRITICAL: this process is spawned by ``claude`` and its STDOUT carries the
JSON-RPC stream — nothing else may be printed there. So it imports ONLY the
stdlib (no bot modules, which print banners at import and would corrupt the
protocol stream), and every diagnostic goes to STDERR.

Transport: newline-delimited JSON-RPC 2.0 over stdio (the MCP stdio framing).

Configuration comes entirely from the environment (set by the bot when it
spawns ``claude`` for a turn):
  - BOT_AI_TOOLS_IPC_URL    base URL of the bot IPC (e.g. http://127.0.0.1:PORT)
  - BOT_AI_TOOLS_IPC_TOKEN  shared secret; sent as the X-Token header
  - BOT_AI_TOOLS_GUILD_ID / _CHANNEL_ID / _USER_ID  per-turn Discord context
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, cast

_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "bottools"
_HTTP_TIMEOUT = 30.0


def _log(msg: str) -> None:
    """Diagnostics go to stderr — stdout is reserved for JSON-RPC."""
    sys.stderr.write(f"[mcp_tools_server] {msg}\n")
    sys.stderr.flush()


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


# The IPC endpoint is always loopback (127.0.0.1 / localhost). Build a
# dedicated opener with an EMPTY ProxyHandler so an operator's HTTP_PROXY /
# HTTPS_PROXY — which the bot deliberately allowlists into this subprocess's
# env so claude itself can reach Anthropic — doesn't route the loopback IPC
# call (and the X-Token shared secret) out through that external proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _ipc_request(path: str, payload: dict | None) -> dict:
    """Call the bot IPC. Returns the parsed JSON body, or raises on failure."""
    base = os.environ.get("BOT_AI_TOOLS_IPC_URL", "").rstrip("/")
    token = os.environ.get("BOT_AI_TOOLS_IPC_TOKEN", "")
    if not base or not token:
        raise RuntimeError("bot IPC not configured")
    url = f"{base}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json", "X-Token": token},
    )
    with _OPENER.open(req, timeout=_HTTP_TIMEOUT) as resp:
        return cast(dict, json.loads(resp.read().decode("utf-8")))


def _turn_context() -> dict:
    """Per-turn Discord context the bot uses to scope + permission-check tools."""
    ctx: dict = {}
    for env_key, ctx_key in (
        ("BOT_AI_TOOLS_GUILD_ID", "guild_id"),
        ("BOT_AI_TOOLS_CHANNEL_ID", "channel_id"),
        ("BOT_AI_TOOLS_USER_ID", "user_id"),
    ):
        raw = os.environ.get(env_key)
        if raw:
            try:
                ctx[ctx_key] = int(raw)
            except ValueError:
                pass
    return ctx


def _handle_tools_list(mid) -> None:
    try:
        body = _ipc_request("/tools", None)
        tools = body.get("tools", [])
    except Exception as e:
        _log(f"tools/list failed: {e}")
        tools = []
    _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})


def _handle_tools_call(mid, params: Any) -> None:
    # A valid JSON-RPC 2.0 frame may carry array (or other non-object) params;
    # `req.get("params") or {}` at the call site does NOT substitute a truthy
    # non-dict (e.g. ["x"]), so without this guard params.get(...) below raises
    # AttributeError, which escapes the stdin loop and kills the server for the
    # whole session — the same class already guarded for `req` in main().
    if not isinstance(params, dict):
        params = {}
    name = params.get("name", "")
    arguments = params.get("arguments") or {}
    try:
        body = _ipc_request(
            "/exec",
            {"tool": name, "args": arguments, "context": _turn_context()},
        )
        text = str(body.get("result", ""))
        is_error = bool(body.get("is_error"))
    except urllib.error.HTTPError as e:
        text = f"Tool call rejected by bot (HTTP {e.code})."
        is_error = True
    except Exception as e:
        _log(f"tools/call '{name}' failed: {e}")
        text = f"Tool call failed: {type(e).__name__}"
        is_error = True
    _send(
        {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    )


def main() -> None:
    # Force UTF-8 on stdio: claude writes UTF-8 JSON-RPC, but on Windows (and
    # any locale where Python's default stdio encoding is a legacy codepage,
    # e.g. cp874/cp1252) a non-ASCII tool argument — Thai text in this repo —
    # would raise UnicodeDecodeError on read and kill the server mid-session.
    # PYTHONUTF8/PYTHONIOENCODING are NOT in the bot's subprocess env
    # allowlist, so reconfigure here rather than relying on the environment.
    try:
        # .reconfigure exists on TextIOWrapper but not the narrower TextIO type
        # the stubs give sys.stdin/stdout; the except below handles streams that
        # genuinely lack it at runtime.
        cast(Any, sys.stdin).reconfigure(encoding="utf-8", errors="replace")
        cast(Any, sys.stdout).reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # already UTF-8, or a stream that doesn't support reconfigure

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        # A valid-JSON non-object (batch array, string, number) would make
        # req.get(...) raise AttributeError and kill the whole server,
        # dropping every tool for the session. Skip it instead.
        if not isinstance(req, dict):
            continue
        method = req.get("method")
        mid = req.get("id")
        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": _PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": _SERVER_NAME, "version": "1.0"},
                    },
                }
            )
        elif method in ("notifications/initialized", "initialized"):
            continue  # notification — no response
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif method == "tools/list":
            _handle_tools_list(mid)
        elif method == "tools/call":
            _handle_tools_call(mid, req.get("params") or {})
        elif mid is not None:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )


if __name__ == "__main__":
    main()
