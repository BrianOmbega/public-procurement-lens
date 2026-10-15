# What makes Public Procurement Lens an agentic AI system

> Submission answer. Every claim below names the file and symbol that implements it,
> so it can be checked rather than believed. Nothing here is aspirational.

**One sentence:** it is a model that plans its own review, selects which tools to call,
writes the findings, observes its own output failing a validator, and revises it in a
capped loop — then stops dead at a human gate before anything is written to disk.

Autonomy is real but *bounded on purpose*. That is the design, not a limitation we are
hiding: in a procurement-integrity system an agent that can do anything unobserved is a
liability, not a feature. The model decides **what to check** and **what to say**; the
graph decides **what may happen next**.

---

## The five properties, with evidence

### 1. The model plans, and its plan changes what gets executed

`LensGraph.plan` calls the LLM (`OpenAICompatModel.plan`) and stores the result in state.
`LensGraph.retrieve` then reads it back and branches on it:

```python
checks = (state.get("plan") or {}).get("checks", [])
if "supplier_history" in checks and supplier:
    history = await self.bridge.call("get_supplier_history", supplier=supplier)
```

The supplier-history tool call happens **only if the model asked for it**. That is
agentic tool selection, not a hardcoded script — remove `supplier_history` from the
model's JSON and the call never fires. (`src/lens/graph.py`)

### 2. It acts on the world through real tools, over a real protocol

Five contract tools (`TOOL_NAMES` in `src/lens/schemas/contract.py`) implemented by its
own MCP server (`lens-mcp`), plus the official `mcp-server-fetch` as a borrowed server —
both reached over MCP stdio through `McpBridge`. The agent does not read files or query
SQLite directly; it calls tools and receives structured, schema-validated responses.
Every call is audited on both sides of the wire.

### 3. Its numbers come from the environment, not from its imagination

`analyze_price` computes median / MAD robust z-scores over actual comparable awards in
the ingested OCDS corpus (`src/lens/analysis.py::build_price_analysis`). The model
receives those computed figures and reasons over them. "2,400,000 KES vs median 495,000"
is a measured statistic the agent looked up, not a plausible-sounding invention.

### 4. It observes its own failure and repairs — the defining property

`LensGraph.self_check` runs every finding through two gates: the pydantic `Finding`
schema, and a check that each cited `ocid` actually appears in the retrieved evidence:

```python
unknown = [s.ocid for s in parsed.sources if s.ocid not in known_ocids]
```

A finding citing a hallucinated identifier is **rejected**, and `route_after_check`
sends the graph *backwards* to `synthesize` with the rejection reasons injected into the
next prompt (`OpenAICompatModel.synthesize`, `feedback`):

> "Your previous findings were REJECTED by the citation validator: [...]. Repair them."

That is a closed perception → action → evaluation → correction loop, capped at
`MAX_REPAIRS = 2`, after which the run **hard-fails** rather than shipping uncited work.
The agent cannot talk its way past its own validator.

### 5. Bounded by a human, with durable state

`LensGraph.human_gate` calls LangGraph's `interrupt(...)`, suspending the graph until a
human resumes it with `{"approved": true, "approver": "<full name>"}`.
`route_after_gate` routes to `fail` on anything else. State survives the suspension via
the `InMemorySaver` checkpointer in `build_graph`, so resuming continues the same run
rather than restarting it. `finalize` — the only node that writes a brief or raises a
flag — is unreachable without that approval.

The brain is swappable (`models.get_model()`): a deterministic `ScriptedModel` for CI,
`ollama/*` open-weights for the real run, or any OpenAI-compatible endpoint. Every model
carries `.name`, so the audit trail attributes each artifact to the specific weights
that produced it.

---

## What it deliberately is NOT

Stated plainly, because overclaiming is the fastest way to lose a judge:

- **Not an open-ended ReAct loop.** Control flow is an explicit `StateGraph`, not a
  model-chosen action sequence. The model's autonomy is in *content and check
  selection*; node ordering is fixed and inspectable. We chose auditability over
  free-form agency, since a procurement trail has to be defensible after the fact.
- **Not self-authorizing.** It cannot approve its own output: the gate requires a named
  human approver recorded in the audit log.
- **Not capable of awarding a tender.** There is no award, rank, or amend tool anywhere
  in the contract. The capability was never built, so it cannot be misused. The agent
  prepares the file; a committee decides.
- **Not infallible.** `EVALS.md` records an honest failure: small models can attach
  real-but-wrong citations. The validator catches invented identifiers, not subtly
  misapplied real ones. That gap is documented with costed next steps rather than hidden.

---

## See it for yourself

```bash
uv run lens-mcp --selftest                          # 5 tools, citation + gate + audit invariants
uv run lens-demo --approve "Your Name"              # offline: plan → repair loop → gate → artifacts
MODEL=ollama/qwen3:1.7b uv run lens-demo --approve "Your Name"   # full task on open weights
```

Then read `logs/audit.jsonl`: one line per tool call and per node, with inputs, outputs,
timestamps, the model that produced it, and the named human who approved it.
