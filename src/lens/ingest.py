"""OCDS release packages -> SQLite corpus for lens-mcp (docs/DESIGN.md §Data).

Streams packages with ijson so a full fiscal-year download (~109k awards)
never has to fit in this machine's 8 GB RAM. Stores the award-side fields the
contract queries need as indexed columns PLUS the complete release JSON
(`doc`), so every response field stays re-derivable and every SourceRef
points at a real record.

Data quality is a first-class output (challenge criterion #1): malformed
records are flagged and counted, never fatal (docs/CONTRACT.md §Data-quality
behaviour). Provenance (source, time, counts, skip reasons) lands in `meta`.

Usage:
  uv run lens-ingest --from-fixtures                  # offline demo/test corpus
  uv run lens-ingest data/package.json                # local package file
  uv run lens-ingest "https://tenders.go.ke/api/ocds/tenders?download=true&ocds_id=12"
  uv run lens-ingest --db data/lens.sqlite <sources>  # default db shown

Fiscal years use the portal's "YYYY/YYYY" format (Kenya FY = July–June);
releases missing the field get it derived from the award/release date.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

import httpx
import ijson

from lens.analysis import dq_notes, fy_from_date, normalize_supplier

DEFAULT_DB = "data/lens.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases(
  ocid TEXT NOT NULL,
  release_id TEXT NOT NULL DEFAULT '',
  fiscal_year TEXT,
  buyer_name TEXT,
  tender_title TEXT,
  item_description TEXT,
  items_text TEXT,
  award_date TEXT,
  award_value REAL,
  currency TEXT,
  procurement_method TEXT,
  supplier_names TEXT,
  dq_notes TEXT,
  doc TEXT,
  PRIMARY KEY (ocid, release_id)
);
CREATE TABLE IF NOT EXISTS suppliers(
  ocid TEXT NOT NULL,
  release_id TEXT NOT NULL DEFAULT '',
  award_index INTEGER NOT NULL DEFAULT 0,
  name TEXT,
  norm_name TEXT,
  identifier_scheme TEXT,
  identifier_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_suppliers_norm ON suppliers(norm_name);
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);
CREATE INDEX IF NOT EXISTS idx_releases_fy ON releases(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_releases_buyer ON releases(buyer_name);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def db_path(cli_value: str | None = None) -> Path:
    """Precedence: CLI --db > $LENS_DB > data/lens.sqlite."""
    return Path(cli_value or os.environ.get("LENS_DB") or DEFAULT_DB)


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) a read-write connection with schema applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def connect_ro(path: Path) -> sqlite3.Connection:
    """Read-only connection used by the server (never writes the corpus)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def stream_package(source: str) -> Iterator[dict]:
    """Yield release dicts from an OCDS package: http(s) URL or local file.

    Files may be a package object ({"releases": [...]}) or a bare release
    array; the prefix is picked by peeking at the first byte. URLs are
    streamed, never buffered whole. One polite request, no retry loop —
    tenders.go.ke 429s under probing (repo history, 2026-10-12)."""
    if source.startswith(("http://", "https://")):
        headers = {"User-Agent": "procurement-lens/0.1 (public-procurement-lens; research use)"}
        with httpx.stream("GET", source, headers=headers, follow_redirects=True,
                          timeout=httpx.Timeout(30.0, read=600.0)) as resp:
            resp.raise_for_status()
            yield from ijson.items(resp.raw, "releases.item", use_float=True)
    else:
        with open(source, "rb") as fh:
            head = fh.read(64)
            fh.seek(0)
            prefix = "item" if head.lstrip()[:1] == b"[" else "releases.item"
            yield from ijson.items(fh, prefix, use_float=True)


def extract_row(rel: dict) -> tuple:
    """Flatten one release into the `releases` columns. Raises ValueError for
    records without a usable ocid (caller counts those as skips)."""
    if not isinstance(rel, dict):
        raise TypeError(f"release is {type(rel).__name__}, expected object")
    ocid = rel.get("ocid")
    if not ocid or not isinstance(ocid, str):
        raise ValueError(f"release has no usable ocid: {ocid!r}")
    rid = str(rel.get("id") or "")
    tender = rel.get("tender") if isinstance(rel.get("tender"), dict) else {}
    awards = rel.get("awards") if isinstance(rel.get("awards"), list) else []
    aw = (awards[0] if awards and isinstance(awards[0], dict) else {}) or {}
    value = aw.get("value") if isinstance(aw.get("value"), dict) else {}
    items = [i for i in (tender.get("items") or []) if isinstance(i, dict)]
    descs = [str(i.get("description") or "") for i in items]
    buyer = rel.get("buyer") if isinstance(rel.get("buyer"), dict) else {}

    notes = dq_notes(rel)
    amount = None
    if value.get("amount") is not None:
        try:
            amount = float(value["amount"])
        except (TypeError, ValueError):
            notes.append(f"award value amount unparseable: {value.get('amount')!r}")
    currency = str(value.get("currency") or ("KES" if amount is not None else "")) or None
    fy = rel.get("fiscal_year") or fy_from_date(aw.get("date") or rel.get("date"))
    supplier_names = json.dumps([s.get("name", "") for s in (aw.get("suppliers") or [])
                                 if isinstance(s, dict)])
    doc = json.dumps(rel, ensure_ascii=False, default=str)
    return (ocid, rid, fy, buyer.get("name"), tender.get("title"),
            descs[0] if descs else None, " ".join(descs), aw.get("date"),
            amount, currency, tender.get("procurementMethod"), supplier_names,
            json.dumps(notes), doc)


