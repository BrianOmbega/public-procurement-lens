# Capabilities demonstrated

> **Owns:** the answer to the submission form field *"Which capabilities does your agent
> demonstrate?"* — the 11-option tick list, and the verified evidence behind each tick.

Every citation below was re-checked against `src/lens/` on 2026-10-15. Claims are stated as
`file:symbol` rather than bare line numbers wherever possible, because line numbers rot and a
judge should be able to open the file and find the thing.

---

## Tick list (copy-paste, in the form's own order)

- [x] **Planning**
- [x] **Reasoning**
- [x] **Decision support**
- [x] **Tool/API calling**
- [x] **Data retrieval**
- [x] **Multi-step execution**
- [x] **Workflow automation**
- [x] **Monitoring** — *tick it, but scope it in the box; see the callout below*
- [x] **Recommendation generation**
- [x] **Information synthesis**
- [x] **Other** — self-correction, human-gate, citation validator, model portability, self-auditing

---

## Evidence per capability

| Form option | Claim | Verified evidence |
|---|---|---|
| **Planning** | Yes | `LensGraph.plan` calls `model.plan(subject_ocid)`, which returns `{task, subject_ocid, checks[]}`. `LensGraph.retrieve` reads that plan back and branches on it — `if "supplier_history" in checks` decides whether `get_supplier_history` is called at all. Remove the key from the model's JSON and the tool call never fires: the plan changes execution, it is not decoration. |
| **Reasoning** | Yes | `LensGraph.synthesize` calls `model.synthesize(subject, evidence, analysis, feedback)`. `OpenAICompatModel` posts at `temperature: 0.1` (`models.py`). Reasoning runs over computed statistics from `analysis.py`, not over guesses. |
| **Decision support** | Yes — the core purpose | The system produces a committee brief and flags *for* humans to act on. `ACTION_TOOLS` contains exactly two tools — `draft_committee_brief` and `raise_flag`. There is no award, rank, or amend capability anywhere in the contract: the agent cannot decide, because the capability was never built. |
| **Tool/API calling** | Yes | Five own tools (`contract.TOOL_NAMES`: `search_awards`, `get_supplier_history`, `analyze_price`, `draft_committee_brief`, `raise_flag`) served by `lens-mcp` over real MCP stdio through `McpBridge`, plus a borrowed upstream `mcp-server-fetch` on the same protocol. The LLM is reached over `httpx` against an OpenAI-compatible endpoint. |
| **Data retrieval** | Yes | `search_awards`, `get_supplier_history` and `analyze_price` query a SQLite corpus seeded by `lens-ingest`, which streams OCDS release packages with `ijson` rather than loading them whole. |
| **Multi-step execution** | Yes | An 8-node LangGraph `StateGraph` — `plan`, `retrieve`, `analyze`, `synthesize`, `self_check`, `human_gate`, `finalize`, `fail` — with four conditional routers (`route_after_retrieve`, `route_after_analyze`, `route_after_check`, `route_after_gate`). One router sends the graph *backwards* to `synthesize` when citation validation fails. Compiled with an `InMemorySaver` checkpointer so state survives the human gate. |
| **Workflow automation** | Yes | `bash run.sh` drives seeding → demo → gated approval in one command; `.github/workflows/ci.yml` runs the suite and the gated offline demo; `lens-ingest` seeds the corpus; `scripts/setup_ollama.sh` provisions the local open-weights model. |
| **Monitoring** | Qualified yes | See the callout below — real in the audit and data-quality sense, absent in the live-operations sense. |
| **Recommendation generation** | Yes | `raise_flag(recommended_action=...)` — the field is declared at `contract.py:248`, and `graph.py` supplies e.g. `"Committee to request written price justification before any award decision"`. **Precision note:** `Finding` itself carries only `claim`, `evidence`, `severity`, `sources`. Recommendations live on the *flag* and in the *brief*, not on findings — do not claim otherwise, the schema contradicts it. |
| **Information synthesis** | Yes | `synthesize` merges corpus search results, supplier history and price analysis into cited findings; `draft_committee_brief` merges those findings into a single document with a provenance footer naming the approving human and the timestamp. |
| **Other** | Yes — five differentiators | **(1) Self-correction:** `self_check` rejects any finding citing an `ocid` absent from the retrieved evidence, and `route_after_check` routes back to `synthesize` with the rejection reasons injected into the next prompt, capped at `MAX_REPAIRS = 2` (`graph.py:31`) — then hard-fails rather than shipping uncited work. **(2) Human-in-the-loop gating:** `interrupt()` suspends the graph; it resumes only via `resume_with` carrying a *validated* named approver. **(3) Hallucination resistance:** the citation validator described in (1). **(4) Model portability:** open-weights (Ollama) ↔ frontier swap by environment variable, with every audit event model-attributed. **(5) Self-auditing:** the agent logs its own tool calls on both sides of the wire — client-side `mcp_call` and server-side `tool_call`. |

