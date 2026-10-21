#!/usr/bin/env python3
"""Render local/diagram/architecture.mmd to PNG + SVG via mermaid.ink.

No dependencies beyond the stdlib: no mmdc, graphviz, imagemagick, matplotlib or
PIL exist on this machine, and the submission artifact still has to exist.

Hard-won service constraints, all observed empirically rather than assumed:
  * The source is ~7 KB. Plain base64 makes a ~9.7k-char URL and mermaid.ink
    answers HTTP 414 Request-URI Too Large, so we must use the `pako:` form from
    the mermaid live editor: base64url(zlib.deflate(JSON state)) -> ~4.5k chars.
  * `?scale=N` alone is rejected: HTTP 400 "scale can only be set when either
    width or height is set". width must be present for scale to be honoured.
  * `width=2400` returns HTTP 503 Service Unavailable: too large to render.
    width=1800 succeeds.
  * Omitting `type` returns a JPEG (\\xff\\xd8 JFIF), NOT a PNG. `type=png` must
    be explicit or the artifact is a lossy raster with muddy small text.
  * SVG lives on the `/svg/` endpoint; `/img/?type=svg` also returns JPEG.

PNG dimensions are read out of the IHDR chunk and JPEG out of its SOF marker, so
"big enough to read" is verified without an image library.

Usage:  uv run python local/diagram/render.py [--width N]
"""
from __future__ import annotations

import base64
import json
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "architecture.mmd"
SERVICE = "https://mermaid.ink"
TIMEOUT = 180
ENDPOINT = {"png": "img", "svg": "svg"}

# Tried in order; first success wins. width is required before scale is honoured,
# and 2400 is known to 503, so the ladder starts at 1800.
LADDER = [
    {"width": "1800", "scale": "2"},
    {"width": "1800"},
    {"width": "1600"},
    {"width": "1400"},
]


def build_url(endpoint: str, kind: str, code: str, extra: dict, mode: str) -> str:
    q = {"bgColor": "FFFFFF", **extra}
    if endpoint == "img":
        q["type"] = kind  # explicit: omitting it silently yields JPEG
    if mode == "pako":
        state = {"code": code, "mermaid": {"theme": "default"}}
        blob = zlib.compress(json.dumps(state).encode("utf-8"), 9)
        token = base64.urlsafe_b64encode(blob).decode("ascii")
        return f"{SERVICE}/{endpoint}/pako:{token}?{urllib.parse.urlencode(q)}"
    token = base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii")
    return f"{SERVICE}/{endpoint}/{token}?{urllib.parse.urlencode(q)}"


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    if data[:3] != b"\xff\xd8\xff":
        return None
    i, n = 2, len(data)
    while i < n - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + seg
    return None


def svg_size(data: bytes) -> tuple[int, int] | None:
    head = data[:4000].decode("utf-8", "replace")
    m = re.search(r'viewBox="[\d.\-\s]+?([\d.]+)[\s,]+([\d.]+)"', head)
    if m:
        return int(float(m.group(1))), int(float(m.group(2)))
    w, h = re.search(r'width="([\d.]+)', head), re.search(r'height="([\d.]+)', head)
    return (int(float(w.group(1))), int(float(h.group(1)))) if w and h else None


def sniff(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data.lstrip()[:5] == b"<?xml" or data.lstrip()[:4] == b"<svg":
        return "svg"
    return "unknown"


def fetch(url: str, out: Path, want: str, label: str) -> tuple[bool, tuple[int, int] | None]:
    req = urllib.request.Request(url, headers={"User-Agent": "lens-diagram-render/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, data = r.status, r.read()
    except urllib.error.HTTPError as e:
        print(f"  [{label}] HTTP {e.code}: {e.read()[:140]!r}")
        return False, None
    except Exception as e:
        print(f"  [{label}] {type(e).__name__}: {e}")
        return False, None

    got = sniff(data)
    if got == "unknown":
        print(f"  [{label}] HTTP {status} but NOT an image: {data[:120]!r}")
        return False, None
    if got != want:
        print(f"  [{label}] HTTP {status} returned {got.upper()}, wanted {want.upper()}"
              f" - rejecting ({len(data)} bytes)")
        return False, None

    dims = {"png": png_size, "jpeg": jpeg_size, "svg": svg_size}[got](data)
    out.write_bytes(data)
    print(f"  [{label}] OK HTTP {status} -> {out.name}: {got.upper()} "
          f"{len(data)} bytes, dims={dims}")
    return True, dims


def render(kind: str, code: str, out: Path, ladder: list[dict]) -> tuple[int, int] | None:
    endpoint = ENDPOINT[kind]
    print(f"\nrendering {kind.upper()} via /{endpoint}/")
    for extra in ladder:
        tag = ",".join(f"{k}={v}" for k, v in extra.items())
        for mode in ("pako", "plain-b64"):
            url = build_url(endpoint, kind, code, extra, mode)
            ok, dims = fetch(url, out, kind, f"{tag}/{mode}")
            if ok:
                return dims
        if extra == ladder[0]:
            print("  (plain-b64 unusable at this source size: HTTP 414)")
    return None


def main() -> int:
    ladder = LADDER
    if "--width" in sys.argv:
        w = sys.argv[sys.argv.index("--width") + 1]
        ladder = [{"width": w, "scale": "2"}, {"width": w}]

    if not SRC.exists():
        print(f"missing source: {SRC}")
        return 2
    code = SRC.read_text(encoding="utf-8")
    print(f"source: {SRC.name} ({len(code)} bytes, {code.count(chr(10))} lines)")

    png_dims = render("png", code, HERE / "architecture.png", ladder)
    svg_dims = render("svg", code, HERE / "architecture.svg", ladder)

    print("\n=== ACCEPTANCE CHECK (task 2) ===")
    fails = []
    png = HERE / "architecture.png"
    if not png.exists() or png_dims is None:
        print("architecture.png missing or not a genuine PNG")
        fails.append("missing-png")
    else:
        long_edge = max(png_dims)
        print(f"genuine PNG, not an HTML error page : True")
        print(f"dimensions                         : {png_dims[0]} x {png_dims[1]}")
        print(f"long edge >= 1600px                : {long_edge} -> {long_edge >= 1600}")
        print(f"byte size                          : {png.stat().st_size}")
        if long_edge < 1600:
            fails.append("too-small")
    if svg_dims is None:
        fails.append("no-svg")
    else:
        print(f"svg dimensions                     : {svg_dims}")

    print(f"\nresult: {'PASS' if not fails else 'FAIL ' + ','.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