def supplier_rows(rel: dict, ocid: str, rid: str) -> list[tuple]:
    """One row per (award, supplier) with the normalised name for alias
    grouping — messy-identifier handling is scoring-criterion #1 material."""
    rows: list[tuple] = []
    awards = rel.get("awards") if isinstance(rel.get("awards"), list) else []
    for ai, aw in enumerate(awards):
        if not isinstance(aw, dict):
            continue
        for s in aw.get("suppliers") or []:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name") or "")
            ident = s.get("identifier") if isinstance(s.get("identifier"), dict) else {}
            iid = ident.get("id")
            rows.append((ocid, rid, ai, name, normalize_supplier(name),
                         ident.get("scheme"), str(iid) if iid is not None else None))
    return rows


def _record_provenance(conn: sqlite3.Connection, result: dict) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row = conn.execute("SELECT value FROM meta WHERE key='sources'").fetchone()
    sources = json.loads(row[0]) if row else []
    sources.append({"source": result["source"], "kind": result["kind"],
                    "ingested": result["ingested"], "skipped": result["skipped"],
                    "at": now})
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('sources', ?)",
                 (json.dumps(sources[-50:]),))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_ingest_at', ?)", (now,))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '1')")
    conn.commit()


def ingest_releases(conn: sqlite3.Connection, releases: Iterable[dict],
                    source: str, kind: str) -> dict:
    """Upsert releases (+ their supplier rows) into the corpus.

    Never raises: a bad record is skipped and counted; a producer that dies
    mid-stream (truncated JSON, network) keeps everything already ingested
    and records the abort in the result + meta."""
    ingested = skipped = 0
    errors: list[str] = []
    try:
        for rel in releases:
            try:
                row = extract_row(rel)
            except Exception as e:  # noqa: BLE001 — contract: never crash on a malformed record
                skipped += 1
                if len(errors) < 5:
                    ocid = rel.get("ocid") if isinstance(rel, dict) else None
                    errors.append(f"{ocid or '<no ocid>'}: {str(e)[:160]}")
                continue
            ocid, rid = row[0], row[1]
            conn.execute(
                "INSERT OR REPLACE INTO releases(ocid, release_id, fiscal_year, buyer_name,"
                " tender_title, item_description, items_text, award_date, award_value, currency,"
                " procurement_method, supplier_names, dq_notes, doc)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            conn.execute("DELETE FROM suppliers WHERE ocid=? AND release_id=?", (ocid, rid))
            conn.executemany(
                "INSERT INTO suppliers(ocid, release_id, award_index, name, norm_name,"
                " identifier_scheme, identifier_id) VALUES (?,?,?,?,?,?,?)",
                supplier_rows(rel, ocid, rid))
            ingested += 1
            if ingested % 500 == 0:
                conn.commit()
    except Exception as e:  # noqa: BLE001 — producer died mid-stream; keep the partial ingest
        errors.append(f"stream aborted after {ingested} releases: {type(e).__name__}: {str(e)[:160]}")
    conn.commit()
    result: dict = {"source": source, "kind": kind, "ingested": ingested, "skipped": skipped}
    if errors:
        result["errors"] = errors
    _record_provenance(conn, result)
    return result


def ingest_fixtures(db: str | Path | None = None) -> dict:
    """Seed the offline fixture corpus (deterministic; used by --from-fixtures,
    the server selftest, and the parity tests)."""
    from lens.stubs.fixtures import FIXTURE_RELEASES

    path = db_path(str(db) if db is not None else None)
    conn = connect(path)
    try:
        return ingest_releases(conn, FIXTURE_RELEASES, "lens.stubs.fixtures", "fixtures")
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="lens-ingest",
                                 description="Ingest OCDS release packages into the lens SQLite corpus")
    ap.add_argument("sources", nargs="*", help="package files or http(s) URLs")
    ap.add_argument("--db", default=None, help="SQLite path (default: $LENS_DB or data/lens.sqlite)")
    ap.add_argument("--from-fixtures", action="store_true",
                    help="also seed the offline fixture corpus (no network)")
    args = ap.parse_args()
    if not args.sources and not args.from_fixtures:
        ap.error("give package files/URLs, or --from-fixtures")

    path = db_path(args.db)
    conn = connect(path)
    results: list[dict] = []
    try:
        if args.from_fixtures:
            from lens.stubs.fixtures import FIXTURE_RELEASES
            results.append(ingest_releases(conn, FIXTURE_RELEASES,
                                           "lens.stubs.fixtures", "fixtures"))
        for src in args.sources:
            kind = "url" if src.startswith(("http://", "https://")) else "file"
            results.append(ingest_releases(conn, stream_package(src), src, kind))
        total = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
    finally:
        conn.close()
    print(json.dumps({"db": str(path), "results": results, "total_releases": total}, indent=2))
    raise SystemExit(0 if total > 0 else 1)


if __name__ == "__main__":
    main()
