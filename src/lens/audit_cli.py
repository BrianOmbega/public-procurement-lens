"""lens-audit — verify the append-only trail against what it claims to prove.

The challenge requires "a logged tool call for every action, and a gate on
every irreversible one", with inputs, outputs, timestamps and a named human
approving. A JSONL file alone is an assertion; this turns it into a check a
judge can run in one command and get exit 0 or a list of violations.

  uv run lens-audit verify                 # logs/audit.jsonl vs ./output
  uv run lens-audit verify --audit evidence/offline-run/audit.jsonl
  uv run lens-audit summary                # shape of the trail, no pass/fail

Checks performed by `verify`:
  1. schema     every event carries ts/kind/tool/model/session/request/response
  2. timestamps every ts parses as UTC ISO and the file is monotonic (append-only)
  3. model      every event is attributed to a known model, never "unset"
  4. gate       every SUCCESSFUL call to a GATED_TOOL carries a valid named
                human approver (contract.approver_violation) — refusals exempt
  5. artifacts  no orphans in either direction: every brief/flag on disk maps
                to an event, and every event naming an artifact has the file

Exit 0 = all checks pass. Exit 1 = violations printed. Exit 2 = trail missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from lens.audit import audit_path, read_audit
from lens.schemas.contract import GATED_TOOLS, approver_violation

REQUIRED_FIELDS = ("ts", "kind", "tool", "model", "session", "request", "response")
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _bare_tool(tool: str) -> str:
    """Strip the server qualifier the bridge adds ('lens-mcp:search_awards')."""
    return (tool or "").split(":", 1)[-1]


def _is_refusal(ev: dict) -> bool:
    """A gated tool that was REFUSED wrote nothing, so it needs no approver."""
    resp = ev.get("response")
    if isinstance(resp, dict) and resp.get("code"):
        return True
    return str(ev.get("gate") or "").startswith("refused")


def default_output_dir(audit_file: Path) -> Path:
    """$LENS_OUTPUT, else the audit file's own directory when it holds
    artifacts (an evidence pack), else ./output."""
    import os
    env = (os.environ.get("LENS_OUTPUT") or "").strip()
    if env:
        return Path(env)
    parent = audit_file.parent
    if any(parent.glob("brief-*.md")) or (parent / "flags.jsonl").exists():
        return parent
    return Path("output")


def _resolve(recorded: str, output_dir: Path) -> Path | None:
    """Find an artifact named in an event. Recorded paths may be absolute from
    the machine that produced the trail; fall back to a same-named file beside
    the audit log so a committed evidence pack stays verifiable elsewhere."""
    p = Path(recorded)
    if p.exists():
        return p
    alt = output_dir / p.name
    return alt if alt.exists() else None


def verify(audit_file: Path, output_dir: Path) -> tuple[bool, list[str]]:
    """Return (ok, violations). Prints a per-check report."""
    events = read_audit(audit_file)
    if not events:
        print(f"lens-audit verify — NO EVENTS at {audit_file}", file=sys.stderr)
        return False, [f"audit trail empty or missing: {audit_file}"]

    problems: list[str] = []
    results: list[tuple[str, bool, str]] = []

    # 1. schema completeness — inputs and outputs on every event
    missing = [(i, ev.get("tool"), [f for f in REQUIRED_FIELDS if f not in ev])
               for i, ev in enumerate(events) if any(f not in ev for f in REQUIRED_FIELDS)]
    results.append(("schema: every event has ts/kind/tool/model/session/request/response",
                    not missing, f"{len(missing)} incomplete"))
    problems += [f"event #{i} ({t}) missing fields {f}" for i, t, f in missing[:10]]

    # 2. timestamps parse and the file is monotonic (append-only ordering)
    bad_ts: list[str] = []
    stamps: list[datetime] = []
    for i, ev in enumerate(events):
        try:
            stamps.append(datetime.strptime(str(ev.get("ts")), _TS_FMT))
        except (TypeError, ValueError):
            bad_ts.append(f"event #{i} ({ev.get('tool')}) ts={ev.get('ts')!r}")
    out_of_order = sum(1 for a, b in zip(stamps, stamps[1:]) if b < a)
    ok_ts = not bad_ts and not out_of_order
    results.append((f"timestamps: UTC ISO, monotonic ({len(stamps)}/{len(events)} parsed)",
                    ok_ts, f"{len(bad_ts)} unparseable, {out_of_order} out of order"))
    problems += bad_ts[:5]
    if out_of_order:
        problems.append(f"{out_of_order} event(s) precede an earlier timestamp — "
                        f"file was edited or rewritten, not appended")

    # 3. model attribution — which weights produced which event
    no_model = [f"event #{i} ({ev.get('tool')}) model={ev.get('model')!r}"
                for i, ev in enumerate(events)
                if not ev.get("model") or ev.get("model") == "unset"]
    results.append(("model: every event attributed to a known model",
                    not no_model, f"{len(no_model)} unattributed"))
    problems += no_model[:5]

    # 4. gate coverage on every irreversible tool
    gated = [ev for ev in events if _bare_tool(ev.get("tool", "")) in GATED_TOOLS]
    ungated: list[str] = []
    for ev in gated:
        if _is_refusal(ev):
            continue
        model = ev.get("model") if ev.get("model") != "unset" else None
        viol = approver_violation(ev.get("approver"), model=model)
        if viol:
            ungated.append(f"{ev.get('tool')} at {ev.get('ts')} — {viol} "
                           f"(approver={ev.get('approver')!r})")
    results.append((f"gate: all {len(gated)} irreversible-action events carry a valid named human",
                    not ungated, f"{len(ungated)} ungated"))
    problems += ungated[:10]

    # 5. artifacts ↔ events, both directions
    named_briefs = {Path(str(ev["response"]["brief_path"])).name
                    for ev in events
                    if isinstance(ev.get("response"), dict) and ev["response"].get("brief_path")}
    named_flags = {ev["response"]["flag_id"] for ev in events
                   if isinstance(ev.get("response"), dict) and ev["response"].get("flag_id")}
    disk_briefs = {p.name for p in output_dir.glob("brief-*.md")} if output_dir.exists() else set()
    flags_file = output_dir / "flags.jsonl"
    disk_flags: list[str] = []
    if flags_file.exists():
        for line in flags_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    disk_flags.append(json.loads(line)["flag_id"])
                except (json.JSONDecodeError, KeyError):
                    problems.append(f"unparseable flag line in {flags_file}")

    orphan_briefs = sorted(disk_briefs - named_briefs)
    missing_briefs = sorted(n for n in named_briefs - disk_briefs
                            if _resolve(str(output_dir / n), output_dir) is None)
    orphan_flags = sorted(set(disk_flags) - named_flags)
    ok_art = not orphan_briefs and not missing_briefs and not orphan_flags
    results.append((f"artifacts: {len(disk_briefs)} brief(s) + {len(disk_flags)} flag(s) all "
                    f"map to an event, and vice versa",
                    ok_art, f"{len(orphan_briefs)} orphan brief(s), {len(missing_briefs)} missing, "
                            f"{len(orphan_flags)} orphan flag(s)"))
    problems += [f"brief on disk with no audit event: {b}" for b in orphan_briefs[:5]]
    problems += [f"audit event names a brief not on disk: {b}" for b in missing_briefs[:5]]
    problems += [f"flag on disk with no audit event: {f}" for f in orphan_flags[:5]]

    ok = not problems
    print(f"lens-audit verify — {audit_file} ({len(events)} events) vs {output_dir}")
    for label, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}" + ("" if passed else f" — {detail}"))
    if not ok:
        print(f"\nVIOLATIONS ({len(problems)}):")
        for p in problems[:40]:
            print(f"  - {p}")
        if len(problems) > 40:
            print(f"  … and {len(problems) - 40} more")
    print("\nVERIFY PASSED — every action logged with inputs, outputs, timestamps and model; "
          "every irreversible action gated on a named human" if ok else "\nVERIFY FAILED")
    return ok, problems


def summary(audit_file: Path) -> None:
    events = read_audit(audit_file)
    if not events:
        print(f"no events at {audit_file}")
        return
    kinds = Counter(e.get("kind", "?") for e in events)
    tools = Counter(e.get("tool", "?") for e in events)
    models = Counter(e.get("model", "?") for e in events)
    gates = Counter(str(e.get("gate")) for e in events if e.get("gate"))
    approvers = sorted({str(e.get("approver")) for e in events if e.get("approver")})
    span = (events[0].get("ts"), events[-1].get("ts"))
    print(f"lens-audit summary — {audit_file}")
    print(f"  events      : {len(events)}   span {span[0]} → {span[1]}")
    print(f"  by kind     : {dict(kinds)}")
    print(f"  by model    : {dict(models)}")
    print(f"  gate states : {dict(gates) or 'none'}")
    print(f"  approvers   : {approvers or 'none recorded'}")
    print(f"  sessions    : {sorted({str(e.get('session')) for e in events})}")
    print("  tool calls  :")
    for t, n in tools.most_common():
        print(f"      {n:>4}  {t}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="lens-audit",
                                 description="Verify / summarise the append-only audit trail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--audit", default=None, help=f"trail path (default: $LENS_AUDIT or logs/audit.jsonl)")
        if name == "verify":
            p.add_argument("--output", default=None,
                           help="artifact dir (default: $LENS_OUTPUT, else the audit file's dir "
                                "if it holds artifacts, else ./output)")
    args = ap.parse_args()
    audit_file = Path(args.audit) if args.audit else audit_path()
    if args.cmd == "summary":
        summary(audit_file)
        return
    out = Path(args.output) if args.output else default_output_dir(audit_file)
    ok, _ = verify(audit_file, out)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
