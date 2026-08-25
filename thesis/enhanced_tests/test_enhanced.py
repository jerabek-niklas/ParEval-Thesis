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
    # -O1 override removed 2026-08-08: enhanced builds at the BuildConfig
    # -O3 like correctness (O-level invariance proven in
    # thesis/experiments/opt-level-probe.md)
    check("builds at BuildConfig -O3, no -O1 override",
          "-O3" in serial and "-O1" not in serial)

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


def test_runtime_fill_machinery():
    print("runtime fill: env twin of spec_defines, values file, grouping")
    from thesis.enhanced_tests.specs import (
        explicit_values_file_text,
        spec_runtime_env,
    )
    from thesis.evaluation.run_enhanced_tests import (
        group_defines,
        group_specs_by_size,
    )

    env = spec_runtime_env(spec("random", size=4))
    check("pattern id as env value", env == {"ENHANCED_FILL_PATTERN": "0"})

    env = spec_runtime_env(spec("ascending", size=4,
                                pattern_params={"value_range": [-1.0, 1.0]}))
    check("range as %.17g pair",
          env["ENHANCED_FILL_RANGE_LO"] == "-1" and env["ENHANCED_FILL_RANGE_HI"] == "1"
          and env["ENHANCED_FILL_PATTERN"] == "3")
    check("round-trip exact for non-trivial doubles",
          spec_runtime_env(spec("ascending", pattern_params={
              "value_range": [0.1, 2.8866015260109088]}))
          ["ENHANCED_FILL_RANGE_HI"] == "2.8866015260109088")

    env = spec_runtime_env(spec("spike_at", size=5, pattern_params={"k": 2}))
    check("k for k-patterns", env["ENHANCED_FILL_K"] == "2")
    check("no k for others",
          "ENHANCED_FILL_K" not in spec_runtime_env(spec("ascending")))

    try:
        spec_runtime_env(spec("explicit_values", size=2, values=[1.0, 2.0]))
        check("explicit_values without file path raises", False)
    except ValueError:
        check("explicit_values without file path raises", True)
    env = spec_runtime_env(spec("explicit_values", size=2, values=[1.0, 2.0]),
                           values_file="/tmp/v.txt")
    check("values file path in env",
          env["ENHANCED_FILL_VALUES_FILE"] == "/tmp/v.txt"
          and env["ENHANCED_FILL_PATTERN"] == "10")

    text = explicit_values_file_text(
        spec("explicit_values", size=2, values=[1.5, -2.0]))
    check("values file: one %.17g per line", text == "1.5\n-2\n")
    check("empty values mirror the header's {0.0} degenerate case",
          explicit_values_file_text(spec("explicit_values", size=0, values=[]))
          == "0\n")
    check("no file text for other patterns",
          explicit_values_file_text(spec("random")) is None)

    groups = group_specs_by_size([
        spec("random", size=7), spec("ascending", size=2),
        spec("descending", size=7), spec("all_zeros", size=2),
    ])
    check("grouped by size, order preserved",
          list(groups) == [7, 2] and len(groups[7]) == 2
          and [s["pattern"] for s in groups[2]] == ["ascending", "all_zeros"])

    defines = group_defines(7, 3)
    check("group defines: size + report cap + runtime flag, NO pattern",
          defines == ["ENHANCED_TEST_SIZE=7", "MISMATCH_REPORT_MAX=3",
                      "ENHANCED_RUNTIME_FILL"]
          and not any("ENHANCED_FILL_PATTERN" in d for d in defines))


