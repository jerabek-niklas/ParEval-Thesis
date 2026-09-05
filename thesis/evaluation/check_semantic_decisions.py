#!/usr/bin/env python3
"""Semantic-decision gate for pilot_002.

Reads the machine-readable source of truth written by the Semantic Interlock
wave (thesis/evaluation/semantic_decisions_pilot002.json) together with the
interlock registry (thesis/evaluation/prompt_oracle_interlock.json) and
classifies every decision:

    unresolved decision                      -> BLOCK
    RESOLVED decision                        -> PASS
    ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002 -> PASS_WITH_DISCLOSURE

A registry entry is therefore NOT automatically a blocker: a deliberately
accepted disclosure passes, provided its reporting requirement is
machine-readable. The consistency checks are:

  RESOLVED
    * the exact convention sentence(s) recorded in the decision appear in all
      three raw prompt files (serial/omp/mpi) AND in the three generated
      entries of thesis/prompts/generation-prompts-thesis.json (atomicity;
      raw and generated may not diverge)
    * the benchmark is NOT listed in the interlock registry any more
  ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002
    * the registry lists the benchmark with exactly that status
    * the decision carries a reporting_requirement with benchmark,
      decision_id(s), short_hint and affected_results
    * the prompt is NOT claimed to have changed for it
  any other status                          -> unresolved -> BLOCK

Output (last lines are machine-readable):
    SEMANTIC_DECISION_UNRESOLVED = <n>
    SEMANTIC_DISCLOSURE_ACCEPTED = <n>
    SEMANTIC_DECISIONS_RESOLVED = <n>
    SEMANTIC_GATE = PASS | PASS_WITH_DISCLOSURE | BLOCK | UNRESOLVED
Exit code: 0 for PASS / PASS_WITH_DISCLOSURE, 1 for BLOCK, 2 when the
artifacts are missing or malformed (UNRESOLVED - never silently green).

This gate answers only "are the semantic decisions final and consistent?".
It does NOT render disclosures (SEMANTIC_DISCLOSURE_RENDERING is a later
reporting-wave obligation) and decides nothing about population, run_id,
reuse or publication.

Python 3.8 compatible; no compiler needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS_PATH = REPO_ROOT / "thesis" / "evaluation" / "semantic_decisions_pilot002.json"
REGISTRY_PATH = REPO_ROOT / "thesis" / "evaluation" / "prompt_oracle_interlock.json"
RAW_ROOT = REPO_ROOT / "thesis" / "prompts" / "raw"
PROMPTS_JSON = REPO_ROOT / "thesis" / "prompts" / "generation-prompts-thesis.json"

MODELS = ("serial", "omp", "mpi")
STATUS_RESOLVED = "RESOLVED"
STATUS_DISCLOSURE = "ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002"
FINAL_STATUSES = (STATUS_RESOLVED, STATUS_DISCLOSURE)
REPORTING_FIELDS = ("benchmark", "decision_ids", "short_hint", "affected_results")


def _load(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _norm(text):
    """Line-ending-insensitive containment (raw prompts are CRLF)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _generated_prompts():
    data = _load(PROMPTS_JSON) or []
    out = {}
    for entry in data:
        key = (entry.get("problem_type", "") + "/" + entry.get("name", ""),
               entry.get("parallelism_model"))
        out[key] = entry.get("prompt", "")
    return out


