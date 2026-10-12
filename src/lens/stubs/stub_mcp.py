"""Stub implementation of the lens-mcp contract (docs/CONTRACT.md v0.1).

Lets the LangGraph orchestration be built and tested BEFORE the real MCP
server exists: same tools, same request/response models, fixtures instead of
the SQLite corpus. The real lens-mcp replaces this via LENS_MCP_CMD with zero
graph-code changes. Not for submission demo runs against real data.

Run as MCP server (stdio):  uv run lens-stub
Contract selftest:          uv run lens-stub --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import uuid
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from lens.audit import audit_event, read_audit
from lens.schemas.contract import (
    ACTION_TOOLS,
    CONTRACT_VERSION,
    PORTAL_BASE,
    TOOL_NAMES,
    AwardSummary,
    DraftBriefRequest,
    DraftBriefResponse,
    Finding,
    FlagCategory,
    Money,
    PriceAnalysisRequest,
    PriceAnalysisResponse,
    PriceOutlier,
    RaiseFlagRequest,
    RaiseFlagResponse,
    SearchAwardsRequest,
    SearchAwardsResponse,
    Severity,
    SourceRef,
    SupplierHistoryRequest,
    SupplierHistoryResponse,
    ToolError,
)
from lens.stubs.fixtures import FIXTURE_RELEASES

mcp = MCPServer("lens-stub")
OUTPUT_DIR = Path("output")

_SUPPLIER_SUFFIXES = {"LTD", "LIMITED", "LLC", "CO", "COMPANY", "ENTERPRISES", "SUPPLIES", "SERVICES"}


def _norm_supplier(name: str) -> str:
    """MEDTECH SOLUTIONS LTD == Medtech Solutions Ltd. == MED-TECH SOLUTIONS LIMITED."""
    n = re.sub(r"[^A-Z0-9]+", " ", (name or "").upper()).strip()
    return "".join(w for w in n.split() if w not in _SUPPLIER_SUFFIXES)


def _dq_notes(rel: dict) -> list[str]:
    notes: list[str] = []
    tp = (rel.get("tender") or {}).get("tenderPeriod") or {}
    if tp.get("startDate") and tp.get("endDate") and tp["startDate"] > tp["endDate"]:
        notes.append(f"tenderPeriod.startDate ({tp['startDate']}) is after endDate ({tp['endDate']})")
    if not (rel.get("buyer") or {}).get("name"):
        notes.append("buyer name missing in source record")
    awards = rel.get("awards") or [{}]
    for s in awards[0].get("suppliers") or []:
        if not (s.get("identifier") or {}).get("id"):
            notes.append(f"supplier identifier missing for {s.get('name')}")
    return notes


def _summary(rel: dict) -> AwardSummary:
    tender = rel.get("tender") or {}
    awards = rel.get("awards") or []
    aw = awards[0] if awards else {}
    value = aw.get("value")
    items = tender.get("items") or []
    return AwardSummary(
        ocid=rel["ocid"],
        release_id=rel.get("id"),
        fiscal_year=rel.get("fiscal_year"),
        buyer_name=(rel.get("buyer") or {}).get("name"),
        tender_title=tender.get("title"),
        item_description=items[0].get("description") if items else None,
        award_date=aw.get("date"),
        award_value=Money(**value) if value else None,
        supplier_names=[s.get("name", "") for s in (aw.get("suppliers") or [])],
        procurement_method=tender.get("procurementMethod"),
        sources=[SourceRef(ocid=rel["ocid"], release_id=rel.get("id"),
                           field_path="awards[0].value.amount", url=f"{PORTAL_BASE}/ocds")],
        data_quality_notes=_dq_notes(rel),
    )


def _match(rel: dict, query: str) -> bool:
    if not query:
        return True
    t = rel.get("tender") or {}
    parts = [t.get("title") or ""] + [i.get("description") or "" for i in t.get("items") or []]
    return query.lower() in " ".join(parts).lower()


def _buyer_match(rel: dict, buyer: str | None) -> bool:
    return buyer is None or buyer.lower() in (((rel.get("buyer") or {}).get("name")) or "").lower()


@mcp.tool()
def search_awards(query: str = "", fiscal_year: str | None = None,
                  buyer: str | None = None, limit: int = 20) -> dict:
    """Search Kenyan PPIP award records by free text / fiscal year / buyer (stub: fixtures)."""
    req = SearchAwardsRequest(query=query, fiscal_year=fiscal_year, buyer=buyer, limit=limit)
    hits = [r for r in FIXTURE_RELEASES
            if _match(r, req.query) and (req.fiscal_year is None or r.get("fiscal_year") == req.fiscal_year)
            and _buyer_match(r, req.buyer)]
    resp = SearchAwardsResponse(awards=[_summary(r) for r in hits[: req.limit]],
                                total_matched=len(hits), truncated=len(hits) > req.limit)
    audit_event("search_awards", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def get_supplier_history(supplier: str, normalize: bool = True, limit: int = 50) -> dict:
    """Award history for a supplier, with alias/identifier normalisation (stub: fixtures)."""
    req = SupplierHistoryRequest(supplier=supplier, normalize=normalize, limit=limit)
    target = _norm_supplier(supplier) if normalize else (supplier or "").upper()
    matched, aliases = [], set()
    for r in FIXTURE_RELEASES:
        for s in ((r.get("awards") or [{}])[0].get("suppliers") or []):
            nm = s.get("name", "")
            hit = _norm_supplier(nm) == target if normalize else nm.upper() == target
            if hit:
                matched.append(r)
                aliases.add(nm)
    if not matched:
        err = ToolError(code="supplier_not_found", message=f"no awards found for supplier '{supplier}'",
                        detail="stub corpus is small; check spelling or pass normalize=false")
        audit_event("get_supplier_history", req, err)
        return err.model_dump(mode="json")
    summaries = [_summary(r) for r in matched[: req.limit]]
    total = sum(a.award_value.amount for a in summaries if a.award_value)
    by_fy: dict[str, int] = {}
    for a in summaries:
        if a.fiscal_year:
            by_fy[a.fiscal_year] = by_fy.get(a.fiscal_year, 0) + 1
    resp = SupplierHistoryResponse(
        canonical_name=sorted(aliases)[0], aliases_matched=sorted(aliases),
        total_awards=len(summaries), total_value=Money(amount=total),
        awards=summaries, buyers=sorted({a.buyer_name for a in summaries if a.buyer_name}),
        by_fiscal_year=by_fy,
        data_quality_notes=sorted({n for a in summaries for n in a.data_quality_notes}),
        sources=[s for a in summaries for s in a.sources],
    )
    audit_event("get_supplier_history", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def analyze_price(item_query: str, buyer: str | None = None,
                  fiscal_years: list[str] | None = None, subject_ocid: str | None = None) -> dict:
    """Median/MAD price analysis vs comparable awards; flags outliers; optional verdict on a subject award."""
    req = PriceAnalysisRequest(item_query=item_query, buyer=buyer,
                               fiscal_years=fiscal_years or [], subject_ocid=subject_ocid)
    fys = set(req.fiscal_years)
    pool = [r for r in FIXTURE_RELEASES if _match(r, req.item_query)
            and _buyer_match(r, req.buyer) and (not fys or r.get("fiscal_year") in fys)]
    subject = next((r for r in pool if r["ocid"] == req.subject_ocid), None)
    comparables = [r for r in pool if r is not subject] if subject else pool
    valued = [(r, _summary(r)) for r in comparables]
    valued = [(r, s) for r, s in valued if s.award_value]
    if len(valued) < 2:
        err = ToolError(code="no_comparables",
                        message=f"fewer than 2 comparable priced awards for '{req.item_query}'",
                        detail="stub corpus: try 'patient monitor' or 'laboratory reagents'")
        audit_event("analyze_price", req, err)
        return err.model_dump(mode="json")
    amounts = [s.award_value.amount for _, s in valued]
    med = statistics.median(amounts)
    mad_raw = statistics.median([abs(a - med) for a in amounts])
    scale = mad_raw * 1.4826 if mad_raw > 0 else (statistics.pstdev(amounts) or 1.0)
    outliers, notes = [], []
    for r, s in valued:
        notes.extend(s.data_quality_notes)
        dev = (s.award_value.amount - med) / scale
        if abs(dev) >= 3:
            outliers.append(PriceOutlier(
                ocid=r["ocid"], award_value=s.award_value, deviation=round(dev, 2),
                reason=(f"award value {s.award_value.amount:,.0f} {s.award_value.currency} deviates "
                        f"{dev:+.1f} robust-z from median {med:,.0f} across {len(valued)} comparables"),
                source=s.sources[0]))
    assessment = None
    if subject and subject is not None:
        ss = _summary(subject)
        if ss.award_value:
            dev = (ss.award_value.amount - med) / scale
            verdict = "an OUTLIER" if abs(dev) >= 3 else "within the normal range"
            assessment = (f"Subject award {subject['ocid']} ({ss.award_value.amount:,.0f} "
                          f"{ss.award_value.currency}) is {verdict} vs median {med:,.0f} across "
                          f"{len(valued)} comparables (robust z={dev:+.1f}).")
    resp = PriceAnalysisResponse(item_query=req.item_query, n_comparables=len(valued),
                                 median=med, mad=round(scale, 2), outliers=outliers,
                                 subject_assessment=assessment,
                                 data_quality_notes=sorted(set(notes)),
                                 sources=[s.sources[0] for _, s in valued])
    audit_event("analyze_price", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def draft_committee_brief(title: str, findings: list[dict],
                          subject_ocids: list[str] | None = None, context: str = "") -> dict:
    """ACTION: writes a cited markdown brief to output/. Findings without sources are rejected."""
    try:
        req = DraftBriefRequest(title=title, findings=[Finding(**f) for f in findings],
                                subject_ocids=subject_ocids or [], context=context)
    except ValidationError as e:
        code = "citation_required" if "sources" in str(e) else "validation"
        err = ToolError(code=code,
                        message="brief rejected: every finding needs >=1 SourceRef (ocid)"
                        if code == "citation_required" else "finding validation failed",
                        detail=str(e)[:600])
        audit_event("draft_committee_brief", {"title": title, "findings": findings}, err)
        return err.model_dump(mode="json")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"brief-{time.strftime('%Y%m%d-%H%M%S')}.md"
    cites = 0
    lines = [f"# {req.title}", "",
             f"_Drafted by the procurement-lens agent (contract {CONTRACT_VERSION}). "
             "DRAFT for human review — not an award decision._", ""]
    if req.context:
        lines += [req.context, ""]
    for i, f in enumerate(req.findings, 1):
        lines += [f"## Finding {i} — {f.severity.value.upper()}", "", f.claim, "",
                  f"**Evidence:** {f.evidence}", "", "**Sources:**"]
        for s in f.sources:
            cites += 1
            ref = f"- `{s.ocid}`"
            if s.release_id:
                ref += f" release `{s.release_id}`"
            if s.field_path:
                ref += f" field `{s.field_path}`"
            if s.quote:
                ref += f" — \"{s.quote}\""
            lines.append(ref)
        lines.append("")
    if req.subject_ocids:
        lines += ["**Subject records:** " + ", ".join(f"`{o}`" for o in req.subject_ocids), ""]
    lines += ["---",
              "Prepared for human review. This brief recommends nothing be awarded; "
              "decisions rest with the evaluation committee.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    resp = DraftBriefResponse(brief_path=str(path), citation_count=cites,
                              findings_included=len(req.findings))
    audit_event("draft_committee_brief", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def raise_flag(category: str, severity: str, claim: str, evidence: str,
               subject_ocids: list[str], sources: list[dict],
               recommended_action: str, approver: str | None = None) -> dict:
    """ACTION (gated): appends a structured flag to output/flags.jsonl; pending_approval until named approver."""
    try:
        req = RaiseFlagRequest(category=FlagCategory(category), severity=Severity(severity),
                               claim=claim, evidence=evidence, subject_ocids=subject_ocids,
                               sources=[SourceRef(**s) for s in sources],
                               recommended_action=recommended_action, approver=approver)
    except (ValidationError, ValueError) as e:
        code = "citation_required" if "sources" in str(e) else "validation"
        err = ToolError(code=code, message="flag rejected", detail=str(e)[:600])
        audit_event("raise_flag", {"claim": claim, "sources": sources}, err, approver=approver)
        return err.model_dump(mode="json")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    flags_path = OUTPUT_DIR / "flags.jsonl"
    status = "approved" if req.approver else "pending_approval"
    record = {"flag_id": uuid.uuid4().hex[:8],
              "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "status": status, **req.model_dump(mode="json")}
    with flags_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    resp = RaiseFlagResponse(flag_id=record["flag_id"], flags_path=str(flags_path), status=status)
    audit_event("raise_flag", req, resp, approver=req.approver)
    return resp.model_dump(mode="json")


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
