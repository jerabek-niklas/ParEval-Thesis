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

and the Wave-1b completions:

  C1.5  reportAndCompareSelectedWith — benchmarks that grade only an
        interior keep their graded index set while gaining the role-aware
        semantics.
  C2b   marker AUTHENTICITY: the marker carries a per-execution nonce; a
        line with a wrong nonce, no nonce, or one a candidate printed
        itself must never influence a verdict.
  C2    MPI: the marker is emitted per RANK, not root-only, and several
        markers are normal there.
  C2c   the marker survives a timeout kill and an abort (explicit flush).
  C3    overview denominators and gridpoint display.
  C3b   terminal repair state, BI + downstream process state, and the
        two-validation-attempt semantics in BOTH orders.

The tests COMPILE AND RUN a small C++ harness against the real header, in
every buildable configuration (serial, omp, mpi with 1 rank, mpi with 2
ranks) and with/without -DNDEBUG. Each case runs in its OWN process, which
is also what makes the "marker printed once per process" property
observable.

Nothing is written inside the repository: the harness source and binaries
go to a temporary directory. Requires a C++ compiler (and mpicxx/mpirun for
the mpi configuration) on PATH, i.e. the analysis container:

    docker run --rm -u 0 -v "<repo>:/workspace" -w /workspace pareval-thesis \
        python3 thesis/evaluation/test_comparator_semantics.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRIVERS_CPP = os.path.join(REPO_ROOT, "drivers", "cpp")

BASELINE_INCOMPATIBLE_MARKER = "BASELINE_INCOMPATIBLE:"
SIZE_MISMATCH_MARKER = "SIZE_MISMATCH"

# Contract C2b: every child of this test suite gets a fixed, known nonce, so
# the assertions can distinguish an AUTHENTIC marker from any other line that
# merely looks like one.
NONCE_ENV = "PAREVAL_BI_NONCE"
TEST_NONCE = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
WRONG_NONCE = "ffffffffffffffffffffffffffffffff"

MARKER_LINE = re.compile(
    r"^BASELINE_INCOMPATIBLE:\s*(?P<reason>\S+)(?:\s+nonce=(?P<nonce>\S+))?\s*$"
)

# (config name, compiler, extra compile flags, run wrapper)
CONFIGS = [
    ("serial", "g++", ["-DUSE_SERIAL"], []),
    ("omp", "g++", ["-DUSE_OMP", "-fopenmp"], []),
    ("mpi", "mpicxx", ["-DUSE_MPI"], ["mpirun", "-n", "1", "--allow-run-as-root",
                                      "--oversubscribe"]),
    # contract C2/C2.5: a REAL multi-rank run, never a parser mock
    ("mpi2", "mpicxx", ["-DUSE_MPI"], ["mpirun", "-n", "2", "--allow-run-as-root",
                                       "--oversubscribe"]),
]

