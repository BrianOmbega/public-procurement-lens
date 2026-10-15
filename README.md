# Public Procurement Lens

Agentic AI that reviews Kenyan public tender awards and prepares a **sourced committee file** for human decision-makers. It never awards the tender: that boundary is enforced in code, not in prompts.

Built for the Agentic AI for Africa Innovation Challenge · Governance track ("The Bid Box Challenge") · team entry led by [@BrianOmbega](https://github.com/BrianOmbega).

## Problem statement

Kenya's Public Procurement Information Portal publishes tender **awards** as OCDS, but nothing checks them before money moves. Evaluation committees work from paper files with no independent price benchmark, no supplier history in front of them, and no machine-readable record of who approved what. Outlier awards and concentrated suppliers therefore pass unnoticed, and when they surface there is no auditable trail of the review.

## Target users

| User | What they get |
|---|---|
| Tender evaluation committees | A sourced brief: every claim tied to the OCDS record backing it |
| Procurement oversight / audit bodies | An append-only trail of every agent action: timestamps, tools, inputs, outputs, model, named approver |
| Civil-society and investigative monitors | Red flags with a stated `recommended_action`, raised only by a named human |

The agent prepares the file; **humans decide**. It has no award capability at all.

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

## Architecture

One reviewing agent on a **LangGraph `StateGraph`**: 8 nodes, 4 conditional routers, one of which routes *backwards* for self-correction.

```
plan → retrieve → analyze → synthesize → self_check ─┐
                     ↑          (repair ≤ 2)         │
                     └───────────────────────────────┘
        → human_gate (interrupt) → finalize | fail
```

Component-by-component map: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Agent architecture

| Component | Implementation |
|---|---|
| Agents | One reviewing agent (`LensGraph`, `src/lens/graph.py`); deliberately not multi-agent |
| Orchestration | LangGraph `StateGraph`, explicit nodes + conditional edges, `InMemorySaver` checkpointer |
| LLMs | OpenAI-compatible client over `httpx` at `temperature=0.1`: `ScriptedModel` (deterministic control), Ollama open-weights (`qwen3:1.7b`), or any frontier model via `OPENAI_BASE_URL` |
| Memory | `LensState` TypedDict (plan → evidence → analysis → findings → validation → gate → artifacts); checkpointer preserves state across the gate pause; append-only JSONL audit trail |
| Tools | 5 own MCP tools + borrowed official `mcp-server-fetch`, both over MCP stdio |
| Workflows | The graph above, `./run.sh` one-command reproduction, CI, `lens-ingest` corpus build |
| Databases | SQLite corpus built by `lens-ingest` (ijson-streamed OCDS), opened read-only |
| APIs | MCP JSON-RPC over stdio · OpenAI-compatible `/chat/completions` · `tenders.go.ke` portal URLs for citations |

Versions and full stack: [`docs/STACK.md`](docs/STACK.md). Why this counts as agentic: [`docs/AGENTIC.md`](docs/AGENTIC.md). Form-field mapping: [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md).

## MCP implementation

Transport is **stdio only**. The client is a single `McpBridge` async context manager owning one `ClientSession`: `stdio_client` → `initialize()` → `call_tool` → `_unwrap` → teardown. The graph never touches SQLite directly; it only ever calls tools.

| Server | Origin | Role |
|---|---|---|
| `lens-mcp` | own (`src/lens/mcp_server.py`) | real server, read-only SQLite corpus |
| `lens-stub` | own (`src/lens/stubs/stub_mcp.py`) | fixture-backed default; makes stub↔real a config swap via `LENS_MCP_CMD` |
| `mcp-server-fetch` | **borrowed official** | opt-in `--with-fetch`; cites live regulation/portal text |

**Tools (5):** `search_awards`, `get_supplier_history`, `analyze_price` (read) · `draft_committee_brief`, `raise_flag` (action, gated).
**Resources: none. Prompts: none.** Tools-only by design: retrieval must be logged and gated, and MCP resources would bypass both.

Errors are structured data (`ToolError{code,message,detail}`) rather than protocol failures, so refusals are routable and auditable. Every call is logged **on both sides of the wire**. Full detail: [`docs/MCP.md`](docs/MCP.md).

## Human-in-the-loop workflow

1. The graph reaches `human_gate` and calls LangGraph `interrupt(...)`: execution **suspends**, nothing is written.
2. A named human resumes with `{"approved": true, "approver": "<full name>"}` (`--approve` on the CLI).
3. `approver_violation()` validates that name: blanks, automation tokens (`auto`, `agent`, `system`, `ci`, `test`, …), model-shaped strings, and **the acting model's own name** are all refused.
4. Only then does `finalize` draft the brief and raise flags, passing the approver through; both action tools independently refuse without one (`approval_required` / `approver_invalid`).
5. Rejection routes to `fail`. `finalize` is unreachable without approval.

```bash
uv run lens-audit verify   # machine-checks the trail: schema, timestamps, gate coverage, orphan artifacts
```

## Technology stack

| Layer | Choice |
|---|---|
| Language / runtime | Python 3.11, `uv` for env + lockfile |
| Orchestration framework | LangGraph (MIT), `StateGraph` + `interrupt` + `InMemorySaver` |
| Agent protocol | MCP (`mcp[cli]`), `FastMCP` server, stdio transport |
| Schemas / validation | pydantic v2 (single contract shared by client and both servers) |
| LLMs | `ScriptedModel` (deterministic) · Ollama `qwen3:1.7b` (open-weights) · any OpenAI-compatible frontier model |
| HTTP client | `httpx` (`temperature=0.1`) |
| Database | SQLite, opened read-only; corpus built by `lens-ingest` streaming OCDS with `ijson` |
| Borrowed MCP server | `mcp-server-fetch` (official, opt-in) |
| Tests / CI | `pytest` (33 tests) + GitHub Actions |
| TypeScript workspace | Node ≥ 20, TypeScript ^5.7.3, express ^4.21.2, `@modelcontextprotocol/sdk` ^1.12.0, zod ^3.25.0, vitest ^2.1.8, Azurite (Azure Blob Storage emulator) |

Exact version floors and the external-API inventory: [`docs/STACK.md`](docs/STACK.md).

## MCP tools and servers

| Tool | Server | Kind | Gate |
|---|---|---|---|
| `search_awards` | `lens-mcp` / `lens-stub` | read | none (read-only) |
| `get_supplier_history` | `lens-mcp` / `lens-stub` | read | none (read-only) |
| `analyze_price` | `lens-mcp` / `lens-stub` | read | none (read-only) |
| `draft_committee_brief` | `lens-mcp` / `lens-stub` | **action** (writes) | named human required |
| `raise_flag` | `lens-mcp` / `lens-stub` | **action** (writes) | named human required |
| `fetch` | `mcp-server-fetch` (borrowed) | read | opt-in via `--with-fetch` |

Three servers, five own tools (3 read + 2 action), one borrowed server. **Resources: none. Prompts: none**: tools-only by design, because retrieval has to be logged and gated and MCP resources would bypass both.

## Development

```bash
uv sync && uv run pytest -q     # offline suite: validator, gate, audit, ingest, stub↔real parity

uv run lens-stub --selftest     # MCP contract selftest over fixtures (stub server)
uv run lens-ingest --from-fixtures   # seed data/lens.sqlite (offline corpus, no network)
uv run lens-mcp --selftest      # real server selftest against data/lens.sqlite (5 tools, 17 checks)

# prove the zero-graph-change stub→real swap end to end (real server over stdio):
LENS_MCP_CMD=.venv/bin/lens-mcp uv run lens-demo --approve "Your Name"
```

Ingest a live/local OCDS package instead of fixtures: `uv run lens-ingest data/package.json` or `uv run lens-ingest "https://tenders.go.ke/api/ocds/…"` (ijson-streamed; a full FY download never has to fit in RAM).

Layout: `src/lens/` (graph, models, mcp_bridge, audit, audit_cli, schemas, stubs, ingest, analysis, actions, mcp_server) · `docs/` (CONTRACT, CONTRIBUTING, DESIGN, description, PR-STATUS, AGENTIC, CAPABILITIES, STACK, MCP) · `ARCHITECTURE.md`, `EVALS.md` (repo root) · `evidence/` (one committed real gated run) · `tests/` · `scripts/`.

## Status (2026-10-15)

Orchestration + open-weights slice green (qwen3:1.7b verified exit 0; qwen3:4b attempts failed on infra limits of this 8 GB machine - see EVALS.md row 9). The real `lens-mcp` server and its `lens-ingest` pipeline (ijson-streamed OCDS → SQLite, DQ flags + provenance) are built in-repo: `lens-mcp --selftest` passes **17/17** against `data/lens.sqlite`, and the full graph runs against the real server with zero graph-code changes via `LENS_MCP_CMD`. Contract-first design made stub ↔ real a config change, as intended.

Added on submission day: both action tools now refuse at the tool boundary without a **validated named human** approver (`approval_required` / `approver_invalid`, gate checked before anything else runs), `lens-audit verify` machine-checks the trail, and `evidence/offline-run/` commits one real gated run so a fresh clone can see the audit trail rather than regenerate it. Suite: 33 tests, stub selftest 13/13, real selftest 17/17. Submission deadline: 2026-10-15.

## Limitations

- **Citation semantic grounding is unfixed** (`EVALS.md` row 11): the validator proves a cited `ocid` exists in retrieved evidence, not that it *supports* the claim. A small model can attach a real-but-wrong citation and pass.
- `qwen3:4b` runs failed on this 8 GB machine's infrastructure limits (`EVALS.md` row 9); `qwen3:1.7b` is the verified open-weights pass.
- `InMemorySaver` cannot resume across processes, so the gate works within a single run; cross-process resume needs `SqliteSaver`.
- Kenya's PPIP publishes awards but **no bid documents**, so evaluating bids themselves is out of scope (see the honesty note above).
- The TypeScript workspace returns synthetic results from its model and source adapters and has no auth middleware: not production-ready and not evidence of a genuine model run.

## Future improvements

- Semantic citation checking (entailment over the cited record) to close `EVALS.md` row 11.
- `SqliteSaver` checkpointer so the human gate survives across processes.
- Wire the TypeScript adapters to real Ollama and real fetch, and add auth middleware.
- Scheduled monitoring over newly published portal releases: today the trail audits a run, it does not watch continuously.
- A wider open-weights model sweep once hardware allows.

## TypeScript service workspace

The repository also contains an API-only TypeScript workspace under `apps/` and `packages/`. It is additive to the Python implementation above; the two implementations currently have separate runtime paths and evaluation status.

```bash
npm install
npm run build
npm test
npm run dev:procurement
```

The procurement MCP service listens on `http://localhost:3000` and exposes `GET /` (diagnostic index), `GET /healthz`, `GET /readyz`, `POST /mcp`, and `POST /api/audit-events`. The local runner can be started with `npm run dev:runner` while the service is running.

Open `http://localhost:3000/` in a browser for a self-contained index page that lists every route and carries a working **Try the MCP search tool** button: it fires a live `tools/call` for `search_historical_awards` and renders the JSON response in the page. Useful endpoints to check by hand:

```bash
curl -s localhost:3000/healthz
curl -s -X POST localhost:3000/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"search_historical_awards","arguments":{"query":"water"}}}'
```

Tool names use **underscores** (`search_historical_awards`, `compare_comparable_prices`, `draft_committee_report`), and `query` is required for search: `{}` or `{"limit":2}` returns `VALIDATION_ERROR`. Most queries match nothing in the fixture corpus; `water` and `supply` do.

⚠️ Run **exactly one** watcher. `npm run dev:procurement` and `npm run dev -w @procurement/procurement-mcp` both start `tsx watch` on the same file and port; two supervisors racing on `:3000` produce intermittent `Cannot GET /` and stale responses. Kill strays with `pkill -f "tsx watch src/index.ts"` before restarting, and use `nohup ... &` if the server must outlive the shell.

The TypeScript runner's source retrieval and model adapters currently return synthetic results, and the service does not yet implement authentication. Do not treat this workspace as production-ready or as evidence of a genuine model run. The workspace is API-only apart from the diagnostic index page at `/`, which exists to make the endpoints inspectable in a browser; it is not a product frontend.

License: MIT.
