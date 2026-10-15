"""lens-audit verify — the trail must be checkable, and the checker must fail.

A verifier that cannot fail is decoration. Each test here tampers with one
property the challenge requires (inputs/outputs, timestamps, model attribution,
a named human on every irreversible action, artifacts matching events) and
asserts the specific check catches it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lens.audit_cli import verify
from lens.schemas.contract import ACTION_TOOLS, GATED_TOOLS

TS = "2026-10-15T12:00:00Z"
APPROVER = "Jane Mwikali"


def _event(tool: str, **kw) -> dict:
    ev = {"ts": kw.pop("ts", TS), "kind": kw.pop("kind", "tool_call"), "tool": tool,
          "model": kw.pop("model", "scripted"), "session": kw.pop("session", "test"),
          "request": kw.pop("request", {}), "response": kw.pop("response", {})}
    ev.update(kw)
    return ev


def _write(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e, default=str) for e in events) + "\n",
                    encoding="utf-8")


@pytest.fixture
def trail(tmp_path):
    """A minimal but complete gated run: read call, gated write on both sides
    of the wire, a flag, and the human gate that authorised them."""
    brief = tmp_path / "brief-20261015-120000.md"
    brief.write_text("# Brief\n\n**Authorised by:** Jane Mwikali\n", encoding="utf-8")
    (tmp_path / "flags.jsonl").write_text(
        json.dumps({"flag_id": "abc123", "status": "approved", "approver": APPROVER}) + "\n",
        encoding="utf-8")
    events = [
        _event("demo_start", kind="run"),
        _event("search_awards", response={"total_matched": 3}),
        _event("lens-mcp:draft_committee_brief", kind="mcp_call", approver=APPROVER,
               response={"brief_path": str(brief), "citation_count": 1, "approver": APPROVER}),
        _event("draft_committee_brief", approver=APPROVER, gate="approved",
               response={"brief_path": str(brief), "citation_count": 1, "approver": APPROVER}),
        _event("raise_flag", approver=APPROVER, gate="approved",
               response={"flag_id": "abc123", "flags_path": str(tmp_path / "flags.jsonl"),
                         "status": "approved"}),
        _event("human_gate", kind="human_gate", approver=APPROVER, gate="approved"),
    ]
    path = tmp_path / "audit.jsonl"
    # Distinct, increasing timestamps: with one shared value a reordering
    # tamper would be a no-op and the monotonicity check untestable.
    for i, ev in enumerate(events):
        ev["ts"] = f"2026-10-15T12:00:{i:02d}Z"
    _write(path, events)
    return path, tmp_path, events


def test_gated_tools_declares_every_irreversible_action():
    assert set(GATED_TOOLS) == set(ACTION_TOOLS)
    assert {"draft_committee_brief", "raise_flag"} <= set(GATED_TOOLS)


def test_verify_passes_on_clean_trail(trail):
    path, out, _ = trail
    ok, problems = verify(path, out)
    assert ok, problems
    assert problems == []


def test_verify_fails_when_approver_stripped(trail):
    path, out, events = trail
    for ev in events:
        if "draft_committee_brief" in ev["tool"]:
            ev.pop("approver", None)
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("approver_missing" in p for p in problems)


def test_verify_fails_when_approver_is_automation(trail):
    """The model approving its own work must not satisfy the gate."""
    path, out, events = trail
    for ev in events:
        if ev.get("approver"):
            ev["approver"] = "auto"
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("approver_not_human" in p for p in problems)


def test_verify_fails_when_model_self_approves(trail):
    """Isolates the self-approval rule: the model name is neither a denylist
    token nor provider-qualified, so only 'approver == acting model' can fire."""
    path, out, events = trail
    for ev in events:
        ev["model"] = "qwen3"
        if ev.get("approver"):
            ev["approver"] = "qwen3"
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("approver_is_the_model" in p for p in problems)


def test_verify_fails_when_artifact_deleted(trail):
    path, out, _ = trail
    (out / "brief-20261015-120000.md").unlink()
    ok, problems = verify(path, out)
    assert not ok
    assert any("not on disk" in p for p in problems)


def test_verify_fails_on_orphan_artifact(trail):
    """A brief nobody logged is exactly the 'action without a tool call' the
    requirement forbids."""
    path, out, _ = trail
    (out / "brief-20261015-999999.md").write_text("# unlogged\n", encoding="utf-8")
    ok, problems = verify(path, out)
    assert not ok
    assert any("no audit event" in p for p in problems)


def test_verify_fails_on_non_monotonic_timestamps(trail):
    path, out, events = trail
    events[0]["ts"], events[-1]["ts"] = events[-1]["ts"], events[0]["ts"]
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("precede" in p for p in problems)


def test_verify_fails_on_unparseable_timestamp(trail):
    path, out, events = trail
    events[1]["ts"] = "yesterday"
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("yesterday" in p for p in problems)


def test_verify_fails_when_inputs_or_outputs_missing(trail):
    path, out, events = trail
    events[1].pop("response", None)
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("missing fields" in p for p in problems)


def test_verify_fails_when_model_unattributed(trail):
    path, out, events = trail
    events[2]["model"] = "unset"
    _write(path, events)
    ok, problems = verify(path, out)
    assert not ok
    assert any("unset" in p for p in problems)


def test_verify_allows_refused_write_without_approver(trail):
    """A refusal wrote nothing, so demanding an approver for it would be wrong."""
    path, out, events = trail
    events[3] = _event("draft_committee_brief", ts=events[3]["ts"], gate="refused",
                       response={"code": "approval_required",
                                 "message": "brief not written: a NAMED HUMAN approver is required"})
    _write(path, events)
    ok, problems = verify(path, out)
    assert ok, problems


def test_verify_fails_on_empty_trail(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    ok, problems = verify(empty, tmp_path)
    assert not ok
    assert any("empty or missing" in p for p in problems)