HARNESS = r"""
// Comparator-semantics harness. One case per process (argv[1]); prints
// RESULT=<true|false> for the comparison plus whatever markers the header
// emits, so the Python side can assert on both.
#include <cstdio>
#include <cstdlib>
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

// contract C1.5: the 1d-stencil grading shape — only [1, n-1) is compared
static bool compareInterior(std::vector<double> const& a,
                            std::vector<double> const& b) {
    const size_t n = a.size();
    return reportAndCompareSelectedWith(
        a, b, static_cast<std::vector<double> const*>(nullptr),
        [](double e, double g) { return std::abs(g - e) > 1e-6; },
        [n](size_t i) { return i >= 1 && i + 1 < n; });
}

// contract C3b.4: the drivers' two-attempt loop, verbatim in structure.
// Prints the same Validation: line a model driver prints, so the Python side
// can assert on the marker AND on the verdict the parser would derive.
static int twoAttempts(std::vector<double> const& ref1,
                       std::vector<double> const& got1,
                       std::vector<double> const& ref2,
                       std::vector<double> const& got2) {
    bool valid = true;
    for (int attempt = 0; attempt < 2 && valid; attempt += 1) {
        const std::vector<double> &r = (attempt == 0) ? ref1 : ref2;
        const std::vector<double> &g = (attempt == 0) ? got1 : got2;
        if (!reportAndCompare(r, g, 1e-6)) {
            valid = false;
        }
    }
    // contract F1: the SAME trusted emitter the model drivers use
    parevalEmitValidation(valid);
    return 0;
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

    // ---- contract C1.5: graded-subset comparison -----------------------
    // The 1d-stencil shape: only [1, n-1) is graded, the two ends are not.
    } else if (c == "selected_interior_equal") {
        std::vector<double> a(5, 1.0), b(5, 1.0);
        a[0] = 7.0;  b[0] = -7.0;          // ungraded end differs
        a[4] = 7.0;  b[4] = -7.0;          // ungraded end differs
        emit(compareInterior(a, b));
    } else if (c == "selected_interior_differs") {
        std::vector<double> a(5, 1.0), b(5, 1.0);
        b[2] = 9.0;                        // graded index differs
        emit(compareInterior(a, b));
    } else if (c == "selected_border_ref_nan") {
        // a non-finite REFERENCE outside the graded set must NOT raise the
        // marker: that index is not part of this benchmark's comparison
        std::vector<double> a(5, 1.0), b(5, 1.0);
        a[0] = NaN;
        emit(compareInterior(a, b));
    } else if (c == "selected_inside_ref_nan") {
        std::vector<double> a(5, 1.0), b(5, 1.0);
        a[2] = NaN;
        emit(compareInterior(a, b));
    } else if (c == "selected_inside_cand_nan") {
        std::vector<double> a(5, 1.0), b(5, 1.0);
        b[2] = NaN;
        emit(compareInterior(a, b));
    } else if (c == "selected_size_mismatch") {
        std::vector<double> a(5, 1.0), b(4, 1.0);
        emit(compareInterior(a, b));

    // ---- contract C3b.4: TWO validation attempts, both orders ----------
    // Emulates the drivers' `for (attempt) { compare; if (!ok) return false; }`
    // loop and prints the same Validation: line the model drivers print.
    } else if (c == "two_attempts_finite_then_nan") {
        std::vector<double> finiteRef(ref), got(ref);
        std::vector<double> nanRef(ref);
        nanRef[1] = NaN;
        rc = twoAttempts(finiteRef, got, nanRef, got);
    } else if (c == "two_attempts_nan_then_finite") {
        std::vector<double> finiteRef(ref), got(ref);
        std::vector<double> nanRef(ref);
        nanRef[1] = NaN;
        rc = twoAttempts(nanRef, got, finiteRef, got);

    // ---- contract C2c: the marker must survive a kill / an abort -------
    } else if (c == "marker_then_hang") {
        std::vector<double> bad(ref);
        bad[1] = NaN;
        reportAndCompare(bad, ref, 1e-6);
        for (;;) { }                       // killed by the caller's timeout
    } else if (c == "marker_then_abort") {
        std::vector<double> bad(ref);
        bad[1] = NaN;
        reportAndCompare(bad, ref, 1e-6);
        abort();

    // ---- contract C2b: a candidate printing the line itself ------------
    } else if (c == "candidate_prints_marker") {
        printf("BASELINE_INCOMPATIBLE: non_finite_reference\n");
        printf("BASELINE_INCOMPATIBLE: non_finite_reference nonce=%s\n",
               "ffffffffffffffffffffffffffffffff");
        emit(true);

#if defined(USE_MPI)
    // ---- contract C2: MPI marker emission ------------------------------
    } else if (c == "mpi_all_ranks_ref_nan") {
        // every rank sees a non-finite reference -> one marker PER RANK
        std::vector<double> bad(ref);
        bad[1] = NaN;
        const bool ok = reportAndCompare(bad, ref, 1e-6);
        MPI_Barrier(MPI_COMM_WORLD);       // proves no rank got stuck earlier
        if (mismatchIsRoot()) { emit(ok); }
    } else if (c == "mpi_nonroot_ref_nan") {
        // ONLY a non-root rank sees it: with the old root-only filter the
        // marker never appeared at all
        int r = 0;
        MPI_Comm_rank(MPI_COMM_WORLD, &r);
        std::vector<double> a(ref), b(ref);
        if (r != 0) { a[1] = NaN; }
        const bool ok = reportAndCompare(a, b, 1e-6);
        MPI_Barrier(MPI_COMM_WORLD);
        if (mismatchIsRoot()) { emit(ok); }
#endif

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
    # contract C1.5: graded-subset comparison keeps the graded index set
    ("selected_interior_equal", True, False, False),
    ("selected_interior_differs", False, False, False),
    # an ungraded index is not part of the comparison, so a non-finite value
    # there is NOT a baseline_incompatible signal
    ("selected_border_ref_nan", True, False, False),
    ("selected_inside_ref_nan", True, True, False),
    ("selected_inside_cand_nan", False, False, False),
    ("selected_size_mismatch", False, False, True),
]

# Cases with their own assertions (not the generic result/marker/size triple).
MPI_ONLY_CASES = ("mpi_all_ranks_ref_nan", "mpi_nonroot_ref_nan")

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


def run_case(exe, config, case, nonce=TEST_NONCE, timeout=120, kill_after=None):
    """Run one harness case. `nonce` is what the CHILD is told (contract
    C2b); `kill_after` turns the run into a timeout kill and still returns
    whatever the child had already written (contract C2c)."""
    _name, _compiler, _flags, runner = config
    argv = list(runner) + [exe, case]

    env = dict(os.environ)
    if nonce is None:
        env.pop(NONCE_ENV, None)
    else:
        env[NONCE_ENV] = nonce

    if kill_after is not None:
        try:
            proc = subprocess.run(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=kill_after, env=env,
            )
            return proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as expired:
            raw = expired.stdout or b""
            out = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            return out, None

    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=timeout, env=env)
    return proc.stdout, proc.returncode


def parse_result(stdout):
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("RESULT="):
            return line.split("=", 1)[1] == "true"
    return None


def marker_lines(stdout):
    """(authentic, other) marker lines, judged against TEST_NONCE."""
    authentic = 0
    other = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith(BASELINE_INCOMPATIBLE_MARKER):
            continue
        match = MARKER_LINE.match(line)
        if match and match.group("nonce") == TEST_NONCE:
            authentic += 1
        else:
            other += 1
    return authentic, other


def run_config(workdir, config, ndebug):
    name = config[0]
    label = "%s%s" % (name, " -DNDEBUG" if ndebug else "")
    print("\n== configuration: %s ==" % label)

    exe, err = compile_harness(workdir, config, ndebug)
    if exe is None:
        check("%s: harness compiles" % label, False, err)
        return

    ranks = 2 if name == "mpi2" else 1

    for case, expect_result, expect_marker, expect_size in CASES:
        stdout, _rc = run_case(exe, config, case)
        got = parse_result(stdout)
        authentic, other = marker_lines(stdout)

        check("%s/%s: comparison result" % (label, case), got is expect_result,
              "expected %s, got %s; stdout=%r" % (expect_result, got, stdout))
        check("%s/%s: baseline_incompatible marker %s"
              % (label, case, "present" if expect_marker else "absent"),
              (authentic > 0) == expect_marker,
              "authentic=%d other=%d; stdout=%r" % (authentic, other, stdout))
        check("%s/%s: no unauthenticated marker line" % (label, case),
              other == 0, "other=%d; stdout=%r" % (other, stdout))
        if expect_marker:
            # contract A1g/C2.2: once per PROCESS, i.e. once per MPI rank —
            # every rank in this harness runs the same comparison
            check("%s/%s: marker emitted once per rank (%d)"
                  % (label, case, ranks),
                  authentic == ranks, "authentic=%d" % authentic)
        if expect_size:
            check("%s/%s: SIZE_MISMATCH printed" % (label, case),
                  SIZE_MISMATCH_MARKER in stdout, "stdout=%r" % stdout)

    stdout, rc = run_case(exe, config, "fequal_symmetry")
    check("%s/fequal_symmetry: symmetric and never true on non-finite" % label,
          rc == 0, stdout.strip())
    print("    %s" % stdout.strip())

    run_nonce_cases(exe, config, label)
    run_two_attempt_cases(exe, config, label, ranks)
    run_survival_cases(exe, config, label, ranks)

    if name == "mpi2":
        run_mpi_rank_cases(exe, config, label)


def run_nonce_cases(exe, config, label):
    """Contract C2b.3: only the nonce THIS execution handed out is accepted."""
    # 1. correct nonce -> accepted
    stdout, _rc = run_case(exe, config, "vec_ref_nan", nonce=TEST_NONCE)
    authentic, other = marker_lines(stdout)
    check("%s/nonce: correct nonce -> marker accepted" % label,
          authentic >= 1 and other == 0,
          "authentic=%d other=%d stdout=%r" % (authentic, other, stdout))

    # 2. the child was given a DIFFERENT nonce -> the marker it prints must
    #    not be accepted by a parser expecting TEST_NONCE
    stdout, _rc = run_case(exe, config, "vec_ref_nan", nonce=WRONG_NONCE)
    authentic, other = marker_lines(stdout)
    check("%s/nonce: wrong nonce -> NOT accepted" % label,
          authentic == 0 and other >= 1,
          "authentic=%d other=%d stdout=%r" % (authentic, other, stdout))

    # 3. no nonce in the environment at all -> not accepted either
    stdout, _rc = run_case(exe, config, "vec_ref_nan", nonce=None)
    authentic, other = marker_lines(stdout)
    check("%s/nonce: missing nonce -> NOT accepted" % label,
          authentic == 0 and other >= 1,
          "authentic=%d other=%d stdout=%r" % (authentic, other, stdout))

    # 4. a candidate printing the marker itself (with and without a guessed
    #    nonce) -> never accepted
    stdout, _rc = run_case(exe, config, "candidate_prints_marker")
    authentic, other = marker_lines(stdout)
    check("%s/nonce: candidate-printed marker -> NOT accepted" % label,
          authentic == 0 and other >= 2,
          "authentic=%d other=%d stdout=%r" % (authentic, other, stdout))


def run_two_attempt_cases(exe, config, label, ranks):
    """Contract C3b.4: a non-finite reference in EITHER attempt makes the
    whole validation baseline_incompatible."""
    for case in ("two_attempts_finite_then_nan", "two_attempts_nan_then_finite"):
        stdout, _rc = run_case(exe, config, case)
        authentic, other = marker_lines(stdout)
        check("%s/%s: marker present" % (label, case), authentic == ranks,
              "authentic=%d other=%d stdout=%r" % (authentic, other, stdout))
        check("%s/%s: not turned into a model failure" % (label, case),
              ("Validation: PASS nonce=%s" % TEST_NONCE) in stdout,
              "stdout=%r" % stdout)


def run_survival_cases(exe, config, label, ranks):
    """Contract C2c: the marker survives a timeout kill and an abort."""
    stdout, rc = run_case(exe, config, "marker_then_hang", kill_after=8)
    authentic, _other = marker_lines(stdout)
    check("%s/marker_then_hang: process was actually killed" % label,
          rc is None, "rc=%r" % rc)
    check("%s/marker_then_hang: marker still reached the runner" % label,
          authentic >= 1, "authentic=%d stdout=%r" % (authentic, stdout))

    stdout, rc = run_case(exe, config, "marker_then_abort")
    authentic, _other = marker_lines(stdout)
    check("%s/marker_then_abort: process died" % label, rc not in (0, None),
          "rc=%r" % rc)
    check("%s/marker_then_abort: marker still reached the runner" % label,
          authentic >= 1, "authentic=%d stdout=%r" % (authentic, stdout))


def run_mpi_rank_cases(exe, config, label):
    """Contract C2/C2.5: real multi-rank emission, no root-only filter."""
    stdout, rc = run_case(exe, config, "mpi_all_ranks_ref_nan")
    authentic, other = marker_lines(stdout)
    check("%s/mpi_all_ranks_ref_nan: one marker per rank (2)" % label,
          authentic == 2, "authentic=%d other=%d stdout=%r"
          % (authentic, other, stdout))
    check("%s/mpi_all_ranks_ref_nan: several markers are not an anomaly" % label,
          other == 0, "other=%d" % other)
    check("%s/mpi_all_ranks_ref_nan: all ranks terminated regularly" % label,
          rc == 0, "rc=%r stdout=%r" % (rc, stdout))
    check("%s/mpi_all_ranks_ref_nan: barrier after the marker completed "
          "(no dead collective)" % label,
          parse_result(stdout) is True, "stdout=%r" % stdout)

    stdout, rc = run_case(exe, config, "mpi_nonroot_ref_nan")
    authentic, other = marker_lines(stdout)
    check("%s/mpi_nonroot_ref_nan: NON-ROOT rank emitted the marker" % label,
          authentic == 1, "authentic=%d other=%d stdout=%r"
          % (authentic, other, stdout))
    check("%s/mpi_nonroot_ref_nan: all ranks terminated regularly" % label,
          rc == 0, "rc=%r stdout=%r" % (rc, stdout))
    check("%s/mpi_nonroot_ref_nan: marker not destroyed by stdout "
          "interleaving" % label,
          other == 0, "other=%d stdout=%r" % (other, stdout))


STUB_TEMPLATE = r"""
#include <cstdio>
#include <unistd.h>
int main() {
    printf("BASELINE_INCOMPATIBLE: non_finite_reference nonce=%(nonce)s\n");
    fflush(stdout);
    printf("Validation: PASS nonce=%(nonce)s\n");
    fflush(stdout);
    printf("Time: 0.1\n");
    printf("BestSequential: 0.1\n");
    %(tail)s
    return 0;
}
"""

# What a CANDIDATE could print next to a genuine trusted verdict: BI markers
# without / with a guessed token, plus a bare Validation line. None of it may
# influence the outcome — the authentic FAIL decides (contract F1.6 rule 4).
STUB_SPOOF = r"""
#include <cstdio>
int main() {
    printf("BASELINE_INCOMPATIBLE: non_finite_reference\n");
    printf("BASELINE_INCOMPATIBLE: non_finite_reference nonce=deadbeef\n");
    printf("Validation: PASS\n");
    printf("Validation: FAIL nonce=%(nonce)s\n");
    return 0;
}
"""

# The trusted driver ran, but the token never reached it: only the exact
# legacy line arrives (contract F1.6 rule 7 / F2.4).
STUB_LEGACY_ONLY = r"""
#include <cstdio>
int main() {
    printf("Validation: PASS\n");
    printf("Time: 0.1\n");
    printf("BestSequential: 0.1\n");
    return 0;
}
"""

# Contract F2.6: echoes the token the CHILD actually received, so the tests can
# observe the per-launch lifetime from the outside. It uses the SAME header the
# model drivers use — and compiles it exactly as drivers/cpp/Makefile does:
# standalone, WITHOUT -DUSE_<MODEL> and WITHOUT -DDRIVER_PROBLEM_SIZE.
STUB_NONCE_ECHO = r"""
#include <cstdio>
#include "harness-markers.hpp"
int main() {
    printf("CHILD_NONCE=%s\n", parevalHarnessNonce());
    printf("AUTHENTICATED=%d\n", parevalAuthenticatedMode() ? 1 : 0);
    parevalEmitValidation(true);
    printf("Time: 0.1\n");
    printf("BestSequential: 0.1\n");
    return 0;
}
"""

STUB_NONCE_ECHO_MPI = r"""
#include <cstdio>
#include <mpi.h>
#include "harness-markers.hpp"
int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);
    int rank = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    printf("CHILD_NONCE=%s rank=%d\n", parevalHarnessNonce(), rank);
    fflush(stdout);
    MPI_Barrier(MPI_COMM_WORLD);
    if (rank == 0) { parevalEmitValidation(true); }
    MPI_Finalize();
    return 0;
}
"""


def build_stub(workdir, name, source, compiler="g++"):
    src = os.path.join(workdir, name + ".cpp")
    exe = os.path.join(workdir, name)
    with open(src, "w") as fh:
        fh.write(source)
    # -I DRIVERS_CPP so the stubs can use harness-markers.hpp; deliberately
    # WITHOUT -DUSE_<MODEL>/-DDRIVER_PROBLEM_SIZE, mirroring how
    # drivers/cpp/Makefile compiles the model drivers standalone
    built = subprocess.run([compiler, "-std=c++17", "-O0", "-I", DRIVERS_CPP,
                            src, "-o", exe],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    if built.returncode != 0:
        return None, built.stderr[-500:]
    return exe, ""


def observed_child_nonces(stdout):
    """Every token the child(ren) reported via CHILD_NONCE=."""
    found = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("CHILD_NONCE="):
            found.append(line[len("CHILD_NONCE="):].split()[0])
    return found


BENCHMARK_DIR = os.path.join(DRIVERS_CPP, "benchmarks", "dense_la",
                             "03_dense_la_axpy")

AXPY_CANDIDATE = (
    "void NO_INLINE axpy(double alpha, std::vector<double> const& x,\n"
    "                    std::vector<double> const& y,\n"
    "                    std::vector<double> &z) {\n"
    "    correctAxpy(alpha, x, y, z);\n"
    "}\n"
)


def build_real_driver(workdir, execution_model):
    """Compile a REAL benchmark against a REAL model driver, exactly as the
    pipeline does. Returns (exe, error)."""
    src_dir = os.path.join(workdir, "real_%s" % execution_model)
    if not os.path.isdir(src_dir):
        os.makedirs(src_dir)
    with open(os.path.join(src_dir, "generated-code.hpp"), "w") as fh:
        fh.write(AXPY_CANDIDATE)

    exe = os.path.join(workdir, "real_%s.out" % execution_model)
    if execution_model == "mpi":
        compiler, extra, macro = "mpicxx", [], "-DUSE_MPI"
        driver = "mpi-driver.cc"
    else:
        compiler, extra, macro = "g++", [], "-DUSE_SERIAL"
        driver = "serial-driver.cc"

    argv = [compiler, "-std=c++17", "-O1", macro] + extra + [
        "-DDRIVER_PROBLEM_SIZE=(1<<4)", "-DENHANCED_TEST_SIZE=8",
        "-I", DRIVERS_CPP, "-I", os.path.join(DRIVERS_CPP, "models"),
        "-I", src_dir,
        os.path.join(DRIVERS_CPP, "models", driver),
        os.path.join(BENCHMARK_DIR, "cpu.cc"),
        "-o", exe,
    ]
    built = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    if built.returncode != 0:
        return None, built.stderr[-800:]
    return exe, ""


def test_real_drivers(workdir):
    """Contract F1.8 items 12/13/14 on the SHIPPED model drivers, not stubs."""
    print("\n== real model drivers ==")

    exe, err = build_real_driver(workdir, "serial")
    if exe is None:
        check("real serial driver builds", False, err)
        return

    base_env = dict(os.environ)
    base_env.pop(NONCE_ENV, None)

    # 12) LEGACY mode: byte-identical historical line, nothing else
    legacy = subprocess.run([exe, "1"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True,
                            env=base_env, timeout=120).stdout
    legacy_lines = [ln for ln in legacy.splitlines()
                    if ln.startswith("Validation:")]
    check("F1.8-12: legacy driver emits EXACTLY 'Validation: PASS'",
          legacy_lines == ["Validation: PASS"], "%r" % (legacy_lines,))

    # 13) the upstream parser still reads it — the real one, on real output
    sys.path.insert(0, os.path.dirname(DRIVERS_CPP))
    from drivers.driver_wrapper import RunOutput

    parsed = RunOutput(0, legacy, "", {})
    check("F1.8-13: the upstream legacy parser still reads it as valid",
          parsed.is_valid is True, "is_valid=%r" % parsed.is_valid)

    # and it is not confused by the authenticated form either
    auth_env = dict(base_env)
    auth_env[NONCE_ENV] = TEST_NONCE
    authed = subprocess.run([exe, "1"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True,
                            env=auth_env, timeout=120).stdout
    auth_lines = [ln for ln in authed.splitlines()
                  if ln.startswith("Validation:")]
    check("F1.8: authenticated driver emits the token form",
          auth_lines == ["Validation: PASS nonce=%s" % TEST_NONCE],
          "%r" % (auth_lines,))
    check("F1.8-13: the upstream parser is robust against the token form",
          RunOutput(0, authed, "", {}).is_valid is True)

    # the thesis parser accepts the authenticated form and rejects the legacy
    from thesis.evaluation.run_correctness import (
        HarnessTransportError, parse_authenticated_validation,
    )

    check("F1.8-1: thesis parser reads the authenticated PASS",
          parse_authenticated_validation(authed, TEST_NONCE)[0] is True)

    raised = False
    try:
        parse_authenticated_validation(legacy, TEST_NONCE)
    except HarnessTransportError:
        raised = True
    check("F1.8-15: real driver without the token -> loud transport error",
          raised, "no HarnessTransportError raised")

    # 14) exactly ONE authentic Validation marker under a real mpirun -n 2
    if shutil.which("mpicxx") and shutil.which("mpirun"):
        mexe, merr = build_real_driver(workdir, "mpi")
        if mexe is None:
            check("real mpi driver builds", False, merr)
        else:
            out = subprocess.run(
                ["mpirun", "-n", "2", "--allow-run-as-root", "--oversubscribe",
                 mexe, "1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, env=auth_env, timeout=180).stdout
            mlines = [ln for ln in out.splitlines()
                      if ln.startswith("Validation:")]
            check("F1.8-14: mpirun -n 2 emits EXACTLY ONE authentic "
                  "Validation marker",
                  mlines == ["Validation: PASS nonce=%s" % TEST_NONCE],
                  "%r" % (mlines,))
            check("F1.8-14: the thesis parser accepts it",
                  parse_authenticated_validation(out, TEST_NONCE)[0] is True)


def test_transport(workdir):
    """Contract A1e/A1f: the marker travels stdout -> parser -> verdict, and
    every consumer treats the value explicitly."""
    print("\n== transport level ==")

    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    from thesis.evaluation.run_correctness import (
        BASELINE_INCOMPATIBLE,
        HarnessTransportError,
        classify_baseline_incompatible,
        count_baseline_incompatible,
        legacy_count_baseline_incompatible,
        legacy_parse_validation,
        new_marker_nonce,
        parse_authenticated_validation,
        run_verdict,
    )

    # contract F2.2: no module-level production token exists any more; a test
    # pins its own deterministic value.
    check("F2.2: no module-level production nonce",
          not hasattr(
              __import__("thesis.evaluation.run_correctness",
                         fromlist=["x"]), "MARKER_NONCE"))

    NONCE = TEST_NONCE
    AUTH = "BASELINE_INCOMPATIBLE: non_finite_reference nonce=%s\n" % NONCE
    MARKER_NONCE = NONCE  # local alias for the assertions below

    # --- parser + verdict -------------------------------------------------
    check("parser: marker absent -> 0",
          count_baseline_incompatible("Validation: PASS\n") == 0)
    check("parser: marker once -> 1",
          count_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: non_finite_reference\nValidation: PASS\n") == 1)
    check("parser: marker twice -> 2 (distinguishable from missing)",
          count_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: a\nBASELINE_INCOMPATIBLE: b\n") == 2)

    # --- contract C2b: authenticity ---------------------------------------
    check("nonce: two nonces differ (per execution)",
          new_marker_nonce() != new_marker_nonce())
    check("nonce: 128 bits of hex", len(new_marker_nonce()) == 32)

    check("authenticity: correct nonce -> authentic",
          classify_baseline_incompatible(AUTH + "Validation: PASS\n",
                                         MARKER_NONCE) == (1, 0))
    check("authenticity: wrong nonce -> unauthenticated, never authentic",
          classify_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: non_finite_reference nonce=deadbeef\n",
              MARKER_NONCE) == (0, 1))
    check("authenticity: no nonce -> unauthenticated",
          classify_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: non_finite_reference\n",
              MARKER_NONCE) == (0, 1))
    check("authenticity: candidate line among real ones is separated",
          classify_baseline_incompatible(
              AUTH + "BASELINE_INCOMPATIBLE: non_finite_reference\n",
              MARKER_NONCE) == (1, 1))
    check("authenticity: several authentic markers (MPI) are counted, not "
          "rejected",
          classify_baseline_incompatible(AUTH + AUTH, MARKER_NONCE) == (2, 0))

    # ---- contract F2.3: a production parser without a token fails LOUDLY ---
    def raises(fn, exc):
        try:
            fn()
        except exc:
            return True
        except Exception:  # noqa: BLE001
            return False
        return False

    check("F2.3: classify_baseline_incompatible without a token raises",
          raises(lambda: classify_baseline_incompatible(AUTH, None), ValueError))
    check("F2.3: classify_baseline_incompatible with an empty token raises",
          raises(lambda: classify_baseline_incompatible(AUTH, ""), ValueError))
    check("F2.3: parse_authenticated_validation without a token raises",
          raises(lambda: parse_authenticated_validation("", None), ValueError))
    check("F2.5: the LEGACY BI counter still works without a token",
          legacy_count_baseline_incompatible(
              "BASELINE_INCOMPATIBLE: non_finite_reference\n") == 1)

    # ---- contract F1.6: authenticated Validation ---------------------------
    def V(verdict, nonce=None):
        if nonce is None:
            return "Validation: %s\n" % verdict
        return "Validation: %s nonce=%s\n" % (verdict, nonce)

    check("F1.6-1: authentic PASS",
          parse_authenticated_validation(V("PASS", NONCE), NONCE)[0] is True)
    check("F1.6-1: authentic FAIL",
          parse_authenticated_validation(V("FAIL", NONCE), NONCE)[0] is False)
    check("F1.6-2: no marker at all -> None",
          parse_authenticated_validation("Segmentation fault\n", NONCE)[0] is None)

    # rule 4: a candidate line next to an authentic one never wins
    check("F1.6-4: candidate PASS before trusted FAIL -> FAIL",
          parse_authenticated_validation(
              V("PASS") + V("FAIL", NONCE), NONCE)[0] is False)
    check("F1.6-4: candidate FAIL before trusted PASS -> PASS",
          parse_authenticated_validation(
              V("FAIL") + V("PASS", NONCE), NONCE)[0] is True)
    check("F1.6-4: the candidate line is reported as an anomaly",
          parse_authenticated_validation(
              V("PASS") + V("FAIL", NONCE), NONCE)[1] != [])
    check("F1.6-4: a candidate line is NOT a harness error",
          parse_authenticated_validation(
              V("PASS") + V("FAIL", NONCE), NONCE)[0] is False)

    check("F1.6-4: foreign token next to an authentic marker -> authentic wins",
          parse_authenticated_validation(
              V("FAIL", "deadbeef") + V("PASS", NONCE), NONCE)[0] is True)
    check("F1.6: ONLY a foreign token -> no verdict",
          parse_authenticated_validation(V("PASS", "deadbeef"), NONCE)[0] is None)

    # rule 3: two authentic markers are a transport anomaly, not "first wins"
    two = parse_authenticated_validation(V("PASS", NONCE) + V("FAIL", NONCE), NONCE)
    check("F1.6-3: two authentic markers -> no verdict", two[0] is None)
    check("F1.6-3: two authentic markers are reported",
          any("AUTHENTIC" in a for a in two[1]), "%r" % (two[1],))

    # rule 7: the token never reached the child
    check("F1.6-7: trusted legacy line in an authenticated run raises",
          raises(lambda: parse_authenticated_validation(V("PASS"), NONCE),
                 HarnessTransportError))
    check("F1.6-7: the same for FAIL",
          raises(lambda: parse_authenticated_validation(V("FAIL"), NONCE),
                 HarnessTransportError))
    check("F1.6-7: NOT raised when an authentic marker is present",
          parse_authenticated_validation(
              V("PASS") + V("PASS", NONCE), NONCE)[0] is True)

    # rule 6: no substring parsing
    check("F1.6-6: 'PASS' elsewhere in the line is not a verdict",
          parse_authenticated_validation(
              "Validation: something PASS\n", NONCE)[0] is None)

    # F1.7: legacy helper accepts ONLY the exact historical line
    check("F1.7: legacy helper reads the historical line",
          legacy_parse_validation(V("PASS")) is True)
    check("F1.7: legacy helper does not read an authenticated line",
          legacy_parse_validation(V("PASS", NONCE)) is None)

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

    # contract C3b.2: BI now outranks the downstream process state. Before
    # Wave 1b `timeout` won and put an ungradeable sample back into the
    # fail-side denominator.
    check("verdict C3b.2: marker + timeout -> baseline_incompatible",
          run_verdict(None, 0, True, baseline_incompatible=True)
          == BASELINE_INCOMPATIBLE)
    check("verdict C3b.2: marker + crash exit -> baseline_incompatible",
          run_verdict(None, 139, False, baseline_incompatible=True)
          == BASELINE_INCOMPATIBLE)
    check("verdict: timeout WITHOUT a marker is still timeout (unchanged)",
          run_verdict(None, 0, True) == "timeout")
    check("verdict: crash WITHOUT a marker is still runtime_error (unchanged)",
          run_verdict(None, 139, False) == "runtime_error")

    # --- enhanced stage transports the same marker ------------------------
    from thesis.evaluation.run_enhanced_tests import run_binary

    stub_exe, err = build_stub(
        workdir, "stub",
        STUB_TEMPLATE % {"nonce": NONCE, "tail": ""})
    if stub_exe is None:
        check("enhanced: stub compiles", False, err)
    else:
        status = run_binary(stub_exe, workdir, 60.0, marker_nonce=NONCE)[0]
        check("enhanced: marker outranks an authentic PASS -> baseline_incompatible",
              status == "baseline_incompatible", "got %r" % status)

    # contract C2c at the enhanced stage: marker, then the process hangs and
    # is killed. The old code discarded stdout on timeout entirely.
    hang_exe, err = build_stub(
        workdir, "stub_hang",
        STUB_TEMPLATE % {"nonce": NONCE, "tail": "for (;;) { sleep(1); }"})
    if hang_exe is None:
        check("enhanced: hang stub compiles", False, err)
    else:
        status = run_binary(hang_exe, workdir, 5.0, marker_nonce=NONCE)[0]
        check("enhanced C2c: marker survives the timeout kill",
              status == "baseline_incompatible", "got %r" % status)

    # contract C2b/F1.6-4 at the enhanced stage: candidate lines — BI without a
    # token, BI with a guessed token, a bare Validation: PASS — must all be
    # ignored, and the AUTHENTIC FAIL must decide
    spoof_exe, err = build_stub(workdir, "stub_spoof",
                                STUB_SPOOF % {"nonce": NONCE})
    if spoof_exe is None:
        check("enhanced: spoof stub compiles", False, err)
    else:
        status = run_binary(spoof_exe, workdir, 60.0, marker_nonce=NONCE)[0]
        check("enhanced C2b: unauthenticated markers do NOT become "
              "baseline_incompatible; the authentic verdict decides",
              status == "fail", "got %r" % status)

    # contract F1.6-7/F2.4 at the enhanced stage: the token never reached the
    # child -> loud transport error, never a model verdict
    legacy_exe, err = build_stub(workdir, "stub_legacy", STUB_LEGACY_ONLY)
    if legacy_exe is None:
        check("enhanced: legacy stub compiles", False, err)
    else:
        raised = False
        try:
            run_binary(legacy_exe, workdir, 60.0, marker_nonce=NONCE)
        except HarnessTransportError:
            raised = True
        except Exception as exc:  # noqa: BLE001
            raised = "wrong exception: %r" % exc
        check("enhanced F1.6-7: legacy-only output in an authenticated run "
              "raises a transport error", raised is True, "got %r" % raised)

    # --- contract F2.6: token LIFETIME, observed from the child ------------
    echo_exe, err = build_stub(workdir, "stub_echo", STUB_NONCE_ECHO)
    if echo_exe is None:
        check("F2.6: nonce-echo stub compiles", False, err)
    else:
        # production path: no marker_nonce argument anywhere
        first = run_binary(echo_exe, workdir, 60.0)[3]
        second = run_binary(echo_exe, workdir, 60.0)[3]
        n1 = observed_child_nonces(first)
        n2 = observed_child_nonces(second)
        check("F2.6-1: the child really received a token",
              len(n1) == 1 and len(n1[0]) == 32, "%r" % (n1,))
        check("F2.6-1: two serial child launches -> different tokens",
              n1 and n2 and n1[0] != n2[0], "%r vs %r" % (n1, n2))
        check("F2.6: the child reports authenticated mode",
              "AUTHENTICATED=1" in first, first)

        # OMP is the same binary at a different launch point
        omp1 = run_binary(echo_exe, workdir, 60.0, execution_model="omp",
                          launch_settings={"omp_threads": 2})[3]
        omp2 = run_binary(echo_exe, workdir, 60.0, execution_model="omp",
                          launch_settings={"omp_threads": 2})[3]
        check("F2.6-2: two omp child launches -> different tokens",
              observed_child_nonces(omp1) != observed_child_nonces(omp2),
              "%r vs %r" % (observed_child_nonces(omp1),
                            observed_child_nonces(omp2)))

    if shutil.which("mpicxx") and shutil.which("mpirun"):
        mpi_exe, err = build_stub(workdir, "stub_echo_mpi",
                                  STUB_NONCE_ECHO_MPI, compiler="mpicxx")
        if mpi_exe is None:
            check("F2.6: mpi nonce-echo stub compiles", False, err)
        else:
            launch = {"mpi_ranks": 2}
            m1 = run_binary(mpi_exe, workdir, 120.0, execution_model="mpi",
                            launch_settings=launch)[3]
            m2 = run_binary(mpi_exe, workdir, 120.0, execution_model="mpi",
                            launch_settings=launch)[3]
            r1 = observed_child_nonces(m1)
            r2 = observed_child_nonces(m2)
            check("F2.6-3: both ranks reported a token", len(r1) == 2, "%r" % (r1,))
            check("F2.6-3: ONE mpirun launch = ONE token on ALL ranks",
                  len(set(r1)) == 1, "%r" % (r1,))
            check("F2.6-4: the next mpirun launch uses a different token",
                  set(r1) != set(r2), "%r vs %r" % (r1, r2))
            check("F2.6-3: exactly one authentic Validation marker per launch",
                  sum(1 for ln in m1.splitlines()
                      if ln.strip().startswith("Validation:")) == 1, m1)

    # --- contract F2.6-5/6/7: gates and probes get their own tokens --------
    import inspect as _inspect
    from thesis.enhanced_tests import baseline_selftest as _bst

    check("F2.6-5: the enhanced spec launcher mints a token per process",
          "new_marker_nonce()" in _inspect.getsource(run_binary))
    check("F2.6-6: the baseline gate mints a token per probe process",
          "new_marker_nonce()" in _inspect.getsource(_bst.compile_and_run))

    # --- contract F1.8-12/13/14: the REAL model drivers --------------------
    test_real_drivers(workdir)

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
    from thesis.repair.orchestrator import (
        STATUS_ACTIVE,
        STATUS_BASELINE_INCOMPATIBLE,
        STATUS_TESTS_PASS,
        TERMINAL_STATUSES,
    )

    check("repair: baseline_incompatible does not start an iteration",
          decision.status != STATUS_ACTIVE,
          "status=%r reason=%r" % (decision.status, decision.stop_reason))
    # contract F3b.1: neither `stopped_tests_pass` (asserts a test pass) nor
    # `stopped_clean` (reads as "nothing was wrong") may describe a sample the
    # oracle never made gradeable. It has its own terminal value.
    check("repair F3b.1: terminal state is stopped_baseline_incompatible",
          decision.status == STATUS_BASELINE_INCOMPATIBLE,
          "status=%r reason=%r" % (decision.status, decision.stop_reason))
    check("repair F3b.3: the new status is terminal",
          STATUS_BASELINE_INCOMPATIBLE in TERMINAL_STATUSES)
    check("repair: stop reason names the real condition, not 'ParEval pass'",
          BASELINE_INCOMPATIBLE in decision.stop_reason,
          "reason=%r" % decision.stop_reason)

    # contract F3b.6: combined_feedback also consumes correctness verdicts and
    # must reach the same terminal state
    combined = evaluate_stop(
        stop_config(), "combined_feedback", 1, 2,
        CLEAN_STATIC, dynamic_record(), record, None,
    )
    check("repair F3b.6: combined_feedback -> stopped_baseline_incompatible",
          combined.status == STATUS_BASELINE_INCOMPATIBLE,
          "status=%r" % combined.status)

    # static_feedback does not consume correctness verdicts at all, so its
    # semantics must be UNCHANGED
    static_only = evaluate_stop(
        stop_config(), "static_feedback", 1, 2,
        CLEAN_STATIC, dynamic_record(), None, None,
    )
    check("repair F3b.6: static_feedback semantics unchanged",
          static_only.status == STATUS_CLEAN, "status=%r" % static_only.status)

    passing = evaluate_stop(
        stop_config(), "test_feedback", 1, 2,
        CLEAN_STATIC, dynamic_record(), correctness_record("pass"), None,
    )
    check("repair: a genuine pass still stops as stopped_tests_pass (control)",
          passing.status == STATUS_TESTS_PASS, "status=%r" % passing.status)

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

    # --- contract C3.1: the gridpoint field --------------------------------
    from thesis.analysis_overview.build_overview import _gridpoint_summary

    check("gridpoints: all evaluable -> plain n/m",
          _gridpoint_summary([{"verdict": "pass"}, {"verdict": "pass"},
                              {"verdict": "validation_failed"}]) == "2/3",
          _gridpoint_summary([{"verdict": "pass"}, {"verdict": "pass"},
                              {"verdict": "validation_failed"}]))
    check("gridpoints: excluded points leave the denominator and are named",
          _gridpoint_summary([{"verdict": "pass"}, {"verdict": "pass"},
                              {"verdict": "validation_failed"},
                              {"verdict": BASELINE_INCOMPATIBLE}])
          == "2/3 (1 excluded)",
          _gridpoint_summary([{"verdict": "pass"}, {"verdict": "pass"},
                              {"verdict": "validation_failed"},
                              {"verdict": BASELINE_INCOMPATIBLE}]))
    check("gridpoints: nothing evaluable is never rendered as 0/0",
          _gridpoint_summary([{"verdict": BASELINE_INCOMPATIBLE}] * 4)
          == "0 evaluable (4 excluded)",
          _gridpoint_summary([{"verdict": BASELINE_INCOMPATIBLE}] * 4))
    check("gridpoints: no runs at all -> NA, no division by zero",
          _gridpoint_summary([]) == "NA", _gridpoint_summary([]))

    # --- contract C3.3: enhanced aggregation -------------------------------
    from thesis.analysis_overview.build_overview import (
        ENHANCED_COUNTED, ENHANCED_GATED, _enhanced_counts,
    )

    check("enhanced: baseline_incompatible is not in the counted set",
          BASELINE_INCOMPATIBLE not in ENHANCED_COUNTED)
    check("enhanced: baseline_incompatible and numerically_unstable stay "
          "distinct gate values",
          BASELINE_INCOMPATIBLE in ENHANCED_GATED
          and "numerically_unstable" in ENHANCED_GATED
          and len(set(ENHANCED_GATED)) == 2)

    mixed = {"enhanced_pass": 3, "enhanced_fail": 1,
             "enhanced_baseline_incompatible": 2,
             "enhanced_numerically_unstable": 1,
             "enhanced_gated": 3}
    check("enhanced: BI specs are out of the pass/fail denominator (3/4)",
          _enhanced_counts(mixed) == (3, 4), "%r" % (_enhanced_counts(mixed),))

    from thesis.analysis_overview.build_overview import (
        enhanced_by_execution_model_section,
    )

    exec_row = dict(mixed)
    exec_row.update({"model": "m1", "variant": "static_feedback", "iteration": 0,
                     "sample_id": "s_bi", "execution_model": "serial",
                     "problem_type": "fft", "benchmark": "05_x",
                     "correctness_verdict": "pass", "status": "stopped_clean"})
    section = enhanced_by_execution_model_section([exec_row])
    check("enhanced C3.3: the two gate reasons are shown separately",
          any("of which baseline_incompatible" in ln for ln in section)
          and any("of which numerically_unstable" in ln for ln in section),
          "section=%r" % section)
    check("enhanced C3.3: the split carries the real counts (2 and 1)",
          any(ln.rstrip().endswith("| 3 | 2 | 1 |") for ln in section),
          "section=%r" % section)

    # --- contract C3.4: opt_level_probe is a real run_verdict consumer ------
    import inspect
    from thesis.experiments import opt_level_probe

    probe_src = inspect.getsource(opt_level_probe.build_and_run)
    check("opt_level_probe: passes baseline_incompatible into run_verdict",
          "baseline_incompatible=" in probe_src, probe_src[-400:])
    check("opt_level_probe: authenticates the marker",
          "classify_baseline_incompatible" in probe_src, probe_src[-400:])
    check("opt_level_probe F2.1: fresh token per run",
          "new_marker_nonce()" in probe_src, probe_src[-400:])

    # --- contract F3b.3: every explicit status enumeration knows the value --
    from thesis.repair import orchestrator as orch

    check("F3b.3: status_row enumerates the new status",
          "stopped_baseline_incompatible" in inspect.getsource(orch.RepairLoop.status_row))

    from thesis.repair import run_repair

    check("F3b.3: the run_repair status table shows it",
          "stopped_baseline_incompatible" in inspect.getsource(run_repair.print_status))

    from thesis.analysis_overview.build_overview import (
        LEGACY_BI_DISPLAY_STATUS, _display_status, stop_reason_table,
    )

    check("F3b.5: a frozen legacy stopped_clean + BI reason is separated",
          _display_status({"status": "stopped_clean",
                           "stop_reason": "own sources clean (ParEval "
                                          "baseline_incompatible)"})
          == LEGACY_BI_DISPLAY_STATUS)
    check("F3b.5: an ordinary stopped_clean stays stopped_clean",
          _display_status({"status": "stopped_clean",
                           "stop_reason": "own sources clean (ParEval pass)"})
          == "stopped_clean")

    bi_rows = [
        {"model": "m1", "variant": "test_feedback", "iteration": 0,
         "sample_id": "s_bi", "execution_model": "serial",
         "problem_type": "fft", "benchmark": "05_x",
         "status": STATUS_BASELINE_INCOMPATIBLE,
         "stop_reason": "own sources clean (ParEval baseline_incompatible)",
         "correctness_verdict": BASELINE_INCOMPATIBLE},
    ]
    srt = stop_reason_table(bi_rows, "test_feedback")
    check("F3b.4: the status is reported under its own name",
          any(STATUS_BASELINE_INCOMPATIBLE in line for line in srt),
          "table=%r" % srt)
    check("F3b.4: it is not counted as stopped_clean",
          not any(line.startswith("| stopped_clean |") for line in srt),
          "table=%r" % srt)


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
