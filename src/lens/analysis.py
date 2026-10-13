"""Shared analysis core — outliers, comparables, supplier normalisation.

Both servers (the offline stub and the real SQLite-backed lens-mcp) delegate
their read-tool logic here, so stub ↔ real parity holds BY CONSTRUCTION
instead of by hope (docs/CONTRACT.md "Stub parity", docs/DESIGN.md repo
layout). The only difference between the servers is where release dicts come
from: in-memory fixtures vs SQLite `doc` columns rehydrated into the same
shape.

Contract rules enforced here:
- never crash on malformed records — problems become data_quality notes;
- missing fields stay missing (None) — never guessed;
- robust stats: median + MAD*1.4826 scale, |z| >= 3 flags an outlier.
"""
from __future__ import annotations

import re
import statistics
from collections.abc import Iterable

from lens.schemas.contract import (
    PORTAL_BASE,
    AwardSummary,
    Money,
    PriceAnalysisResponse,
    PriceOutlier,
    SourceRef,
    SupplierHistoryResponse,
)

_SUPPLIER_SUFFIXES = {"LTD", "LIMITED", "LLC", "CO", "COMPANY", "ENTERPRISES", "SUPPLIES", "SERVICES"}


def normalize_supplier(name: str) -> str:
    """MEDTECH SOLUTIONS LTD == Medtech Solutions Ltd. == MED-TECH SOLUTIONS LIMITED."""
    n = re.sub(r"[^A-Z0-9]+", " ", (name or "").upper()).strip()
    return "".join(w for w in n.split() if w not in _SUPPLIER_SUFFIXES)


def fy_from_date(date_str: str | None) -> str | None:
    """Kenya fiscal year (July–June) in the portal's "YYYY/YYYY" format."""
    if not date_str:
        return None
    m = re.match(r"(\d{4})-(\d{2})", str(date_str))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    start = year if month >= 7 else year - 1
    return f"{start}/{start + 1}"


def dq_notes(rel: dict) -> list[str]:
    """Per-release data-quality flags. Flags are data, not errors — a
    malformed record is surfaced with notes, never dropped silently and
    never fatal (docs/CONTRACT.md §Data-quality behaviour)."""
    notes: list[str] = []
    tender = rel.get("tender") if isinstance(rel.get("tender"), dict) else {}
    tp = tender.get("tenderPeriod") if isinstance(tender.get("tenderPeriod"), dict) else {}
    if tp.get("startDate") and tp.get("endDate") and tp["startDate"] > tp["endDate"]:
        notes.append(f"tenderPeriod.startDate ({tp['startDate']}) is after endDate ({tp['endDate']})")
    buyer = rel.get("buyer") if isinstance(rel.get("buyer"), dict) else {}
    if not buyer.get("name"):
        notes.append("buyer name missing in source record")
    awards = rel.get("awards") if isinstance(rel.get("awards"), list) else []
    first = (awards[0] if awards and isinstance(awards[0], dict) else {}) or {}
    for s in first.get("suppliers") or []:
        if not isinstance(s, dict):
            continue
        if not (s.get("identifier") or {}).get("id"):
            notes.append(f"supplier identifier missing for {s.get('name')}")
    return notes


def award_summary(rel: dict) -> AwardSummary:
    """Map one OCDS release dict to the contract's AwardSummary.

    Mirrors awards[0] (the contract's summary shape is single-award). Values
    that cannot parse stay None + a DQ note — never guessed, never fatal."""
    tender = rel.get("tender") if isinstance(rel.get("tender"), dict) else {}
    awards = rel.get("awards") if isinstance(rel.get("awards"), list) else []
    aw = (awards[0] if awards and isinstance(awards[0], dict) else {}) or {}
    value = aw.get("value") if isinstance(aw.get("value"), dict) else {}
    items = [i for i in (tender.get("items") or []) if isinstance(i, dict)]
    buyer = rel.get("buyer") if isinstance(rel.get("buyer"), dict) else {}

    money = None
    notes = dq_notes(rel)
    if value.get("amount") is not None:
        try:
            money = Money(amount=float(value["amount"]), currency=str(value.get("currency") or "KES"))
        except (TypeError, ValueError):
            notes.append(f"award value amount unparseable: {value.get('amount')!r}")

    return AwardSummary(
        ocid=str(rel.get("ocid") or ""),
        release_id=rel.get("id"),
        fiscal_year=rel.get("fiscal_year") or fy_from_date(aw.get("date") or rel.get("date")),
        buyer_name=buyer.get("name"),
        tender_title=tender.get("title"),
        item_description=items[0].get("description") if items else None,
        award_date=aw.get("date"),
        award_value=money,
        supplier_names=[s.get("name", "") for s in (aw.get("suppliers") or []) if isinstance(s, dict)],
        procurement_method=tender.get("procurementMethod"),
        sources=[SourceRef(ocid=str(rel.get("ocid") or ""), release_id=rel.get("id"),
                           field_path="awards[0].value.amount", url=f"{PORTAL_BASE}/ocds")],
        data_quality_notes=notes,
    )


def match_text(rel: dict, query: str) -> bool:
    """Free-text match: substring of tender title + all item descriptions."""
    if not query:
        return True
    t = rel.get("tender") if isinstance(rel.get("tender"), dict) else {}
    items = [i for i in (t.get("items") or []) if isinstance(i, dict)]
    parts = [t.get("title") or ""] + [i.get("description") or "" for i in items]
    return query.lower() in " ".join(parts).lower()