def test_jobs_and_derived_names():
    print("jobs: config defaults/merge/validation, --jobs parsing, file names")
    from thesis.evaluation.run_enhanced_tests import (
        derived_file_names,
        parse_jobs_arg,
        resolve_jobs,
    )

    check("built-in default 1/1/1 (historical serial behavior)",
          stage_settings(cfg())["jobs"] == {"serial": 1, "omp": 1, "mpi": 1})
    check("partial config keeps the other defaults",
          stage_settings(cfg(jobs={"serial": 2}))["jobs"]
          == {"serial": 2, "omp": 1, "mpi": 1})

    for bad, label in (
        (cfg(jobs={"gpt5": 2}), "jobs with LLM-model-like key"),
        (cfg(jobs={"serial": 0}), "jobs zero"),
        (cfg(jobs={"omp": True}), "jobs bool"),
    ):
        try:
            validate_enhanced_settings(bad)
            check(label + " rejected", False)
        except ValueError:
            check(label + " rejected", True)

    check("--jobs 2 hits all EXECUTION models",
          parse_jobs_arg("2") == {"serial": 2, "omp": 2, "mpi": 2})
    check("--jobs per-model list",
          parse_jobs_arg("serial=2,omp=1,mpi=1")
          == {"serial": 2, "omp": 1, "mpi": 1})
    check("--jobs partial list", parse_jobs_arg("serial=3") == {"serial": 3})

    for bad_text, label in (
        ("gpu=2", "unknown execution model"),
        ("0", "zero"),
        ("serial=0", "per-model zero"),
        ("abc", "non-integer"),
        ("serial=x", "non-integer value"),
    ):
        try:
            parse_jobs_arg(bad_text)
            check("--jobs %s rejected" % label, False)
        except ValueError:
            check("--jobs %s rejected" % label, True)

    settings = stage_settings(cfg(jobs={"serial": 2}))
    check("CLI overrides config which overrides default",
          resolve_jobs(settings, {"omp": 4})
          == {"serial": 2, "omp": 4, "mpi": 1})
    check("no CLI: config resolved as-is",
          resolve_jobs(settings, None) == {"serial": 2, "omp": 1, "mpi": 1})

    check("default names stay the documented ones",
          derived_file_names("enhanced_tests.jsonl")
          == ("enhanced_build_groups.jsonl", "enhanced_tests_summary.json"))
    check("probe names derive from the output name (reference untouched)",
          derived_file_names("enhanced_tests_runtime_fill_probe.jsonl")
          == ("enhanced_tests_runtime_fill_probe_build_groups.jsonl",
              "enhanced_tests_runtime_fill_probe_summary.json"))

    # 'enhanced_tests' (extension-less) would derive the REFERENCE summary
    # name and clobber it — hard-rejected (review finding 2026-08-08)
    try:
        derived_file_names("enhanced_tests")
        check("extension-less output name rejected", False)
    except ValueError:
        check("extension-less output name rejected", True)

    # stale operator ENHANCED_FILL_* exports must never leak into spec
    # processes (both-range-vars-present is a VALID header config -> no
    # abort would fire; review finding 2026-08-08)
    import os
    from thesis.evaluation.run_enhanced_tests import sanitized_child_env
    os.environ["ENHANCED_FILL_RANGE_LO"] = "0"
    os.environ["ENHANCED_FILL_RANGE_HI"] = "1"
    try:
        # contract F2.2: the harness token is now a per-child-launch argument
        env = sanitized_child_env({"OMP_NUM_THREADS": "4"},
                                  {"ENHANCED_FILL_PATTERN": "3"},
                                  "0123456789abcdef0123456789abcdef")
        check("inherited ENHANCED_FILL_* stripped",
              "ENHANCED_FILL_RANGE_LO" not in env
              and "ENHANCED_FILL_RANGE_HI" not in env)
        check("launch env and the spec's own fill env survive",
              env.get("OMP_NUM_THREADS") == "4"
              and env.get("ENHANCED_FILL_PATTERN") == "3")
        check("the caller's harness token is placed in the child env",
              env.get("PAREVAL_BI_NONCE")
              == "0123456789abcdef0123456789abcdef")
    finally:
        del os.environ["ENHANCED_FILL_RANGE_LO"]
        del os.environ["ENHANCED_FILL_RANGE_HI"]


def test_preprocessor_guarantee():
    print("preprocessor: header inert without ENHANCED_* defines (g++ -E)")
    import shutil
    import subprocess
    import tempfile

    if shutil.which("g++") is None:
        print("  [skip] g++ not available on this host — run the suite in "
              "the pareval-thesis container for the binding proof")
        return

    drivers = REPO_ROOT / "drivers" / "cpp"

    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.cc"
        probe.write_text(
            '#include "enhanced-fill.hpp"\n'
            "PROBE_MARKER ENHANCED_FILL(arr, lo, hi);\n",
            encoding="utf-8",
        )

        def preprocess(*defines):
            return subprocess.run(
                ["g++", "-std=c++17", "-E", "-P", "-I", str(drivers),
                 *defines, str(probe)],
                capture_output=True, text=True, timeout=60,
            )

        plain = preprocess()
        expansion = [l for l in plain.stdout.splitlines() if "PROBE_MARKER" in l]
        check("no defines: ENHANCED_FILL is exactly fillRand",
              plain.returncode == 0 and len(expansion) == 1
              and "fillRand((arr), (lo), (hi))" in expansion[0])
        check("no defines: zero runtime machinery in the TU",
              "enhancedRuntimeFill" not in plain.stdout
              and "EnhancedRuntimeFillConfig" not in plain.stdout)

        runtime = preprocess("-DENHANCED_RUNTIME_FILL")
        check("runtime define: ENHANCED_FILL dispatches to the runtime fill",
              runtime.returncode == 0
              and any("enhancedRuntimeFill((arr), (lo), (hi))" in l
                      for l in runtime.stdout.splitlines()
                      if "PROBE_MARKER" in l))

        define = preprocess("-DENHANCED_FILL_PATTERN=3")
        check("pattern define path unchanged",
              define.returncode == 0
              and any("enhancedFillPattern" in l
                      for l in define.stdout.splitlines()
                      if "PROBE_MARKER" in l))

        both = preprocess("-DENHANCED_RUNTIME_FILL", "-DENHANCED_FILL_PATTERN=3")
        check("both defines: hard #error (mutually exclusive)",
              both.returncode != 0 and "mutually exclusive" in both.stderr)


