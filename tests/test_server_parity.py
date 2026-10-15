"""Stub <-> real-server parity (docs/CONTRACT.md "Stub parity").

Same request through both servers, in-process, over the same fixture corpus:
identical responses (or identical code+message for structured errors). The
only sanctioned deltas are documented in mcp_server.py's module docstring
(result ORDER under truncation); everything else must be equal, because both
servers delegate to the same lens.analysis / lens.actions cores.
"""
from __future__ import annotations

import json

import pytest

from lens import mcp_server
from lens.ingest import ingest_fixtures
from lens.stubs import stub_mcp


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    db = tmp_path / "corpus.sqlite"
    ingest_fixtures(db)
    monkeypatch.setenv("LENS_DB", str(db))
    monkeypatch.setenv("LENS_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.chdir(tmp_path)
    return db


def _sorted_awards(resp: dict) -> list[dict]:
    return sorted(resp.get("awards", []), key=lambda a: a["ocid"])


def test_search_parity_full_pages(seeded):
    cases = [
        {"query": "patient monitor"},
        {"query": ""},
        {"query": "", "fiscal_year": "2026/2027"},
        {"query": "reagents", "buyer": "nakuru"},
        {"query": "cleaning"},
    ]
    for req in cases:
        s = stub_mcp.search_awards(**req)
        r = mcp_server.search_awards(**req)
        assert s["total_matched"] == r["total_matched"], req
        assert s["truncated"] == r["truncated"] is False, req
        assert _sorted_awards(s) == _sorted_awards(r), req


def test_search_parity_truncated_page(seeded):
    # Ordering is a documented delta (stub: fixture order; real: date DESC),
    # so under truncation the totals/flags must match and both pages be full.
    s = stub_mcp.search_awards(query="patient monitor", limit=2)
    r = mcp_server.search_awards(query="patient monitor", limit=2)
    assert s["total_matched"] == r["total_matched"] == 5
    assert s["truncated"] is r["truncated"] is True
    assert len(s["awards"]) == len(r["awards"]) == 2


def test_supplier_history_parity(seeded):
    for name in ("medtech solutions ltd.", "bluebird supplies ltd", "labcare ltd"):
        s = stub_mcp.get_supplier_history(supplier=name)
        r = mcp_server.get_supplier_history(supplier=name)
        assert s == r, name
    s3 = stub_mcp.get_supplier_history(supplier="ghost supplier ltd")
    r3 = mcp_server.get_supplier_history(supplier="ghost supplier ltd")
    assert s3["code"] == r3["code"] == "supplier_not_found"
    assert s3["message"] == r3["message"]


def test_price_analysis_parity(seeded):
    req = {"item_query": "patient monitor", "subject_ocid": "ocds-vn56pm-stub-0004"}
    s = stub_mcp.analyze_price(**req)
    r = mcp_server.analyze_price(**req)
    assert s == r  # median, mad, outliers, assessment, notes, sources — identical
    assert "OUTLIER" in r["subject_assessment"]
    req2 = {"item_query": "laboratory reagents"}
    assert stub_mcp.analyze_price(**req2) == mcp_server.analyze_price(**req2)
    s3 = stub_mcp.analyze_price(item_query="zzz-nothing-matches")
    r3 = mcp_server.analyze_price(item_query="zzz-nothing-matches")
    assert s3["code"] == r3["code"] == "no_comparables"
    assert s3["message"] == r3["message"]


def test_action_tool_parity(seeded):
    # Gate is checked BEFORE citations, so an unauthorised caller gets
    # approval_required rather than citation feedback.
    uncited = [{"claim": "c", "evidence": "e", "sources": []}]
    bad_s = stub_mcp.draft_committee_brief(title="t", findings=uncited)
    bad_r = mcp_server.draft_committee_brief(title="t", findings=uncited)
    assert bad_s == bad_r and bad_s["code"] == "approval_required"

    src = {"ocid": "ocds-vn56pm-stub-0004", "field_path": "awards[0].value.amount"}
    # With a valid named approver, the citation rule is what rejects it.
    bad2_s = stub_mcp.draft_committee_brief(title="t", findings=uncited, approver="Test Approver")
    bad2_r = mcp_server.draft_committee_brief(title="t", findings=uncited, approver="Test Approver")
    assert bad2_s == bad2_r and bad2_s["code"] == "citation_required"

    kwargs = {"category": "price_outlier", "severity": "high", "claim": "c", "evidence": "e",
              "subject_ocids": ["ocds-vn56pm-stub-0004"], "sources": [src],
              "recommended_action": "a"}
    fs = stub_mcp.raise_flag(**kwargs)
    fr = mcp_server.raise_flag(**kwargs)
    assert fs["status"] == fr["status"] == "pending_approval"
    assert fs["requires_approval"] is fr["requires_approval"] is True
    assert fs["flags_path"] == fr["flags_path"]
    lines = (seeded.parent / "output" / "flags.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(x)["status"] == "pending_approval" for x in lines)


def test_gated_brief_refuses_without_named_human(seeded, tmp_path, monkeypatch):
    """Requirement: a gate on every irreversible action. draft_committee_brief
    writes to disk, so it must refuse — and write nothing — without a valid
    named human approver. Identical behaviour on stub and real server."""
    out = tmp_path / "gated"
    monkeypatch.setenv("LENS_OUTPUT", str(out))
    cited = [{"claim": "c", "evidence": "e", "severity": "high",
              "sources": [{"ocid": "ocds-vn56pm-stub-0004"}]}]

    for server in (stub_mcp, mcp_server):
        for bad_approver, expected in ((None, "approval_required"),
                                       ("", "approval_required"),
                                       ("auto", "approver_invalid"),
                                       ("x", "approver_invalid"),
                                       ("ollama/qwen3:1.7b", "approver_invalid")):
            r = server.draft_committee_brief(title="t", findings=cited, approver=bad_approver)
            assert r["code"] == expected, (server.__name__, bad_approver, r)
    assert not out.exists() or not any(out.iterdir()), "refused call must not write a brief"

    ok_s = stub_mcp.draft_committee_brief(title="t", findings=cited, approver="Test Approver")
    ok_r = mcp_server.draft_committee_brief(title="t", findings=cited, approver="Test Approver")
    assert ok_s["citation_count"] == ok_r["citation_count"] == 1
    assert ok_s["approver"] == ok_r["approver"] == "Test Approver"


def test_model_cannot_approve_its_own_flag(seeded, monkeypatch):
    """The acting model passing its own name as approver must not promote a
    flag to approved."""
    monkeypatch.setenv("MODEL", "ollama/qwen3:1.7b")
    src = {"ocid": "ocds-vn56pm-stub-0004"}
    kwargs = {"category": "price_outlier", "severity": "high", "claim": "c", "evidence": "e",
              "subject_ocids": ["ocds-vn56pm-stub-0004"], "sources": [src],
              "recommended_action": "a"}
    for bad in ("ollama/qwen3:1.7b", "qwen3:1.7b", "auto", "agent"):
        r = mcp_server.raise_flag(**kwargs, approver=bad)
        assert r["code"] == "approver_invalid", (bad, r)
    good = mcp_server.raise_flag(**kwargs, approver="Jane Mwikali")
    assert good["status"] == "approved"


def test_missing_corpus_is_structured_not_fatal(seeded, monkeypatch):
    monkeypatch.setenv("LENS_DB", str(seeded.parent / "nope.sqlite"))
    for call in (lambda: mcp_server.search_awards(query="x"),
                 lambda: mcp_server.get_supplier_history(supplier="x"),
                 lambda: mcp_server.analyze_price(item_query="x")):
        r = call()
        assert r["code"] == "internal"
        assert "lens-ingest" in r["detail"]
