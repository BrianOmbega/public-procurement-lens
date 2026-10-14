# Architecture — Public Procurement Lens (one page)

```
                    ┌───────────────────────────────────────────────────────┐
                    │        LangGraph StateGraph (src/lens/graph.py)       │
                    │                                                       │
 plan ──► retrieve ──► analyze ──► synthesize ──► self_check ──► human_gate ──► finalize
 (LLM)    (MCP read)   (MCP read)     (LLM)        citation      interrupt()   (MCP ACTIONS:
                                                   validator     named          brief + flags)
                                                       │         approver
                                                       ▼ reject
                                                 repair loop ≤2 ──► hard fail (nothing written)
```

## Components

- **`graph.py`** — orchestration (LangGraph 1.x, MIT). Explicit nodes, not a black-box loop: every decision point is traceable and judgeable. In-memory checkpointer, one thread per run; gate resume is same-process.
- **`models.py`** — swappable brain: `MODEL=scripted` (deterministic offline) | `ollama/<name>` (local open-weights, OpenAI-compat on :11434) | any OpenAI-compatible endpoint via `OPENAI_BASE_URL`/`OPENAI_API_KEY`. Model name is stamped on **every** audit event — that's the open-weights evidence trail. Hardened for slow local models: 2700s call timeout, 900-token cap, Qwen3 `/no_think`, JSON mode + few-shot shape example.
- **`mcp_bridge.py`** — talks to MCP servers over stdio (the real wire, never in-process), so stub ↔ real server is config (`LENS_MCP_CMD`). Own server: `lens-mcp`. Borrowed: official `mcp-server-fetch` (opt-in `--with-fetch`) — **why borrowed beats written**: maintained by the MCP project itself (redirects, robots.txt, encoding handled), lets the agent cite regulation text and portal pages live without us shipping and maintaining a fragile scraper.
- **`schemas/contract.py`** — single source of truth (pydantic) for the 5-tool contract v0.1; stub and real server both import it (`docs/CONTRACT.md`). Schema-level invariants: no award tool exists; `Finding.sources` requires ≥1 `SourceRef`; `raise_flag` returns `requires_approval: true` until a named approver.
- **`audit.py`** — append-only JSONL: every node, MCP call, validation verdict, and gate decision with ts, tool, inputs, outputs, model, approver.

## Invariants (enforced in code, not in prompts)

1. **Never awards** — no tool or node can alter a procurement outcome; the capability doesn't exist.
2. **No citation → no finding** — validator rejects missing sources and ocids absent from retrieved evidence; repair loop capped at 2, then the run hard-fails closed.
3. **No human → no artifacts** — `finalize` is unreachable unless `interrupt()` returns `{approved: true, approver: "<name>"}`; the decision is audited.
4. **Everything → audit** — orchestration-side and server-side events, both model-attributed.

## Known limits (honest)

- **Citation presence ≠ entailment**: the validator checks an ocid exists in the evidence corpus, not that it *supports* the claim. Observed live with qwen3:1.7b (EVALS.md #11). Next: numeric-entailment rule, deterministic finding assembly, grounding-critic pass.
- **In-memory checkpointer**: cross-process gate resume needs SqliteSaver (path is clear, not built).
- **Stub corpus**: real PPIP ingestion (ijson-streamed OCDS → SQLite) is a teammate workstream behind the same contract; the messiness (invalid dates, missing buyers, broken supplier IDs) is already fixture-encoded.
- **Item matching** is substring-based; a real corpus needs embeddings or a normalized taxonomy.

## TypeScript API workspace

The separate TypeScript implementation lives under `apps/procurement-mcp`, `apps/agent-runner`, and `packages/contracts`. The MCP service provides health checks, tool calls, and JSONL audit/report persistence; the local runner posts audit events to that service. It is not yet wired to the Python graph or its MCP implementation.

This workspace remains scaffold-level in two important areas: its source fetch and model adapters return synthetic data, and the HTTP service has no authentication middleware. The API smoke test proves route behavior and runner-to-backend audit transport only; it does not establish production readiness or genuine source/model integration.
