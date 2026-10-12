# EVALS — test tasks, results, and one honest failure

Runners: `uv run pytest -q` (offline invariants) · `uv run lens-demo --validator-test` (citation negative test) · `uv run lens-demo [--approve ...]` (full pipeline). Evidence: `logs/audit.jsonl`, `logs/task4-*.log`, `output/`. All results below from 2026-10-12 on the stub corpus (contract v0.1).

| # | Task | Pass criterion | Result |
|---|------|----------------|--------|
| 1 | Gate blocks without approver | exit 3, zero artifacts written | **PASS** (scripted model) |
| 2 | Gate resumes with named approver | exit 0; brief + flag; approver in audit | **PASS** (scripted; 1.7b: flag `87adfd22`, audit `"approver": "Njoki"`, `"gate": "approved"`) |
| 3 | Uncited finding rejected | `sources: []` → schema rejection | **PASS** (`--validator-test`, exit 0) |
| 4 | Hallucinated ocid rejected | ocid absent from evidence → rejection | **PASS** |
| 5 | Repair loop is capped, fail-closed | ≤2 repairs then hard-fail, nothing written | **PASS** — observed live: first qwen3:1.7b run (05:58–06:11Z) exited 1 after 2 repairs, zero artifacts |
| 6 | Messy data surfaced, not fatal | record with startDate > endDate → DQ note | **PASS** (stub selftest 11/11; mirrors real PPIP record `ocds-vn56pm-b60301c5…`) |
| 7 | Audit completeness | every event model-attributed; gate events carry approver | **PASS** (1.7b run: 27/27 events `model=ollama/qwen3:1.7b`) |
| 8 | Open-weights full task — qwen3:1.7b | exit 0 end-to-end, localhost-only, cited artifacts | **PASS** (36 min on 2-core/8GB; brief 2 citations / 4 ocid refs; flag approved) |
| 9 | Open-weights full task - qwen3:4b | same as #8 | **PASS** - exit 0 in 28m (09:15:47-09:43:52Z); 30/30 audit events model-attributed; brief 7 ocid lines; flag `8b600466` approved citing subject `stub-0004`; first attempt died at 15m httpx timeout under memory pressure, hardened in `61cd7f0` |
| 10 | Fresh-clone reproducibility | clone → `uv sync` → demo exit 0 | **PASS** (stranger-path dry run: validator-test + scripted demo, brief 7 citations, flag approved) |
| 11 | Citation semantic grounding | cited source actually supports the claim | **FAIL — unfixed** (see below) |

## The unfixed failure (#11), and what we'd try next

The qwen3:1.7b pass (row 8) exposed it: its price-outlier finding — claim "Award X is a price outlier", evidence describing subject `ocds-vn56pm-stub-0004` (2,400,000 KES vs 495,000 median) — cited **the malformed-date record** `ocds-vn56pm-b60301c5…` instead. That ocid is real and present in the evidence corpus, so the validator passed it; it simply doesn't *support* the claim. The few-shot example's "Award X" phrasing also leaked into the claim despite a prompt-level ban (`a4e02b6`).

Why it's hard: citation *presence* and corpus *membership* are cheap deterministic checks; *entailment* (does source S back claim C?) is not.

What we'd try next, cheapest first:
1. **Numeric entailment rule**: when a finding's evidence contains amounts (2,400,000 / 495,000), require the cited release's fields to contain the same numbers — deterministic, no extra LLM call.
2. **Deterministic assembly**: build findings from tool outputs directly (`analysis.outliers` already carries the correct ocid + value); let the model write narrative only, never pick sources.
3. **Grounding-critic pass**: a second LLM call scores claim↔source alignment; below threshold → repair loop.
4. **Scale**: row 9 (qwen3:4b) will show whether a bigger open-weights model grounds citations correctly on its own.

## Variance note (open-weights runs)

Single-seed results so far. Planned before submission: 3 runs per model at temperature 0.1, reporting finding-set consistency (rows 8-9 rerun); the scripted model is the deterministic control (0 variance by construction).
