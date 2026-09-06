"""Timing contract + validator tests (pilot_002 pre-run wave, block D).

Run:  python thesis/evaluation/test_timing_semantics.py
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import check_timing_semantics as validator  # noqa: E402
from thesis.evaluation import timing_semantics as ts  # noqa: E402
from thesis.generation import common  # noqa: E402

FAILURES = []


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


MODEL = "m1"
RUN = "r1"
S1 = "m1__reduce__25_reduce_xor__serial__sample_0"
S2 = "m1__reduce__25_reduce_xor__omp__sample_0"


def world(tmp):
    return {"outputs": {"raw_dir": (Path(tmp) / "raw").as_posix(),
                        "intermediate_dir": (Path(tmp) / "inter").as_posix()},
            "stages": {"correctness_tests": {"run_timeout_seconds": 120},
                       "enhanced_tests": {"run_timeout_seconds": 60}}}


def gen_record(sample_id, mode="direct", duration=1.5, **extra):
    status = {"success": True, "truncated": False, "timing_mode": mode,
              "duration_seconds": duration}
    status.update(extra)
    return {"sample_id": sample_id, "status": status,
            "prompt": {"problem_type": "reduce", "name": "25_reduce_xor",
                       "parallelism_model": "serial"},
            "output": {"raw_text": ""}}


def write(config, run, model, name, records, raw=False):
    root = Path(config["outputs"]["raw_dir" if raw else "intermediate_dir"])
    path = root / run / model / name
    if path.exists():
        path.unlink()
    for record in records:
        common.append_jsonl(path, record)
    return path


def main():
    print("== the contract itself ==")
    contract = ts.timing_contract()
    check("contract version and content-addressed sha",
          contract["contract_version"] == "timing_semantics.v1"
          and len(ts.timing_contract_sha256(contract)) == 64)
    import re as _re

    check("sha is stable across rebuilds (no timestamp or hostname inside)",
          ts.timing_contract_sha256() == ts.timing_contract_sha256(ts.timing_contract())
          and not _re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", json.dumps(contract)))
    required = {"field", "producer", "unit", "meaning", "clock_source", "start_boundary",
                "end_boundary", "available_in_direct_mode", "available_in_batch_mode",
                "includes", "suitable_for", "allowed_aggregation", "on_timeout", "consumers"}
    check("every field entry answers every contracted question",
          all(required <= set(entry) for entry in contract["fields"]))
    includes_keys = {"client_retries", "sdk_internal_retries", "provider_queue_wait",
                     "build", "process_startup", "launcher_overhead",
                     "runtime_initialization"}
    check("every field states what it includes",
          all(includes_keys <= set(entry["includes"]) for entry in contract["fields"]))
    statements = contract["global_statements"]
    check("run seconds are declared NOT comparable across execution models",
          statements["RUN_SECONDS_CROSS_EXECUTION_MODEL_COMPARABLE"] is False)
    check("batch queue time is declared NOT model latency",
          statements["BATCH_QUEUE_TIME_IS_MODEL_LATENCY"] is False)
    check("static durations are declared NOT model speed",
          statements["STATIC_DURATION_IS_MODEL_SPEED"] is False)
    produced = {"generation.status.duration_seconds", "correctness.compile.duration_seconds",
                "correctness.runs[].duration_seconds", "enhanced_build_groups.compile_seconds",
                "enhanced_tests.duration_seconds", "static_analysis.tools",
                "dynamic_analysis.tools"}
    covered = " ".join(f["field"] for f in contract["fields"])
    check("EVERY producing field of the pipeline has a contract entry (incl. dynamic tools)",
          all(name.split("[")[0] in covered for name in produced))
    check("mpi run seconds declare launcher overhead, omp runtime init, serial startup",
          statements["MPI_RUN_SECONDS_INCLUDE_LAUNCHER_OVERHEAD"] is True
          and statements["OMP_RUN_SECONDS_INCLUDE_RUNTIME_INITIALIZATION"] is True
          and statements["SERIAL_RUN_SECONDS_INCLUDE_PROCESS_STARTUP"] is True)
    correctness_run = [f for f in contract["fields"] if f["field"].startswith("correctness.runs")][0]
    check("only within-execution-model cross-model comparison is allowed",
          correctness_run["suitable_for"]["cross_model_within_execution_model"] is True
          and correctness_run["suitable_for"]["cross_execution_model"] is False)
    direct = [f for f in contract["fields"] if "timing_mode=direct" in f["field"]][0]
    check("direct latency includes retries and adapter overhead",
          direct["includes"]["client_retries"] and direct["includes"]["sdk_internal_retries"]
          and direct["includes"]["adapter_overhead"]
          and direct["includes"]["provider_queue_wait"] is False)
    batch = [f for f in contract["fields"] if "timing_mode=batch" in f["field"]][0]
    check("batch duration_seconds is contracted as ALWAYS null",
          "null" in batch["meaning"] and batch["available_in_direct_mode"] is False)
    exported = json.loads((Path(__file__).with_name("timing_semantics.json"))
                          .read_text(encoding="utf-8"))
    check("the exported JSON matches the code (single source of truth)",
          exported["timing_contract_sha256"] == ts.timing_contract_sha256())

    print("== the producers ==")
    record = {"status": {}}
    common.apply_direct_timing(record, started_at=0.0, started_perf=None)
    check("legacy direct timing keeps the wall clock and says so",
          record["status"]["timing_clock"] == "time"
          and record["status"]["timing_mode"] == "direct")
    record = {"status": {}}
    import time

    start = time.perf_counter()
    common.apply_direct_timing(record, started_at=time.time(), started_perf=start)
    check("direct timing measures the MONOTONIC clock when the caller passes it",
          record["status"]["timing_clock"] == "perf_counter"
          and 0 <= record["status"]["duration_seconds"] < 5)
    record = {"status": {}}
    common.apply_batch_timing(record, "2026-08-12T12:00:00.000000Z", "2026-08-12T14:30:00.000000Z")
    check("batch timing leaves duration_seconds null and names the queue span separately",
          record["status"]["duration_seconds"] is None
          and record["status"]["batch_wall_clock_seconds"] == 9000.0
          and record["status"]["timing_mode"] == "batch")
    record = {"status": {}}
    common.apply_batch_timing(record, None, None)
    check("a batch job without stamps yields a null span, never 0",
          record["status"]["batch_wall_clock_seconds"] is None)

    print("== the validator ==")
    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl",
              [gen_record(S1), gen_record(S2)], raw=True)
        write(config, RUN, MODEL, "correctness.jsonl", [{
            "sample_id": S1, "compile": {"duration_seconds": 3.0, "timed_out": False},
            "runs": [{"duration_seconds": 0.5, "timed_out": False}]}])
        report = validator.validate_run(config, RUN, [MODEL])
        check("a clean run passes", report["status"] == "PASS"
              and report["models"][MODEL]["generation"]["class"] == ts.DIRECT_LATENCY_AVAILABLE)
        check("limits fall back to the live config when there is no manifest, and say so",
              report["limits"]["source"] == "LEGACY_FALLBACK_LIVE_CONFIG"
              and report["limits"]["correctness_run_timeout_seconds"] == 120)
        check("all-direct models make a latency ranking available",
              report["cross_model_latency_ranking"] == "AVAILABLE")

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl",
              [gen_record(S1, "batch", None,
                          batch_submitted_at_utc="2026-08-12T12:00:00Z",
                          batch_completed_at_utc="2026-08-12T13:00:00Z"),
               gen_record(S2)], raw=True)
        report = validator.validate_run(config, RUN, [MODEL])
        check("a model mixing direct and batch is classified MIXED and blocks the ranking",
              report["models"][MODEL]["generation"]["class"] == ts.MIXED_DIRECT_AND_BATCH
              and report["cross_model_latency_ranking"] == "NOT_AVAILABLE")

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl",
              [gen_record(S1, "batch", 42.0)], raw=True)
        report = validator.validate_run(config, RUN, [MODEL])
        check("a batch record with a duration is a VIOLATION (queue time as latency)",
              report["status"] == "FAIL"
              and any("non-null duration" in v["what"] for v in report["violations"]))

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl", [gen_record(S1, "direct", None)], raw=True)
        report = validator.validate_run(config, RUN, [MODEL])
        check("a direct record without a duration is a VIOLATION",
              report["status"] == "FAIL"
              and report["models"][MODEL]["generation"]["class"] == ts.TIMING_PROVENANCE_INSUFFICIENT)

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl", [gen_record(S1)], raw=True)
        write(config, RUN, MODEL, "correctness.jsonl", [{
            "sample_id": S1, "compile": {"duration_seconds": -1.0, "timed_out": False},
            "runs": [{"duration_seconds": float("nan"), "timed_out": False},
                     {"duration_seconds": 5.0, "timed_out": True}]}])
        report = validator.validate_run(config, RUN, [MODEL])
        whats = [v["what"] for v in report["violations"]]
        check("negative durations are violations", any("negative" in w for w in whats))
        check("NaN durations are violations", any("non-finite" in w for w in whats))
        check("a timed-out row below the configured limit is a violation",
              any("below the configured limit" in w for w in whats))

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl", [gen_record(S1)], raw=True)
        # the real pilot_001 artifact: a wall-clock suspension inside a build
        write(config, RUN, MODEL, "enhanced_build_groups.jsonl",
              [{"sample_id": S1, "compile_seconds": 70714.574, "build_status": "success"}])
        write(config, RUN, MODEL, "enhanced_tests.jsonl",
              [{"sample_id": S1, "duration_seconds": 59.999, "status": "timeout"},
               {"sample_id": S1, "duration_seconds": None, "status": "pass"}])
        report = validator.validate_run(config, RUN, [MODEL])
        check("a wall-clock anomaly is reported as an ANOMALY, not a violation",
              report["status"] == "PASS"
              and any("wall-clock suspension" in a["what"] for a in report["anomalies"]))
        check("the 1 ms rounding epsilon keeps a real 59.999 s timeout legal",
              not any("below the configured limit" in v["what"] for v in report["violations"]))
        check("verdict-only enhanced rows without a duration are legal",
              report["models"][MODEL]["enhanced"]["without_duration"] == 1)

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        report = validator.validate_run(config, "run_that_does_not_exist")
        check("a run with no evidence is a VIOLATION, never a silent PASS",
              report["status"] == "FAIL"
              and any("inspected nothing" in v["what"] for v in report["violations"]))
        write(config, RUN, MODEL, "generations.jsonl", [gen_record(S1)], raw=True)
        report = validator.validate_run(config, RUN, ["explicit_model_without_records"])
        check("an explicitly named model is never silently replaced by discovery",
              list(report["models"]) == ["explicit_model_without_records"])

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        write(config, RUN, MODEL, "generations.jsonl", [gen_record(S1)], raw=True)
        write(config, RUN, MODEL, "correctness.jsonl", [{
            "sample_id": S1, "compile": {"duration_seconds": 3.0, "timed_out": False},
            "runs": []}])
        report = validator.validate_run(config, RUN, [MODEL])
        check("a model that never ran a test is not TEST_RUNTIME_AVAILABLE",
              report["models"][MODEL]["correctness"]["class"] == ts.TIMING_PROVENANCE_INSUFFICIENT)

    with tempfile.TemporaryDirectory() as tmp:
        config = world(tmp)
        config["stages"]["correctness_tests"]["build_timeout_seconds"] = 300
        write(config, RUN, MODEL, "generations.jsonl", [gen_record(S1)], raw=True)
        write(config, RUN, MODEL, "correctness.jsonl", [{
            "sample_id": S1, "compile": {"duration_seconds": 300.05, "timed_out": True},
            "runs": [{"duration_seconds": 60.05, "timed_out": True}]}])
        report = validator.validate_run(config, RUN, [MODEL], run_timeout_override=60)
        check("a configured build timeout is honoured instead of the code default",
              report["limits"]["build_timeout_seconds"] == 300
              and report["limits"]["build_timeout_source"] == "MANIFEST")
        check("a declared --run-timeout override removes the false timeout violation",
              report["status"] == "PASS"
              and report["limits"]["correctness_run_timeout_source"] == "DECLARED_CLI_OVERRIDE")
        undeclared = validator.validate_run(config, RUN, [MODEL])
        check("without the declaration the same row IS reported",
              undeclared["status"] == "FAIL")

    print("== the real pilot_001 evidence (read-only) ==")
    from thesis.config.load_config import load_config

    config = load_config(REPO_ROOT / "thesis" / "config" / "config.yaml")
    report = validator.validate_run(config, "pilot_001")
    check("pilot_001 has no timing violations", report["status"] == "PASS")
    check("pilot_001 limits come from the run MANIFEST", report["limits"]["source"] == "MANIFEST")
    classes = {m: e["generation"]["class"] for m, e in report["models"].items()}
    batch_models = [m for m, c in classes.items() if c == ts.BATCH_QUEUE_ONLY]
    direct_models = [m for m, c in classes.items() if c == ts.DIRECT_LATENCY_AVAILABLE]
    check("pilot_001 splits into 6 batch-only and 5 direct-latency models",
          len(batch_models) == 6 and len(direct_models) == 5)
    check("pilot_001 therefore has NO cross-model latency ranking",
          report["cross_model_latency_ranking"] == "NOT_AVAILABLE")
    check("every pilot_001 model has correctness runtimes",
          all(e["correctness"]["class"] == ts.TEST_RUNTIME_AVAILABLE
              for e in report["models"].values()))
    check("the single known pilot_001 anomaly is surfaced",
          len(report["anomalies"]) == 1
          and report["anomalies"][0]["value"]["elapsed"] > 70000)

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for item in FAILURES:
            print("  -", item)
        sys.exit(1)
    print("All timing semantics tests passed.")


if __name__ == "__main__":
    main()
