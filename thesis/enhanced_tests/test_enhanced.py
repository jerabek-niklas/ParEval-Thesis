"""Tests for the enhanced-tests spec machinery (pattern: test_evaluation.py).

Run:  python thesis/enhanced_tests/test_enhanced.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests.specs import (  # noqa: E402
    build_benchmark_specs,
    explicit_values_header,
    spec_defines,
    spec_key,
    stage_settings,
    static_base_specs,
    validate_enhanced_settings,
    validate_spec,
)
from thesis.enhanced_tests.generate_test_specs import (  # noqa: E402
    generate_for_benchmark,
)

FAILURES = []


def check(label, condition):
    status = "ok" if condition else "FAIL"
    print("  [%s] %s" % (status, label))
    if not condition:
        FAILURES.append(label)


BENCH = "dense_la/00_dense_la_lu_decomp"   # n x n matrix (single fill site)
ONE_D_BENCH = "reduce/27_reduce_average"   # 1-D, n elements
MULTI_SITE_BENCH = "dense_la/03_dense_la_axpy"  # fills x AND y
KNOWN = {BENCH}


def cfg(**enhanced):
    return {"stages": {"enhanced_tests": enhanced}}


def spec(pattern="random", size=4, source="llm", **extra):
    s = {
        "benchmark": BENCH,
        "size": size,
        "pattern": pattern,
        "pattern_params": extra.pop("pattern_params", {}),
        "source": source,
        "rationale": "t",
    }
    s.update(extra)
    return s


def test_config_overrides():
    print("config: overrides reach settings, static set and target")
    config = cfg(
        static_base_sizes=[0, 3],
        target_cases_per_benchmark=6,
        offered_patterns=["random", "ascending"],
    )
    settings = stage_settings(config)
    check("sizes list", settings["static_base_sizes"] == [0, 3])
    check("target", settings["target_cases_per_benchmark"] == 6)

    static = static_base_specs(BENCH, settings["static_base_sizes"])
    check("static set from config sizes", [s["size"] for s in static] == [0, 3])

    result = build_benchmark_specs(BENCH, [], config)
    check("target respected", len(result) <= 6)
    check("legacy alias honored", stage_settings(cfg(max_cases_per_benchmark=9))[
        "target_cases_per_benchmark"] == 9)


def test_config_validation():
    print("config: hard errors")
    for bad, label in (
        (cfg(offered_patterns=["random", "fibonacci"]), "unknown pattern"),
        (cfg(llm_specs_min=9, llm_specs_max=5), "min > max"),
        (cfg(static_base_sizes=[0, 1, 2, 7], target_cases_per_benchmark=3), "target < static set"),
    ):
        try:
            validate_enhanced_settings(bad)
            check(label + " rejected", False)
        except ValueError:
            check(label + " rejected", True)

    validate_enhanced_settings(cfg())  # defaults must pass
    check("defaults valid", True)


def test_new_pattern_validation():
    print("patterns: k-range, size>=2, explicit_values rules")
    ok, _ = validate_spec(spec("duplicate_at", size=4, pattern_params={"k": 3}), KNOWN)
    check("duplicate_at k=size-1 ok", ok)

    for bad, label in (
        (spec("duplicate_at", size=4, pattern_params={"k": 4}), "k out of range"),
        (spec("spike_at", size=1, pattern_params={"k": 0}), "size < 2"),
        (spec("sorted_except_one", size=4, pattern_params={}), "k missing"),
        (spec("explicit_values", size=3, values=[1.0, 2.0]), "wrong value count"),
        # BENCH is an n x n matrix benchmark: size 9 needs 81 values, which
        # is over the element-count cap (64)
        (spec("explicit_values", size=9, values=[0.0] * 81), "explicit > max element count"),
    ):
        ok, _ = validate_spec(bad, KNOWN)
        check(label + " rejected", not ok)

    # explicit_values counts ELEMENTS, not `size`: the expected number comes
    # from the benchmark's input shape (benchmark_shapes.json). BENCH is an
    # n x n matrix benchmark, so size 3 needs 3*3 = 9 values.
    ok, reason = validate_spec(
        spec("explicit_values", size=3, values=[1.0] * 9), KNOWN
    )
    check("explicit_values matrix case (n*n values)", ok)

    ok, reason = validate_spec(
        spec("explicit_values", size=3, values=[1.0, 2.0, 3.0]), KNOWN
    )
    check("matrix with only n values rejected", not ok and "9 numbers" in reason)

    # 1-D benchmark: size == value count (historical behavior, unchanged)
    one_d = dict(spec("explicit_values", size=3, values=[1.0, 2.0, 3.0]))
    one_d["benchmark"] = ONE_D_BENCH
    ok, _ = validate_spec(one_d, KNOWN | {ONE_D_BENCH})
    check("explicit_values 1-D case (n values)", ok)

    # multi-fill-site benchmark: refused explicitly instead of guessing
    # which values go into which container
    multi = dict(spec("explicit_values", size=3, values=[1.0, 2.0, 3.0]))
    multi["benchmark"] = MULTI_SITE_BENCH
    ok, reason = validate_spec(multi, KNOWN | {MULTI_SITE_BENCH})
    check("explicit_values refused for multi-site benchmark",
          not ok and "not supported" in reason)

    ok, reason = validate_spec(spec("spike_at", size=4, pattern_params={"k": 1}),
                               KNOWN, allowed_patterns=["random"])
    check("not-offered pattern rejected for llm", not ok and "not offered" in reason)


def test_defines_and_header():
    print("defines: PARAM_K define, explicit header, key compatibility")
    d = spec_defines(spec("spike_at", size=5, pattern_params={"k": 2}))
    check("K define present", "ENHANCED_FILL_PARAM_K=2" in d)
    check("pattern id 9", "ENHANCED_FILL_PATTERN=9" in d)

    header = explicit_values_header(spec("explicit_values", size=2, values=[1.5, -2.0]))
    check("header has values", "1.5, -2.0" in header and "ENHANCED_EXPLICIT_COUNT = 2" in header)
    check("no header for other patterns", explicit_values_header(spec("random")) is None)

    old = spec_key(spec("ascending", size=7))
    check("old-pattern keys stay 4-tuples (gate/resume compat)", len(old) == 4)
    check("k extends key", len(spec_key(spec("spike_at", size=4, pattern_params={"k": 1}))) == 5)


def test_refill_rounds():
    print("generation: refill trigger, do-not-repeat, under_target")
    settings = stage_settings(cfg(llm_specs_min=3, llm_specs_max=4))
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            # 1 valid + 1 invalid -> below min -> refill
            return ('[{"size": 2, "pattern": "ascending", "rationale": "a"},'
                    ' {"size": 2, "pattern": "fibonacci", "rationale": "b"}]')
        # refill answers: 2 new + 1 duplicate of the accepted one
        return ('[{"size": 3, "pattern": "descending", "rationale": "c"},'
                ' {"size": 2, "pattern": "ascending", "rationale": "dup"},'
                ' {"size": 4, "pattern": "all_zeros", "rationale": "d"}]')

    accepted, discarded, under = generate_for_benchmark(
        fake_llm, BENCH, "sig", "baseline", settings, KNOWN, "spec_model_x"
    )
    check("refill happened (2 calls)", len(calls) == 2)
    check("refill prompt quotes accepted", "do NOT repeat" in calls[1])
    check("refill prompt quotes reasons", "REJECTED" in calls[1])
    check("3 accepted after refill", len(accepted) == 3)
    check("duplicate discarded", any(d["reason"] == "duplicate spec" for d in discarded))
    check("not under target", not under)
    check("spec_model set by script", all(s["spec_model"] == "spec_model_x" for s in accepted))

    def always_empty(prompt):
        return "[]"

    accepted2, _discarded2, under2 = generate_for_benchmark(
        always_empty, BENCH, "sig", "baseline", settings, KNOWN, "m"
    )
    check("under_target after max refills", under2 and len(accepted2) == 0)


def test_mutation_fillup():
    print("mutation: multi-round fill-up + exhaustion break + parent_source")
    config = cfg(static_base_sizes=[0, 1, 2, 7], target_cases_per_benchmark=30)
    llm = [spec("ascending", size=3, pattern_params={"value_range": [0, 10]})]
    result = build_benchmark_specs(BENCH, llm, config)
    check("multi-round reaches target 30", len(result) == 30)

    mutants = [s for s in result if s["source"] == "mutation"]
    check("mutants exist", len(mutants) > 0)
    check("parent_source recorded", all(s.get("parent_source") in ("static", "llm") for s in mutants))
    check("some mutants from llm seed", any(s.get("parent_source") == "llm" for s in mutants))

    deterministic = build_benchmark_specs(BENCH, llm, config)
    check("deterministic across calls", result == deterministic)

    # exhaustion: single size-0 static seed, no ranges -> tiny space
    tiny = cfg(static_base_sizes=[0], target_cases_per_benchmark=50, max_spec_size=2)
    small = build_benchmark_specs(BENCH, [], tiny)
    check("exhaustion returns fewer than target", 0 < len(small) < 50)

    # explicit_values specs are never mutated
    ev = [spec("explicit_values", size=2, values=[1.0, 2.0])]
    with_ev = build_benchmark_specs(BENCH, ev, cfg(target_cases_per_benchmark=25))
    check(
        "explicit_values not mutated",
        not any(s["source"] == "mutation" and s["pattern"] == "explicit_values" for s in with_ev),
    )


def test_parallel_execution_models():
    print("parallel: config switch, per-model build argv, fixed launch point")
    from types import SimpleNamespace

    from thesis.enhanced_tests.specs import DEFAULT_SETTINGS
    from thesis.evaluation.run_enhanced_tests import compile_argv, launch_command

    # ---- config switch ------------------------------------------------
    check("default is serial (historical behavior)",
          stage_settings(cfg())["execution_models"] == ["serial"])
    check("pilot list honored",
          stage_settings(cfg(execution_models=["serial", "omp", "mpi"]))
          ["execution_models"] == ["serial", "omp", "mpi"])
    check("partial enhanced_launch keeps the other default",
          stage_settings(cfg(enhanced_launch={"omp_threads": 2}))
          ["enhanced_launch"] == {"omp_threads": 2, "mpi_ranks": 4})
    check("defaults object not mutated",
          DEFAULT_SETTINGS["enhanced_launch"] == {"omp_threads": 4, "mpi_ranks": 4})

    for bad, label in (
        (cfg(execution_models=["gpu"]), "unknown execution model"),
        (cfg(execution_models=[]), "empty execution_models"),
        (cfg(enhanced_launch={"omp_threads": 0}), "non-positive threads"),
        (cfg(enhanced_launch={"ranks": 4}), "unknown launch key"),
    ):
        try:
            validate_enhanced_settings(bad)
            check(label + " rejected", False)
        except ValueError:
            check(label + " rejected", True)

    # ---- build argv per execution model -------------------------------
    sample = SimpleNamespace(
        source_path=Path("/x/sources/s1/generated-code.hpp"),
        benchmark_dir=Path("/x/bench/dense_la/00_dense_la_lu_decomp"),
    )

    serial = compile_argv(sample, ["ENHANCED_TEST_SIZE_DEFAULT=4"], "/tmp/o")
    check("serial: g++, no -fopenmp, USE_SERIAL",
          serial[0] == "g++" and "-fopenmp" not in serial
          and "-DUSE_SERIAL" in serial)
    check("serial default equals explicit serial (old behavior unchanged)",
          serial == compile_argv(sample, ["ENHANCED_TEST_SIZE_DEFAULT=4"],
                                 "/tmp/o", None, "serial"))
    check("historical -O1 override still last",
          serial.index("-O3") < serial.index("-O1"))

    omp = compile_argv(sample, [], "/tmp/o", None, "omp")
    check("omp: -fopenmp + USE_OMP + omp driver",
          "-fopenmp" in omp and "-DUSE_OMP" in omp
          and any("omp-driver.cc" in part for part in omp))

    mpi = compile_argv(sample, [], "/tmp/o", None, "mpi")
    check("mpi: mpicxx + USE_MPI + mpi driver",
          mpi[0] == "mpicxx" and "-DUSE_MPI" in mpi
          and any("mpi-driver.cc" in part for part in mpi))

    # ---- one fixed launch point ---------------------------------------
    launch = {"omp_threads": 4, "mpi_ranks": 4}

    check("serial launch byte-identical to the old direct call",
          launch_command("/tmp/b", "serial", launch) == (["/tmp/b", "1"], {}))
    check("omp launch: thread count via argv AND env",
          launch_command("/tmp/b", "omp", launch)
          == (["/tmp/b", "4"], {"OMP_NUM_THREADS": "4"}))
    check("mpi launch: mpirun -np ranks",
          launch_command("/tmp/b", "mpi", launch)
          == (["mpirun", "-np", "4", "/tmp/b", "1"], {}))
    check("configured ranks respected",
          launch_command("/tmp/b", "mpi", {"omp_threads": 4, "mpi_ranks": 2})[0][2]
          == "2")


def main():
    tests = [
        test_config_overrides,
        test_config_validation,
        test_new_pattern_validation,
        test_defines_and_header,
        test_refill_rounds,
        test_mutation_fillup,
        test_parallel_execution_models,
    ]

    for test in tests:
        test()
        print()

    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), FAILURES))
        sys.exit(1)

    print("All %d enhanced-tests test groups passed." % len(tests))


if __name__ == "__main__":
    main()
