"""Unit tests for the MCP stdio tools server (JSON-RPC framing robustness)."""

from __future__ import annotations

from unittest.mock import patch


class TestHandleToolsCall:
    def test_non_dict_params_does_not_raise(self):
        # Regression: a valid JSON-RPC 2.0 frame may carry array params; the call
        # site passes them through unchanged (`req.get("params") or {}` does not
        # substitute a truthy non-dict). Without the isinstance guard,
        # params.get(...) raised AttributeError that escaped the stdin loop and
        # killed the MCP server for the whole session.
        from cogs.ai_core.api import mcp_tools_server as mcp

        sent: list = []
        with (
            patch.object(mcp, "_send", side_effect=sent.append),
            patch.object(mcp, "_turn_context", return_value={}),
            patch.object(mcp, "_ipc_request", return_value={"result": "ok", "is_error": False}),
        ):
            # Must not raise even though params is a list, not a dict.
            mcp._handle_tools_call(1, ["unexpected", "array"])

        assert sent, "handler should still emit a JSON-RPC response"
        assert sent[0]["id"] == 1

    def test_dict_params_still_dispatch(self):
        from cogs.ai_core.api import mcp_tools_server as mcp

        sent: list = []
        with (
            patch.object(mcp, "_send", side_effect=sent.append),
            patch.object(mcp, "_turn_context", return_value={}),
            patch.object(mcp, "_ipc_request", return_value={"result": "done", "is_error": False}),
        ):
            mcp._handle_tools_call(2, {"name": "ping", "arguments": {}})

        assert sent and sent[0]["id"] == 2
        assert sent[0]["result"]["content"][0]["text"] == "done"
