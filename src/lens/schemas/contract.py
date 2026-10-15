"""Tool contract v0.1 for lens-mcp — single source of truth.

The real MCP server (teammate) and the dev stub (src/lens/stubs/) both import
these models, so orchestration can be built and tested before the real server
exists. See docs/CONTRACT.md for the human-readable version.

Invariants (challenge rules):
- No tool awards or alters a tender outcome.
- Every analytic response carries SourceRef entries; a Finding or flag with
  zero sources is a validation error, not a style issue.
- Action-tool results are audited; BOTH action tools require a named human
  approver before anything irreversible is written (see GATED_TOOLS and
  approver_violation below). Enforcement lives at the tool boundary, not only
  in the orchestrator, so an MCP client that bypasses LangGraph is still gated.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

CONTRACT_VERSION = "0.1.0"

TOOL_NAMES: tuple[str, ...] = (
    "search_awards",
    "get_supplier_history",
    "analyze_price",
    "draft_committee_brief",
    "raise_flag",
)
READ_TOOLS: tuple[str, ...] = TOOL_NAMES[:3]
ACTION_TOOLS: tuple[str, ...] = TOOL_NAMES[3:]

# Irreversible tools: each writes to disk. Declared here so the requirement
# "a gate on every irreversible one" is machine-readable and checkable —
# `lens-audit verify` asserts every successful call to a GATED_TOOL carries a
# valid named approver in the audit trail.
GATED_TOOLS: tuple[str, ...] = ACTION_TOOLS

PORTAL_BASE = "https://tenders.go.ke"


# ---------- named-human approver validation ----------

# Whole-string matches only (case/whitespace normalised), so "CI Reviewer" and
# "Test Approver" still pass while bare automation tokens do not.
APPROVER_DENYLIST: frozenset[str] = frozenset({
    "auto", "automatic", "agent", "ai", "bot", "system", "self", "selftest",
    "llm", "model", "none", "null", "nil", "true", "false", "unknown",
    "anonymous", "admin", "root", "test", "ci", "script", "scripted",
    "automation", "machine", "langgraph", "n/a", "na", "-", ".", "tbd",
    "approved", "approve", "approver", "human", "user", "demo",
})

_WS = re.compile(r"\s+")


def _norm_approver(approver: str) -> str:
    return _WS.sub(" ", (approver or "").strip()).lower()


def approver_violation(approver: Optional[str], *, model: Optional[str] = None) -> Optional[str]:
    """Return None if `approver` is an acceptable NAMED HUMAN, else a short
    machine-readable reason. `model` is the acting model name, so an agent
    cannot approve its own work by passing its own identity.

    Rules (deliberately structural, not a name blocklist of real people):
      1. present and >= 2 chars after whitespace collapse
      2. contains at least one alphabetic character
      3. not a bare automation token (APPROVER_DENYLIST)
      4. not the acting model's own name or provider-qualified tail
      5. contains no "/" — model specs are provider-qualified, human names are not
    """
    if not approver:
        return "approver_missing"
    n = _norm_approver(approver)
    if len(n) < 2:
        return "approver_too_short"
    if not any(c.isalpha() for c in n):
        return "approver_not_a_name"
    if n in APPROVER_DENYLIST:
        return "approver_not_human"
    if "/" in n:
        return "approver_looks_like_model"
    if model:
        m = _norm_approver(model)
        if n == m or n == m.split("/")[-1]:
            return "approver_is_the_model"
    return None


def approver_ok(approver: Optional[str], *, model: Optional[str] = None) -> bool:
    """Convenience inverse of approver_violation()."""
    return approver_violation(approver, model=model) is None



class Money(BaseModel):
    amount: float
    currency: str = "KES"


class SourceRef(BaseModel):
    """Citation anchor. ocid is the only mandatory field — everything else
    helps a human re-find the exact byte the claim came from."""

    ocid: str
    release_id: Optional[str] = None
    field_path: Optional[str] = None  # e.g. "awards[0].value.amount"
    url: Optional[str] = None
    quote: Optional[str] = None


# ---------- search_awards ----------

class AwardSummary(BaseModel):
    ocid: str
    release_id: Optional[str] = None
    fiscal_year: Optional[str] = None  # portal format "YYYY/YYYY"
    buyer_name: Optional[str] = None  # null when missing — never guessed
    tender_title: Optional[str] = None
    item_description: Optional[str] = None
    award_date: Optional[str] = None
    award_value: Optional[Money] = None
    supplier_names: list[str] = Field(default_factory=list)
    procurement_method: Optional[str] = None
    sources: list[SourceRef] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)


class SearchAwardsRequest(BaseModel):
    query: str = ""
    fiscal_year: Optional[str] = None
    buyer: Optional[str] = None
    limit: int = Field(20, ge=1, le=200)


class SearchAwardsResponse(BaseModel):
    awards: list[AwardSummary] = Field(default_factory=list)
    total_matched: int = 0
    truncated: bool = False


# ---------- get_supplier_history ----------

class SupplierHistoryRequest(BaseModel):
    supplier: str
    normalize: bool = True  # alias/identifier dedupe (broken IDs are common)
    limit: int = Field(50, ge=1, le=500)


class SupplierHistoryResponse(BaseModel):
    canonical_name: str
    aliases_matched: list[str] = Field(default_factory=list)
    total_awards: int = 0
    total_value: Optional[Money] = None
    awards: list[AwardSummary] = Field(default_factory=list)
    buyers: list[str] = Field(default_factory=list)
    by_fiscal_year: dict[str, int] = Field(default_factory=dict)
    data_quality_notes: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


# ---------- analyze_price ----------

class PriceAnalysisRequest(BaseModel):
    item_query: str
    buyer: Optional[str] = None
    fiscal_years: list[str] = Field(default_factory=list)  # empty = all
    subject_ocid: Optional[str] = None  # if set, judge this award vs comparables


class PriceOutlier(BaseModel):
    ocid: str
    award_value: Optional[Money] = None
    deviation: float  # robust z: (value - median) / scaled MAD
    reason: str
    source: SourceRef


class PriceAnalysisResponse(BaseModel):
    item_query: str
    n_comparables: int = 0
    median: Optional[float] = None
    mad: Optional[float] = None
    outliers: list[PriceOutlier] = Field(default_factory=list)
    subject_assessment: Optional[str] = None  # human-readable verdict
    data_quality_notes: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


# ---------- draft_committee_brief (ACTION) ----------

class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FlagCategory(str, Enum):
    price_outlier = "price_outlier"
    supplier_concentration = "supplier_concentration"
    sole_source = "sole_source"
    data_quality = "data_quality"
    process = "process"


class Finding(BaseModel):
    claim: str
    evidence: str
    severity: Severity = Severity.medium
    sources: list[SourceRef] = Field(min_length=1)  # citation REQUIRED


class DraftBriefRequest(BaseModel):
    title: str
    findings: list[Finding] = Field(min_length=1)
    subject_ocids: list[str] = Field(default_factory=list)
    context: str = ""
    # GATED: writing the brief is irreversible (a file lands in output/), so it
    # requires a named human approver validated by contract.approver_violation.
    # Absent or invalid -> structured ToolError, nothing written.
    approver: Optional[str] = None


class DraftBriefResponse(BaseModel):
    brief_path: str
    citation_count: int = 0
    findings_included: int = 0
    # The named human who authorised this write; always set on success because
    # the gate refuses the call before a brief can be produced without one.
    approver: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


# ---------- raise_flag (ACTION, gated) ----------

class RaiseFlagRequest(BaseModel):
    category: FlagCategory
    severity: Severity
    claim: str
    evidence: str
    subject_ocids: list[str] = Field(min_length=1)
    sources: list[SourceRef] = Field(min_length=1)  # citation REQUIRED
    recommended_action: str
    approver: Optional[str] = None  # named human; pending until provided


class RaiseFlagResponse(BaseModel):
    flag_id: str
    flags_path: str
    status: Literal["pending_approval", "approved"]
    requires_approval: bool = True


# ---------- errors ----------

class ToolError(BaseModel):
    code: str  # citation_required | no_comparables | supplier_not_found | bad_fiscal_year | validation | internal | approval_required | approver_invalid
    message: str
    detail: Optional[str] = None
