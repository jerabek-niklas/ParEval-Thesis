"""Regression tests for the comparator semantics of drivers/cpp/utilities.hpp.

Covers the execution contract:

  A1  non-finite semantics, three cases, checked in this order
      1. reference NaN/+-Inf      -> baseline_incompatible (stdout marker),
                                     never a model failure
      2. reference finite, candidate NaN/+-Inf -> FAIL
      3. both finite              -> unchanged numeric comparison
      plus the level separation of A1c: fequal is symmetric and never true
      on a non-finite operand, while reportAndCompare* are role aware.

  A2  size mismatch: the former assert() is gone; a wrong-length candidate
      prints SIZE_MISMATCH and fails, also under -DNDEBUG (where the assert
      used to vanish and leave a silent PASS behind).

The tests COMPILE AND RUN a small C++ harness against the real header, in
every buildable configuration (serial, omp, mpi) and with/without -DNDEBUG.
Each case runs in its OWN process, which is also what makes the "marker
printed exactly once per process" property observable.

Nothing is written inside the repository: the harness source and binaries
go to a temporary directory. Requires a C++ compiler (and mpicxx/mpirun for
the mpi configuration) on PATH, i.e. the analysis container:

    docker run --rm -u 0 -v "<repo>:/workspace" -w /workspace pareval-thesis \
        python3 thesis/evaluation/test_comparator_semantics.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRIVERS_CPP = os.path.join(REPO_ROOT, "drivers", "cpp")

BASELINE_INCOMPATIBLE_MARKER = "BASELINE_INCOMPATIBLE:"
SIZE_MISMATCH_MARKER = "SIZE_MISMATCH"

# (config name, compiler, extra compile flags, run wrapper)
CONFIGS = [
    ("serial", "g++", ["-DUSE_SERIAL"], []),
    ("omp", "g++", ["-DUSE_OMP", "-fopenmp"], []),
    ("mpi", "mpicxx", ["-DUSE_MPI"], ["mpirun", "-n", "1", "--allow-run-as-root",
                                      "--oversubscribe"]),
]

HARNESS = r"""
// Comparator-semantics harness. One case per process (argv[1]); prints
// RESULT=<true|false> for the comparison plus whatever markers the header
// emits, so the Python side can assert on both.
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>
#include <complex>
#include <string>

#include "utilities.hpp"

static const double NaN = std::numeric_limits<double>::quiet_NaN();
static const double Inf = std::numeric_limits<double>::infinity();
static const double DENORM = std::numeric_limits<double>::denorm_min();

static void emit(bool r) { printf("RESULT=%s\n", r ? "true" : "false"); }

// fequal symmetry over a representative value set (contract A1c)
static int symmetryCheck() {
    const double values[] = {NaN, Inf, -Inf, 0.0, -0.0, DENORM, -DENORM,
                             1.0, -1.0, 1e300, -1e300};
    const size_t n = sizeof(values) / sizeof(values[0]);
    size_t asymmetric = 0;
    size_t trueOnNonFinite = 0;

    for (size_t i = 0; i < n; i += 1) {
        for (size_t j = 0; j < n; j += 1) {
            std::vector<double> a(1, values[i]);
            std::vector<double> b(1, values[j]);
            const bool ab = fequal(a, b, 1e-6);
            const bool ba = fequal(b, a, 1e-6);
            if (ab != ba) {
                asymmetric += 1;
            }
            const bool nonFinite = !mismatchIsFinite(values[i])
                                || !mismatchIsFinite(values[j]);
            if (nonFinite && (ab || ba)) {
                trueOnNonFinite += 1;
            }
        }
    }

    printf("PAIRS=%zu ASYMMETRIC=%zu TRUE_ON_NONFINITE=%zu\n",
           n * n, asymmetric, trueOnNonFinite);
    return (asymmetric == 0 && trueOnNonFinite == 0) ? 0 : 1;
}