def evaluate(decisions_doc, registry_doc, generated=None):
    """Return an OrderedDict with per-decision rows and the aggregate verdict.

    Pure function of the three inputs so the preflight and the tests can call
    it without touching stdout.
    """
    generated = _generated_prompts() if generated is None else generated
    rows = []
    problems = []

    registry_entries = {}
    for entry in (registry_doc or {}).get("interlocks", []) or []:
        registry_entries[entry.get("benchmark")] = entry

    decisions = (decisions_doc or {}).get("decisions") or []
    if not isinstance(decisions, list) or not decisions:
        problems.append("decision artifact has no decisions list")

    for dec in decisions:
        benchmark = dec.get("benchmark")
        status = dec.get("status")
        ids = list(dec.get("decision_ids") or [])
        row = OrderedDict([
            ("benchmark", benchmark),
            ("decision_ids", ids),
            ("status", status),
            ("gate", None),
            ("issues", []),
        ])
        issues = row["issues"]

        if status == STATUS_RESOLVED:
            row["gate"] = "PASS"
            sentences = dec.get("prompt_convention_sentences") or []
            if dec.get("prompt_changed") and not sentences:
                issues.append("prompt_changed but no prompt_convention_sentences recorded")
            models = list(dec.get("parallelism_models") or MODELS)
            for model in models:
                raw_path = RAW_ROOT / benchmark / model
                raw = _norm(raw_path.read_text(encoding="utf-8")) if raw_path.is_file() else None
                gen = generated.get((benchmark, model))
                if raw is None:
                    issues.append("raw prompt missing: %s" % raw_path)
                if gen is None:
                    issues.append("generated prompt entry missing for %s/%s" % (benchmark, model))
                for sentence in sentences:
                    s = _norm(sentence)
                    if raw is not None and s not in raw:
                        issues.append("convention sentence absent from raw %s prompt: %r"
                                      % (model, sentence[:60]))
                    if gen is not None and s not in _norm(gen):
                        issues.append("convention sentence absent from generated %s prompt: %r"
                                      % (model, sentence[:60]))
                if raw is not None and gen is not None and raw != _norm(gen):
                    issues.append("raw and generated %s prompt differ (regenerate the JSON)" % model)
            if benchmark in registry_entries:
                issues.append("RESOLVED benchmark is still listed in the interlock registry")
            if issues:
                row["gate"] = "BLOCK"
        elif status == STATUS_DISCLOSURE:
            row["gate"] = "PASS_WITH_DISCLOSURE"
            reg = registry_entries.get(benchmark)
            if reg is None:
                issues.append("accepted-disclosure benchmark is missing from the interlock registry")
            elif reg.get("status") != STATUS_DISCLOSURE:
                issues.append("registry status is %r, expected %r"
                              % (reg.get("status"), STATUS_DISCLOSURE))
            req = dec.get("reporting_requirement")
            if not isinstance(req, dict):
                issues.append("reporting_requirement missing or not an object")
            else:
                for field in REPORTING_FIELDS:
                    value = req.get(field)
                    if value in (None, "", [], {}):
                        issues.append("reporting_requirement.%s missing" % field)
                if req.get("benchmark") not in (None, benchmark):
                    issues.append("reporting_requirement.benchmark does not match")
            if dec.get("prompt_changed"):
                issues.append("a disclosure decision must not claim a prompt change")
            if issues:
                row["gate"] = "BLOCK"
        else:
            row["gate"] = "BLOCK"
            issues.append("status %r is not final (expected one of %s)"
                          % (status, ", ".join(FINAL_STATUSES)))
        rows.append(row)

    # every registry entry must be covered by a decision
    decided = {r["benchmark"] for r in rows}
    for benchmark in registry_entries:
        if benchmark not in decided:
            problems.append("registry benchmark %s has no decision" % benchmark)

    unresolved = sum(1 for r in rows if r["gate"] == "BLOCK")
    accepted = sum(1 for r in rows if r["gate"] == "PASS_WITH_DISCLOSURE")
    resolved = sum(1 for r in rows if r["gate"] == "PASS")

    counts_declared = {
        "resolved_count": decisions_doc.get("resolved_count") if decisions_doc else None,
        "disclosure_count": decisions_doc.get("disclosure_count") if decisions_doc else None,
        "unresolved_count": decisions_doc.get("unresolved_count") if decisions_doc else None,
    }
    if decisions_doc:
        if counts_declared["resolved_count"] not in (None, resolved):
            problems.append("declared resolved_count %r != computed %d"
                            % (counts_declared["resolved_count"], resolved))
        if counts_declared["disclosure_count"] not in (None, accepted):
            problems.append("declared disclosure_count %r != computed %d"
                            % (counts_declared["disclosure_count"], accepted))
        if counts_declared["unresolved_count"] not in (None, unresolved):
            problems.append("declared unresolved_count %r != computed %d"
                            % (counts_declared["unresolved_count"], unresolved))
        meta = (registry_doc or {}).get("_meta") or {}
        if meta.get("interlock_benchmark_count") not in (None, len(registry_entries)):
            problems.append("registry _meta.interlock_benchmark_count %r != %d entries"
                            % (meta.get("interlock_benchmark_count"), len(registry_entries)))
        pairs = sum(len(e.get("prompt_pairs") or []) for e in registry_entries.values())
        if meta.get("interlock_prompt_pair_count") not in (None, pairs):
            problems.append("registry _meta.interlock_prompt_pair_count %r != %d pairs"
                            % (meta.get("interlock_prompt_pair_count"), pairs))

    if problems:
        gate = "UNRESOLVED"
    elif unresolved:
        gate = "BLOCK"
    elif accepted:
        gate = "PASS_WITH_DISCLOSURE"
    else:
        gate = "PASS"

    return OrderedDict([
        ("rows", rows),
        ("problems", problems),
        ("unresolved", unresolved),
        ("accepted_disclosure", accepted),
        ("resolved", resolved),
        ("registry_benchmarks", sorted(registry_entries)),
        ("gate", gate),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    decisions_doc = _load(DECISIONS_PATH)
    registry_doc = _load(REGISTRY_PATH)
    if decisions_doc is None or registry_doc is None:
        missing = [str(p) for p, d in ((DECISIONS_PATH, decisions_doc),
                                       (REGISTRY_PATH, registry_doc)) if d is None]
        print("SEMANTIC_GATE = UNRESOLVED (missing/unreadable: %s)" % ", ".join(missing))
        return 2

    result = evaluate(decisions_doc, registry_doc)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("SEMANTIC_DECISIONS (%s)" % DECISIONS_PATH.relative_to(REPO_ROOT))
        for row in result["rows"]:
            print("  %-48s %-44s %s" % (row["benchmark"], ",".join(row["decision_ids"]), row["gate"]))
            for issue in row["issues"]:
                print("      - %s" % issue)
        for problem in result["problems"]:
            print("  PROBLEM: %s" % problem)
        print("  registry now lists: %s" % (", ".join(result["registry_benchmarks"]) or "(none)"))
        print("SEMANTIC_DECISION_UNRESOLVED = %d" % result["unresolved"])
        print("SEMANTIC_DISCLOSURE_ACCEPTED = %d" % result["accepted_disclosure"])
        print("SEMANTIC_DECISIONS_RESOLVED = %d" % result["resolved"])
        print("SEMANTIC_DISCLOSURE_RENDERING = NOT_IMPLEMENTED (reporting-wave obligation;"
              " this gate only proves the requirement is machine-readable)")
        print("SEMANTIC_GATE = %s" % result["gate"])
    if result["gate"] == "UNRESOLVED":
        return 2
    return 1 if result["gate"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
