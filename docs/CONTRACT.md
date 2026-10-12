# lens-mcp Tool Contract — v0.1.0

**Status: PROPOSED** (needs review by @BrianOmbega + the MCP-server builder).
Machine-readable source of truth: `src/lens/schemas/contract.py` (pydantic models). If this doc and the module disagree, the module wins; fix the doc by PR.

## Why this file exists

Orchestration (LangGraph) and the MCP server are being built by different people in parallel against an empty repo. This contract decouples them: orchestration codes against these schemas and develops/tests against the stub server (`lens-stub`); the real `lens-mcp` implements the same tools with the same request/response shapes. Swapping stub → real server is a config change (`LENS_MCP_CMD`), zero graph-code changes.

## Invariants (challenge rules — non-negotiable)

1. **No award tool.** Nothing in this contract can award, rank winners, or alter a tender outcome. The agent prepares the file; humans decide. The graph has no award capability by construction.
2. **Every finding cites sources.** `Finding.sources` and `RaiseFlagRequest.sources` require ≥1 `SourceRef` (`ocid` mandatory; `release_id`/`field_path`/`url`/`quote` optional). An uncited finding is a schema-validation error, not a style issue.
3. **Every call is audited.** All tool calls — read or action — append to `logs/audit.jsonl`: timestamp, tool, request, response, model, session, approver where applicable.
4. **Flags are gated.** `raise_flag` always returns `requires_approval: true`; status stays `pending_approval` until a named human `approver` is supplied, and the approval event is audited.

## Tools (5) — 3 read, 2 action

### Read

| Tool | Purpose | Request → Response |
|---|---|---|
| `search_awards` | find awards/tenders by free text, fiscal year, buyer | `SearchAwardsRequest` → `SearchAwardsResponse` |
| `get_supplier_history` | supplier award history with alias/identifier normalisation | `SupplierHistoryRequest` → `SupplierHistoryResponse` |
| `analyze_price` | median/MAD price analysis vs comparable awards; outlier list; optional verdict on a subject award | `PriceAnalysisRequest` → `PriceAnalysisResponse` |

### Action (the agent's hands — challenge requires ≥1)

| Tool | Effect | Request → Response |
|---|---|---|
| `draft_committee_brief` | writes a cited markdown brief to `output/brief-<ts>.md` | `DraftBriefRequest` → `DraftBriefResponse` |
| `raise_flag` | appends a structured flag to `output/flags.jsonl`; stays `pending_approval` until a named approver | `RaiseFlagRequest` → `RaiseFlagResponse` |

## Errors

Tools return structured errors instead of throwing across the wire: `ToolError {code, message, detail?}`. Reserved codes: `citation_required`, `no_comparables`, `supplier_not_found`, `bad_fiscal_year`, `validation`, `internal`.

## Data-quality behaviour (judging criterion 1)

Kenya PPIP data is messy by design. Servers MUST:

- Never crash on malformed records — e.g. `tenderPeriod.startDate > endDate` is real (seen tonight: `ocds-vn56pm-b60301c5-9058-4118-a31e-939970e0e4c5`, FY 2026/27, KHWS/OT/09/2026-2027).
- Surface problems, not hide them: every response carries `data_quality_notes: [str]`, and offending fields get a `SourceRef` with `field_path`.
- Report missing fields as missing (`buyer_name: null` + note) — never fill from guesswork.

## Stub parity

`src/lens/stubs/stub_mcp.py` implements this contract over fixtures hand-cut from real Kenya records (including the malformed-date and missing-buyer cases). Parity rule: any request valid against the real server must be valid against the stub with the same response shape. Contract changes = a PR touching `contract.py`, pinging both owners.

## Versioning

`CONTRACT_VERSION` in `contract.py` (semver, `0.x` until merged reality). Breaking change → bump in the same PR that changes schemas; stub and real server update together.

## Open questions for Brian / teammate

1. Real-server storage: SQLite built from bulk FY downloads (server ignores `Range`; sizes unknown until download → stream-parse with `ijson`)? Agreed?
2. Fiscal-year key format: portal uses `YYYY/YYYY` (e.g. `2026/2027`); fixtures currently use the same string. Standardise on that everywhere?
3. Who owns the ingest pipeline (the data half the README must declare)?
