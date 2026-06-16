"""Localhost IPC endpoint that executes the AI's tool calls inside the bot.

The Claude CLI can only take custom tools via an MCP server it spawns as a
child process (``mcp_tools_server.py``). That child can't reach the live
discord.py ``bot``/guild or the in-memory long-term-memory manager, so it
proxies every ``tools/call`` to THIS endpoint over authenticated localhost
HTTP. Here — in the bot process, on the event loop — we run the tool with the
real bot state:

  - memory tools (``remember`` / ``recall_memory``) go straight to the live
    ``long_term_memory`` manager (so writes hit the same index reads use), and
  - server tools (create channel/role, read channel, …) are dispatched through
    the existing :func:`cogs.ai_core.tools.execute_tool_call`, which already
    enforces the requesting member's Discord permissions and reuses the
    battle-tested ``COMMAND_HANDLERS``.

Security model:
  - Binds 127.0.0.1 on an OS-assigned port; the URL is handed to the child via
    env, never exposed off-host.
  - Every request must carry the per-process ``X-Token`` shared secret.
  - Server (Discord-mutating / reading) tools are OFF unless the operator sets
    ``DASHBOARD_CLI_SERVER_ACTIONS=1`` — and even then each call is gated by the
    chatting member's own guild permissions (a non-admin can't drive an admin
    action). Memory tools are read/write of the user's OWN facts and default on.
"""

from __future__ import annotations

import functools
import hmac
import logging
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from discord.ext.commands import Bot

logger = logging.getLogger(__name__)


def _flag(name: str, default: str) -> bool:
    # A SET-but-blank env var (e.g. ``export FOO=``) returns "" from getenv, NOT
    # the default — and "" isn't in the falsy set, so a *cleared* security gate
    # would otherwise read as enabled. Treat blank/whitespace as "use default".
    val = os.getenv(name, default).strip()
    if not val:
        val = default.strip()
    return val.lower() not in ("0", "false", "no", "off")


# Memory tools are safe (a user's own facts) — on by default. Server tools touch
# the guild, so they are opt-in and additionally permission-checked per call.
def _memory_enabled() -> bool:
    return _flag("DASHBOARD_CLI_AI_TOOLS", "1")


def _server_actions_enabled() -> bool:
    return _flag("DASHBOARD_CLI_SERVER_ACTIONS", "0")


# Tools handled directly here against the live memory manager.
_MEMORY_TOOLS = ("remember", "recall_memory")

# Server tools that only READ — their cmd_* post output to the channel and
# return a status string, so we run them against a capture channel and hand the
# collected text back to the model instead (mirrors execute_tool_call's own set).
_READ_ONLY_TOOLS = frozenset(
    {"list_channels", "list_roles", "list_members", "get_user_info", "read_channel"}
)


