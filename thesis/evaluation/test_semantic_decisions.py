#!/usr/bin/env python3
"""Tests for the semantic-decision gate (Semantic Interlock wave).

Two layers:
  A. the gate LOGIC on synthetic inputs - unresolved -> BLOCK, resolved -> PASS,
     accepted disclosure -> PASS_WITH_DISCLOSURE, and every consistency rule
     (missing reporting requirement, registry still listing a resolved
     benchmark, wrong registry status, count mismatches) fails closed;
  B. the REAL artifacts - every former interlock has a final status, resolved
     conventions are present atomically in serial/omp/mpi (raw AND generated),
     disclosure cases carry machine-readable reporting requirements, the
     registry only lists disclosure/unresolved cases, and the worked examples
     of the resolved benchmarks are untouched.

Run:  python thesis/evaluation/test_semantic_decisions.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_semantic_decisions as gate  # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# A. synthetic
# ---------------------------------------------------------------------------

def synthetic_generated(bench, sentence):
    return {(bench, m): "/* task\n   %s\n   Example:\n*/\nvoid f() {" % sentence
            for m in gate.MODELS}


def group_logic():
    print("A. gate logic on synthetic inputs")
    bench_r = "fake/01_resolved"
    bench_d = "fake/02_disclosure"
    sentence = "If the vector is empty, return 0."
    generated = synthetic_generated(bench_r, sentence)

    # raw prompt files are read from disk; point the gate at a temp raw root
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="semantic_gate_test_"))
    old_raw = gate.RAW_ROOT
    gate.RAW_ROOT = tmp
    for m in gate.MODELS:
        p = tmp / bench_r / m
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(generated[(bench_r, m)].replace("\n", "\r\n").encode("utf-8"))

    registry = {"_meta": {"interlock_benchmark_count": 1, "interlock_prompt_pair_count": 3},
                "interlocks": [{"benchmark": bench_d, "status": gate.STATUS_DISCLOSURE,
                                "prompt_pairs": [{}, {}, {}]}]}
    decisions = {
        "resolved_count": 1, "disclosure_count": 1, "unresolved_count": 0,
        "decisions": [
            {"benchmark": bench_r, "decision_ids": ["X-1"], "status": gate.STATUS_RESOLVED,
             "prompt_changed": True, "prompt_convention_sentences": [sentence],
             "parallelism_models": list(gate.MODELS)},
            {"benchmark": bench_d, "decision_ids": ["X-2"], "status": gate.STATUS_DISCLOSURE,
             "prompt_changed": False,
             "reporting_requirement": {"benchmark": bench_d, "decision_ids": ["X-2"],
                                       "short_hint": "open tolerance", "affected_results": ["correctness"]}},
        ]}
    try:
        res = gate.evaluate(decisions, registry, generated)
        check("resolved -> PASS, disclosure -> PASS_WITH_DISCLOSURE",
              [r["gate"] for r in res["rows"]] == ["PASS", "PASS_WITH_DISCLOSURE"], str(res["rows"]))
        check("aggregate gate is PASS_WITH_DISCLOSURE", res["gate"] == "PASS_WITH_DISCLOSURE")
        check("no problems on a consistent artifact", not res["problems"], str(res["problems"]))

        # 1. an unresolved status blocks
        d = copy.deepcopy(decisions); d["decisions"][0]["status"] = "BLOCKED_PENDING_SEMANTIC_DECISION"
        d["resolved_count"] = 0; d["unresolved_count"] = 1
        res = gate.evaluate(d, registry, generated)
        check("unresolved status -> BLOCK", res["gate"] == "BLOCK" and res["unresolved"] == 1)

        # 2. a resolved benchmark still in the registry blocks
        reg = copy.deepcopy(registry)
        reg["interlocks"].append({"benchmark": bench_r, "status": "BLOCKED_PENDING_SEMANTIC_DECISION",
                                  "prompt_pairs": [{}, {}, {}]})
        reg["_meta"]["interlock_benchmark_count"] = 2; reg["_meta"]["interlock_prompt_pair_count"] = 6
        res = gate.evaluate(decisions, reg, generated)
        # the row blocks; the aggregate is additionally UNRESOLVED because the
        # artifact's declared counts no longer match - never green either way
        check("resolved benchmark still listed in the registry -> BLOCK",
              res["rows"][0]["gate"] == "BLOCK" and res["gate"] in ("BLOCK", "UNRESOLVED"))
        d = copy.deepcopy(decisions); d["resolved_count"] = 0; d["unresolved_count"] = 1
        res = gate.evaluate(d, reg, generated)
        check("...and with consistent counts the aggregate is BLOCK", res["gate"] == "BLOCK")

        # 3. convention sentence missing from ONE model -> not atomic -> BLOCK
        gen2 = dict(generated); gen2[(bench_r, "mpi")] = gen2[(bench_r, "mpi")].replace(sentence, "")
        res = gate.evaluate(decisions, registry, gen2)
        check("convention missing from one generated model -> BLOCK (atomicity)",
              res["rows"][0]["gate"] == "BLOCK")

        # 4. raw/generated divergence -> BLOCK
        (tmp / bench_r / "omp").write_bytes(b"/* something else */\r\nvoid f() {")
        res = gate.evaluate(decisions, registry, generated)
        check("raw prompt diverging from generated -> BLOCK", res["rows"][0]["gate"] == "BLOCK")
        (tmp / bench_r / "omp").write_bytes(generated[(bench_r, "omp")].replace("\n", "\r\n").encode("utf-8"))

        # 5. disclosure without reporting requirement -> BLOCK
        d = copy.deepcopy(decisions); d["decisions"][1].pop("reporting_requirement")
        res = gate.evaluate(d, registry, generated)
        check("disclosure without reporting_requirement -> BLOCK", res["rows"][1]["gate"] == "BLOCK")
        d = copy.deepcopy(decisions); d["decisions"][1]["reporting_requirement"]["affected_results"] = []
        res = gate.evaluate(d, registry, generated)
        check("disclosure with empty affected_results -> BLOCK", res["rows"][1]["gate"] == "BLOCK")

        # 6. disclosure whose registry status is still the old pending one -> BLOCK
        reg = copy.deepcopy(registry); reg["interlocks"][0]["status"] = "BLOCKED_PENDING_SEMANTIC_DECISION"
        res = gate.evaluate(decisions, reg, generated)
        check("disclosure with stale registry status -> BLOCK", res["rows"][1]["gate"] == "BLOCK")

        # 7. disclosure claiming a prompt change -> BLOCK
        d = copy.deepcopy(decisions); d["decisions"][1]["prompt_changed"] = True
        res = gate.evaluate(d, registry, generated)
        check("disclosure claiming a prompt change -> BLOCK", res["rows"][1]["gate"] == "BLOCK")

        # 8. declared counts disagreeing with the rows -> UNRESOLVED (never green)
        d = copy.deepcopy(decisions); d["disclosure_count"] = 5
        res = gate.evaluate(d, registry, generated)
        check("declared count mismatch -> UNRESOLVED", res["gate"] == "UNRESOLVED")

        # 9. a registry benchmark without any decision -> UNRESOLVED
        reg = copy.deepcopy(registry)
        reg["interlocks"].append({"benchmark": "fake/03_orphan", "status": gate.STATUS_DISCLOSURE,
                                  "prompt_pairs": [{}, {}, {}]})
        reg["_meta"]["interlock_benchmark_count"] = 2; reg["_meta"]["interlock_prompt_pair_count"] = 6
        res = gate.evaluate(decisions, reg, generated)
        check("registry benchmark without a decision -> UNRESOLVED", res["gate"] == "UNRESOLVED")

        # 10. all resolved, nothing accepted -> plain PASS
        d = copy.deepcopy(decisions); d["decisions"] = d["decisions"][:1]
        d["disclosure_count"] = 0
        reg = {"_meta": {"interlock_benchmark_count": 0, "interlock_prompt_pair_count": 0}, "interlocks": []}
        res = gate.evaluate(d, reg, generated)
        check("only resolved decisions -> PASS", res["gate"] == "PASS")
    finally:
        gate.RAW_ROOT = old_raw
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# B. real artifacts
# ---------------------------------------------------------------------------

def group_real():
    print("B. the real semantic decision artifact")
    decisions = json.loads(gate.DECISIONS_PATH.read_text(encoding="utf-8"))
    registry = json.loads(gate.REGISTRY_PATH.read_text(encoding="utf-8"))
    res = gate.evaluate(decisions, registry)
    check("artifact evaluates without problems", not res["problems"], str(res["problems"]))
    check("no unresolved decision remains", res["unresolved"] == 0,
          str([r for r in res["rows"] if r["gate"] == "BLOCK"]))
    check("gate is PASS or PASS_WITH_DISCLOSURE", res["gate"] in ("PASS", "PASS_WITH_DISCLOSURE"), res["gate"])
    check("schema version is recorded", decisions.get("schema_version") == "semantic_decisions.v1")
    check("source_head is a 40-hex commit", len(str(decisions.get("source_head", ""))) == 40)
    check("declared counts equal computed counts",
          decisions.get("resolved_count") == res["resolved"]
          and decisions.get("disclosure_count") == res["accepted_disclosure"]
          and decisions.get("unresolved_count") == res["unresolved"])
    check("benchmark_count equals the number of decisions",
          decisions.get("benchmark_count") == len(decisions["decisions"]))

    expected = {"dense_la/00_dense_la_lu_decomp", "geometry/12_geometry_smallest_triangle",
                "geometry/13_geometry_closest_pair_2d", "geometry/14_geometry_closest_pair_1d",
                "histogram/22_histogram_count_quadrants", "scan/34_scan_largest_contiguous_subarray_sum",
                "search/37_search_find_the_closest_number_to_pi"}
    check("all seven former interlocks carry a decision",
          {d["benchmark"] for d in decisions["decisions"]} == expected)

    for d in decisions["decisions"]:
        b = d["benchmark"]
        check("%s: every decision id has a final status" % b,
              d.get("status") in gate.FINAL_STATUSES and d.get("decision_ids"))
        check("%s: parallelism models are serial/omp/mpi" % b,
              list(d.get("parallelism_models") or []) == list(gate.MODELS))
        check("%s: evidence recorded" % b, bool(d.get("evidence")))
        if d["status"] == gate.STATUS_RESOLVED:
            check("%s: resolved decision is written out exactly" % b,
                  bool(d.get("decision")) and bool(d.get("prompt_convention_sentences")))
            check("%s: resolved -> not in registry" % b,
                  b not in {e["benchmark"] for e in registry["interlocks"]})
        else:
            req = d.get("reporting_requirement") or {}
            check("%s: disclosure has benchmark/decision_ids/short_hint/affected_results" % b,
                  all(req.get(k) for k in gate.REPORTING_FIELDS))
            check("%s: disclosure did not change prompt/oracle/domain" % b,
                  not d.get("prompt_changed") and not d.get("oracle_changed")
                  and not d.get("input_domain_changed"))

    # registry: only disclosure / unresolved cases remain, meta counts consistent
    remaining = registry["interlocks"]
    check("registry contains only accepted-disclosure entries",
          all(e.get("status") == gate.STATUS_DISCLOSURE for e in remaining),
          str([e.get("status") for e in remaining]))
    check("registry _meta.interlock_benchmark_count matches",
          registry["_meta"].get("interlock_benchmark_count") == len(remaining))
    check("registry _meta.interlock_prompt_pair_count matches",
          registry["_meta"].get("interlock_prompt_pair_count")
          == sum(len(e.get("prompt_pairs") or []) for e in remaining))
    check("no registry entry still says BLOCKED_PENDING_SEMANTIC_DECISION",
          not any("BLOCKED_PENDING" in str(e.get("status", "")) for e in remaining))
    check("every remaining registry entry carries a machine-readable reporting_requirement",
          all(isinstance(e.get("reporting_requirement"), dict)
              and all(e["reporting_requirement"].get(k) for k in gate.REPORTING_FIELDS)
              for e in remaining))

    # worked examples of resolved benchmarks are untouched: the fixture's
    # example_source lines must still be present verbatim in the prompt
    fixtures = json.loads((REPO_ROOT / "thesis/evaluation/prompt_oracle_fixtures.json").read_text(encoding="utf-8"))
    generated = gate._generated_prompts()
    for d in decisions["decisions"]:
        if d["status"] != gate.STATUS_RESOLVED:
            continue
        name = d["benchmark"].split("/", 1)[1]
        example = fixtures[name]["example_source"]
        ex_lines = [l.strip() for l in example.splitlines() if l.strip().startswith(("input:", "output:"))]
        ok = all(any(l in gate._norm(generated[(d["benchmark"], m)]) for l in ex_lines[:1])
                 for m in gate.MODELS) if ex_lines else True
        check("%s: worked example input line still present in all prompts" % d["benchmark"], ok)


def main():
    group_logic()
    if gate.DECISIONS_PATH.is_file():
        group_real()
    else:
        print("B. skipped: %s does not exist yet" % gate.DECISIONS_PATH)
        FAILURES.append("decision artifact missing")
    if FAILURES:
        print("\nFAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("\nAll semantic-decision test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
