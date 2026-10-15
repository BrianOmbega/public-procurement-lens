# How MCP is implemented

> **Owns:** the answer to the submission form field *"Explain how you implemented Model Context
> Protocol (MCP) in your solution. Identify the MCP servers, tools, resources, and integrations
> used and explain how they connect to your agent."*
>
> Every statement below was checked against `src/lens/` on 2026-10-15. Where a rationale is my
> reasoning rather than a quoted design decision, it is labelled as such.

MCP is not a decorative dependency here. It is the **only** path between the agent and its data:
the graph never opens SQLite, never imports the server's functions, and never calls a tool
in-process. That constraint is what makes the audit trail and the approval gate trustworthy — a
tool call cannot happen without crossing a wire that logs it.

---

## Servers

Three MCP servers, all over **stdio**:

| Server | Ours? | Source | Role |
|---|---|---|---|
| **`lens-mcp`** | written here | `src/lens/mcp_server.py` | The real server: 5 tools over the SQLite corpus, opened **read-only** so it can never mutate the data it cites. `FastMCP("lens-mcp")`, registered with five `@mcp.tool()` decorators, started by `mcp.run()`. |
| **`lens-stub`** | written here | `src/lens/stubs/stub_mcp.py` | The same 5-tool contract over in-memory fixtures. The default `LENS_MCP_CMD` target, so the whole graph runs offline and deterministically in CI. |
| **`mcp-server-fetch`** | **borrowed** | PyPI `mcp-server-fetch>=2026.7.10`, run as `python -m mcp_server_fetch` | The official upstream fetch server. Opt-in via `lens-demo --with-fetch`. |