class _CaptureChannel:
    """Proxy that delegates every attribute to a real Discord channel EXCEPT
    ``send`` — which it collects instead of posting. Lets the read-only cmd_*
    run with their real permission filtering (against the delegated guild/member)
    while we capture their text output for the AI rather than spamming chat."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self._sent: list[str] = []

    async def send(self, content: str = "", **_kwargs: Any) -> None:
        if content:
            self._sent.append(str(content))

    def text(self) -> str:
        return "\n".join(self._sent)

    def __getattr__(self, name: str) -> Any:
        # Reached only for attributes not set on the instance (e.g. .guild, .id,
        # .permissions_for) — delegate them to the real channel.
        return getattr(self._real, name)


_MEMORY_TOOL_SCHEMAS = [
    {
        "name": "remember",
        "description": (
            "Save an important fact about the user to long-term memory so you "
            "recall it in future conversations. Use for stable preferences, "
            "personal details the user shares, or commitments — not trivia."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to remember, one sentence."}
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall_memory",
        "description": (
            "Retrieve what you've stored about the current user in long-term "
            "memory. Call before answering questions that depend on the user's "
            "history or preferences. Optionally filter by a keyword."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to filter facts (substring match).",
                }
            },
            "required": [],
        },
    },
]

_TYPE_MAP = {
    "STRING": "string",
    "OBJECT": "object",
    "INTEGER": "integer",
    "BOOLEAN": "boolean",
    "NUMBER": "number",
    "ARRAY": "array",
}


def _server_tool_schemas() -> list[dict[str, Any]]:
    """Translate the Gemini-format server tool defs to MCP JSON-Schema, minus
    ``remember`` (handled by the memory path above)."""
    from ..tools import get_tool_definitions

    out: list[dict[str, Any]] = []
    for group in get_tool_definitions():
        for fn in group.get("function_declarations", []):
            if fn["name"] in _MEMORY_TOOLS:
                continue
            params = fn.get("parameters", {}) or {}
            props = {}
            for pname, pdef in (params.get("properties", {}) or {}).items():
                props[pname] = {
                    "type": _TYPE_MAP.get(str(pdef.get("type", "STRING")).upper(), "string"),
                    "description": pdef.get("description", ""),
                }
            out.append(
                {
                    "name": fn["name"],
                    "description": fn["description"],
                    "inputSchema": {
                        "type": "object",
                        "properties": props,
                        "required": list(params.get("required", [])),
                    },
                }
            )
    return out


@functools.cache
def _server_tool_names() -> frozenset[str]:
    # get_tool_definitions() is process-invariant, so memoize the derived name
    # set — avoids rebuilding the full MCP schema list on every /exec dispatch.
    return frozenset(t["name"] for t in _server_tool_schemas())


def list_tool_schemas() -> list[dict[str, Any]]:
    """The MCP tool list exposed to the model, honouring the enable flags."""
    tools: list[dict[str, Any]] = []
    if _memory_enabled():
        tools.extend(_MEMORY_TOOL_SCHEMAS)
    if _server_actions_enabled():
        tools.extend(_server_tool_schemas())
    return tools


class _AiToolsIpc:
    """Holds the running aiohttp site + the bot reference + the auth token."""

    def __init__(self) -> None:
        self.bot: Bot | None = None
        self.token: str = ""
        self.url: str = ""
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def ready(self) -> bool:
        return bool(self.url and self.token and self.bot is not None)

    async def start(self, bot: Bot) -> None:
        if self._runner is not None:
            return  # already started
        import secrets

        self.bot = bot
        self.token = secrets.token_urlsafe(32)
        app = web.Application()
        app.router.add_get("/tools", self._handle_tools)
        app.router.add_post("/exec", self._handle_exec)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        # Resolve the OS-assigned port.
        port = 0
        for sockaddr in self._runner.addresses:
            if isinstance(sockaddr, tuple) and len(sockaddr) >= 2:
                port = sockaddr[1]
                break
        if not port:
            await self.stop()
            raise RuntimeError("AI-tools IPC could not determine its bound port")
        self.url = f"http://127.0.0.1:{port}"
        logger.info(
            "🔧 AI-tools IPC listening on %s (memory=%s server=%s)",
            self.url,
            _memory_enabled(),
            _server_actions_enabled(),
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        self.url = ""
        self.token = ""

    def env(self) -> dict[str, str]:
        """The env the spawned ``claude`` needs so its MCP child can reach us."""
        if not self.ready:
            return {}
        return {"BOT_AI_TOOLS_IPC_URL": self.url, "BOT_AI_TOOLS_IPC_TOKEN": self.token}

    def _authed(self, request: web.Request) -> bool:
        # Constant-time compare — this is the auth gate for Discord-mutating
        # tool execution; ``==`` on the shared secret leaks length/prefix
        # timing. (ws_dashboard uses hmac.compare_digest for its equivalent.)
        token = request.headers.get("X-Token") or ""
        return bool(self.token) and hmac.compare_digest(token, self.token)

    async def _handle_tools(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"tools": list_tool_schemas()})

    async def _handle_exec(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"result": "Malformed request body.", "is_error": True})
        # A valid-JSON non-object (`[]`, `"x"`, `1`) passes request.json() but
        # would AttributeError on data.get below — return the intended error
        # instead of an unhandled 500 with a traceback.
        if not isinstance(data, dict):
            return web.json_response({"result": "Malformed request body.", "is_error": True})
        tool = str(data.get("tool", ""))
        args = data.get("args") or {}
        ctx = data.get("context") or {}
        if not isinstance(args, dict):
            args = {}
        # Mirror the args guard: a non-dict truthy `context` (list/str) would
        # otherwise reach _dispatch_*'s `ctx.get(...)` and AttributeError into
        # the broad except below, surfacing a confusing "'list' object has no
        # attribute 'get'" instead of the intended clean empty-context path.
        if not isinstance(ctx, dict):
            ctx = {}
        try:
            result, is_error = await self._dispatch(tool, args, ctx)
        except Exception as e:
            logger.exception("AI tool '%s' raised", tool)
            # The raw exception string is returned to the MCP child and fed back
            # to the model, so funnel it through the project-wide secret-redaction
            # filter first (mirrors api_failover._safe_error_summary). Fall back to
            # the exception type name if redaction itself is unavailable.
            try:
                from utils.monitoring.logger import _redact_sensitive

                detail = _redact_sensitive(str(e))
            except Exception:
                detail = type(e).__name__
            result, is_error = f"Tool '{tool}' failed: {detail}", True
        return web.json_response({"result": result, "is_error": is_error})

    async def _dispatch(self, tool: str, args: dict, ctx: dict) -> tuple[str, bool]:
        if tool in _MEMORY_TOOLS:
            if not _memory_enabled():
                return "Memory tools are disabled.", True
            return await self._dispatch_memory(tool, args, ctx)
        if tool in _server_tool_names():
            if not _server_actions_enabled():
                return "Server tools are disabled (set DASHBOARD_CLI_SERVER_ACTIONS=1).", True
            return await self._dispatch_server(tool, args, ctx)
        return f"Unknown tool: {tool}", True

    async def _dispatch_memory(self, tool: str, args: dict, ctx: dict) -> tuple[str, bool]:
        from ..memory.long_term_memory import long_term_memory

        user_id = ctx.get("user_id")
        if not isinstance(user_id, int):
            return "No user context for memory tool.", True
        channel_id = ctx.get("channel_id") if isinstance(ctx.get("channel_id"), int) else None
        if tool == "remember":
            content = str(args.get("content", "")).strip()
            if not content:
                return "Nothing to remember (empty content).", True
            fact = await long_term_memory.add_explicit_fact(user_id, content, channel_id=channel_id)
            # add_explicit_fact returns the EXISTING fact on a duplicate and
            # None ONLY on a store FAILURE — the old `if fact is None` branch
            # had it backwards: it reported a real write failure as a benign
            # "already remembered" with is_error=False (masking the failure),
            # and reported genuine duplicates as a fresh "Remembered: …".
            if fact is None:
                return "Failed to save memory (storage error).", True
            return f"Remembered: {content}", False
        # recall_memory
        query = str(args.get("query", "")).strip().lower()
        facts = await long_term_memory.get_user_facts(user_id)
        if not facts:
            return "No stored facts for this user yet.", False
        lines = [getattr(f, "content", str(f)) for f in facts]
        if query:
            lines = [ln for ln in lines if query in ln.lower()]
        if not lines:
            return f"No stored facts match '{query}'.", False
        return "Stored facts:\n" + "\n".join(f"- {ln}" for ln in lines[:20]), False

    async def _dispatch_server(self, tool: str, args: dict, ctx: dict) -> tuple[str, bool]:
        from ..tools import execute_tool_call

        if self.bot is None:
            return "Bot unavailable.", True
        channel_id = ctx.get("channel_id")
        user_id = ctx.get("user_id")
        if not isinstance(channel_id, int) or not isinstance(user_id, int):
            return "No guild/channel/user context for server tool.", True
        channel = self.bot.get_channel(channel_id)
        guild = getattr(channel, "guild", None)
        if channel is None or guild is None:
            return "Channel/guild not found.", True
        member = guild.get_member(user_id)
        if member is None:
            return "Requesting member not found in guild.", True
        # execute_tool_call reads .input (dict) for Anthropic-shape tool calls;
        # it enforces the member's guild permissions internally.
        tool_call = SimpleNamespace(name=tool, input=args)
        if tool in _READ_ONLY_TOOLS:
            # The read cmd_* POST their (permission-filtered) output to the
            # channel and return only a status string. For the AI to actually
            # USE the data, run them against a capture channel — this REUSES
            # execute_tool_call's vetted view-permission filtering verbatim (no
            # risky reimplementation) but collects the text instead of spamming
            # the chat with embeds, and returns it to the model.
            capture = _CaptureChannel(channel)
            status = await execute_tool_call(self.bot, capture, member, tool_call)
            data = capture.text().strip()
            if data:
                return data, data.startswith(("⛔", "❌"))
            # Nothing captured → a permission denial / error came back as the
            # status string; surface that (is_error if it looks like a refusal).
            text = str(status)
            return text, text.startswith(("⛔", "❌"))
        result = await execute_tool_call(self.bot, channel, member, tool_call)
        text = str(result)
        return text, text.startswith(("⛔", "❌"))


# Module-level singleton.
ai_tools_ipc = _AiToolsIpc()


async def start_ai_tools_ipc(bot: Bot) -> None:
    """Start the IPC endpoint (best-effort; failure leaves tools simply absent)."""
    try:
        await ai_tools_ipc.start(bot)
    except Exception:
        logger.exception("Failed to start AI-tools IPC; AI tools will be unavailable")


async def stop_ai_tools_ipc() -> None:
    try:
        await ai_tools_ipc.stop()
    except Exception:
        logger.exception("Error stopping AI-tools IPC")
