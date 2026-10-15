"""Shared ACTION-tool bodies for both servers (stub and real lens-mcp).

One implementation of the contract's two action tools so the citation and
human-gate invariants cannot drift between servers (docs/CONTRACT.md
invariants 2–4, docs/CONTRIBUTING.md rules 2–5). Each server registers a
thin @mcp.tool() wrapper around these functions; the bodies do their own
audit_event calls in the shared JSONL format (lens.audit).

GATE LOCATION: both tools write to disk, so both are gated HERE, at the tool
boundary — not only in the LangGraph human_gate. An MCP client that never
touches the graph (Claude Desktop, a script, another agent) is still refused
without a valid named human approver. Defence in depth, not duplication.

Hard boundary: these tools prepare files (a cited brief, a gated flag).
Nothing here can award, rank, or alter a tender outcome — the capability
does not exist (challenge rule, CONTRACT.md invariant 1).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lens.audit import audit_event
from lens.schemas.contract import (
    CONTRACT_VERSION,
    DraftBriefRequest,
    DraftBriefResponse,
    Finding,
    FlagCategory,
    RaiseFlagRequest,
    RaiseFlagResponse,
    Severity,
    SourceRef,
    ToolError,
    approver_violation,
)

OUTPUT_DIR = Path("output")


def _output_dir(output_dir: Path | None) -> Path:
    """Resolve the artifact directory at CALL time: explicit arg wins, then
    $LENS_OUTPUT, then ./output. Call-time resolution (not a default arg) is
    what lets tests and the evidence pack redirect artifacts without touching
    the live output/ directory."""
    if output_dir is not None:
        return output_dir
    env = (os.environ.get("LENS_OUTPUT") or "").strip()
    return Path(env) if env else OUTPUT_DIR


def _acting_model(model: str | None) -> str | None:
    """Best-known identity of the acting model, so an agent cannot pass its own
    name as the approving human."""
    return model or os.environ.get("LENS_MODEL") or os.environ.get("MODEL") or None


def _gate_refusal(tool: str, violation: str, request: Any, approver: str | None,
                  what: str) -> dict:
    """Structured refusal for a gated write. Audited as a gate event; the caller
    returns it verbatim. Nothing has been written to disk at this point."""
    err = ToolError(
        code="approval_required" if violation == "approver_missing" else "approver_invalid",
        message=f"{what} not written: a NAMED HUMAN approver is required",
        detail=f"approver rejected ({violation}). Pass approver=\"<full name>\" for the human "
               f"who authorised this; blanks, automation tokens and the acting model's own "
               f"name are all refused. Nothing was written to disk.")
    audit_event(tool, request, err, approver=approver,
                gate="refused", gate_reason=violation)
    return err.model_dump(mode="json")


def draft_committee_brief(title: str, findings: list[dict],
                          subject_ocids: list[str] | None = None, context: str = "",
                          approver: str | None = None, model: str | None = None,
                          output_dir: Path | None = None) -> dict:
    """Write a cited markdown brief — GATED on a valid named human approver,
    then on citations. Findings without >=1 SourceRef are rejected with a
    structured ToolError (citation_required): validation, not a style issue.

    Gate is checked FIRST, so an unauthorised caller receives no citation
    feedback either — the boundary refuses, it does not negotiate.
    """
    violation = approver_violation(approver, model=_acting_model(model))
    if violation:
        return _gate_refusal("draft_committee_brief", violation,
                             {"title": title, "findings": findings, "approver": approver},
                             approver, "brief")
    try:
        req = DraftBriefRequest(title=title, findings=[Finding(**f) for f in findings],
                                subject_ocids=subject_ocids or [], context=context,
                                approver=approver)
    except (ValidationError, TypeError, ValueError) as e:
        code = "citation_required" if "sources" in str(e) else "validation"
        err = ToolError(code=code,
                        message="brief rejected: every finding needs >=1 SourceRef (ocid)"
                        if code == "citation_required" else "finding validation failed",
                        detail=str(e)[:600])
        audit_event("draft_committee_brief", {"title": title, "findings": findings}, err)
        return err.model_dump(mode="json")
    output_dir = _output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"brief-{time.strftime('%Y%m%d-%H%M%S')}.md"
    cites = 0
    lines = [f"# {req.title}", "",
             (f"_Drafted by the procurement-lens agent (contract {CONTRACT_VERSION}). "
              + "DRAFT for human review — not an award decision._"), "",
             f"**Authorised by:** {req.approver}", ""]
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
              (f"Prepared for human review; authorised by {req.approver} at "
               f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}. This brief recommends "
               + "nothing be awarded; decisions rest with the evaluation committee."), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    resp = DraftBriefResponse(brief_path=str(path), citation_count=cites,
                              findings_included=len(req.findings), approver=req.approver)
    audit_event("draft_committee_brief", req, resp, approver=req.approver, gate="approved")
    return resp.model_dump(mode="json")


def raise_flag(category: str, severity: str, claim: str, evidence: str,
               subject_ocids: list[str], sources: list[dict],
               recommended_action: str, approver: str | None = None,
               model: str | None = None,
               output_dir: Path | None = None) -> dict:
    """Append a structured flag to output/flags.jsonl. Stays pending_approval
    until a NAMED HUMAN approver is supplied; both states are audited.

    A supplied-but-invalid approver ("auto", the model's own name, "x") is
    refused outright with approver_invalid and writes nothing — an automation
    token must not be able to promote a flag to approved.
    """
    if approver:
        violation = approver_violation(approver, model=_acting_model(model))
        if violation:
            return _gate_refusal("raise_flag", violation,
                                 {"claim": claim, "sources": sources, "approver": approver},
                                 approver, "flag")
    try:
        req = RaiseFlagRequest(category=FlagCategory(category), severity=Severity(severity),
                               claim=claim, evidence=evidence, subject_ocids=subject_ocids,
                               sources=[SourceRef(**s) for s in sources],
                               recommended_action=recommended_action, approver=approver)
    except (ValidationError, TypeError, ValueError) as e:
        code = "citation_required" if "sources" in str(e) else "validation"
        err = ToolError(code=code, message="flag rejected", detail=str(e)[:600])
        audit_event("raise_flag", {"claim": claim, "sources": sources}, err, approver=approver)
        return err.model_dump(mode="json")
    output_dir = _output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    flags_path = output_dir / "flags.jsonl"
    status = "approved" if req.approver else "pending_approval"
    record = {"flag_id": uuid.uuid4().hex[:8],
              "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "status": status, **req.model_dump(mode="json")}
    with flags_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    resp = RaiseFlagResponse(flag_id=record["flag_id"], flags_path=str(flags_path), status=status)
    audit_event("raise_flag", req, resp, approver=req.approver, gate=status)
    return resp.model_dump(mode="json")

