"""Full LangGraph run over the real MCP wire (stdio subprocess) against the
REAL lens-mcp binary — proves the LENS_MCP_CMD swap is config-only with zero
graph-code changes (docs/ARCHITECTURE.md, docs/CONTRACT.md swap promise).

Same scenario as test_lens.test_gate_approval_finalizes_cited_artifacts, but
the bridge spawns `lens-mcp` (SQLite corpus seeded from fixtures) instead of
`lens-stub`. Both process sides audit into the same JSONL (CONTRIBUTING rule 4).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from langgraph.types import Command

from lens.graph import build_graph
from lens.ingest import ingest_fixtures
from lens.mcp_bridge import McpBridge
from lens.models import ScriptedModel

SUBJECT = "ocds-vn56pm-stub-0004"
REAL_CMD = str(Path(sys.executable).parent / "lens-mcp")


def test_full_graph_over_wire_against_real_server(tmp_path, monkeypatch):
    db = tmp_path / "corpus.sqlite"
    assert ingest_fixtures(db)["ingested"] == 10
    monkeypatch.setenv("LENS_DB", str(db))
    monkeypatch.setenv("LENS_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.chdir(tmp_path)
    model = ScriptedModel()

    async def go():
        async with McpBridge(REAL_CMD, "lens-mcp", model=model.name) as bridge:
            graph = build_graph(bridge, model)
            cfg = {"configurable": {"thread_id": "wire-test"}}
            r1 = await graph.ainvoke(
                {"subject_ocid": SUBJECT, "model": model.name,
                 "task": "price_reasonableness", "repair_count": 0}, cfg)
            assert "__interrupt__" in r1, "graph must halt at the human gate"
            return await graph.ainvoke(
                Command(resume={"approved": True, "approver": "Wire Test"}), cfg)

    result = asyncio.run(go())
    assert not result.get("error"), result.get("error")

    brief = result["artifacts"]["brief"]
    brief_path = Path(brief["brief_path"])
    assert brief_path.exists() and brief["citation_count"] >= 1
    text = brief_path.read_text(encoding="utf-8").lower()
    assert SUBJECT in text
    assert "not an award decision" in text

    flags = result["artifacts"]["flags"]
    assert flags and flags[0]["status"] == "approved"

    events = [json.loads(line)
              for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    kinds = {e.get("kind") for e in events}
    # node: graph-side | mcp_call: bridge-side | tool_call: SERVER-side | human_gate
    assert {"node", "mcp_call", "tool_call", "human_gate"} <= kinds
    assert all("model" in e for e in events)
    gate = [e for e in events if e.get("kind") == "human_gate"]
    assert gate and gate[0]["approver"] == "Wire Test" and gate[0]["gate"] == "approved"
