"""The real lens-mcp server — contract v0.1 over the SQLite corpus.

Same 5 tools, same request/response models, same audit trail as the stub
(src/lens/stubs/stub_mcp.py); the difference is the data half: releases come
from the SQLite corpus built by lens-ingest (docs/DESIGN.md §Data) instead of
in-memory fixtures. Read-side logic is shared through lens.analysis and action
bodies through lens.actions, so stub ↔ real parity holds by construction
(docs/CONTRACT.md "Stub parity").

Run as MCP server (stdio):  uv run lens-mcp            # corpus: $LENS_DB or data/lens.sqlite
Contract selftest:          uv run lens-mcp --selftest # seeds a temp corpus from fixtures
Graph swap (zero code changes, docs/ARCHITECTURE.md):
  LENS_MCP_CMD="uv run lens-mcp" uv run lens-demo --approve "Your Name"

Corpus missing or empty → every read tool returns a structured
ToolError(code="internal") pointing at lens-ingest — never a crash, never
invented data. Action tools (brief/flag) don't read the corpus and work
regardless.

Documented deltas vs the stub (supersets; identical on the fixture corpus):
- search_awards orders by award_date DESC (stub: fixture order) and also
  matches ocid/release_id tokens; fiscal_year matches the stored column,
  which ingest derives (Kenya FY, July–June) when the source lacks it.
- analyze_price fiscal-year filtering derives missing FYs from award dates.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lens import actions as _actions
from lens.analysis import (
    build_price_analysis,
    build_supplier_history,
    match_buyer,
    match_fy,
    match_text,
    normalize_supplier,
    supplier_matches,
)
from lens.audit import audit_event, read_audit
from lens.ingest import connect_ro, db_path, ingest_fixtures
from lens.schemas.contract import (
    ACTION_TOOLS,
    CONTRACT_VERSION,
    PORTAL_BASE,
    TOOL_NAMES,
    AwardSummary,
    Money,
    PriceAnalysisRequest,
    SearchAwardsRequest,
    SearchAwardsResponse,
    SourceRef,
    SupplierHistoryRequest,
    ToolError,
)

mcp = FastMCP("lens-mcp")

_ROW_COLS = ("ocid, release_id, fiscal_year, buyer_name, tender_title, item_description,"
             " award_date, award_value, currency, procurement_method, supplier_names, dq_notes")


# ---------- corpus access ----------

def _corpus_error(tool: str, req) -> dict:
    path = db_path()
    err = ToolError(
        code="internal",
        message=f"corpus database not available at {path}",
        detail="build it first: uv run lens-ingest --from-fixtures (offline demo corpus) "
               "or ingest real OCDS packages — see README §Data")
    audit_event(tool, req, err)
    return err.model_dump(mode="json")


def _open(tool: str, req) -> tuple[sqlite3.Connection | None, dict | None]:
    """(conn, None) on success; (None, ToolError dict) when the corpus is
    missing, unreadable, or empty. Read-only — the server never writes it."""
    path = db_path()
    if not path.exists():
        return None, _corpus_error(tool, req)
    try:
        conn = connect_ro(path)
        n = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
    except sqlite3.Error:
        return None, _corpus_error(tool, req)
    if n == 0:
        conn.close()
        return None, _corpus_error(tool, req)
    return conn, None


def _summary_from_row(row: sqlite3.Row) -> AwardSummary:
    """AwardSummary straight from indexed columns — no JSON rehydration on the
    hot search path. Field-for-field what analysis.award_summary(doc) gives."""
    value = None
    if row["award_value"] is not None:
        value = Money(amount=row["award_value"], currency=row["currency"] or "KES")
    return AwardSummary(
        ocid=row["ocid"], release_id=row["release_id"] or None,
        fiscal_year=row["fiscal_year"], buyer_name=row["buyer_name"],
        tender_title=row["tender_title"], item_description=row["item_description"],
        award_date=row["award_date"], award_value=value,
        supplier_names=json.loads(row["supplier_names"] or "[]"),
        procurement_method=row["procurement_method"],
        sources=[SourceRef(ocid=row["ocid"], release_id=row["release_id"] or None,
                           field_path="awards[0].value.amount", url=f"{PORTAL_BASE}/ocds")],
        data_quality_notes=json.loads(row["dq_notes"] or "[]"),
    )


def _exact_text_match(row: sqlite3.Row, query: str) -> bool:
    """analysis.match_text semantics over columns: whole-query substring of
    title + item descriptions (items_text is the joined descriptions)."""
    if not query:
        return True
    title = row["tender_title"] or ""
    items = row["items_text"] or ""
    joined = title + (" " + items if items else "")
    return query.lower() in joined.lower()


# ---------- read tools ----------

@mcp.tool()
def search_awards(query: str = "", fiscal_year: str | None = None,
                  buyer: str | None = None, limit: int = 20) -> dict:
    """Search Kenyan PPIP award records by free text / fiscal year / buyer (SQLite corpus)."""
    req = SearchAwardsRequest(query=query, fiscal_year=fiscal_year, buyer=buyer, limit=limit)
    conn, err = _open("search_awards", req)
    if err:
        return err
    try:
        where: list[str] = []
        params: list = []
        for tok in req.query.lower().split():  # token prefilter: superset of the substring match
            where.append("(LOWER(tender_title) LIKE ? OR LOWER(items_text) LIKE ? OR LOWER(ocid) LIKE ?)")
            params += [f"%{tok}%"] * 3
        if req.fiscal_year:
            where.append("fiscal_year = ?")
            params.append(req.fiscal_year)
        if req.buyer:
            where.append("LOWER(buyer_name) LIKE ?")
            params.append(f"%{req.buyer.lower()}%")
        sql = f"SELECT {_ROW_COLS}, items_text FROM releases"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY award_date DESC, ocid"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    hits = [r for r in rows
            if _exact_text_match(r, req.query)
            and (req.buyer is None or req.buyer.lower() in (r["buyer_name"] or "").lower())]
    resp = SearchAwardsResponse(awards=[_summary_from_row(r) for r in hits[: req.limit]],
                                total_matched=len(hits), truncated=len(hits) > req.limit)
    audit_event("search_awards", req, resp)
    return resp.model_dump(mode="json")


@mcp.tool()
def get_supplier_history(supplier: str, normalize: bool = True, limit: int = 50) -> dict:
    """Award history for a supplier, with alias/identifier normalisation (SQLite corpus)."""
    req = SupplierHistoryRequest(supplier=supplier, normalize=normalize, limit=limit)
    conn, err = _open("get_supplier_history", req)
    if err:
        return err
    try:
        target = normalize_supplier(req.supplier) if req.normalize else (req.supplier or "").upper()
        col = "norm_name" if req.normalize else "UPPER(name)"
        keys = (conn.execute(f"SELECT DISTINCT ocid, release_id FROM suppliers WHERE {col} = ?",
                             (target,)).fetchall() if target else [])
        if not keys:
            return _supplier_not_found(req)
        ph = ",".join(["(?,?)"] * len(keys))
        params = [x for k in keys for x in (k["ocid"], k["release_id"])]
        rows = conn.execute(
            f"SELECT doc FROM releases WHERE (ocid, release_id) IN (VALUES {ph}) ORDER BY rowid",
            params).fetchall()
    finally:
        conn.close()
    rels = [json.loads(r["doc"]) for r in rows]
    matched, aliases = supplier_matches(rels, req.supplier, req.normalize)
    if not matched:  # SQL prefilter covers every award; the contract summary shape is awards[0]
        return _supplier_not_found(req)
    resp = build_supplier_history(req.supplier, matched, aliases, req.limit)
    audit_event("get_supplier_history", req, resp)
    return resp.model_dump(mode="json")


def _supplier_not_found(req: SupplierHistoryRequest) -> dict:
    err = ToolError(code="supplier_not_found",
                    message=f"no awards found for supplier '{req.supplier}'",
                    detail="corpus may be a subset; check spelling or pass normalize=false")
    audit_event("get_supplier_history", req, err)
    return err.model_dump(mode="json")


@mcp.tool()
def analyze_price(item_query: str, buyer: str | None = None,
                  fiscal_years: list[str] | None = None, subject_ocid: str | None = None) -> dict:
    """Median/MAD price analysis vs comparable awards; flags outliers; optional verdict on a subject award."""
    req = PriceAnalysisRequest(item_query=item_query, buyer=buyer,
                               fiscal_years=fiscal_years or [], subject_ocid=subject_ocid)
    conn, err = _open("analyze_price", req)
    if err:
        return err
    try:
        where: list[str] = []
        params: list = []
        for tok in req.item_query.lower().split():
            where.append("(LOWER(tender_title) LIKE ? OR LOWER(items_text) LIKE ?)")
            params += [f"%{tok}%"] * 2
        if req.buyer:
            where.append("LOWER(buyer_name) LIKE ?")
            params.append(f"%{req.buyer.lower()}%")
        if req.fiscal_years:
            where.append(f"fiscal_year IN ({','.join('?' * len(req.fiscal_years))})")
            params += list(req.fiscal_years)
        sql = "SELECT doc FROM releases"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rowid"
        rels = [json.loads(r["doc"]) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
    pool = [r for r in rels
            if match_text(r, req.item_query) and match_buyer(r, req.buyer)
            and match_fy(r, req.fiscal_years)]
    subject = next((r for r in pool if r["ocid"] == req.subject_ocid), None)
    resp = build_price_analysis(req.item_query, pool, subject)
    if resp is None:
        err2 = ToolError(code="no_comparables",
                         message=f"fewer than 2 comparable priced awards for '{req.item_query}'",
                         detail="try a broader item_query, or extend the corpus: uv run lens-ingest …")
        audit_event("analyze_price", req, err2)
        return err2.model_dump(mode="json")
    audit_event("analyze_price", req, resp)
    return resp.model_dump(mode="json")


# ---------- action tools (shared bodies; gated + audited) ----------

@mcp.tool()
def draft_committee_brief(title: str, findings: list[dict],
                          subject_ocids: list[str] | None = None, context: str = "",
                          approver: str | None = None) -> dict:
    """ACTION (gated): writes a cited markdown brief to output/. Requires a NAMED HUMAN
    approver — refused with approval_required/approver_invalid otherwise, nothing written.
    Findings without sources are rejected with citation_required."""
    return _actions.draft_committee_brief(title=title, findings=findings,
                                          subject_ocids=subject_ocids, context=context,
                                          approver=approver)


@mcp.tool()
def raise_flag(category: str, severity: str, claim: str, evidence: str,
               subject_ocids: list[str], sources: list[dict],
               recommended_action: str, approver: str | None = None) -> dict:
    """ACTION (gated): appends a structured flag to output/flags.jsonl; pending_approval until named approver."""
    return _actions.raise_flag(category=category, severity=severity, claim=claim, evidence=evidence,
                               subject_ocids=subject_ocids, sources=sources,
                               recommended_action=recommended_action, approver=approver)


# ---------- selftest ----------

def _selftest() -> int:
    print(f"lens-mcp selftest — contract {CONTRACT_VERSION}, corpus: SQLite "
          f"({len(TOOL_NAMES)} tools: {len(TOOL_NAMES) - len(ACTION_TOOLS)} read, {len(ACTION_TOOLS)} action)")
    tmp = Path(tempfile.mkdtemp(prefix="lens-mcp-selftest-"))
    # Artifacts land in the temp dir, never the live output/ (LENS_OUTPUT).
    os.environ["LENS_OUTPUT"] = str(tmp / "out")
    before = len(read_audit())
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if not cond and detail else ""))
        if not cond:
            failures.append(name)

    check("all 5 contract tools implemented",
          {"search_awards", "get_supplier_history", "analyze_price",
           "draft_committee_brief", "raise_flag"} == set(TOOL_NAMES))

    os.environ["LENS_DB"] = str(tmp / "missing.sqlite")
    r0 = search_awards(query="patient monitor")
    check("missing corpus -> structured ToolError with ingest hint (no crash, no invented data)",
          r0.get("code") == "internal" and "lens-ingest" in (r0.get("detail") or ""), str(r0)[:200])

    seeded = ingest_fixtures(tmp / "corpus.sqlite")
    os.environ["LENS_DB"] = str(tmp / "corpus.sqlite")
    check("fixture corpus seeded (10 releases)", seeded.get("ingested") == 10, str(seeded)[:200])

    r = search_awards(query="patient monitor")
    check("search_awards returns corpus rows", r.get("total_matched", 0) >= 4, str(r)[:200])
    malformed = [a for a in r.get("awards", [])
                 if any("startDate" in n for n in a.get("data_quality_notes", []))]
    check("malformed-date record surfaced with DQ note (no crash)", len(malformed) >= 1)

    r2 = get_supplier_history(supplier="medtech solutions ltd.")
    check("supplier alias normalisation (3 spellings collapse)",
          len(r2.get("aliases_matched", [])) >= 2 and r2.get("total_awards", 0) >= 2,
          json.dumps(r2)[:200])
    r2b = get_supplier_history(supplier="Ghost Supplier Ltd")
    check("unknown supplier -> supplier_not_found", r2b.get("code") == "supplier_not_found")

    r3 = analyze_price(item_query="patient monitor", subject_ocid="ocds-vn56pm-stub-0004")
    check("price analysis flags outlier comparables", len(r3.get("outliers", [])) >= 1,
          json.dumps(r3)[:300])
    check("subject 5x award assessed OUTLIER", "OUTLIER" in (r3.get("subject_assessment") or ""),
          str(r3.get("subject_assessment")))
    r3b = analyze_price(item_query="zzz-nothing-matches-this")
    check("thin pool -> no_comparables", r3b.get("code") == "no_comparables")

    bad = draft_committee_brief(title="t", findings=[{"claim": "c", "evidence": "e", "sources": []}])
    check("brief GATED: no named approver -> approval_required (nothing written)",
          bad.get("code") == "approval_required", str(bad)[:200])

    ocid, src = "ocds-vn56pm-stub-0004", {"ocid": "ocds-vn56pm-stub-0004", "field_path": "awards[0].value.amount"}
    bot = draft_committee_brief(title="t", findings=[{"claim": "c", "evidence": "e",
                                                      "severity": "high", "sources": [src]}],
                                approver="auto")
    check("automation token refused as approver -> approver_invalid",
          bot.get("code") == "approver_invalid", str(bot)[:200])

    uncited = draft_committee_brief(title="t", findings=[{"claim": "c", "evidence": "e",
                                                          "sources": []}],
                                    approver="Njoki (selftest)")
    check("uncited finding rejected (citation_required)",
          uncited.get("code") == "citation_required", str(uncited)[:200])

    r4 = draft_committee_brief(
        title="Price reasonableness review — patient monitors",
        findings=[{"claim": "Award value is ~5x the comparable median",
                   "evidence": "KES 2,400,000 vs median ~KES 495,000 across 4 comparables",
                   "severity": "high", "sources": [src]}],
        subject_ocids=[ocid], approver="Njoki (selftest)")
    check("brief drafted with citation once a named human approves",
          r4.get("citation_count", 0) >= 1 and Path(r4.get("brief_path", "")).exists()
          and r4.get("approver") == "Njoki (selftest)", str(r4)[:200])

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

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + (f"SELFTEST FAILED: {', '.join(failures)}" if failures
                  else "SELFTEST PASSED — 5/5 tools on SQLite; citation + gate + audit invariants hold"))
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="lens-mcp",
                                 description="Real lens-mcp server (contract v0.1, SQLite corpus)")
    ap.add_argument("--selftest", action="store_true",
                    help="seed a temp corpus from fixtures, exercise all tools in-process, exit 0/1")
    ap.add_argument("--db", default=None,
                    help="corpus path (default: $LENS_DB or data/lens.sqlite)")
    args = ap.parse_args()
    if args.db:
        os.environ["LENS_DB"] = args.db
    if args.selftest:
        raise SystemExit(_selftest())
    mcp.run()  # stdio transport — the LENS_MCP_CMD swap target


if __name__ == "__main__":
    main()
