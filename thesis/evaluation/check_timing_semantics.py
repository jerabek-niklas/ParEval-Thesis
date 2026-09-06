"""Timing semantics validator (pilot_002 pre-run wave, block D).

Checks every timing field of one run against the timing contract
(timing_semantics.py) - READ-ONLY:

  VIOLATIONS (exit 1)
    negative / NaN / infinite durations
    direct generation record without a numeric duration
    batch generation record with a non-null duration_seconds
    timed-out row whose observed elapsed is below the configured limit
      (minus a 2 ms rounding epsilon)
    non-numeric build or run duration where the record claims a run
  ANOMALIES (reported, exit 0)
    non-timeout row with elapsed > limit + 2 s (wall-clock suspension or
    clock step, e.g. pilot_001 claude_opus_5 compile_seconds 70714.574)
    generation records without timing_mode (legacy)

Configured limits come from the run MANIFEST (source of truth); a run
without a manifest falls back to the live config and says so
(LEGACY_FALLBACK_LIVE_CONFIG).

Per model the generation timing class is derived (DIRECT_LATENCY_AVAILABLE
/ BATCH_QUEUE_ONLY / MIXED_DIRECT_AND_BATCH / TIMING_PROVENANCE_INSUFFICIENT)
and the correctness class (TEST_RUNTIME_AVAILABLE / INSUFFICIENT).

    python thesis/evaluation/check_timing_semantics.py --config thesis/config/config.yaml \
        --run-id pilot_001 [--model-id X] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import timing_semantics as ts  # noqa: E402
from thesis.evaluation.run_manifest import load_manifest  # noqa: E402


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def configured_limits(config: Dict[str, Any], run_id: str,
                      run_timeout_override: "Optional[float]" = None
                      ) -> "OrderedDict[str, Any]":
    manifest = load_manifest(config, run_id)
    if manifest and manifest.get("resolved_config"):
        stages = (manifest["resolved_config"].get("stages") or {})
        source = "MANIFEST"
    else:
        stages = (config.get("stages") or {})
        source = "LEGACY_FALLBACK_LIVE_CONFIG"
    correctness = (stages.get("correctness_tests") or {})
    run_timeout = correctness.get("run_timeout_seconds")
    if run_timeout_override is not None:
        run_timeout = run_timeout_override
    return OrderedDict([
        ("source", source),
        ("correctness_run_timeout_seconds", run_timeout),
        # run_correctness.py accepts --run-timeout and persists it nowhere, so a run
        # that used one must declare it; otherwise its timeout rows look inconsistent
        ("correctness_run_timeout_source",
         "DECLARED_CLI_OVERRIDE" if run_timeout_override is not None else source),
        ("enhanced_run_timeout_seconds",
         (stages.get("enhanced_tests") or {}).get("run_timeout_seconds")),
        # the build limit is configurable (stages.correctness_tests.build_timeout_seconds);
        # only its absence falls back to the code default
        ("build_timeout_seconds",
         correctness.get("build_timeout_seconds", ts.BUILD_TIMEOUT_DEFAULT_SECONDS)),
        ("build_timeout_source",
         "MANIFEST" if correctness.get("build_timeout_seconds") is not None
         else "CODE_DEFAULT"),
    ])


class Checker:
    def __init__(self, limits: Dict[str, Any]) -> None:
        self.limits = limits
        self.violations: List[Dict[str, Any]] = []
        self.anomalies: List[Dict[str, Any]] = []

    def violation(self, where: str, sample_id: Any, what: str, value: Any = None) -> None:
        self.violations.append(OrderedDict([("where", where), ("sample_id", sample_id),
                                            ("what", what), ("value", value)]))

    def anomaly(self, where: str, sample_id: Any, what: str, value: Any = None) -> None:
        self.anomalies.append(OrderedDict([("where", where), ("sample_id", sample_id),
                                           ("what", what), ("value", value)]))

    def duration(self, where: str, sample_id: Any, value: Any, required: bool,
                 timed_out: bool, limit: Optional[float]) -> None:
        if value is None:
            if required:
                self.violation(where, sample_id, "missing duration on a row that ran")
            return
        if not _finite(value):
            self.violation(where, sample_id, "non-finite or non-numeric duration", value)
            return
        if value < 0:
            self.violation(where, sample_id, "negative duration", value)
            return
        if limit is None:
            return
        if timed_out and value < limit - ts.TIMEOUT_EPSILON_SECONDS:
            self.violation(where, sample_id,
                           "timed_out row below the configured limit (if the run used a "
                           "--run-timeout override, declare it with --run-timeout-seconds; "
                           "the producer does not persist it)",
                           {"elapsed": value, "limit": limit})
        if not timed_out and value > limit + ts.WALL_CLOCK_ANOMALY_SLACK_SECONDS:
            self.anomaly(where, sample_id,
                         "elapsed exceeds limit + slack without a timeout flag "
                         "(wall-clock suspension / clock step suspected)",
                         {"elapsed": value, "limit": limit})


def check_generation(checker: Checker, path: Path) -> "OrderedDict[str, Any]":
    direct = batch = unknown = 0
    direct_missing = 0
    clocks: Dict[str, int] = {}
    for record in _iter_jsonl(path):
        status = record.get("status") or {}
        mode = status.get("timing_mode")
        duration = status.get("duration_seconds")
        sample_id = record.get("sample_id")
        clock = status.get("timing_clock") or "legacy_time"
        clocks[clock] = clocks.get(clock, 0) + 1
        if mode == "direct":
            direct += 1
            if duration is None or not _finite(duration):
                direct_missing += 1
                checker.violation("generation.direct", sample_id,
                                  "direct record without a numeric duration", duration)
            elif duration < 0:
                checker.violation("generation.direct", sample_id, "negative duration", duration)
        elif mode == "batch":
            batch += 1
            if duration is not None:
                checker.violation("generation.batch", sample_id,
                                  "batch record with a non-null duration_seconds "
                                  "(queue time masquerading as latency)", duration)
            span = status.get("batch_wall_clock_seconds")
            if span is not None and (not _finite(span) or span < 0):
                checker.violation("generation.batch", sample_id, "invalid batch_wall_clock_seconds", span)
            if not status.get("batch_submitted_at_utc") or not status.get("batch_completed_at_utc"):
                checker.anomaly("generation.batch", sample_id, "batch record without both job stamps")
        else:
            unknown += 1
            checker.anomaly("generation", sample_id, "record without timing_mode (legacy)")
    if direct and not batch and not unknown and not direct_missing:
        klass = ts.DIRECT_LATENCY_AVAILABLE
    elif batch and not direct and not unknown:
        klass = ts.BATCH_QUEUE_ONLY
    elif direct and batch and not unknown:
        klass = ts.MIXED_DIRECT_AND_BATCH
    elif direct + batch + unknown == 0:
        klass = "NO_RECORDS"
    else:
        klass = ts.TIMING_PROVENANCE_INSUFFICIENT
    return OrderedDict([("direct", direct), ("batch", batch), ("unknown_mode", unknown),
                        ("direct_missing_duration", direct_missing),
                        ("clocks", clocks), ("class", klass)])


def check_correctness(checker: Checker, path: Path, limits: Dict[str, Any]) -> "OrderedDict[str, Any]":
    records = compiles = runs = timeouts = 0
    complete = True
    for record in _iter_jsonl(path):
        records += 1
        sample_id = record.get("sample_id")
        compile_info = record.get("compile") or {}
        if compile_info:
            compiles += 1
            checker.duration("correctness.compile", sample_id, compile_info.get("duration_seconds"),
                             True, bool(compile_info.get("timed_out")), limits["build_timeout_seconds"])
        else:
            complete = False
        for run in record.get("runs") or []:
            runs += 1
            if run.get("timed_out"):
                timeouts += 1
            checker.duration("correctness.run", sample_id, run.get("duration_seconds"), True,
                             bool(run.get("timed_out")), limits["correctness_run_timeout_seconds"])
    # the class asserts that BUILD AND RUN timings exist: a model whose samples all
    # failed to build has compile timings but no run timings and must not claim it
    klass = ts.TEST_RUNTIME_AVAILABLE if records and complete and runs else (
        "NO_RECORDS" if not records else ts.TIMING_PROVENANCE_INSUFFICIENT)
    return OrderedDict([("records", records), ("compiles", compiles), ("runs", runs),
                        ("run_timeouts", timeouts), ("class", klass)])


def check_enhanced(checker: Checker, run_path: Path, build_path: Path,
                   limits: Dict[str, Any]) -> "OrderedDict[str, Any]":
    records = with_duration = without_duration = timeouts = builds = 0
    for record in _iter_jsonl(run_path):
        records += 1
        sample_id = record.get("sample_id")
        duration = record.get("duration_seconds")
        timed_out = record.get("status") == "timeout"
        if timed_out:
            timeouts += 1
        if duration is None:
            without_duration += 1  # verdict-only specs carry no run
            continue
        with_duration += 1
        checker.duration("enhanced.run", sample_id, duration, False, timed_out,
                         limits["enhanced_run_timeout_seconds"])
    for record in _iter_jsonl(build_path):
        builds += 1
        sample_id = record.get("sample_id")
        checker.duration("enhanced.build", sample_id, record.get("compile_seconds"), True,
                         record.get("build_status") == "timeout", limits["build_timeout_seconds"])
    return OrderedDict([("records", records), ("with_duration", with_duration),
                        ("without_duration", without_duration), ("run_timeouts", timeouts),
                        ("build_groups", builds)])


def check_tools(checker: Checker, path: Path, where: str) -> "OrderedDict[str, Any]":
    records = tools = 0
    for record in _iter_jsonl(path):
        records += 1
        sample_id = record.get("sample_id")
        for name, entry in (record.get("tools") or {}).items():
            tools += 1
            duration = entry.get("duration_seconds")
            state = entry.get("analysis_state")
            timed_out = state == "TIMEOUT" or ("timeout" in str(entry.get("error") or "").lower())
            checker.duration("%s.%s" % (where, name), sample_id, duration,
                             bool(entry.get("ran")), timed_out, None)
    return OrderedDict([("records", records), ("tool_entries", tools)])


def validate_run(config: Dict[str, Any], run_id: str,
                 model_ids: "Optional[List[str]]" = None,
                 run_timeout_override: "Optional[float]" = None) -> "OrderedDict[str, Any]":
    limits = configured_limits(config, run_id, run_timeout_override)
    checker = Checker(limits)
    intermediate = Path(config["outputs"]["intermediate_dir"]) / run_id
    raw = Path(config["outputs"]["raw_dir"]) / run_id
    models: "OrderedDict[str, Any]" = OrderedDict()
    # explicit --model-id always wins; only the DISCOVERY needs the raw dir
    if model_ids:
        candidates = list(model_ids)
    elif raw.is_dir():
        candidates = sorted(p.name for p in raw.iterdir() if p.is_dir())
    else:
        candidates = []
    if not candidates:
        checker.violation("run", run_id,
                          "no model evidence found for this run (missing run id, missing raw "
                          "directory or empty run) - a timing validation that inspected "
                          "nothing proves nothing",
                          {"raw_dir": str(raw)})
    for model_id in candidates:
        before_v, before_a = len(checker.violations), len(checker.anomalies)
        entry = OrderedDict()
        entry["generation"] = check_generation(checker, raw / model_id / "generations.jsonl")
        entry["correctness"] = check_correctness(checker, intermediate / model_id / "correctness.jsonl", limits)
        entry["enhanced"] = check_enhanced(checker, intermediate / model_id / "enhanced_tests.jsonl",
                                           intermediate / model_id / "enhanced_build_groups.jsonl", limits)
        entry["static"] = check_tools(checker, intermediate / model_id / "static_analysis.jsonl", "static")
        entry["dynamic"] = check_tools(checker, intermediate / model_id / "dynamic_analysis.jsonl", "dynamic")
        entry["violations"] = len(checker.violations) - before_v
        entry["anomalies"] = len(checker.anomalies) - before_a
        models[model_id] = entry
    gen_classes = [m["generation"]["class"] for m in models.values()]
    ranking = "AVAILABLE" if gen_classes and all(c == ts.DIRECT_LATENCY_AVAILABLE for c in gen_classes) \
        else "NOT_AVAILABLE"
    return OrderedDict([
        ("schema_version", "timing_validation.v1"),
        ("contract_version", ts.TIMING_CONTRACT_VERSION),
        ("timing_contract_sha256", ts.timing_contract_sha256()),
        ("run_id", run_id),
        ("limits", limits),
        ("models", models),
        ("cross_model_latency_ranking", ranking),
        ("violations", checker.violations),
        ("anomalies", checker.anomalies),
        ("status", "PASS" if not checker.violations else "FAIL"),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-id", action="append", default=None)
    parser.add_argument("--run-timeout-seconds", type=float, default=None,
                        help="the EFFECTIVE correctness run timeout of this run when it "
                             "was started with --run-timeout (the producer persists no "
                             "such override)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    config = load_config(Path(args.config).resolve())
    report = validate_run(config, args.run_id, args.model_id, args.run_timeout_seconds)
    print("TIMING_VALIDATION run=%s status=%s limits_source=%s violations=%d anomalies=%d"
          % (args.run_id, report["status"], report["limits"]["source"],
             len(report["violations"]), len(report["anomalies"])))
    print("CROSS_MODEL_LATENCY_RANKING = %s" % report["cross_model_latency_ranking"])
    for model_id, m in report["models"].items():
        print("  %-20s gen=%s (direct %d / batch %d / unknown %d) correctness=%s runs=%d enhanced=%d/%d builds=%d viol=%d anom=%d"
              % (model_id, m["generation"]["class"], m["generation"]["direct"], m["generation"]["batch"],
                 m["generation"]["unknown_mode"], m["correctness"]["class"], m["correctness"]["runs"],
                 m["enhanced"]["with_duration"], m["enhanced"]["records"], m["enhanced"]["build_groups"],
                 m["violations"], m["anomalies"]))
    for a in report["anomalies"][:20]:
        print("  ANOMALY %s %s: %s %s" % (a["where"], a["sample_id"], a["what"], a["value"]))
    for v in report["violations"][:20]:
        print("  VIOLATION %s %s: %s %s" % (v["where"], v["sample_id"], v["what"], v["value"]))
    if args.out:
        atomic_io.atomic_write_json(Path(args.out), report)
        print("written:", args.out)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