def test_runtime_range_equivalence():
    print("range conversion: runtime path bit-equal to define path (g++)")
    import shutil
    import subprocess
    import tempfile

    if shutil.which("g++") is None:
        print("  [skip] g++ not available on this host — run the suite in "
              "the pareval-thesis container for the binding proof")
        return

    drivers = REPO_ROOT / "drivers" / "cpp"

    # both paths fill a size_t vector (the sparse_la index-site shape), an
    # int vector and a double vector under a range that is OUT OF RANGE for
    # the integral types — GCC constant-folds the define path's literal
    # cast with truncate-then-saturate semantics, and the runtime path must
    # reproduce that exactly (review finding 2026-08-08: a plain
    # static_cast wraps via cvttsd2si instead)
    probe_text = (
        "#include <vector>\n"
        "#include <cstdlib>\n"
        "#include <cstdio>\n"
        "#include <algorithm>\n"
        "template <typename T, typename DType>\n"
        "void fillRand(T &x, DType lo, DType hi) {\n"
        "    for (size_t i = 0; i < x.size(); i += 1)\n"
        "        x[i] = (DType)((rand() / (double) RAND_MAX) * (hi - lo) + lo);\n"
        "}\n"
        '#include "enhanced-fill.hpp"\n'
        "int main() {\n"
        "    std::vector<size_t> idx(6);\n"
        "    std::vector<int> ints(6);\n"
        "    std::vector<double> vals(6);\n"
        "    ENHANCED_FILL(idx, (size_t)0, (size_t)8);\n"
        "    ENHANCED_FILL(ints, 0, 8);\n"
        "    ENHANCED_FILL(vals, -1.0, 1.0);\n"
        "    for (size_t i = 0; i < 6; i += 1)\n"
        '        std::printf("%zu %d %.17g\\n", idx[i], ints[i], vals[i]);\n'
        "    return 0;\n"
        "}\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.cc"
        probe.write_text(probe_text, encoding="utf-8")

        def build_and_run(defines, env_extra):
            binary = Path(tmp) / "probe.out"
            build = subprocess.run(
                ["g++", "-std=c++17", "-O2", "-I", str(drivers),
                 *defines, str(probe), "-o", str(binary)],
                capture_output=True, text=True, timeout=120,
            )
            if build.returncode != 0:
                return None
            import os
            env = dict(os.environ)
            env.update(env_extra)
            run = subprocess.run([str(binary)], capture_output=True,
                                 text=True, timeout=30, env=env)
            return run.stdout if run.returncode == 0 else None

        # ascending with a range far outside int/size_t: [-10, 3e9]
        define_out = build_and_run(
            ["-DENHANCED_FILL_PATTERN=3",
             "-DENHANCED_FILL_LO=(-10.0)", "-DENHANCED_FILL_HI=(3000000000.0)"],
            {},
        )
        runtime_out = build_and_run(
            ["-DENHANCED_RUNTIME_FILL"],
            {"ENHANCED_FILL_PATTERN": "3",
             "ENHANCED_FILL_RANGE_LO": "-10", "ENHANCED_FILL_RANGE_HI": "3000000000"},
        )
        check("ascending, out-of-range bounds: outputs byte-identical",
              define_out is not None and define_out == runtime_out)

        # random (pattern 0) with the same hostile range: exercises the
        # fillRand rand() stream with converted lo/hi on all three types
        define_rand = build_and_run(
            ["-DENHANCED_FILL_PATTERN=0",
             "-DENHANCED_FILL_LO=(-10.0)", "-DENHANCED_FILL_HI=(3000000000.0)"],
            {},
        )
        runtime_rand = build_and_run(
            ["-DENHANCED_RUNTIME_FILL"],
            {"ENHANCED_FILL_PATTERN": "0",
             "ENHANCED_FILL_RANGE_LO": "-10", "ENHANCED_FILL_RANGE_HI": "3000000000"},
        )
        check("random, out-of-range bounds: outputs byte-identical",
              define_rand is not None and define_rand == runtime_rand)

        # no range at all: call-site lo/hi, both paths
        define_plain = build_and_run(["-DENHANCED_FILL_PATTERN=5"], {})
        runtime_plain = build_and_run(
            ["-DENHANCED_RUNTIME_FILL"], {"ENHANCED_FILL_PATTERN": "5"})
        check("no range: call-site lo/hi byte-identical",
              define_plain is not None and define_plain == runtime_plain)


def main():
    tests = [
        test_config_overrides,
        test_config_validation,
        test_new_pattern_validation,
        test_defines_and_header,
        test_refill_rounds,
        test_mutation_fillup,
        test_parallel_execution_models,
        test_runtime_fill_machinery,
        test_jobs_and_derived_names,
        test_preprocessor_guarantee,
        test_runtime_range_equivalence,
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