---

## Monitoring: tick it, but scope it

This is the one option that is half-true, and a half-true claim is cheaper to lose than to
overstate. What exists:

- **Every action of the agent is logged.** Each audit event carries `ts`, `kind`, `tool`,
  `model`, `session`, `request`, `response`, and `approver` (`audit.py:audit_event`) — inputs,
  outputs, timestamps and the named approving human, on both sides of the MCP wire.
- **The trail is machine-checked, not just written.** `lens-audit verify` asserts field
  completeness, timestamp monotonicity, model attribution, that every successful call to a
  `GATED_TOOLS` member carries a valid approver, and that artifacts and events agree in both
  directions — no orphan file on disk, no event pointing at a missing file.
- **Record-level data quality is monitored.** `analysis.py` never crashes on a malformed record;
  parse failures become `data_quality_notes`, and `graph.py` has a `"data_quality"` router path.

What does **not** exist: no scheduler, no alerting, no dashboard, no live feed. It is not
continuous production monitoring.

**Sentence to paste in the form box:**

> Monitoring in two senses only: every action the agent takes is logged with inputs, outputs,
> timestamps, model identity and the named human approver, and that trail is machine-verified by
> `lens-audit verify`; separately, malformed source records are surfaced as data-quality notes
> rather than silently dropped. There is no scheduler, alerting or dashboard — this is audit and
> data-quality monitoring, not live operational monitoring.

---

## What it is not

Stated plainly, because overclaiming loses a judge faster than a modest system does.

- **Not an open-ended ReAct loop.** The graph is fixed and inspectable. The model's autonomy is in
  *what it decides to check and what it writes*, not in choosing which node runs next. That is a
  deliberate trade: auditability over free-form agency.
- **Not self-authorizing.** It cannot approve its own output — `validate_approver` rejects
  automation tokens, blanks, and the acting model's own name.
- **Not capable of awarding a tender.** No such tool exists in the contract.
- **Not infallible.** `EVALS.md` row 11 ("Citation semantic grounding") is recorded as
  **FAIL — unfixed**: on an open-weights run, `qwen3:1.7b` cited a *real* `ocid` that was present
  in the evidence corpus but did not support the claim. The validator passed it, because citation
  *presence* and corpus *membership* are cheap deterministic checks while *entailment* is not.
  It catches invented identifiers, not subtly misapplied real ones.

---

## Reproduce it

Only tracked paths are referenced here, so this works from a cold clone. The audit trail and the
generated brief are runtime artifacts, deliberately gitignored — you regenerate them rather than
trust a committed copy.

```bash
bash run.sh                 # seed corpus, run the gated demo, approve as the named human
uv run lens-audit verify    # machine-check the trail that run just produced
```

`lens-audit verify` exits non-zero on any violation. To see it fail rather than trust that it
can, tamper with a copy of the trail — strip an `approver`, delete an artifact, or reorder two
timestamps — and re-run.

For the deeper question of *why* this counts as an agentic system rather than a scripted
pipeline, see `docs/AGENTIC.md`. For the ~300-word submission blurb, see `docs/description.md`.
