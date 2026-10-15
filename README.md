# Public Procurement Lens

Agentic AI that reviews Kenyan public tender awards and prepares a **sourced committee file** for human decision-makers. It never awards the tender: that boundary is enforced in code, not in prompts.

Built for the Agentic AI for Africa Innovation Challenge · Governance track ("The Bid Box Challenge") · team entry led by [@BrianOmbega](https://github.com/BrianOmbega).

## What it does

Given an award (`ocid`), the agent plans the review, retrieves the award record, supplier history, and price comparables through its own MCP server, runs robust price analysis (median/MAD outliers), and synthesizes findings in which **every claim must cite the OCDS record backing it**. A citation validator rejects unsourced or hallucinated references through a capped repair loop; whatever survives stops at a **human approval gate** (LangGraph `interrupt`, named approver) before the agent drafts the committee brief and raises red flags. Every action lands in an append-only audit trail (`logs/audit.jsonl`: timestamps, tools, inputs/outputs, model, approver).

## Which half of the data this builds (honesty note)

Kenya's PPIP publishes tenders and awards as OCDS (`https://tenders.go.ke/api/ocds` — verified live), but **no bid documents**. This repo builds the **awards/pricing half**: price outliers vs historic awards, supplier award concentration, data-integrity flags. Evaluating bids themselves would need documents nobody publishes.

## Run it (one command)

```bash
git clone https://github.com/BrianOmbega/public-procurement-lens && cd public-procurement-lens
./run.sh    # deps + validator negative test + full offline demo (scripted model, stub corpus)
```

## Open-weights run (procurement data never leaves the machine)

```bash
./scripts/setup_ollama.sh    # installs Ollama (prebuilt zip; brew opt-in) + pulls qwen3:1.7b
MODEL=ollama/qwen3:1.7b uv run lens-demo --task price_reasonableness --approve "Your Name"
```

Optional frontier comparison: set `OPENAI_BASE_URL` + `OPENAI_API_KEY` and `MODEL=<name>`.

## Bid Box non-negotiables → where each lives

| Requirement | Implementation |
|---|---|
| Open-source orchestration | LangGraph (MIT), explicit nodes: plan → retrieve → analyze → synthesize → self-check ⇄ repair ≤2 → human gate → finalize (`src/lens/graph.py`) |
| Own MCP server, 3+ tools, ≥1 action | `lens-mcp` contract v0.1: 5 tools — 3 read + 2 action (`draft_committee_brief`, `raise_flag`). Real server built (`src/lens/mcp_server.py`, ijson-streamed SQLite corpus via `lens-ingest`); swaps in with zero graph changes via `LENS_MCP_CMD=.venv/bin/lens-mcp` (`docs/CONTRACT.md`) |
| One MCP server you didn't write | Official `mcp-server-fetch` (`--with-fetch`). Why it beats writing it: maintained by the MCP project — redirects, robots, encoding handled — so the agent cites regulation text and portal pages live without us shipping a fragile scraper |
| One full task on an open-weights model | Ollama + Qwen3, fully local. qwen3:1.7b pass verified end-to-end (exit 0, 27/27 audit events model-attributed, localhost only) — `EVALS.md` rows 8-9 |
| Every action logged, every irreversible action gated | `logs/audit.jsonl` + named-approver `interrupt()` gate; flags stay `pending_approval` without one |

## Development

```bash
uv sync && uv run pytest -q     # offline suite: validator, gate, audit, ingest, stub↔real parity

uv run lens-stub --selftest     # MCP contract selftest over fixtures (stub server)
uv run lens-ingest --from-fixtures   # seed data/lens.sqlite (offline corpus, no network)
uv run lens-mcp --selftest      # real server selftest against data/lens.sqlite (5 tools, 15 checks)

# prove the zero-graph-change stub→real swap end to end (real server over stdio):
LENS_MCP_CMD=.venv/bin/lens-mcp uv run lens-demo --approve "Your Name"
```

Ingest a live/local OCDS package instead of fixtures: `uv run lens-ingest data/package.json` or `uv run lens-ingest "https://tenders.go.ke/api/ocds/…"` (ijson-streamed; a full FY download never has to fit in RAM).

Layout: `src/lens/` (graph, models, mcp_bridge, audit, schemas, stubs, ingest, analysis, actions, mcp_server) · `docs/` (CONTRACT, CONTRIBUTING, DESIGN, description, PR-STATUS) · `ARCHITECTURE.md`, `EVALS.md` (repo root) · `tests/` · `scripts/`.

## Status (2026-10-14)

Orchestration + open-weights slice green (qwen3:1.7b verified exit 0; qwen3:4b attempts failed on infra limits of this 8 GB machine - see EVALS.md row 9). The real `lens-mcp` server and its `lens-ingest` pipeline (ijson-streamed OCDS → SQLite, DQ flags + provenance) are now built in-repo: `lens-mcp --selftest` passes 15/15 against `data/lens.sqlite`, and the full graph runs against the real server with zero graph-code changes via `LENS_MCP_CMD`. Contract-first design made stub ↔ real a config change, as intended. Submission deadline: 2026-10-15.

## TypeScript service workspace

The repository also contains an API-only TypeScript workspace under `apps/` and `packages/`. It is additive to the Python implementation above; the two implementations currently have separate runtime paths and evaluation status.

```bash
npm install
npm run build
npm test
npm run dev:procurement
```

The procurement MCP service listens on `http://localhost:3000` and exposes `GET /healthz`, `GET /readyz`, `POST /mcp`, and `POST /api/audit-events`. The local runner can be started with `npm run dev:runner` while the service is running.

The TypeScript runner's source retrieval and model adapters currently return synthetic results, and the service does not yet implement authentication. Do not treat this workspace as production-ready or as evidence of a genuine model run. There is no frontend; the TypeScript plan is API-only.

License: MIT.
