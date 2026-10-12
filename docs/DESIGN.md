# Public Procurement Lens — Design & Scope

**Target:** The Bid Box Challenge — Governance track (Agentic AI for Africa).
**Submission deadline:** 15 October 2026 (repo cloned at deadline timestamp → must be public + final by then).
**Theme (stated assumption):** Value for money — award/price/supplier side of Kenya PPIP data.

---

## The four build non-negotiables we own

| # | Requirement | How this project satisfies it |
|---|---|---|
| 1 | Open-source orchestration (LangGraph/CrewAI/Pydantic AI/etc.) | **LangGraph** StateGraph: plan → tool calls → citation self-check → human-gate interrupt → finalize. No closed no-code builders. |
| 2 | One full task on an open-weights model | Swappable model layer (`MODEL=` env). Primary: **Qwen3 via Ollama locally** (bounded task — see Hardware reality). Backup/parallel: Qwen3/Llama via Groq or OpenRouter (same open weights, faster). Frontier run alongside for comparison. |
| 3 | Own MCP server, ≥3 tools, ≥1 that *does something* | **`lens-mcp`** (official Python `mcp` SDK / FastMCP), 5 tools — reads: `search_awards`, `get_supplier_history`, `analyze_price`; **actions**: `draft_committee_brief`, `raise_flag` (gated + logged). |
| 4 | One MCP server we did not write + one-line why | Official **`mcp-server-fetch`**. Why it beats writing our own: maintained by the MCP project itself — handles redirects/robots/encoding/content-type negotiation — so we ship no fragile scraper and can cite PPRA Act text and PPIP web pages live. |

Remaining non-negotiables (whole-team context): per-action tool-call log (JSONL: inputs, outputs, timestamps, approver) + human gate on every irreversible action; new work built in window (this repo was empty on 2026-10-11).

**Hard boundary:** the agent prepares the file — it never awards. Every finding cites a source (ocid + release URL).

---

## What the agent does (named office, real workflow)

An auditor / procurement oversight officer points the Lens at an award (or a buyer + category). The agent produces a **sourced pre-award review file**:

1. Pull the target award/tender from Kenya PPIP OCDS (local SQLite mirror; live fetch for freshness).
2. Pull comparable historical awards (same buyer / category / item).
3. Price analysis: distribution vs comparables, outlier detection, unit-price sanity.
4. Supplier analysis: award frequency, single-source patterns, identifier inconsistencies (the data is deliberately dirty — messy-identifier handling is scoring criterion #1 material).
5. Every flag carries evidence + exact citation (ocid, release id, URL).
6. **Action:** drafts a committee brief (markdown) and files flags (JSON) — behind a **human-approval gate** (LangGraph interrupt, named approver + timestamp in the audit log).

## Data (verified live 2026-10-11)

- Portal: `https://tenders.go.ke` (Kenya PPIP), API base `https://tenders.go.ke/api/ocds`
  - `/index?...&fy=YYYY-YYYY` → fiscal-year package list (Kenya FY = July–June; 2026/2027 = `ocds_id=12`)
  - `/tenders?download=true&ocds_id=N` → full release-package JSON stream
- Scale: ~260k tenders, ~109k awards; updated daily.
- Confirmed dirt in first records: `tenderPeriod.startDate` (2026-09-30) **after** `endDate` (2026-06-03) → data-quality flags are a first-class output, not an edge case.
- Strategy: download FY 2025-26 + 2026-27 packages once into `data/` (gitignored), parse into **SQLite** for fast offline analysis; one MCP tool does live re-fetch for freshness. "Data doesn't leave the country" pairs with the open-weights requirement.
- README states which half we build: awards/prices/suppliers (published); bid documents (never published) are out of scope.

## Hardware reality (build machine)

- Intel i7-5650U (2 cores), **8 GB RAM**, no GPU, 53 GB free disk, macOS, Python 3.11.2 + `uv`.
- Ollama not yet installed (install = system change → needs owner approval; planned Day 2).
- Local open-weights ceiling: `qwen3:4b` (~3 GB, ~2–4 tok/s on this CPU). The open-weights requirement is **one full task** — so we design a bounded task (award price-reasonableness review, few tool calls, structured output) that a 4B model completes reliably, and keep Groq/OpenRouter-hosted Qwen3-14B as the fast lane for the recorded demo.

## Repo layout (target)

```
public-procurement-lens/
├── README.md            # one-command run + which half we build
├── ARCHITECTURE.md      # one page (submission requirement)
├── EVALS.md             # ≥8 tasks, pass/fail, one unfixed failure
├── LICENSE              # MIT
├── pyproject.toml       # uv-managed: langgraph, mcp, httpx, pytest
├── src/lens/
│   ├── ingest.py        # OCDS packages → SQLite (+ quality flags)
│   ├── analysis.py      # outliers, comparables, supplier normalization
│   ├── mcp_server.py    # lens-mcp (5 tools, JSONL audit log)
│   ├── graph.py         # LangGraph pipeline + human gate
│   ├── models.py        # swappable: frontier | ollama | hosted-open-weights
│   ├── demo.py          # end-to-end sample run
│   └── evals.py         # eval harness
├── data/                # gitignored: OCDS dumps + lens.sqlite
└── output/              # gitignored: briefs, flags, audit logs
```

## Schedule (4 days, deadline Oct 15)

| Day | Deliverable |
|---|---|
| Oct 11 (tonight) | Scaffold, LICENSE, ingestion + SQLite schema, first ingest run |
| Oct 12 | Analysis core + tests; `lens-mcp` with audit log; Ollama installed (approval) |
| Oct 13 | LangGraph pipeline + human gate; mcp-server-fetch wired; open-weights full-task run |
| Oct 14 | Evals (≥8 + variance runs + one honest failure); README one-command run; ARCHITECTURE.md; 300-word description; demo video; push |
| Oct 15 | Buffer + submit repo link via the Google Form (no commits after deadline timestamp) |

## Open items (owner decisions)

1. Application via the challenge Google Form — filed already? Repo link can be appended later, but the form is mandatory.
2. Theme confirmation: Value for money (recommended) vs Open contracting.
3. Ollama install approval (system-level change).