def match_buyer(rel: dict, buyer: str | None) -> bool:
    if buyer is None:
        return True
    b = rel.get("buyer") if isinstance(rel.get("buyer"), dict) else {}
    return buyer.lower() in ((b.get("name")) or "").lower()


def match_fy(rel: dict, fiscal_years: Iterable[str]) -> bool:
    fys = set(fiscal_years or ())
    if not fys:
        return True
    fy = rel.get("fiscal_year") or fy_from_date(
        ((rel.get("awards") or [{}])[0] or {}).get("date") or rel.get("date"))
    return fy in fys


def robust_scale(amounts: list[float]) -> tuple[float, float]:
    """(median, MAD-based scale). MAD*1.4826 when non-degenerate, else pstdev,
    else floor at 1.0 so deviations stay finite. Callers guarantee len >= 2."""
    med = statistics.median(amounts)
    mad_raw = statistics.median([abs(a - med) for a in amounts])
    scale = mad_raw * 1.4826 if mad_raw > 0 else (statistics.pstdev(amounts) or 1.0)
    return float(med), float(scale)


def supplier_matches(releases: Iterable[dict], supplier: str,
                     normalize: bool = True) -> tuple[list[dict], set[str]]:
    """Releases whose awards[0] suppliers match `supplier`.

    Scans awards[0] only, mirroring the contract's single-award summary shape.
    A release matched by two alias spellings appears twice — same as the
    original stub semantics (total_awards counts award mentions)."""
    target = normalize_supplier(supplier) if normalize else (supplier or "").upper()
    matched: list[dict] = []
    aliases: set[str] = set()
    if not target:
        return matched, aliases
    for r in releases:
        awards = r.get("awards") if isinstance(r.get("awards"), list) else []
        first = (awards[0] if awards and isinstance(awards[0], dict) else {}) or {}
        for s in first.get("suppliers") or []:
            if not isinstance(s, dict):
                continue
            nm = s.get("name", "")
            hit = normalize_supplier(nm) == target if normalize else nm.upper() == target
            if hit:
                matched.append(r)
                aliases.add(nm)
    return matched, aliases


def build_supplier_history(supplier: str, matched: list[dict], aliases: Iterable[str],
                           limit: int) -> SupplierHistoryResponse:
    """Assemble the contract response from matched releases (caller guarantees
    matched is non-empty; empty maps to ToolError supplier_not_found)."""
    alias_list = sorted(a for a in aliases if a)
    summaries = [award_summary(r) for r in matched[:limit]]
    total = sum(a.award_value.amount for a in summaries if a.award_value)
    by_fy: dict[str, int] = {}
    for a in summaries:
        if a.fiscal_year:
            by_fy[a.fiscal_year] = by_fy.get(a.fiscal_year, 0) + 1
    return SupplierHistoryResponse(
        canonical_name=alias_list[0] if alias_list else supplier,
        aliases_matched=alias_list,
        total_awards=len(summaries), total_value=Money(amount=total),
        awards=summaries,
        buyers=sorted({a.buyer_name for a in summaries if a.buyer_name}),
        by_fiscal_year=by_fy,
        data_quality_notes=sorted({n for a in summaries for n in a.data_quality_notes}),
        sources=[s for a in summaries for s in a.sources],
    )


def build_price_analysis(item_query: str, pool: list[dict],
                         subject: dict | None) -> PriceAnalysisResponse | None:
    """Median/MAD price analysis over the pre-filtered pool.

    `subject` (when given) must be an element of `pool` (identity) — it is
    excluded from its own comparables and optionally judged against them.
    Returns None when fewer than 2 priced comparables exist; callers map that
    to ToolError(code="no_comparables")."""
    comparables = [r for r in pool if r is not subject] if subject is not None else pool
    valued = [(r, award_summary(r)) for r in comparables]
    valued = [(r, s) for r, s in valued if s.award_value]
    if len(valued) < 2:
        return None
    amounts = [s.award_value.amount for _, s in valued]
    med, scale = robust_scale(amounts)

    outliers: list[PriceOutlier] = []
    notes: list[str] = []
    for r, s in valued:
        notes.extend(s.data_quality_notes)
        dev = (s.award_value.amount - med) / scale
        if abs(dev) >= 3:
            outliers.append(PriceOutlier(
                ocid=str(r.get("ocid") or ""), award_value=s.award_value,
                deviation=round(dev, 2),
                reason=(f"award value {s.award_value.amount:,.0f} {s.award_value.currency} deviates "
                        f"{dev:+.1f} robust-z from median {med:,.0f} across {len(valued)} comparables"),
                source=s.sources[0]))

    assessment = None
    if subject is not None:
        ss = award_summary(subject)
        if ss.award_value:
            dev = (ss.award_value.amount - med) / scale
            verdict = "an OUTLIER" if abs(dev) >= 3 else "within the normal range"
            assessment = (f"Subject award {subject.get('ocid')} ({ss.award_value.amount:,.0f} "
                          f"{ss.award_value.currency}) is {verdict} vs median {med:,.0f} across "
                          f"{len(valued)} comparables (robust z={dev:+.1f}).")

    return PriceAnalysisResponse(
        item_query=item_query, n_comparables=len(valued), median=med, mad=round(scale, 2),
        outliers=outliers, subject_assessment=assessment,
        data_quality_notes=sorted(set(notes)),
        sources=[s.sources[0] for _, s in valued])
