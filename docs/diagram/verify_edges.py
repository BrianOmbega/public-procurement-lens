#!/usr/bin/env python3
"""Prove every arrow in architecture.mmd corresponds to real code.

The brief says an unsourced finding against a supplier is worse than no finding
at all. A diagram is the same kind of claim: an arrow asserts that a connection
exists. So every edge is matched to a `file:pattern` pair that grep must find in
src/lens/. Edges are extracted from the .mmd programmatically, and any edge with
NO entry in the mapping table fails the run - so a forgotten justification is
caught rather than silently passing.

Usage:  uv run python local/diagram/verify_edges.py
Exit 0 only if every extracted edge has a mapping and every mapped pattern
is found in the cited file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # local/diagram/ -> repo root
SRC = ROOT / "src" / "lens"
MMD = Path(__file__).resolve().parent / "architecture.mmd"

# edge (from, to) -> (relative file under src/lens, regex that must match)
MAPPING: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("OCDS", "DB"): [("ingest.py", r"ijson"), ("ingest.py", r"sqlite3\.connect")],
    ("DB", "READ"): [("ingest.py", r"mode=ro"), ("mcp_server.py", r"connect_ro")],
    ("BRIDGE", "LENS"): [("mcp_bridge.py", r"stdio_client"), ("mcp_bridge.py", r"ClientSession")],
    ("BRIDGE", "STUB"): [("mcp_bridge.py", r"DEFAULT_LENS_CMD"), ("mcp_bridge.py", r"lens-stub")],
    ("BRIDGE", "FETCH"): [("demo.py", r"mcp-server-fetch")],
    ("LENS", "READ"): [("mcp_server.py", r"@mcp\.tool\(\)"), ("mcp_server.py", r"get_supplier_history")],
    ("LENS", "ACT"): [("mcp_server.py", r"draft_committee_brief"), ("mcp_server.py", r"raise_flag")],
    ("LG", "BRIDGE"): [("graph.py", r"self\.bridge\.call")],
    ("LG", "GM"): [("graph.py", r"self\.model\.plan"), ("models.py", r"def get_model")],
    ("GM", "OW"): [("models.py", r"qwen3"), ("models.py", r"11434|ollama")],
    ("GM", "FR"): [("models.py", r"OPENAI_BASE_URL")],
    ("LG", "CHK"): [("graph.py", r'self_check')],
    ("CHK", "LG"): [("graph.py", r"MAX_REPAIRS"), ("graph.py", r'"synthesize"')],
    ("LG", "GATE"): [("graph.py", r"human_gate"), ("graph.py", r"interrupt\(")],
    ("GATE", "NAME"): [("graph.py", r"approver_violation")],
    ("NAME", "ACT"): [("graph.py", r'approver=gate')],
    ("NAME", "FAIL"): [("graph.py", r'"fail"')],
    ("ACT", "BRIEF"): [("actions.py", r"brief-"), ("schemas/contract.py", r"TOOL_NAMES")],
    ("ACT", "PORTAL"): [("schemas/contract.py", r"PORTAL_BASE"), ("analysis.py", r"PORTAL_BASE")],
    ("FETCH", "OCP"): [("graph.py", r"open-contracting\.org")],
    ("LG", "AUDIT"): [("graph.py", r"audit_event|_audit_node")],
    ("BRIDGE", "AUDIT"): [("mcp_bridge.py", r"audit_event")],
    ("ACT", "AUDIT"): [("actions.py", r"audit_event")],
}


def extract_edges(text: str) -> list[tuple[str, str]]:
    """Pull (src, dst) from every `A --> B`, `A -->|label| B`, `A -.-> B`."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("%%") or s.startswith("subgraph") or s.startswith("class"):
            continue
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]*)\s*(?:-\.?->|-->)\s*(?:\|[^|]*\|\s*)?([A-Z][A-Z0-9_]*)", s):
            out.append((m.group(1), m.group(2)))
    return out


def main() -> int:
    if not SRC.is_dir():
        print(f"FATAL: {SRC} is not a directory - ROOT/parents[] offset is wrong.")
        print("       Fix ROOT above rather than trusting the FILE MISSING cascade.")
        return 2
    text = MMD.read_text(encoding="utf-8")
    edges = extract_edges(text)
    uniq = sorted(set(edges))
    print(f"extracted {len(edges)} edge declarations, {len(uniq)} unique")
    print(f"mapping table covers {len(MAPPING)} edges\n")

    unmatched, failed, ok = [], [], []
    for e in uniq:
        if e not in MAPPING:
            unmatched.append(e)
            continue
        for rel, pat in MAPPING[e]:
            f = SRC / rel
            if not f.exists():
                failed.append((e, rel, pat, "FILE MISSING"))
                continue
            body = f.read_text(encoding="utf-8", errors="replace")
            hit = re.search(pat, body)
            if hit:
                line = body[: hit.start()].count("\n") + 1
                ok.append((e, f"{rel}:{line}", pat))
            else:
                failed.append((e, rel, pat, "pattern not found"))

    # Reverse check: mappings for edges that no longer exist in the diagram.
    stale = [e for e in MAPPING if e not in set(uniq)]

    print("=== EDGE -> SOURCE (verified) ===")
    for e, loc, pat in ok:
        print(f"  {e[0]:>7} -> {e[1]:<7} {loc:<26} /{pat}/")

    if unmatched:
        print("\n=== EDGES WITH NO JUSTIFICATION (must be deleted or mapped) ===")
        for e in unmatched:
            print(f"  {e[0]} -> {e[1]}")
    if failed:
        print("\n=== MAPPINGS THAT DID NOT RESOLVE ===")
        for e, rel, pat, why in failed:
            print(f"  {e[0]} -> {e[1]}   {rel}   /{pat}/   {why}")
    if stale:
        print("\n=== STALE MAPPINGS (edge no longer drawn) ===")
        for e in stale:
            print(f"  {e[0]} -> {e[1]}")

    print(f"\nedges drawn            : {len(uniq)}")
    print(f"source refs verified   : {len(ok)}")
    print(f"unjustified edges      : {len(unmatched)}")
    print(f"unresolved refs        : {len(failed)}")
    print(f"stale mappings         : {len(stale)}")
    bad = bool(unmatched or failed)
    print(f"\nRESULT: {'PASS - every arrow traces to source' if not bad else 'FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
