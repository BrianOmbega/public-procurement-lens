"""Stub implementation of the lens-mcp contract (docs/CONTRACT.md v0.1).

Lets the LangGraph orchestration be built and tested BEFORE the real MCP
server exists: same tools, same request/response models, fixtures instead of
the SQLite corpus. The real lens-mcp replaces this via LENS_MCP_CMD with zero
graph-code changes. Not for submission demo runs against real data.

Read-tool logic lives in lens.analysis and action-tool bodies in lens.actions
— both shared with the real server (src/lens/mcp_server.py), so stub ↔ real
parity holds by construction, not by coincidence.

Run as MCP server (stdio):  uv run lens-stub
Contract selftest:          uv run lens-stub --selftest
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lens import actions as _actions
from lens.analysis import (
    award_summary,
    build_price_analysis,
    build_supplier_history,
    match_buyer,
    match_text,
    supplier_matches,
)
from lens.audit import audit_event, read_audit
from lens.schemas.contract import (
    ACTION_TOOLS,
    CONTRACT_VERSION,
    TOOL_NAMES,
    PriceAnalysisRequest,
    SearchAwardsRequest,
    SearchAwardsResponse,
    SupplierHistoryRequest,
    ToolError,
)
from lens.stubs.fixtures import FIXTURE_RELEASES

mcp = FastMCP("lens-stub")


@mcp.tool()
def search_awards(query: str = "", fiscal_year: str | None = None,
                  buyer: str | None = None, limit: int = 20) -> dict:
    """Search Kenyan PPIP award records by free text / fiscal year / buyer (stub: fixtures)."""
    req = SearchAwardsRequest(query=query, fiscal_year=fiscal_year, buyer=buyer, limit=limit)
    hits = [r for r in FIXTURE_RELEASES
            if match_text(r, req.query) and (req.fiscal_year is None or r.get("fiscal_year") == req.fiscal_year)
            and match_buyer(r, req.buyer)]
    resp = SearchAwardsResponse(awards=[award_summary(r) for r in hits[: req.limit]],
                                total_matched=len(hits), truncated=len(hits) > req.limit)
    audit_event("search_awards", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def get_supplier_history(supplier: str, normalize: bool = True, limit: int = 50) -> dict:
    """Award history for a supplier, with alias/identifier normalisation (stub: fixtures)."""
    req = SupplierHistoryRequest(supplier=supplier, normalize=normalize, limit=limit)
    matched, aliases = supplier_matches(FIXTURE_RELEASES, req.supplier, req.normalize)
    if not matched:
        err = ToolError(code="supplier_not_found", message=f"no awards found for supplier '{supplier}'",
                        detail="stub corpus is small; check spelling or pass normalize=false")
        audit_event("get_supplier_history", req, err)
        return err.model_dump(mode="json")
    resp = build_supplier_history(req.supplier, matched, aliases, req.limit)
    audit_event("get_supplier_history", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def analyze_price(item_query: str, buyer: str | None = None,
                  fiscal_years: list[str] | None = None, subject_ocid: str | None = None) -> dict:
    """Median/MAD price analysis vs comparable awards; flags outliers; optional verdict on a subject award."""
    req = PriceAnalysisRequest(item_query=item_query, buyer=buyer,
                               fiscal_years=fiscal_years or [], subject_ocid=subject_ocid)
    fys = set(req.fiscal_years)
    pool = [r for r in FIXTURE_RELEASES if match_text(r, req.item_query)
            and match_buyer(r, req.buyer) and (not fys or r.get("fiscal_year") in fys)]
    subject = next((r for r in pool if r["ocid"] == req.subject_ocid), None)
    resp = build_price_analysis(req.item_query, pool, subject)
    if resp is None:
        err = ToolError(code="no_comparables",
                        message=f"fewer than 2 comparable priced awards for '{req.item_query}'",
                        detail="stub corpus: try 'patient monitor' or 'laboratory reagents'")
        audit_event("analyze_price", req, err)
        return err.model_dump(mode="json")
    audit_event("analyze_price", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def draft_committee_brief(title: str, findings: list[dict],
                          subject_ocids: list[str] | None = None, context: str = "") -> dict:
    """ACTION: writes a cited markdown brief to output/. Findings without sources are rejected."""
    return _actions.draft_committee_brief(title=title, findings=findings,
                                          subject_ocids=subject_ocids, context=context)


@mcp.tool()
def raise_flag(category: str, severity: str, claim: str, evidence: str,
               subject_ocids: list[str], sources: list[dict],
               recommended_action: str, approver: str | None = None) -> dict:
    """ACTION (gated): appends a structured flag to output/flags.jsonl; pending_approval until named approver."""
    return _actions.raise_flag(category=category, severity=severity, claim=claim, evidence=evidence,
                               subject_ocids=subject_ocids, sources=sources,
                               recommended_action=recommended_action, approver=approver)


def _selftest() -> int:
    print(f"lens-stub selftest — contract {CONTRACT_VERSION} "
          f"({len(TOOL_NAMES)} tools: {len(TOOL_NAMES) - len(ACTION_TOOLS)} read, {len(ACTION_TOOLS)} action)")
    before = len(read_audit())
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if not cond and detail else ""))
        if not cond:
            failures.append(name)

    check("all 5 contract tools implemented",
          {"search_awards", "get_supplier_history", "analyze_price",
           "draft_committee_brief", "raise_flag"} == set(TOOL_NAMES))

    r = search_awards(query="patient monitor")
    check("search_awards returns fixtures", r.get("total_matched", 0) >= 4, str(r)[:200])
    malformed = [a for a in r.get("awards", [])
                 if any("startDate" in n for n in a.get("data_quality_notes", []))]
    check("malformed-date record surfaced with DQ note (no crash)", len(malformed) >= 1)

    r2 = get_supplier_history(supplier="medtech solutions ltd.")
    check("supplier alias normalisation (3 spellings collapse)",
          len(r2.get("aliases_matched", [])) >= 2 and r2.get("total_awards", 0) >= 2,
          json.dumps(r2)[:200])

    r3 = analyze_price(item_query="patient monitor", subject_ocid="ocds-vn56pm-stub-0004")
    check("price analysis flags outlier comparables", len(r3.get("outliers", [])) >= 1,
          json.dumps(r3)[:300])
    check("subject 5x award assessed OUTLIER", "OUTLIER" in (r3.get("subject_assessment") or ""),
          str(r3.get("subject_assessment")))

    bad = draft_committee_brief(title="t", findings=[{"claim": "c", "evidence": "e", "sources": []}])
    check("uncited finding rejected (citation_required)", bad.get("code") == "citation_required",
          str(bad)[:200])

    ocid, src = "ocds-vn56pm-stub-0004", {"ocid": "ocds-vn56pm-stub-0004", "field_path": "awards[0].value.amount"}
    r4 = draft_committee_brief(
        title="Price reasonableness review — patient monitors",
        findings=[{"claim": "Award value is ~5x the comparable median",
                   "evidence": "KES 2,400,000 vs median ~KES 495,000 across 4 comparables",
                   "severity": "high", "sources": [src]}],
        subject_ocids=[ocid])
    check("brief drafted with citation", r4.get("citation_count", 0) >= 1
          and Path(r4.get("brief_path", "")).exists(), str(r4)[:200])

    r5 = raise_flag(category="price_outlier", severity="high", claim="~5x median price",
                    evidence="analyze_price robust z >= +3 vs 4 comparables",
                    subject_ocids=[ocid], sources=[src],
                    recommended_action="Committee to request written price justification before any award decision")
    check("flag gated: pending_approval without approver",
          r5.get("status") == "pending_approval" and r5.get("requires_approval") is True, str(r5)[:200])

    r6 = raise_flag(category="price_outlier", severity="high", claim="~5x median price",
                    evidence="as above", subject_ocids=[ocid], sources=[src],
                    recommended_action="as above", approver="Njoki (selftest)")
    check("named approver flips flag to approved", r6.get("status") == "approved", str(r6)[:200])

    gained = len(read_audit()) - before
    check(f"audit trail gained >=5 events (got {gained})", gained >= 5)

    print("\n" + (f"SELFTEST FAILED: {', '.join(failures)}" if failures
                  else "SELFTEST PASSED — 5/5 tools; citation + gate + audit invariants hold"))
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="lens-stub", description="Stub lens-mcp server (contract v0.1)")
    ap.add_argument("--selftest", action="store_true",
                    help="exercise all contract tools in-process, verify invariants, exit 0/1")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(_selftest())
    mcp.run()  # stdio transport, same as the real server will use


if __name__ == "__main__":
    main()
