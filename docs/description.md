# Submission description (~300 words)

**What it does.** Public Procurement Lens is an agentic reviewer of Kenyan public tender awards. Given an award, it plans the review, retrieves the award record, supplier history, and price comparables through its own MCP server (`lens-mcp`: 5 tools — 3 read, 2 action), runs robust price analysis (median/MAD outliers), and synthesizes findings in which every claim must cite the OCDS record backing it. A citation validator rejects unsourced or hallucinated references through a capped repair loop; whatever survives stops at a human approval gate (LangGraph `interrupt`, named approver) before the agent drafts a committee brief and raises red flags. Every action lands in an append-only audit trail. The agent never awards the tender — no such tool exists.

**Theme.** Value for money (financial services): price outliers vs historic awards, supplier award concentration, and data-integrity flags — built on the awards/pricing half of Kenya PPIP's live OCDS feed (tenders.go.ke; bid documents are not published anywhere, and the README says so plainly).

**Which institution and workflow.** Kenyan procuring entities and PPRA/auditor oversight: the price-reasonableness review that evaluation committees and auditors perform by hand before award decisions — hours of cross-referencing reduced to a sourced draft file that a named human approves, rejects, or edits, with the full tool-call trail retained for defensibility.

**How it's built.** LangGraph orchestration (open-source, MIT). Own MCP server implementing a versioned pydantic contract, with a stub that swaps to the real server via config. Official `mcp-server-fetch` as the borrowed MCP server — maintained by the MCP project, it beats hand-rolling a scraper for citing regulation text and portal pages live. One full task runs end-to-end on a local open-weights model (Qwen3 via Ollama; procurement data never leaves the machine), with an optional frontier comparison. An 11-task eval suite reports results honestly, including one unfixed failure — small models can attach real-but-wrong citations — with four costed next steps.

*(293 words)*
