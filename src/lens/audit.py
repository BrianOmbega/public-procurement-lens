"""Shared JSONL audit trail — challenge requirement: every tool call logged.

One JSON event per line in logs/audit.jsonl (path overridable via LENS_AUDIT):
ts (UTC ISO), kind, tool, model, session, request, response, approver?, extras.
Append-only. The stub uses it now; the real lens-mcp and the LangGraph graph
MUST use the same format (docs/CONTRIBUTING.md rule 4).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def audit_path() -> Path:
    return Path(os.environ.get("LENS_AUDIT", "logs/audit.jsonl"))


def audit_event(
    tool: str,
    request: Any = None,
    response: Any = None,
    *,
    kind: str = "tool_call",
    model: str | None = None,
    session: str | None = None,
    approver: str | None = None,
    **extra: Any,
) -> dict:
    """Append one audit event; returns it. Never raises on odd payloads."""
    event: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        "tool": tool,
        "model": model or os.environ.get("LENS_MODEL") or os.environ.get("MODEL") or "unset",
        "session": session or os.environ.get("LENS_SESSION", "local"),
        "request": _jsonable(request),
        "response": _jsonable(response),
    }
    if approver is not None:
        event["approver"] = approver
    event.update(extra)
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
    return event


def read_audit(path: Path | None = None) -> list[dict]:
    p = path or audit_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return str(obj)
