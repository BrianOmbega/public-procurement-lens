"""MCP client bridge — the graph talks to lens-mcp over the real MCP wire
(stdio), never in-process, so swapping stub → real server is config-only
(LENS_MCP_CMD). Graph-side calls are audited with node/model context; the
server audits its own side too (docs/CONTRIBUTING.md rule 4).

BORROWED SERVER (challenge requirement #4): official `mcp-server-fetch` via
uvx. One-line why: it is maintained by the MCP project itself — redirects,
robots and encoding handled — so the agent can cite regulation text and
portal pages live instead of us shipping a fragile scraper we must maintain.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from lens.audit import audit_event

DEFAULT_LENS_CMD = str(Path(sys.executable).parent / "lens-stub")
DEFAULT_FETCH_CMD = f"{sys.executable} -m mcp_server_fetch"  # in-venv module exec: uvx launcher needs realpath (absent on macOS 12)


def _text_of(result: Any) -> str:
    return "\n".join(c.text for c in getattr(result, "content", []) if getattr(c, "text", None))


class McpBridge:
    """Async context manager owning one MCP stdio session."""

    def __init__(self, command: str, server_name: str, model: str = "unset") -> None:
        parts = shlex.split(command)
        self._params = StdioServerParameters(command=parts[0], args=parts[1:],
                                             env=dict(os.environ), cwd=str(Path.cwd()))
        self.server_name = server_name
        self.model = model
        self._stdio_cm: Any = None
        self._sess_cm: Optional[ClientSession] = None
        self._session: Optional[ClientSession] = None

    async def __aenter__(self) -> "McpBridge":
        self._stdio_cm = stdio_client(self._params)
        read, write = await self._stdio_cm.__aenter__()
        self._sess_cm = ClientSession(read, write)
        self._session = await self._sess_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._sess_cm is not None:
            await self._sess_cm.__aexit__(*exc)
        if self._stdio_cm is not None:
            await self._stdio_cm.__aexit__(*exc)

    async def call(self, tool: str, **args: Any) -> dict:
        assert self._session is not None, "bridge used outside async-with"
        result = await self._session.call_tool(tool, args)
        payload = self._unwrap(result)
        audit_event(tool=f"{self.server_name}:{tool}", request=args, response=payload,
                    kind="mcp_call", model=self.model, server=self.server_name)
        return payload

    @staticmethod
    def _unwrap(result: Any) -> dict:
        if getattr(result, "isError", False):
            return {"code": "tool_error", "message": _text_of(result)[:500]}
        sc = getattr(result, "structuredContent", None)
        if isinstance(sc, dict):
            # some FastMCP-style servers wrap dict returns under "result"
            if set(sc.keys()) == {"result"} and isinstance(sc.get("result"), dict):
                return sc["result"]
            return sc
        txt = _text_of(result)
        try:
            parsed = json.loads(txt)
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        except (json.JSONDecodeError, ValueError):
            return {"raw": txt}