**Why borrow the fetch server instead of writing one** (this is challenge requirement #4): it is
maintained by the MCP project itself, so redirects, `robots.txt` and character encoding are already
handled. It lets the agent cite regulation text and portal pages live without us shipping and
maintaining a fragile scraper. The launch command is a module exec rather than the `uvx` launcher
because `uvx` needs a realpath that is absent on macOS 12 — noted in `mcp_bridge.py`.

**Stub ↔ real is a config change, not a code change.** `demo.py` reads `LENS_MCP_CMD` (default
`lens-stub`) and constructs `McpBridge(lens_cmd, "lens-mcp", model=model.name)`. Pointing it at
`lens-mcp` swaps the implementation with **zero graph edits**. That works because both servers
import the same pydantic contract *and* the same shared cores (`analysis.py`, `actions.py`), so
parity is structural rather than copy-pasted. `tests/test_server_parity.py` asserts the two return
identical payloads for identical inputs.

## Tools

Five, declared once in `schemas/contract.py` as `TOOL_NAMES`:

| Tool | Kind | What it does |
|---|---|---|
| `search_awards` | read | Query the corpus; returns award records with provenance. |
| `get_supplier_history` | read | Supplier alias-normalised history across awards. |
| `analyze_price` | read | Median / MAD robust z-score against comparables. |
| `draft_committee_brief` | **action — gated** | Writes the committee brief. Refuses without a validated named approver. |
| `raise_flag` | **action — gated** | Appends a flag. Without an approver it lands as `pending_approval`, never `approved`. |

`ACTION_TOOLS = TOOL_NAMES[3:]` and `GATED_TOOLS = ACTION_TOOLS`, so "a gate on every irreversible
action" is a machine-readable declaration rather than a convention. `lens-audit verify` asserts
every *successful* call to a `GATED_TOOLS` member carries a valid approver.

Requests and responses are pydantic models from that one contract module; errors come back as a
`ToolError` payload (`code`, `message`, `detail`) rather than a protocol-level exception, so a
refusal is **data the graph can route on** and the audit trail can record.

## Resources and prompts: none

There are **no MCP resources and no MCP prompts** in this solution. Verified: no `@mcp.resource`,
no `@mcp.prompt`, no `list_resources`/`list_prompts` anywhere in either server. The surface is
tools-only.

*Reasoning, not a quoted decision:* that is deliberate and it is the right shape for this problem.
A resource is passive content a client may read at will; here, every access to the corpus has to be
**logged with inputs and outputs** and, when it writes, **gated on a named human**. Routing corpus
access through `search_awards` instead of exposing the database as a resource means there is no
read path that bypasses the audit event. Exposing the SQLite file as an MCP resource would create
exactly the untracked side door the requirement forbids.

## How it connects to the agent

`McpBridge` (`src/lens/mcp_bridge.py`) is an async context manager owning **one** MCP session:

```
StdioServerParameters(command, args, env, cwd)
  → stdio_client(params)            # spawns the server subprocess
  → ClientSession(read, write)
  → await session.initialize()      # MCP handshake
  → await session.call_tool(name, args)
  → _unwrap(result)                 # normalise 3 possible result shapes
  → nested __aexit__ teardown
```

The graph holds two bridges and nothing else: `self.bridge` (lens server) and `self.fetch`
(borrowed server, `None` unless `--with-fetch`). Node code is therefore plain tool calls:

```python
corpus   = await self.bridge.call("search_awards", query="", limit=200)
history  = await self.bridge.call("get_supplier_history", supplier=supplier)
analysis = await self.bridge.call("analyze_price", item_query=item,
                                  subject_ocid=subject.get("ocid"))
page     = await self.fetch.call("fetch", url=url, max_length=2000)   # only if --with-fetch
brief    = await self.bridge.call("draft_committee_brief", title=..., findings=...,
                                  subject_ocids=[...], context=...,
                                  approver=gate.get("approver"))
```

Note the last line: the approver captured at the human gate is what authorises the write. If the
tool refuses, `finalize` returns the refusal as a structured error and **does not raise flags
either** — one gate covers the whole irreversible step, not just its first half.

**`_unwrap` is what makes the client tolerant of other people's servers.** It handles three result
shapes: `isError` → a structured `{code: "tool_error", message}` truncated to 500 chars;
`structuredContent` as a dict, unwrapping FastMCP's `{"result": {...}}` envelope when present;
otherwise the text content parsed as JSON, falling back to `{"raw": text}`. The borrowed fetch
server does not have to match our conventions for this to work.

## Audit on both sides of the wire

Every call produces **two** events, which is the point:

- **Client side** (`McpBridge.call`): `kind="mcp_call"`, `tool="lens-mcp:<name>"`, with the request
  args and the unwrapped response.
- **Server side** (inside each tool): `kind="tool_call"`, `tool="<name>"`.

Two details that make those events actually comparable:

1. **Model attribution across a process boundary.** The server is a subprocess and cannot see the
   graph's model object, so its events would read `model: "unset"`. The bridge injects
   `LENS_MODEL` into the subprocess env, and `audit.py` reads that first — so all events in a run
   name the same brain. This was a real bug found and fixed by the verifier, not a design flourish.
2. **Approver lifted to the top level on both sides.** The server already recorded it there; without
   the matching client-side field, one logical action produced two differently-shaped events and an
   auditor filtering on `.approver` would see only half of every gated write.

## Integrations summary

| Integration | Mechanism |
|---|---|
| Agent ↔ own tools | MCP stdio, `lens-stub` or `lens-mcp` selected by `LENS_MCP_CMD` |
| Agent ↔ borrowed fetch | MCP stdio, `python -m mcp_server_fetch`, selected by `LENS_FETCH_CMD`, opt-in `--with-fetch` |
| Agent ↔ LLM | `httpx` to an OpenAI-compatible `/chat/completions`, or Ollama; **not** MCP |
| Tools ↔ data | `sqlite3`, read-only, corpus seeded by `lens-ingest` (ijson-streamed OCDS) |
| Everything ↔ audit | append-only JSONL via `audit.py`, verified by `lens-audit verify` |
| Citation targets | `tenders.go.ke` portal URLs (`PORTAL_BASE`) embedded in `SourceRef` |

## See also

- `docs/STACK.md` — the architecture and full technology stack
- `docs/CONTRACT.md` — the 5-tool contract, v0.1 IMPLEMENTED
- `docs/CAPABILITIES.md` — the capability list mapped to code
- `evidence/README.md` — one real gated run's trail and artifacts, with the verifier's verdict
