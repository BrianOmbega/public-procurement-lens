# Evidence — one real, gated run

> **Why this directory is committed:** `logs/`, `output/` and `data/` are gitignored, so a cold
> clone of this repo contains **zero** audit trail. The submission requirement is "a logged tool
> call for every action, and a gate on every irreversible one — inputs, outputs, timestamps, and a
> named human approving." This directory is the receipt: a complete run's trail, the artifacts it
> produced, and a machine verdict over both.

## What is in here

| File | What it is |
|---|---|
| `audit.jsonl` | The full append-only trail of one gated run: 18 events, each with `ts`, `kind`, `tool`, `model`, `session`, `request`, `response`, and `approver` where a human authorised something. |
| `brief-20261015-204521.md` | The committee brief that run produced: 3 findings, 7 citations, naming the approving human and the timestamp. |
| `flags.jsonl` | The flag raised by that run, `status: approved`, `approver: Njoki Mwangi`, with `recommended_action`. |
| `demo.log` | The demo's own stdout, including the `resume_with` payload the gate waited on. |
| `verify.txt` | Output of `lens-audit verify` and `lens-audit summary` over the two files above. |

## Honest scope — read this before judging the pack

The run uses the **`scripted` model**, the deterministic offline control. Every one of the 18
events says `model: scripted`.

That is deliberate, and it bounds the claim:

- **What this pack proves** is the *machinery*: the model's plan drives which tools fire, retrieval
  and price analysis run, the citation validator rejects uncited findings, the graph suspends at
  `interrupt()` until a validated named human approves, both action tools refuse without one, every
  call is logged on both sides of the MCP wire, and the artifacts and the trail agree in both
  directions.
- **What it does not prove** is model quality. It is not an open-weights run and must not be read
  as one. For that, see `EVALS.md` row 8 (`qwen3:1.7b`, full task, exit 0) — including row 11,
  which stays **FAIL — unfixed** on citation semantic grounding.

Deterministic on purpose: re-running the generator produces a byte-identical pack apart from
timestamps and the artifact filename.

## Verify it yourself

```bash
uv run lens-audit verify --audit evidence/offline-run/audit.jsonl --output evidence/offline-run
```

Expected: 5/5 `[PASS]` and `VERIFY PASSED`, exit 0. The five checks are schema completeness,
timestamp monotonicity, model attribution, gate coverage over `GATED_TOOLS`, and artifact/event
agreement in both directions.

**Do not take "PASSED" on faith — make it fail.** Copy the trail somewhere writable and tamper with
it, then re-run against the copy:

```bash
cp evidence/offline-run/audit.jsonl /tmp/t.jsonl
# note the trailing /g — audit.py appends `approver` LAST, so the key also appears
# nested inside `request` earlier on the same line. Without /g, sed nulls only that
# first nested copy and the top-level approver the verifier reads survives.
sed -i.bak 's/"approver": "Njoki Mwangi"/"approver": null/g' /tmp/t.jsonl
uv run lens-audit verify --audit /tmp/t.jsonl --output evidence/offline-run   # -> FAIL, exit 1
```

Both of these were run and do fail, exit 1:

```bash
# strip every approver  -> [FAIL] gate: ... 4 ungated
# drop the brief file    -> [FAIL] artifacts: ... 1 missing
```

Stripping an approver, deleting an artifact, reordering two timestamps, or blanking a `model` field
each produce a distinct named failure. A verifier that cannot fail proves nothing.

## Regenerate it

```bash
bash scripts/make_evidence.sh            # approver defaults to "Njoki Mwangi"
bash scripts/make_evidence.sh "Your Name"
```

The script wipes and rebuilds this directory, then runs the verifier. It exits non-zero if the run
does not verify, so a broken pack cannot be committed by accident.

## Related

- `docs/CAPABILITIES.md` — the submission form's capability list, mapped to code
- `docs/AGENTIC.md` — why this is an agentic system rather than a scripted pipeline
- `EVALS.md` — test results, the one honest failure, and open-weights variance
