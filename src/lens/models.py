"""Swappable model layer (challenge requirement #2: open-weights task runs).

MODEL env picks the brain:
  unset | "scripted"  deterministic offline model — tests, gate checks, CI
  "ollama/<name>"     local open-weights model via Ollama's OpenAI-compat API
  "<name>"            any OpenAI-compatible endpoint (OPENAI_BASE_URL + OPENAI_API_KEY)

Every model carries `.name` so audit events prove WHICH weights produced which
artifact — that trail is the open-weights evidence for the judges.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

PLAN_SYSTEM = (
    "You are the planning step of a public-procurement evaluation agent. "
    'Return ONLY JSON: {"task": "price_reasonableness", "subject_ocid": "<given>", '
    '"checks": ["price_analysis", "supplier_history", "data_quality"]}. '
    "The agent prepares files for humans; it never awards tenders."
)

SYNTH_SYSTEM = (
    "You are the findings-synthesis step of a public-procurement evaluation agent. "
    "Build findings ONLY from the tool outputs you are given. Every finding MUST cite "
    ">=1 source whose ocid appears VERBATIM in the inputs — never invent or reshape an "
    "identifier; uncited findings are rejected by the validator. severity is one of "
    "low|medium|high|critical. Return ONLY JSON: {\"findings\": [{\"claim\": str, "
    '"evidence\": str, "severity\": str, "sources": [{"ocid": str, "field_path"?: str, '
    '"quote"?: str}]}]}. The agent prepares the file; humans decide awards.'
)

_DEFAULT_CHECKS = ["price_analysis", "supplier_history", "data_quality"]


class ScriptedModel:
    """Deterministic 'model' for offline runs: builds findings directly from
    tool outputs, always with citations from the evidence. Not an LLM — it
    exists so the graph mechanics (gate, validator, audit) are testable
    without any weights, and as the CI baseline."""

    name = "scripted"

    async def plan(self, subject_ocid: str) -> dict:
        return {"task": "price_reasonableness", "subject_ocid": subject_ocid,
                "checks": list(_DEFAULT_CHECKS)}

    async def synthesize(self, subject: dict, evidence: dict, analysis: dict,
                         feedback: Optional[list] = None) -> list[dict]:
        findings: list[dict] = []
        subj_src = {"ocid": subject.get("ocid", ""), "field_path": "awards[0].value.amount"}
        assessment = analysis.get("subject_assessment") or ""
        if "OUTLIER" in assessment:
            findings.append({
                "claim": f"Award {subject.get('ocid')} is a price outlier versus comparable awards",
                "evidence": assessment,
                "severity": "high",
                "sources": [subj_src],
            })
        hist = evidence.get("history") or {}
        if hist.get("total_awards", 0) >= 2:
            findings.append({
                "claim": (f"Supplier '{hist.get('canonical_name')}' holds {hist['total_awards']} "
                          f"corpus awards under {len(hist.get('aliases_matched', []))} name variants"),
                "evidence": "Alias-normalised supplier history; identifiers inconsistent across releases",
                "severity": "medium",
                "sources": [{"ocid": a["ocid"]} for a in hist.get("awards", [])][:3] or [subj_src],
            })
        notes = analysis.get("data_quality_notes") or []
        dq_awards = [a for a in (evidence.get("corpus") or []) if a.get("data_quality_notes")]
        if notes and dq_awards:
            findings.append({
                "claim": "Source data contains integrity defects that must be resolved before any award decision",
                "evidence": "; ".join(dict.fromkeys(notes))[:400],
                "severity": "medium",
                "sources": [{"ocid": a["ocid"], "quote": a["data_quality_notes"][0]} for a in dq_awards][:3],
            })
        return findings


class OpenAICompatModel:
    """Any OpenAI-compatible /chat/completions endpoint: Ollama (open-weights,
    local — data never leaves the machine) by default; point OPENAI_BASE_URL +
    OPENAI_API_KEY at a frontier provider for the alongside comparison run."""

    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def _chat(self, system: str, user: str) -> str:
        if "qwen3" in self.name.lower():
            system += "\n/no_think"  # Qwen3 thinking-mode soft switch: caps latency blowup on CPU
        async with httpx.AsyncClient(timeout=900) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.name.split("/", 1)[-1],
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}],
                      "temperature": 0.1,
                      "max_tokens": 1500})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(text: str) -> Any:
        t = text.strip()
        starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
        if not starts:
            raise ValueError(f"no JSON in model output: {t[:200]!r}")
        start = min(starts)
        end = max(t.rfind("}"), t.rfind("]"))
        return json.loads(t[start:end + 1])

    async def plan(self, subject_ocid: str) -> dict:
        out = await self._chat(PLAN_SYSTEM, f"Subject award ocid: {subject_ocid}")
        plan = self._parse_json(out)
        if not isinstance(plan, dict):
            raise ValueError("plan was not a JSON object")
        plan.setdefault("checks", list(_DEFAULT_CHECKS))
        plan["subject_ocid"] = subject_ocid
        return plan

    async def synthesize(self, subject: dict, evidence: dict, analysis: dict,
                         feedback: Optional[list] = None) -> list[dict]:
        payload = {
            "subject": subject,
            "analysis": {k: analysis.get(k) for k in
                         ("median", "mad", "n_comparables", "outliers",
                          "subject_assessment", "data_quality_notes")},
            "supplier_history": {k: (evidence.get("history") or {}).get(k) for k in
                                 ("canonical_name", "aliases_matched", "total_awards",
                                  "buyers", "data_quality_notes")},
        }
        user = json.dumps(payload, default=str)[:7000]
        if feedback:
            user += ("\n\nYour previous findings were REJECTED by the citation validator: "
                     + json.dumps(feedback)[:800] + "\nRepair them: every source ocid must "
                     "appear verbatim in the inputs above.")
        out = await self._chat(SYNTH_SYSTEM, user)
        data = self._parse_json(out)
        findings = data.get("findings") if isinstance(data, dict) else data
        if not isinstance(findings, list):
            raise ValueError("model did not return a findings list")
        return findings


def get_model() -> Any:
    spec = (os.environ.get("MODEL") or "scripted").strip()
    if not spec or spec.lower() == "scripted":
        return ScriptedModel()
    if spec.startswith("ollama/"):
        base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
        return OpenAICompatModel(spec, base, os.environ.get("OPENAI_API_KEY", "ollama"))
    return OpenAICompatModel(
        spec,
        os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        os.environ.get("OPENAI_API_KEY", "ollama"),
    )
