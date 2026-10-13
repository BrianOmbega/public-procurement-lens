"""Ingest pipeline tests: fixture round-trip, malformed records, FY derivation,
package-file streaming (both package-object and bare-array forms)."""
from __future__ import annotations

import json
import sqlite3

from lens.analysis import fy_from_date
from lens.ingest import connect, ingest_fixtures, ingest_releases, stream_package
from lens.stubs.fixtures import FIXTURE_RELEASES


def test_fixtures_roundtrip(tmp_path):
    db = tmp_path / "corpus.sqlite"
    result = ingest_fixtures(db)
    assert result["ingested"] == 10 and result["skipped"] == 0
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT ocid, doc FROM releases").fetchall()
    assert len(rows) == 10
    by_ocid = {ocid: json.loads(doc) for ocid, doc in rows}
    for rel in FIXTURE_RELEASES:
        assert by_ocid[rel["ocid"]] == rel, f"doc round-trip changed {rel['ocid']}"
    srcs = json.loads(conn.execute("SELECT value FROM meta WHERE key='sources'").fetchone()[0])
    assert srcs[-1]["kind"] == "fixtures" and srcs[-1]["ingested"] == 10
    conn.close()


def test_supplier_names_normalised_for_alias_grouping(tmp_path):
    db = tmp_path / "corpus.sqlite"
    ingest_fixtures(db)
    conn = sqlite3.connect(db)
    norms = {r[0] for r in conn.execute(
        "SELECT DISTINCT norm_name FROM suppliers WHERE name LIKE '%ech %' OR name LIKE '%ECH %'")}
    # normalize_supplier strips punctuation AND joins tokens without separators,
    # so all three fixture spellings (MEDTECH…/Medtech…/MED-TECH…LIMITED)
    # collapse to one norm — the "3 spellings collapse" fixture promise.
    assert norms == {"MEDTECHSOLUTIONS"}
    conn.close()


def test_malformed_records_skipped_not_fatal(tmp_path):
    db = tmp_path / "corpus.sqlite"
    conn = connect(db)
    good = FIXTURE_RELEASES[0]
    stream = [
        {"id": "no-ocid"},                          # no ocid -> skip
        "not-an-object",                            # wrong type -> skip
        {"ocid": "ocds-x", "id": "r",               # ingested WITH DQ notes, not crashed
         "awards": [{"value": {"amount": "NaN-ish"}}],
         "tender": {"title": "unparseable amount"}},
        good,
    ]
    result = ingest_releases(conn, stream, "test", "fixtures")
    assert result["ingested"] == 2 and result["skipped"] == 2
    assert len(result["errors"]) == 2
    notes = conn.execute("SELECT dq_notes FROM releases WHERE ocid='ocds-x'").fetchone()[0]
    assert "unparseable" in notes and "buyer name missing" in notes
    conn.close()


def test_reingest_upserts_instead_of_duplicating(tmp_path):
    db = tmp_path / "corpus.sqlite"
    ingest_fixtures(db)
    again = ingest_fixtures(db)
    assert again["ingested"] == 10
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0] == 10
    conn.close()


def test_fy_derivation_kenya_july_june():
    assert fy_from_date("2025-08-14") == "2025/2026"
    assert fy_from_date("2026-06-30") == "2025/2026"
    assert fy_from_date("2026-07-01") == "2026/2027"
    assert fy_from_date(None) is None
    assert fy_from_date("garbage") is None


def test_stream_package_object_and_bare_array(tmp_path):
    pkg = tmp_path / "pkg.json"
    pkg.write_text(json.dumps({"uri": "x", "releases": FIXTURE_RELEASES[:2]}))
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(FIXTURE_RELEASES[2:4]))
    got_pkg = [r["ocid"] for r in stream_package(str(pkg))]
    got_bare = [r["ocid"] for r in stream_package(str(bare))]
    assert got_pkg == [r["ocid"] for r in FIXTURE_RELEASES[:2]]
    assert got_bare == [r["ocid"] for r in FIXTURE_RELEASES[2:4]]
