"""Reporting contract tests (pilot_002 pre-run wave, block E / GATE 4).

Covers: accepted-disclosure rendering (dense_la/00 BL-01) with aggregate
marking and without any causal claim, manifest-over-live-config precedence,
static coverage-limitation reporting, repair infrastructure statuses,
cross-pilot consumption, and the content-addressed report provenance.

Run:  python thesis/analysis_overview/test_report_contracts.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.analysis_overview import report_contracts as rc  # noqa: E402

FAILURES = []


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


DENSE = "dense_la/00_dense_la_lu_decomp"

# forbidden in a disclosure block: any claim that the convention CAUSED an
# observed result, or that the benchmark is dropped
CAUSAL_PHRASES = ("caused by", "because of the convention", "explains the",
                  "is due to", "therefore fails", "excluded from", "removed from",
                  "we exclude", "dropped from")


def rows_for(benchmark, model="m1", n=1, variants=("static_feedback", "test_feedback")):
    problem_type, name = benchmark.split("/", 1)
    rows = []
    for variant in variants:
        for index in range(n):
            for execution_model in ("serial", "omp", "mpi"):
                rows.append({
                    "sample_id": "%s__%s__%s__%s__sample_%d" % (model, problem_type, name,
                                                                execution_model, index),
                    "model": model, "problem_type": problem_type, "benchmark": name,
                    "execution_model": execution_model, "variant": variant, "iteration": 0,
                    "status": "stopped_clean", "data_complete": True,
                })
    return rows


def main():
    print("== accepted semantic disclosures (GATE 4) ==")
    disclosures = rc.disclosure_decisions()
    check("the accepted disclosure is read from the decision artifact",
          len(disclosures) == 1 and disclosures[0]["benchmark"] == DENSE
          and disclosures[0]["decision_ids"] == ["BL-01"]
          and disclosures[0]["status"].startswith("ACCEPTED_DISCLOSURE"))

    rows = rows_for(DENSE)
    text = "\n".join(rc.disclosure_section(rows, disclosures))
    check("the benchmark and its decision id are rendered",
          DENSE in text and "BL-01" in text)
    check("a cautious methodological limitation is rendered",
          "may be sensitive to the accepted LU tolerance/rounding convention" in text)
    check("the affected results from the artifact are rendered",
          "correctness-stage verdicts" in text and "aggregates" in text)
    check("the artifact's not-affected list is rendered",
          "enhanced_tests stage" in text)
    # the closing sentence NEGATES a causal claim ("does not claim ... was
    # caused by"); scan everything except that explicit disclaimer
    body = text.lower().split("this disclosure states a limitation only")[0]
    check("NO causal claim is made",
          not any(phrase in body for phrase in CAUSAL_PHRASES))
    check("the limitation is stated explicitly as a limitation only",
          "states a limitation only" in text and "does not claim" in text)
    check("the benchmark is NOT excluded from any aggregate",
          "does not remove the benchmark from any aggregate" in text)
    check("prompt/oracle unchanged is carried over from the decision",
          "prompt changed: no" in text and "oracle changed: no" in text)
    check("the sample count is counted per unique sample, not per row",
          "base population): 3 (mpi 1, omp 1, serial 1)" in text)

    marker = rc.disclosure_marker(rows, disclosures)
    check("aggregates containing the benchmark are marked",
          marker is not None and DENSE in marker and "NOT excluded" in marker)
    other = rows_for("reduce/25_reduce_xor")
    check("a run WITHOUT the benchmark is not marked",
          rc.disclosure_marker(other, disclosures) is None)

    parts = ["# report", "", "## Pass-rate trajectories", "| a |", "",
             "## Static analysis coverage (tool states)", "| t |", "",
             "## Accepted semantic disclosures", "text", "", "## Report provenance", "x"]
    marked = rc.mark_aggregate_sections(parts, marker)
    check("the marker is inserted under aggregate headers only",
          marked[marked.index("## Pass-rate trajectories") + 2] == marker
          and marker not in marked[marked.index("## Accepted semantic disclosures"):
                                   marked.index("## Accepted semantic disclosures") + 3]
          and marker not in marked[marked.index("## Report provenance"):])
    check("tables that aggregate over the benchmark are marked too (static coverage)",
          marked[marked.index("## Static analysis coverage (tool states)") + 2] == marker)

    print("== the decision artifact itself is evidence ==")
    check("a present artifact is reported as PRESENT",
          rc.decisions_artifact_state() == "PRESENT")
    for state, payload in (("MALFORMED", {"decisions": "not a list"}),):
        check("a malformed artifact is classified %s" % state,
              rc.decisions_artifact_state(payload) == state)
    for state in ("MISSING", "UNREADABLE", "MALFORMED"):
        text_unknown = "\n".join(rc.disclosure_section(rows, [], artifact_state=state))
        marker_unknown = rc.disclosure_marker(rows, [], artifact_state=state)
        check("an unreadable artifact (%s) yields UNKNOWN, never 'none registered'" % state,
              "UNKNOWN" in text_unknown and state in text_unknown
              and "No accepted-disclosure decision is registered" not in text_unknown
              and marker_unknown is not None and "UNKNOWN" in marker_unknown)
    present_none = "\n".join(rc.disclosure_section(rows, [], artifact_state="PRESENT"))
    check("a readable artifact with zero disclosures says exactly that",
          "artifact read successfully, 0 accepted disclosures" in present_none)

    with_absent = rc.disclosure_section(other, disclosures)
    check("a registered disclosure whose benchmark is absent is still listed as such",
          any("benchmark not in this run's rows" in line for line in with_absent))

    print("== manifest over live config ==")
    live = {"outputs": {"intermediate_dir": "x"},
            "stages": {"correctness_tests": {"run_timeout_seconds": 90},
                       "enhanced_tests": {"run_timeout_seconds": 30}},
            "models": [{"id": "m1", "enabled": True}, {"id": "m_new", "enabled": True}]}
    manifest = {"resolved_config": {
        "stages": {"correctness_tests": {"run_timeout_seconds": 60},
                   "enhanced_tests": {"run_timeout_seconds": 60}},
        "models": [{"id": "m1", "enabled": True}]}}
    effective, source = rc.effective_config(live, manifest)
    check("manifest timeout 60 beats live 90", source == rc.CONFIG_SOURCE_MANIFEST
          and rc.stage_timeouts(effective)["correctness_run_timeout_seconds"] == 60)
    check("the manifest's model list wins over a model added later",
          [m["id"] for m in rc.effective_models(effective)] == ["m1"])
    check("paths still come from the live config (the manifest pins the method, not the mount)",
          effective["outputs"]["intermediate_dir"] == "x")
    legacy_effective, legacy_source = rc.effective_config(live, None)
    check("no manifest -> explicit LEGACY FALLBACK, live values",
          legacy_source == rc.CONFIG_SOURCE_LEGACY
          and rc.stage_timeouts(legacy_effective)["correctness_run_timeout_seconds"] == 90)

    print("== static coverage and repair statuses ==")
    static_rows = rows_for(DENSE, n=1, variants=("static_feedback",))
    static_rows[0].update({"compiler_analysis_state": "COMPLETED", "compiler_blocking": 0})
    static_rows[1].update({"compiler_analysis_state": "COMPLETED", "compiler_blocking": 3})
    static_rows[2].update({"compiler_analysis_state": "NOT_ANALYZED", "compiler_blocking": None,
                           "low_confidence_count": 2})
    section = "\n".join(rc.static_coverage_section(static_rows, ["compiler"],
                                                   {"m1": {"llov_classes": {"OK": 1}}}))
    check("CLEAN / DEFECT_FOUND / gap states are separated",
          "| compiler | 1 | 1 | 0 | 1 |" in section)
    check("coverage limitations are named as such, not as clean verdicts",
          "coverage limitation" in section.lower()
          and "Base samples with at least one coverage limitation: 1 of 3" in section)
    check("low-confidence findings stay visible and are NOT attributed to one tool",
          "Low-confidence findings over all analysis tools" in section
          and "NOT attributed to a single tool" in section and ": 2 " in section)
    check("LLOV classes are rendered", "LLOV classes (m1): OK=1" in section)

    repair_rows = rows_for(DENSE, n=1, variants=("static_feedback",))
    repair_rows[0]["status"] = "stopped_analysis_incomplete"
    repair_rows[1]["status"] = "stopped_api_exhausted"
    repair_rows[2]["status"] = "stopped_clean"
    repair_section = "\n".join(rc.repair_status_section(repair_rows))
    check("infrastructure statuses are classified as non-model outcomes",
          "stopped_analysis_incomplete | INFRASTRUCTURE STATE" in repair_section.replace("_(", " (")
          .replace("INFRASTRUCTURE_STATE (not a model failure)", "INFRASTRUCTURE STATE")
          or "INFRASTRUCTURE_STATE" in repair_section)
    check("both infrastructure statuses are classified, the model outcome is not",
          rc.repair_status_class("stopped_analysis_incomplete").startswith("INFRASTRUCTURE")
          and rc.repair_status_class("stopped_api_exhausted").startswith("INFRASTRUCTURE")
          and rc.repair_status_class("stopped_clean") == "MODEL_OUTCOME"
          and rc.repair_status_class("stopped_tests_pass") == "MODEL_OUTCOME")

    print("== cross-pilot consumption ==")
    artifact = rc.load_json(rc.CROSS_PILOT_PATH)
    cross = "\n".join(rc.cross_pilot_section(artifact))
    check("the artifact fingerprint and classification are consumed, not re-derived",
          artifact["cross_pilot_fingerprint_sha256"][:12] in cross
          and artifact["classification"] in cross)
    check("comparability is stated per cell and a global improvement claim is refused",
          "per cell" in cross and "no 'pilot_001 improved by X%'" in cross)
    check("statistical caveats and mandatory disclosures are carried over",
          "Statistical caveat:" in cross and "mandatory disclosure:" in cross)
    check("the reuse decision is reported as UNDECIDED and not taken",
          "Reuse status: UNDECIDED" in cross and "NOT made by this report" in cross)
    check("a missing artifact yields UNKNOWN, never a silent claim",
          "UNKNOWN" in "\n".join(rc.cross_pilot_section(None)))

    print("== provenance ==")
    condition = rc.report_condition()
    check("the report condition pins the implementation LF-normalized",
          all(e["lf_normalized_sha256"] for e in condition["implementation"])
          and {e["path"] for e in condition["implementation"]}
          == {"thesis/analysis_overview/build_overview.py",
              "thesis/analysis_overview/report_contracts.py",
              "thesis/evaluation/check_timing_semantics.py"})
    check("the report condition sha is stable and timestamp-free",
          rc.report_condition_sha256() == rc.report_condition_sha256()
          and "T" + "00:" not in json.dumps(condition))

    block = rc.provenance_block({"outputs": {"intermediate_dir": "nowhere"}}, "ghost_run",
                                None, rc.CONFIG_SOURCE_LEGACY, ["m1"])
    unknowns = [k for k, v in block.items() if v == rc.UNKNOWN]
    check("a run without a manifest reports UNKNOWN for every pinned condition",
          {"manifest_sha256", "assembly_condition_sha256", "static_analysis_condition_sha256",
           "repair_condition_sha256", "contract_sha256", "runtime_evidence_sha256"}
          <= set(unknowns))
    check("artifact-derived values are still present without a manifest",
          block["semantic_decisions_sha256_lf_normalized"] != rc.UNKNOWN
          and block["cross_pilot_artifact_sha256"] != rc.UNKNOWN
          and block["report_condition_sha256"] == rc.report_condition_sha256())
    check("a value recomputed from the CURRENT repo is named as such, not as run provenance",
          "evaluation_condition_sha256_recomputed_now" in block
          and "evaluation_condition_sha256" not in block)
    rendered = "\n".join(rc.render_provenance(block))
    check("the provenance block renders UNKNOWN explicitly and flags recomputed values",
          "UNKNOWN" in rendered and "never guessed" in rendered
          and "_recomputed_now" in rendered and "NOT from" in rendered)

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for item in FAILURES:
            print("  -", item)
        sys.exit(1)
    print("All reporting contract tests passed.")


if __name__ == "__main__":
    main()