int main(int argc, char **argv) {
#if defined(USE_MPI)
    MPI_Init(&argc, &argv);
#endif
    const std::string c = (argc > 1) ? argv[1] : "";
    int rc = 0;

    std::vector<double> ref;
    ref.push_back(1.5);
    ref.push_back(2.5);

    // ---- vector comparator, contract A1b -------------------------------
    if (c == "vec_finite_correct") {
        std::vector<double> got(ref);
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "vec_finite_wrong") {
        std::vector<double> got(ref);
        got[1] = 9.0;
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "vec_cand_nan") {
        std::vector<double> got(ref);
        got[1] = NaN;
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "vec_cand_posinf") {
        std::vector<double> got(ref);
        got[1] = Inf;
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "vec_cand_neginf") {
        std::vector<double> got(ref);
        got[1] = -Inf;
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "vec_ref_nan") {
        std::vector<double> bad(ref);
        bad[1] = NaN;
        emit(reportAndCompare(bad, ref, 1e-6));
    } else if (c == "vec_ref_posinf") {
        std::vector<double> bad(ref);
        bad[1] = Inf;
        emit(reportAndCompare(bad, ref, 1e-6));
    } else if (c == "vec_ref_neginf") {
        std::vector<double> bad(ref);
        bad[1] = -Inf;
        emit(reportAndCompare(bad, ref, 1e-6));
    } else if (c == "vec_both_nan") {
        std::vector<double> bad(ref);
        bad[1] = NaN;
        std::vector<double> got(bad);
        emit(reportAndCompare(bad, got, 1e-6));
    } else if (c == "vec_both_posinf") {
        // the case a naive implementation reports as PASS
        std::vector<double> bad(ref);
        bad[1] = Inf;
        std::vector<double> got(bad);
        emit(reportAndCompare(bad, got, 1e-6));

    // ---- scalar comparator, same three cases ---------------------------
    } else if (c == "scalar_finite_correct") {
        emit(reportAndCompareScalar(2.5, 2.5, 1e-6));
    } else if (c == "scalar_finite_wrong") {
        emit(reportAndCompareScalar(2.5, 9.0, 1e-6));
    } else if (c == "scalar_cand_nan") {
        emit(reportAndCompareScalar(2.5, NaN, 1e-6));
    } else if (c == "scalar_cand_posinf") {
        emit(reportAndCompareScalar(2.5, Inf, 1e-6));
    } else if (c == "scalar_cand_neginf") {
        emit(reportAndCompareScalar(2.5, -Inf, 1e-6));
    } else if (c == "scalar_ref_nan") {
        emit(reportAndCompareScalar(NaN, 2.5, 1e-6));
    } else if (c == "scalar_ref_posinf") {
        emit(reportAndCompareScalar(Inf, 2.5, 1e-6));
    } else if (c == "scalar_ref_neginf") {
        emit(reportAndCompareScalar(-Inf, 2.5, 1e-6));
    } else if (c == "scalar_both_nan") {
        emit(reportAndCompareScalar(NaN, NaN, 1e-6));
    } else if (c == "scalar_both_posinf") {
        emit(reportAndCompareScalar(Inf, Inf, 1e-6));

    // ---- complex value type (same header path) -------------------------
    } else if (c == "complex_ref_nan") {
        std::vector<std::complex<double> > a, b;
        a.push_back(std::complex<double>(NaN, 0.0));
        b.push_back(std::complex<double>(1.0, 0.0));
        emit(reportAndCompare(a, b, 1e-6));
    } else if (c == "complex_cand_nan") {
        std::vector<std::complex<double> > a, b;
        a.push_back(std::complex<double>(1.0, 0.0));
        b.push_back(std::complex<double>(NaN, 0.0));
        emit(reportAndCompare(a, b, 1e-6));

    // ---- contract A2, size mismatch ------------------------------------
    } else if (c == "size_equal_same") {
        std::vector<double> got(ref);
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "size_equal_diff") {
        std::vector<double> got(ref);
        got[0] = 42.0;
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "size_cand_shorter") {
        std::vector<double> got(1, 1.5);
        emit(reportAndCompare(ref, got, 1e-6));
    } else if (c == "size_cand_longer") {
        std::vector<double> got(ref);
        got.push_back(3.5);
        emit(reportAndCompare(ref, got, 1e-6));

    // ---- fequal level (contract A1c) -----------------------------------
    } else if (c == "fequal_symmetry") {
        rc = symmetryCheck();
    } else if (c == "fequal_size_mismatch") {
        std::vector<double> got(1, 1.5);
        emit(fequal(ref, got, 1e-6));
    } else {
        printf("UNKNOWN_CASE\n");
        rc = 2;
    }

#if defined(USE_MPI)
    MPI_Finalize();
#endif
    return rc;
}
"""

# case -> (expected comparison result, marker expected, size-mismatch expected)
# "baseline_incompatible" cases are the ones whose observable is the marker;
# their comparison result must NOT be a model failure.
CASES = [
    ("vec_finite_correct", True, False, False),
    ("vec_finite_wrong", False, False, False),
    ("vec_cand_nan", False, False, False),
    ("vec_cand_posinf", False, False, False),
    ("vec_cand_neginf", False, False, False),
    ("vec_ref_nan", True, True, False),
    ("vec_ref_posinf", True, True, False),
    ("vec_ref_neginf", True, True, False),
    ("vec_both_nan", True, True, False),
    ("vec_both_posinf", True, True, False),
    ("scalar_finite_correct", True, False, False),
    ("scalar_finite_wrong", False, False, False),
    ("scalar_cand_nan", False, False, False),
    ("scalar_cand_posinf", False, False, False),
    ("scalar_cand_neginf", False, False, False),
    ("scalar_ref_nan", True, True, False),
    ("scalar_ref_posinf", True, True, False),
    ("scalar_ref_neginf", True, True, False),
    ("scalar_both_nan", True, True, False),
    ("scalar_both_posinf", True, True, False),
    ("complex_ref_nan", True, True, False),
    ("complex_cand_nan", False, False, False),
    ("size_equal_same", True, False, False),
    ("size_equal_diff", False, False, False),
    ("size_cand_shorter", False, False, True),
    ("size_cand_longer", False, False, True),
    ("fequal_size_mismatch", False, False, False),
]

FAILURES = []


def check(label, condition, detail=""):
    status = "ok" if condition else "FAIL"
    print("  [%s] %s%s" % (status, label, ("  -- " + detail) if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def compile_harness(workdir, config, ndebug):
    name, compiler, flags, _runner = config
    src = os.path.join(workdir, "harness_%s.cpp" % name)
    with open(src, "w") as fh:
        fh.write(HARNESS)

    exe = os.path.join(workdir, "harness_%s%s" % (name, "_ndebug" if ndebug else ""))
    argv = [compiler, "-std=c++17", "-O2"] + list(flags) + [
        "-DDRIVER_PROBLEM_SIZE=(1<<4)",
        "-I", DRIVERS_CPP,
        src, "-o", exe,
    ]
    if ndebug:
        argv.insert(3, "-DNDEBUG")

    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    if proc.returncode != 0:
        return None, proc.stderr[-1500:]
    return exe, ""


def run_case(exe, config, case):
    _name, _compiler, _flags, runner = config
    argv = list(runner) + [exe, case]
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=120)
    return proc.stdout, proc.returncode


def parse_result(stdout):
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("RESULT="):
            return line.split("=", 1)[1] == "true"
    return None


def run_config(workdir, config, ndebug):
    name = config[0]
    label = "%s%s" % (name, " -DNDEBUG" if ndebug else "")
    print("\n== configuration: %s ==" % label)

    exe, err = compile_harness(workdir, config, ndebug)
    if exe is None:
        check("%s: harness compiles" % label, False, err)
        return

    for case, expect_result, expect_marker, expect_size in CASES:
        stdout, _rc = run_case(exe, config, case)
        got = parse_result(stdout)
        markers = [ln for ln in stdout.splitlines()
                   if ln.strip().startswith(BASELINE_INCOMPATIBLE_MARKER)]

        check("%s/%s: comparison result" % (label, case), got is expect_result,
              "expected %s, got %s; stdout=%r" % (expect_result, got, stdout))
        check("%s/%s: baseline_incompatible marker %s"
              % (label, case, "present" if expect_marker else "absent"),
              (len(markers) > 0) == expect_marker,
              "markers=%d; stdout=%r" % (len(markers), stdout))
        if expect_marker:
            # contract A1g: exactly once per process, root rank only
            check("%s/%s: marker emitted exactly once" % (label, case),
                  len(markers) == 1, "markers=%d" % len(markers))
        if expect_size:
            check("%s/%s: SIZE_MISMATCH printed" % (label, case),
                  SIZE_MISMATCH_MARKER in stdout, "stdout=%r" % stdout)

    stdout, rc = run_case(exe, config, "fequal_symmetry")
    check("%s/fequal_symmetry: symmetric and never true on non-finite" % label,
          rc == 0, stdout.strip())
    print("    %s" % stdout.strip())


STUB = r"""
#include <cstdio>
int main() {
    printf("BASELINE_INCOMPATIBLE: non_finite_reference\n");
    printf("Validation: PASS\n");
    printf("Time: 0.1\n");
    printf("BestSequential: 0.1\n");
    return 0;
}
"""


def test_transport(workdir):
    """Contract A1e/A1f: the marker travels stdout -> parser -> verdict, and
    every consumer treats the value explicitly."""
    print("\n== transport level ==")

    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    from thesis.evaluation.run_correctness import (
        BASELINE_INCOMPATIBLE,
        count_baseline_incompatible,
        run_verdict,
    )

    # --- parser + verdict -------------------------------------------------
    check("parser: marker absent -> 0",
          count_baseline_incompatible("Validation: PASS\n") == 0)
    check("parser: marker once -> 1",
          count_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: non_finite_reference\nValidation: PASS\n") == 1)
    check("parser: marker twice -> 2 (distinguishable from missing)",
          count_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: a\nBASELINE_INCOMPATIBLE: b\n") == 2)

    check("verdict: marker + PASS -> baseline_incompatible",
          run_verdict(True, 0, False, baseline_incompatible=True)
          == BASELINE_INCOMPATIBLE)
    check("verdict: marker + FAIL -> baseline_incompatible (case 1 first)",
          run_verdict(False, 0, False, baseline_incompatible=True)
          == BASELINE_INCOMPATIBLE)
    check("verdict: no marker + FAIL -> validation_failed (unchanged)",
          run_verdict(False, 0, False) == "validation_failed")
    check("verdict: no marker + PASS -> pass (unchanged)",
          run_verdict(True, 0, False) == "pass")
    check("verdict: timeout still outranks (unchanged)",
          run_verdict(None, 0, True, baseline_incompatible=True) == "timeout")

    # --- enhanced stage transports the same marker ------------------------
    from thesis.evaluation.run_enhanced_tests import run_binary

    stub_src = os.path.join(workdir, "stub.cpp")
    stub_exe = os.path.join(workdir, "stub")
    with open(stub_src, "w") as fh:
        fh.write(STUB)
    built = subprocess.run(["g++", "-std=c++17", "-O0", stub_src, "-o", stub_exe],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    if built.returncode != 0:
        check("enhanced: stub compiles", False, built.stderr[-500:])
    else:
        status = run_binary(stub_exe, workdir, 60.0)[0]
        check("enhanced: marker outranks 'Validation: PASS' -> baseline_incompatible",
              status == "baseline_incompatible", "got %r" % status)

    # --- repair: no model repair, no correctness feedback -----------------
    from thesis.repair import feedback
    from thesis.repair.orchestrator import evaluate_stop, STATUS_CLEAN
    from thesis.repair.test_orchestrator import (
        CLEAN_STATIC, correctness_record, dynamic_record, stop_config,
    )

    record = correctness_record(BASELINE_INCOMPATIBLE)

    settings = feedback.feedback_settings(stop_config())
    check("repair: no correctness feedback rendered",
          feedback.render_correctness(record, settings, with_mismatch=True) == [])
    check("repair: not summarised as a test failure",
          feedback.summarize_correctness(record) is None)

    decision = evaluate_stop(
        stop_config(), "test_feedback", 1, 2,
        CLEAN_STATIC, dynamic_record(), record, None,
    )
    from thesis.repair.orchestrator import STATUS_ACTIVE, STATUS_TESTS_PASS

    check("repair: baseline_incompatible does not start an iteration",
          decision.status in (STATUS_CLEAN, STATUS_TESTS_PASS),
          "status=%r reason=%r" % (decision.status, decision.stop_reason))
    check("repair: stop reason names the real condition, not 'ParEval pass'",
          BASELINE_INCOMPATIBLE in decision.stop_reason,
          "reason=%r" % decision.stop_reason)

    failing = evaluate_stop(
        stop_config(), "test_feedback", 1, 2,
        CLEAN_STATIC, dynamic_record(), correctness_record("validation_failed"), None,
    )
    check("repair: a real failure still starts an iteration (control)",
          failing.status == STATUS_ACTIVE, "status=%r" % failing.status)

    # --- overview: not a model failure, not in the denominator ------------
    from thesis.analysis_overview.build_overview import (
        breakdown_table, clean_but_incorrect, trajectory_table,
    )

    def row(sample, verdict, status="stopped_clean"):
        return {
            "model": "m1", "variant": "static_feedback", "iteration": 0,
            "sample_id": sample, "execution_model": "serial",
            "problem_type": "sparse_la", "benchmark": "45_x",
            "correctness_verdict": verdict, "status": status,
            "enhanced_pass": 20, "enhanced_fail": 0,
        }

    rows = [
        row("s_pass", "pass"),
        row("s_fail", "validation_failed"),
        row("s_bi", BASELINE_INCOMPATIBLE),
    ]

    traj = trajectory_table(rows, "static_feedback")
    check("overview: denominator excludes the status (1/2, not 1/3)",
          any("1/2" in line for line in traj),
          "table=%r" % traj)
    check("overview: trajectory reports the status explicitly",
          any(BASELINE_INCOMPATIBLE in line for line in traj),
          "table=%r" % traj)

    cbi = clean_but_incorrect(rows)
    check("overview: clean-but-incorrect denominator excludes it",
          any("1/2" in line for line in cbi), "lines=%r" % cbi)
    check("overview: clean-but-incorrect names the exclusion",
          any("excluded" in line for line in cbi), "lines=%r" % cbi)

    bt = breakdown_table(rows, "static_feedback", "execution_model")
    check("overview: breakdown denominator excludes it",
          any("1/2" in line for line in bt), "table=%r" % bt)


def main():
    print("Comparator semantics (execution contract A1 + A2)")
    print("repo: %s" % REPO_ROOT)

    workdir = tempfile.mkdtemp(prefix="comparator_semantics_")
    try:
        for config in CONFIGS:
            compiler = config[1]
            if shutil.which(compiler) is None:
                print("\n== configuration: %s == SKIPPED (%s not on PATH)"
                      % (config[0], compiler))
                FAILURES.append("%s: compiler missing" % config[0])
                continue
            if config[3] and shutil.which(config[3][0]) is None:
                print("\n== configuration: %s == SKIPPED (%s not on PATH)"
                      % (config[0], config[3][0]))
                FAILURES.append("%s: runner missing" % config[0])
                continue
            for ndebug in (False, True):
                run_config(workdir, config, ndebug)
        if shutil.which("g++") is not None:
            test_transport(workdir)
        else:
            print("\n== transport level == SKIPPED (g++ not on PATH)")
            FAILURES.append("transport: compiler missing")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("")
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES[:12])))
        return 1
    print("all comparator-semantics checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
