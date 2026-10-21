#!/usr/bin/env python3
"""Measure whether local/diagram/architecture.svg is actually READABLE.

An HTTP 200 from a render service is not verification. The first attempt produced
a syntactically valid, technically correct diagram whose text measured 3.1px at a
1200px display width (58 node boxes on a 4708x5326 canvas). That is unreadable,
and only geometry reveals it.

    effective_px = declared_font_px * display_width / viewBox_width

WHY THIS DOES NOT JUST TAKE min(all font-size declarations):
Mermaid emits CSS rules for elements that a static export does not contain. On
this diagram the declarations were 12px, 18px and 34px, and the naive minimum
made it look like edge labels were 12px (4.1px effective -> "BAD"). Inspecting
the selectors showed otherwise:

    12px  #mermaid-svg div.mermaidTooltip    -> hover tooltip, 0 such elements
    18px  #mermaid-svg .flowchartTitleText   -> diagram title, 0 such elements
    34px  #mermaid-svg / #mermaid-svg svg     -> inherited by ALL visible text

Node labels, subgraph (cluster) titles and edge labels all render via
`<span class="nodeLabel">`, so every visible glyph is 34px. Grading legibility
on an unused tooltip rule would have driven a pointless redesign.

So each rule is classified by whether its selector matches an element that is
actually present, and only present-element sizes count.

Usage:  uv run python local/diagram/measure.py
Exit 0 only if all visible text is >= THRESHOLD px effective at CRITICAL_WIDTH.
"""
from __future__ import annotations

import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG = HERE / "architecture.svg"
PNG = HERE / "architecture.png"

REQUIRED_LABELS = [
    "Agents", "LLMs/models", "MCP client/server", "MCP tools/resources",
    "External APIs", "Data sources", "Human-in-the-loop", "OVERALL DATA FLOW",
]
DISPLAY_WIDTHS = (900, 1200, 1600, 3600)
THRESHOLD = 9.0
CRITICAL_WIDTH = 1200


def png_size(data: bytes):
    return struct.unpack(">II", data[16:24]) if data[:8] == b"\x89PNG\r\n\x1a\n" else None


def classify_font_rules(svg: str) -> tuple[float | None, dict[float, str], list[str]]:
    """Return (baseline_size, {size: selectors_present}, [absent_selectors])."""
    body = re.sub(r"<style[^>]*>.*?</style>", "", svg, flags=re.S)
    style = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", svg, re.S))

    rules: list[tuple[str, float]] = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*font-size:\s*([\d.]+)px[^{}]*)\}", style):
        rules.append((m.group(1).strip(), float(m.group(3))))

    baseline, present, absent = None, {}, []
    for selector, size in rules:
        classes = re.findall(r"\.([A-Za-z][\w-]*)", selector)
        # A rule is "generic" when it targets the root svg rather than a class.
        generic = not classes
        if generic:
            baseline = size if baseline is None else max(baseline or 0, size)
            present.setdefault(size, selector[-60:])
            continue
        if any(re.search(r'class="[^"]*\b' + re.escape(c) + r'\b', body) for c in classes):
            present.setdefault(size, selector[-60:])
        else:
            absent.append(f"{size}px <- {selector.strip()[-70:]}")
    return baseline, present, absent


def main() -> int:
    if not SVG.exists():
        print(f"missing {SVG}")
        return 2
    svg = SVG.read_text(encoding="utf-8")

    vb = [float(x) for x in re.search(r'viewBox="([\d.\-\s]+)"', svg).group(1).split()]
    vw, vh = vb[2], vb[3]
    root = ET.fromstring(svg)
    rects = [(float(r.get("width", 0)), float(r.get("height", 0)))
             for r in root.iter("{http://www.w3.org/2000/svg}rect") if r.get("width")]
    nodes = [r for r in rects if r[0] > 40 and r[1] > 20]

    baseline, present, absent = classify_font_rules(svg)
    visible_sizes = sorted(present) or ([baseline] if baseline else [])
    vmin, vmax = (min(visible_sizes), max(visible_sizes)) if visible_sizes else (0, 0)

    print(f"viewBox           : {vw:.0f} x {vh:.0f}   aspect {vw / vh:.2f}")
    print(f"node boxes        : {len(nodes)}")
    print(f"visible text sizes: {visible_sizes}  (inherited baseline {baseline}px)")
    print(f"nodeLabel spans   : {svg.count('class=' + chr(34) + 'nodeLabel')}")
    print(f"edgeLabel groups  : {len(re.findall(r'class=' + chr(34) + r'edgeLabel', svg))}")
    print(f"cluster titles    : {svg.count('cluster-label')}")
    if absent:
        print(f"\nrules EXCLUDED (selector matches no element in a static export):")
        for a in absent:
            print(f"   {a}")
    if PNG.exists():
        d = png_size(PNG.read_bytes())
        print(f"\npng               : {d[0]} x {d[1]}  ({PNG.stat().st_size} bytes)")

    print(f"\n{'display width':>14} | {'smallest visible':>18} | {'largest visible':>16}")
    print("-" * 56)
    worst = None
    for disp in DISPLAY_WIDTHS:
        lo, hi = vmin * disp / vw, vmax * disp / vw
        if disp == CRITICAL_WIDTH:
            worst = lo
        mark = "OK " if lo >= THRESHOLD else ("~  " if lo >= 6 else "BAD")
        star = "  <-- critical" if disp == CRITICAL_WIDTH else ""
        print(f"{disp:>11}px | {lo:8.1f}px {mark}      | {hi:8.1f}px{star}")

    errors = re.findall(r"(?i)syntax error|error in text|parse error", svg)
    missing = [l for l in REQUIRED_LABELS if l not in svg]
    print(f"\nrender-error strings     : {len(errors)}")
    print(f"required labels missing  : {missing or 'none - all 8 present'}")
    print(f"paths / marker refs      : {svg.count('<path')} / {svg.count('marker')}")
    print(f"\nsmallest visible text @{CRITICAL_WIDTH}px : {worst:.1f}px (threshold {THRESHOLD})")

    fails = []
    if errors:
        fails.append("render-errors")
    if missing:
        fails.append(f"missing-labels:{missing}")
    if worst is None or worst < THRESHOLD:
        fails.append(f"smallest-visible-{worst:.1f}px<{THRESHOLD}")

    print(f"\nRESULT: {'PASS - legible' if not fails else 'FAIL ' + ','.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
