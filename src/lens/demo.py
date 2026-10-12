"""One-shot demo runner for the procurement-lens graph.

Exit codes: 0 finalized | 3 paused at human gate | 1 failed

Examples:
  uv run lens-demo                             # stops at the gate (exit 3)
  uv run lens-demo --approve "Njoki"           # gate → finalize → exit 0
  uv run lens-demo --validator-test            # citation-validator negative test
  MODEL=ollama/qwen3:4b uv run lens-demo --task price_reasonableness --approve "Njoki"
  uv run lens-demo --approve "Njoki" --with-fetch   # + borrowed mcp-server-fetch
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

from langgraph.types import Command

from lens.audit import audit_event
from lens.graph import build_graph, validate_findings
from lens.mcp_bridge import DEFAULT_FETCH_CMD, DEFAULT_LENS_CMD, McpBridge
from lens.models import get_model


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="lens-demo", description="Run the procurement-lens graph once")
    ap.add_argument("--subject", default="ocds-vn56pm-stub-0004",
                    help="ocid of the award under review (default: the stub 5x outlier)")
    ap.add_argument("--approve", metavar="FULL NAME", default=None,
                    help="named human approver; resumes the gate in-process")
    ap.add_argument("--task", default="price_reasonableness", help="task label for the audit trail")
    ap.add_argument("--thread", default=None, help="checkpoint thread id (default: demo-<ts>)")
    ap.add_argument("--with-fetch", action="store_true",
                    help="also start the borrowed mcp-server-fetch for live provenance citations")
    ap.add_argument("--validator-test", action="store_true",
                    help="run the citation-validator negative test and exit")
    return ap.parse_args()


def _validator_test(model: Any) -> int:
    """Negative test: an uncited finding and a hallucinated-ocid finding must
    BOTH be rejected by validate_findings."""
    known = {"ocds-vn56pm-stub-0004"}
    bad = [
        {"claim": "uncited claim", "evidence": "e", "sources": []},
        {"claim": "fabricated source", "evidence": "e", "sources": [{"ocid": "ocds-fake-9999"}]},
    ]
    accepted, rejected = validate_findings(bad, known)
    audit_event(tool="validator_negative_test", kind="validation", model=model.name,
                request={"n_bad_findings": len(bad)},
                response={"accepted": len(accepted),
                          "rejected": [r["reason"][:200] for r in rejected]})
    ok = not accepted and len(rejected) == 2
    print(f"validator negative test: {'PASS' if ok else 'FAIL'} "
          f"(accepted={len(accepted)}, rejected={len(rejected)})")
    for r in rejected:
        print(f"  rejected: {r['reason'][:110]}")
    return 0 if ok else 1


async def _amain(args: argparse.Namespace) -> int:
    model = get_model()
    if args.validator_test:
        return _validator_test(model)

    thread = args.thread or f"demo-{time.strftime('%Y%m%d-%H%M%S')}"
    lens_cmd = os.environ.get("LENS_MCP_CMD", DEFAULT_LENS_CMD)
    fetch: Any = None
    async with McpBridge(lens_cmd, "lens-mcp", model=model.name) as bridge:
        if args.with_fetch:
            try:
                fetch = await McpBridge(os.environ.get("LENS_FETCH_CMD", DEFAULT_FETCH_CMD),
                                        "fetch", model=model.name).__aenter__()
            except BaseException as e:  # anyio cleanup can raise ExceptionGroup (BaseException)
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                print(f"[warn] borrowed fetch server unavailable ({str(e)[:140]}) — continuing without it")
                fetch = None
        try:
            graph = build_graph(bridge, model, fetch)
            config = {"configurable": {"thread_id": thread}}
            inputs = {"subject_ocid": args.subject, "model": model.name,
                      "task": args.task, "repair_count": 0}
            audit_event(tool="demo_start", kind="run", model=model.name,
                        request=inputs, response=None, thread=thread)
            print(f"lens-demo — subject={args.subject} task={args.task} model={model.name} thread={thread}")
            result = await asyncio.wait_for(graph.ainvoke(inputs, config), timeout=3300)

            intr = result.get("__interrupt__")
            if intr:
                payload = intr[0].value if hasattr(intr[0], "value") else intr[0]
                print("\n=== HUMAN GATE — run paused ===")
                print(json.dumps(payload, indent=2, default=str)[:1600])
                if not args.approve:
                    print(f"\nAWAITING HUMAN APPROVAL (thread {thread}). "
                          'Re-run with --approve "<Full Name>" to finalize. Nothing was written.')
                    return 3
                result = await asyncio.wait_for(
                    graph.ainvoke(Command(resume={"approved": True, "approver": args.approve}), config),
                    timeout=3300)

            if result.get("error"):
                print(f"\nRUN FAILED: {result['error']}")
                return 1

            arts = result.get("artifacts") or {}
            brief = arts.get("brief") or {}
            print(f"\n=== FINALIZED (task={args.task}, model={model.name}) ===")
            print(f"brief: {brief.get('brief_path')} (citations: {brief.get('citation_count')}, "
                  f"findings: {brief.get('findings_included')})")
            for fl in arts.get("flags") or []:
                print(f"flag {fl.get('flag_id')}: {fl.get('status')} — {fl.get('flags_path')}")
            return 0
        finally:
            if fetch is not None:
                await fetch.__aexit__(None, None, None)


def main() -> None:
    import threading

    def _watchdog() -> None:
        # Last resort: anyio/MCP cleanup can deadlock on error paths (observed
        # live 2026-10-12: demo hung 40+ min after the LLM call timed out).
        time.sleep(int(os.environ.get("LENS_WATCHDOG_SECS", "3600")))
        os._exit(2)

    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        code = asyncio.run(_amain(_parse_args()))
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    os._exit(code)  # skip async cleanup at shutdown — same deadlock class


if __name__ == "__main__":
    main()
