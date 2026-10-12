"""Tests for the orchestration invariants — run offline (scripted model + stub MCP).

Covers the judge-facing guarantees:
- citation validator rejects uncited AND hallucinated-ocid findings
- full graph run halts at the human gate; approval finalizes cited artifacts
- gate rejection writes NOTHING (no brief, no flags)
- every audit event carries the model identity
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from langgraph.types import Command

from lens.graph import build_graph, validate_findings
from lens.mcp_bridge import DEFAULT_LENS_CMD, McpBridge
from lens.models import ScriptedModel

SUBJECT = "ocds-vn56pm-stub-0004"


def test_validate_rejects_uncited():
    accepted, rejected = validate_findings(
        [{"claim": "c", "evidence": "e", "sources": []}], {SUBJECT}
    )
    assert not accepted
    assert len(rejected) == 1 and "schema" in rejected[0]["reason"]


def test_validate_rejects_hallucinated_ocid():
    finding = {"claim": "c", "evidence": "e", "severity": "high",
               "sources": [{"ocid": "ocds-fake-9999"}]}
    accepted, rejected = validate_findings([finding], {SUBJECT})
    assert not accepted
    assert "not in evidence" in rejected[0]["reason"]


def test_validate_accepts_cited():
    finding = {"claim": "c", "evidence": "e", "severity": "high",
               "sources": [{"ocid": SUBJECT, "field_path": "awards[0].value.amount"}]}
    accepted, rejected = validate_findings([finding], {SUBJECT})
    assert len(accepted) == 1 and not rejected


def _run_graph(tmp_path, monkeypatch, resume_decision):
    monkeypatch.setenv("LENS_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.chdir(tmp_path)
    model = ScriptedModel()

    async def go():
        async with McpBridge(DEFAULT_LENS_CMD, "lens-test", model=model.name) as bridge:
            graph = build_graph(bridge, model)
            cfg = {"configurable": {"thread_id": "pytest-thread"}}
            r1 = await graph.ainvoke(
                {"subject_ocid": SUBJECT, "model": model.name,
                 "task": "price_reasonableness", "repair_count": 0}, cfg)
            assert "__interrupt__" in r1, "graph must halt at the human gate"
            r2 = await graph.ainvoke(Command(resume=resume_decision), cfg)
            return r1, r2

    return asyncio.run(go())


def test_gate_approval_finalizes_cited_artifacts(tmp_path, monkeypatch):
    _, result = _run_graph(tmp_path, monkeypatch,
                           {"approved": True, "approver": "Test Approver"})
    assert not result.get("error")
    arts = result["artifacts"]
    brief = Path(arts["brief"]["brief_path"])
    assert brief.exists()
    text = brief.read_text(encoding="utf-8").lower()
    assert SUBJECT in text
    assert "not an award decision" in text
    assert arts["brief"]["citation_count"] >= 1
    flags = arts["flags"]
    assert flags and flags[0]["status"] == "approved"

    events = [json.loads(line)
              for line in (tmp_path / "audit.jsonl").read_text().splitlines() if line.strip()]
    gate = [e for e in events if e.get("kind") == "human_gate"]
    assert gate and gate[0]["approver"] == "Test Approver" and gate[0]["gate"] == "approved"
    assert all("model" in e for e in events)


def test_gate_rejection_writes_nothing(tmp_path, monkeypatch):
    _, result = _run_graph(tmp_path, monkeypatch, {"approved": False})
    assert result.get("error")
    assert not result.get("artifacts")
    assert not (tmp_path / "output").exists(), "rejection must not write brief or flags"
