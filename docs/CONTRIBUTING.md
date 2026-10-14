# Contributing to public-procurement-lens

Proposed team workflow — pending confirmation from @BrianOmbega.

## Access model

- **Preferred**: collaborator access + branch protection on `main`; contributors push `contrib/*` branches and open PRs.
- **Fallback**: fork + PR. Note: a fork PR needs at least one upstream commit — the repo is currently empty, so someone must push the seed first (proposed: njoki's local scaffold — LICENSE, pyproject, contract, stub, docs — as the initial commit).

## Branches

| Branch | Contents | Owner |
|---|---|---|
| `main` | seed: license, pyproject, contract, docs, stub | proposed: njoki's scaffold |
| `contrib/orchestration` | LangGraph graph, models layer, audit, demo | njoki |
| `contrib/open-weights-run` | Ollama/Qwen local task run + evidence | njoki |
| `contrib/mcp-server` | real lens-mcp + ingest pipeline | njoki — **built & merged to `main`** (`15590e1`, `d6bb587`, `a6ca35e`) |

## Lanes

| Area | Owner |
|---|---|
| Repo, submission, demo video | Brian |
| Orchestration + open-weights task (requirements 1 & 2) | njoki |
| lens-mcp server + data ingest (requirements 3 & 4 wiring) | njoki — **built** (`lens-ingest` + `lens-mcp`, selftest 15/15, full-graph demo green via `LENS_MCP_CMD`) |
| Tool contract (`docs/CONTRACT.md` + `src/lens/schemas/`) | shared — changes via PR pinging both builders |

## Dev setup

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```bash
uv sync                        # installs project + deps (dev group included)
uv run lens-stub --selftest    # contract smoke test against fixtures
uv run pytest -q               # test suite
```

`data/`, `output/`, `logs/` are gitignored — never commit them.

## Rules

1. Small, tested, self-contained PRs. Conventional-ish commit subjects (`Add …`, `Fix …`).
2. Every finding/flag in any code path carries ≥1 `SourceRef` — the citation validator rejects uncited findings and the schema enforces it. Don't weaken either.
3. **Nothing awards a tender. Ever.** No tool, no graph node, no "recommend winner" field. The agent prepares the file; humans decide.
4. The audit log format (`logs/audit.jsonl`, one JSON event per line: ts, kind, tool, model, session, request, response, approver?) is part of the contract — don't fork it per component.
5. Human-gate: irreversible artifacts (final flags, published briefs) require a named approver recorded in the audit log.

## Deadline discipline

Submission closes **2026-10-15** and the repo is cloned at the deadline timestamp:

- Everything merged to `main` by **Oct 14**; Oct 15 is buffer only.
- New work built during the submission window only; any reused component gets disclosed in the README (challenge rule).
