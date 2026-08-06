"""Tests for the phase-2 backfill runner (pattern: test_orchestrator.py).

Run:  python thesis/repair/test_backfill.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402
from thesis.repair import run_backfill  # noqa: E402
from thesis.repair.run_backfill import (  # noqa: E402
    check_toolchain,
    discover_runs,
    external_pending,
    loops_terminated,
    plan_run,
)

FAILURES = []


def check(label, condition):
    status = "ok" if condition else "FAIL"
    print("  [%s] %s" % (status, label))
    if not condition:
        FAILURES.append(label)


# A real, enhanced-parameterizable benchmark (all 60 drivers carry the
# ENHANCED_TEST_SIZE_DEFAULT macro after the size patch).
REAL_BENCHMARK = "drivers/cpp/benchmarks/dense_la/00_dense_la_lu_decomp"

MODEL = "m1"
S_SERIAL = "m1__dense_la__00_dense_la_lu_decomp__serial__sample_0"
S_MPI = "m1__sparse_la__96_spmv__mpi__sample_0"


def base_config(tmp):
    return {
        "outputs": {
            "raw_dir": (Path(tmp) / "raw").as_posix(),
            "intermediate_dir": (Path(tmp) / "intermediate").as_posix(),
        },
        "models": [{"id": MODEL, "provider": "openai_compatible",
                    "model_name": "fake", "enabled": True}],
        "stages": {
            "static_analysis": {
                "tools": {
                    "compiler": {"enabled": True},
                    "clang_tidy": {"enabled": True},
                    # off here so the fixture's static records stay a minimal
                    # two-tool set; gcc_analyzer is enabled in the real config
                    "gcc_analyzer": {"enabled": False},
                    "cppcheck": {"enabled": False},
                    "infer": {"enabled": False},
                    "parcoach": {"enabled": True, "execution_models": ["mpi"],
                                 "low_precision_warning": True},
                    "llov": {"enabled": False},
                }
            },
            "dynamic_analysis": {
                "tools": {
                    "asan_ubsan": {"enabled": True},
                    "tsan": {"enabled": False},
                    "memcheck": {"enabled": False},
                    "must": {"enabled": False},
                }
            },
            "correctness_tests": {},
            "enhanced_tests": {},
            "repair": {
                "max_iterations": 3,
                "variants": ["static_feedback", "test_feedback"],
                "external_tools_mode": "manual",
            },
        },
    }


def write_assembly(config, run_id, samples):
    intermediate = Path(config["outputs"]["intermediate_dir"])
    path = intermediate / run_id / MODEL / "assembly.jsonl"
    if path.exists():
        path.unlink()

    for sample_id in samples:
        # dense_la ids (serial AND omp in these fixtures) sit on the real
        # parameterizable benchmark; the mpi id keeps a non-existent path
        benchmark_dir = (
            REAL_BENCHMARK if "dense_la" in sample_id
            else "drivers/cpp/benchmarks/sparse_la/96_spmv"
        )
        common.append_jsonl(path, {
            "sample_id": sample_id,
            "assembled": True,
            "source_path": "x",
            "drivers": {"benchmark_dir": benchmark_dir},
        })


def write_stage(config, run_id, stage_file, samples, tools=None):
    intermediate = Path(config["outputs"]["intermediate_dir"])
    path = intermediate / run_id / MODEL / stage_file
    if path.exists():
        path.unlink()

    for sample_id in samples:
        record = {"sample_id": sample_id}
        if tools is not None:
            record["tools"] = {
                t: {"tool": t, "ran": True, "findings": [],
                    "num_findings": 0, "num_blocking": 0}
                for t in tools
            }
        common.append_jsonl(path, record)


def write_state(config, variant, statuses):
    """statuses: {sample_id: status} — one state record each."""
    intermediate = Path(config["outputs"]["intermediate_dir"])
    path = intermediate / "base_run" / MODEL / "repair" / variant / "state.jsonl"
    if path.exists():
        path.unlink()

    for sample_id, status in statuses.items():
        common.append_jsonl(path, {
            "sample_id": sample_id, "variant": variant, "iteration": 1,
            "status": status, "stop_reason": "x",
        })


class StubExecutor:
    def __init__(self):
        self.calls = []

    def run_static(self, run_id, model_id):
        self.calls.append(("static", run_id))

    def run_correctness(self, run_id, model_id):
        self.calls.append(("correctness", run_id))

    def run_dynamic(self, run_id, model_id):
        self.calls.append(("dynamic", run_id))

    def run_enhanced(self, run_id, model_id):
        self.calls.append(("enhanced", run_id))


def make_tree(tmp):
    """base_run + static_feedback iter1/iter2 + test_feedback iter1, with
    deliberate gaps:
      base:  static complete, correctness complete, dynamic MISSING,
             enhanced MISSING (serial sample eligible)
      sf/1:  static complete internal, parcoach missing for the mpi sample,
             correctness MISSING, dynamic missing
      sf/2:  everything missing except assembly
      tf/1:  static compiler-only (loop-time minimum) -> internal partial
    """
    config = base_config(tmp)

    write_assembly(config, "base_run", [S_SERIAL, S_MPI])
    write_stage(config, "base_run", "static_analysis.jsonl",
                [S_SERIAL, S_MPI], tools=["compiler", "clang_tidy", "parcoach"])
    write_stage(config, "base_run", "correctness.jsonl", [S_SERIAL, S_MPI])

    write_assembly(config, "base_run__static_feedback__iter1", [S_SERIAL, S_MPI])
    write_stage(config, "base_run__static_feedback__iter1", "static_analysis.jsonl",
                [S_SERIAL, S_MPI], tools=["compiler", "clang_tidy"])

    write_assembly(config, "base_run__static_feedback__iter2", [S_SERIAL])

    write_assembly(config, "base_run__test_feedback__iter1", [S_SERIAL])
    write_stage(config, "base_run__test_feedback__iter1", "static_analysis.jsonl",
                [S_SERIAL], tools=["compiler"])
    write_stage(config, "base_run__test_feedback__iter1", "correctness.jsonl",
                [S_SERIAL])
    write_stage(config, "base_run__test_feedback__iter1", "dynamic_analysis.jsonl",
                [S_SERIAL])

    # decoy directories the discovery must ignore
    intermediate = Path(config["outputs"]["intermediate_dir"])
    (intermediate / "base_run__static_feedback__iterX" / MODEL).mkdir(parents=True)
    (intermediate / "base_run__unknownvariant__iter1" / MODEL).mkdir(parents=True)

    return config


# ---------------------------------------------------------------------------
# Group 1: discovery
# ---------------------------------------------------------------------------


def test_discovery():
    print("discovery over the run-id convention")

    with tempfile.TemporaryDirectory() as tmp:
        config = make_tree(tmp)

        runs = discover_runs(config, "base_run", MODEL)
        got = [(r["variant"], r["iteration"]) for r in runs]
        check("all runs found in order", got == [
            ("shared", 0),
            ("static_feedback", 1), ("static_feedback", 2),
            ("test_feedback", 1),
        ])

        runs = discover_runs(config, "base_run", MODEL,
                             variant_filter="test_feedback")
        got = [(r["variant"], r["iteration"]) for r in runs]
        check("variant filter keeps shared iteration 0",
              got == [("shared", 0), ("test_feedback", 1)])

        check("no runs for unknown model",
              discover_runs(config, "base_run", "nope") == [])


# ---------------------------------------------------------------------------
# Group 2: gap detection (plan)
# ---------------------------------------------------------------------------


def test_plan_gaps():
    print("gap detection per run")

    with tempfile.TemporaryDirectory() as tmp:
        config = make_tree(tmp)
        marker_cache = {}

        def plan_for(variant, iteration, run_id):
            return plan_run(
                config,
                {"variant": variant, "iteration": iteration, "run_id": run_id},
                MODEL, REPO_ROOT, marker_cache,
            )

        base = plan_for("shared", 0, "base_run")
        check("base static ok", base["static"] == "ok")
        check("base correctness ok", base["correctness"] == "ok")
        check("base dynamic missing", base["dynamic"] == "missing")
        check("base enhanced missing (serial eligible)",
              base["enhanced"] == "missing")
        check("base external satisfied (parcoach present)",
              base["external"] == [])

        sf1 = plan_for("static_feedback", 1, "base_run__static_feedback__iter1")
        check("sf1 internal static ok", sf1["static"] == "ok")
        check("sf1 parcoach pending for the mpi sample",
              sf1["external"] == [("parcoach", 1)])
        check("sf1 correctness missing", sf1["correctness"] == "missing")

        sf2 = plan_for("static_feedback", 2, "base_run__static_feedback__iter2")
        check("sf2 everything missing",
              sf2["static"] == "missing" and sf2["correctness"] == "missing"
              and sf2["dynamic"] == "missing" and sf2["enhanced"] == "missing")
        check("sf2 no external pending (serial-only run)",
              sf2["external"] == [])

        tf1 = plan_for("test_feedback", 1, "base_run__test_feedback__iter1")
        check("tf1 compiler-only static detected as incomplete",
              tf1["static"] == "missing")
        check("tf1 correctness+dynamic ok",
              tf1["correctness"] == "ok" and tf1["dynamic"] == "ok")
        check("tf1 enhanced missing", tf1["enhanced"] == "missing")


# ---------------------------------------------------------------------------
# Group 3: held-out gate for enhanced
# ---------------------------------------------------------------------------


def test_enhanced_gate():
    print("enhanced refuses while any configured loop is unfinished")

    with tempfile.TemporaryDirectory() as tmp:
        config = make_tree(tmp)
        executor = StubExecutor()

        # only static_feedback has state; test_feedback never ran
        write_state(config, "static_feedback",
                    {S_SERIAL: "stopped_clean", S_MPI: "stopped_budget"})

        terminated, reasons = loops_terminated(config, "base_run", MODEL)
        check("missing variant state -> not terminated", not terminated)
        check("reason names the variant",
              any("test_feedback" in r for r in reasons))

        run_backfill.backfill_model(
            config, "cfg.yaml", "unit", "base_run", MODEL, executor,
            variant_filter=None, skip_enhanced=False,
        )
        check("no enhanced invocation while blocked",
              all(stage != "enhanced" for stage, _ in executor.calls))
        check("tool stages still ran while blocked",
              ("dynamic", "base_run") in executor.calls)

        # an ACTIVE sample also blocks
        write_state(config, "test_feedback", {S_SERIAL: "active"})
        terminated, reasons = loops_terminated(config, "base_run", MODEL)
        check("active sample -> not terminated", not terminated)

        # all terminal -> enhanced runs for every run with gaps
        write_state(config, "test_feedback", {S_SERIAL: "stopped_tests_pass"})
        terminated, reasons = loops_terminated(config, "base_run", MODEL)
        check("all terminal -> terminated", terminated and reasons == [])

        executor = StubExecutor()
        run_backfill.backfill_model(
            config, "cfg.yaml", "unit", "base_run", MODEL, executor,
            variant_filter=None, skip_enhanced=False,
        )
        enhanced_runs = [run_id for stage, run_id in executor.calls
                         if stage == "enhanced"]
        check("enhanced invoked for gapped runs incl. iteration 0",
              "base_run" in enhanced_runs
              and "base_run__test_feedback__iter1" in enhanced_runs)


def test_enhanced_execution_models():
    print("enhanced applicability follows stages.enhanced_tests.execution_models")

    s_omp = "m1__dense_la__00_dense_la_lu_decomp__omp__sample_0"

    with tempfile.TemporaryDirectory() as tmp:
        config = base_config(tmp)
        write_assembly(config, "base_run", [s_omp])
        run = {"run_id": "base_run", "variant": None, "iteration": 0}

        # default config = [serial]: an omp-only iteration is genuinely
        # not applicable (historical behavior)
        plan = run_backfill.plan_run(
            config, run, MODEL, run_backfill.REPO_ROOT, {}
        )
        check("config [serial]: omp-only iteration not_applicable",
              plan["enhanced"] == "not_applicable")

        # pilot config: the same iteration becomes coverable
        config["stages"]["enhanced_tests"] = {
            "execution_models": ["serial", "omp", "mpi"]
        }
        plan = run_backfill.plan_run(
            config, run, MODEL, run_backfill.REPO_ROOT, {}
        )
        check("config [serial,omp,mpi]: omp-only iteration pending",
              plan["enhanced"] == "missing")

        # resume semantics: an existing SERIAL record stays valid, the omp
        # gap makes the run partial (the runner adds only the missing part)
        write_assembly(config, "base_run", [S_SERIAL, s_omp])
        write_stage(config, "base_run", "enhanced_tests.jsonl", [S_SERIAL])
        plan = run_backfill.plan_run(
            config, run, MODEL, run_backfill.REPO_ROOT, {}
        )
        check("existing serial records stay valid; omp gap -> partial",
              plan["enhanced"] == "partial")

        # ...and the runner is actually invoked once the loops are terminal
        write_state(config, "static_feedback", {S_SERIAL: "stopped_clean",
                                                s_omp: "stopped_budget"})
        write_state(config, "test_feedback", {S_SERIAL: "stopped_tests_pass",
                                              s_omp: "stopped_tests_pass"})
        executor = StubExecutor()
        run_backfill.backfill_model(
            config, "cfg.yaml", "unit", "base_run", MODEL, executor,
            variant_filter=None, skip_enhanced=False,
        )
        check("runner invoked for the omp-covering config",
              ("enhanced", "base_run") in executor.calls)


# ---------------------------------------------------------------------------
# Group 4: external pending file (manual mode)
# ---------------------------------------------------------------------------


def test_external_manual():
    print("manual mode writes backfill_pending.txt")

    with tempfile.TemporaryDirectory() as tmp:
        config = make_tree(tmp)
        write_state(config, "static_feedback", {S_SERIAL: "stopped_clean"})
        write_state(config, "test_feedback", {S_SERIAL: "stopped_tests_pass"})

        executor = StubExecutor()
        run_backfill.backfill_model(
            config, "cfg.yaml", "unit", "base_run", MODEL, executor,
            variant_filter=None, skip_enhanced=True,
        )

        pending_path = run_backfill.pending_file_path(config, "base_run", MODEL)
        check("pending file exists", pending_path.exists())
        content = pending_path.read_text(encoding="utf-8") if pending_path.exists() else ""
        check("command carries the iteration run id",
              "--run-id base_run__static_feedback__iter1" in content)
        check("command names the tool", "--tools parcoach" in content)

        # scope honored: serial-only runs never demand parcoach
        check("no parcoach command for the serial-only iter2 run",
              "--run-id base_run__static_feedback__iter2" not in content)


# ---------------------------------------------------------------------------
# Group 5: toolchain consistency
# ---------------------------------------------------------------------------


def test_toolchain():
    print("toolchain record / match / mismatch / strict")

    with tempfile.TemporaryDirectory() as tmp:
        current = Path(tmp) / "current.txt"
        stored = Path(tmp) / "run" / "toolchain-versions.txt"

        check("unavailable when container file missing",
              check_toolchain(current, stored, strict=False) == "unavailable")

        current.write_text("gcc 13.3.0\n", encoding="utf-8")
        check("first contact records",
              check_toolchain(current, stored, strict=False) == "recorded")
        check("record persisted", stored.read_text(encoding="utf-8") == "gcc 13.3.0\n")

        check("identical manifests match",
              check_toolchain(current, stored, strict=False) == "match")

        current.write_text("gcc 14.1.0\n", encoding="utf-8")
        check("difference warns (no abort)",
              check_toolchain(current, stored, strict=False) == "mismatch")

        try:
            check_toolchain(current, stored, strict=True)
            check("--strict-toolchain raises", False)
        except RuntimeError as error:
            check("--strict-toolchain raises", True)
            check("error shows both manifests",
                  "gcc 13.3.0" in str(error) and "gcc 14.1.0" in str(error))


# ---------------------------------------------------------------------------
# Group 6: execution sequencing (stub executor)
# ---------------------------------------------------------------------------


def test_execution_sequencing():
    print("backfill invokes exactly the gapped stages")

    with tempfile.TemporaryDirectory() as tmp:
        config = make_tree(tmp)
        write_state(config, "static_feedback", {S_SERIAL: "stopped_clean"})
        write_state(config, "test_feedback", {S_SERIAL: "stopped_tests_pass"})

        executor = StubExecutor()
        run_backfill.backfill_model(
            config, "cfg.yaml", "unit", "base_run", MODEL, executor,
            variant_filter=None, skip_enhanced=True,
        )

        calls = set(executor.calls)
        check("base: dynamic runs, static/correctness skipped",
              ("dynamic", "base_run") in calls
              and ("static", "base_run") not in calls
              and ("correctness", "base_run") not in calls)
        check("sf1: correctness+dynamic run, internal static skipped",
              ("correctness", "base_run__static_feedback__iter1") in calls
              and ("static", "base_run__static_feedback__iter1") not in calls)
        check("sf2: all three stages run",
              {("static", "base_run__static_feedback__iter2"),
               ("correctness", "base_run__static_feedback__iter2"),
               ("dynamic", "base_run__static_feedback__iter2")} <= calls)
        check("tf1: static completed, correctness/dynamic skipped",
              ("static", "base_run__test_feedback__iter1") in calls
              and ("correctness", "base_run__test_feedback__iter1") not in calls)
        check("no enhanced with --skip-enhanced",
              all(stage != "enhanced" for stage, _ in executor.calls))


# ---------------------------------------------------------------------------


def main():
    tests = [
        test_discovery,
        test_plan_gaps,
        test_enhanced_gate,
        test_enhanced_execution_models,
        test_external_manual,
        test_toolchain,
        test_execution_sequencing,
    ]

    for test in tests:
        test()
        print()

    if FAILURES:
        print("FAILED (%d):" % len(FAILURES))
        for label in FAILURES:
            print("  - " + label)
        sys.exit(1)

    print("All %d backfill test groups passed." % len(tests))


if __name__ == "__main__":
    main()
