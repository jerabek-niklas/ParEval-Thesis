"""Detection verification for the static-analysis tools.

For every tool we inject a bug that is representative of the tool's detection
method into a generated-code.hpp, run it through the REAL tool code (the same
invocation, parsing, attribution and filtering the pipeline uses), and assert
the tool (a) reports a finding of the expected class, (b) attributes it to the
model file only, and (c) marks it blocking where expected.

This guards against the failure mode that a tool "runs" and reports 0 findings may in fact be structurally unable to
see the model code. "0 findings" only means "clean" once we have proven the
tool fires on a planted bug.

The tools live in three containers; this script verifies whichever tools are
available in the current one and skips the rest, so run it in each:

    # main toolchain image (compiler, clang_tidy, cppcheck, infer, MPI-Checker)
    docker run --rm -v "$(pwd):/workspace" -w /workspace pareval-thesis \
        python3 thesis/evaluation/verify_detection.py

    # PARCOACH container
    docker run --rm -u 0 -v "$(pwd):/workspace" -w /workspace \
        registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1 \
        python3 thesis/evaluation/verify_detection.py

    # LLOV container
    docker run --rm -u 0 -v "$(pwd):/workspace" -w /workspace pareval-llov \
        python3.8 thesis/evaluation/verify_detection.py

Exit code is non-zero if any *available* tool fails its detection case.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation.framework import AssembledSample, EvaluationContext  # noqa: E402
from thesis.evaluation.tools import register_default_tools  # noqa: E402
from thesis.evaluation.dynamic_tools import register_dynamic_tools  # noqa: E402

# Benchmark whose signature every planted kernel matches (has serial/omp/mpi).
BENCHMARK_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks" / "dense_la" / "00_dense_la_lu_decomp"

MODEL_FILE = "generated-code.hpp"


@dataclass
class Case:
    tool: str
    execution_model: str
    label: str
    source: str
    # a finding is "the expected one" if this substring is in its check_id
    # or message (case-insensitive); None means "any finding counts"
    expect_match: str | None
    expect_blocking: bool


def has_expected(result, match: str | None, blocking: bool) -> bool:
    candidates = result.findings

    if match is not None:
        needle = match.lower()
        candidates = [
            f for f in candidates
            if needle in f.check_id.lower() or needle in f.message.lower()
        ]

    if not candidates:
        return False

    return any(f.blocking for f in candidates) if blocking else True


def attribution_clean(result) -> bool:
    """No finding may be attributed to a non-model file."""
    return all(f.file in (None, MODEL_FILE) for f in result.findings)


# Each source is a full generated-code.hpp: the NO_INLINE-patched signature the
# benchmark expects, plus a planted bug of the tool's class.
CASES: list[Case] = [
    Case(
        tool="compiler",
        execution_model="serial",
        label="compiler: unused-variable warning",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int planted_unused_variable = 42;\n"
            "  for (size_t k = 0; k < N; ++k) A[k*N+k] = A[k*N+k];\n"
            "}\n"
        ),
        expect_match="unused",
        expect_blocking=False,
    ),
    Case(
        tool="clang_tidy",
        execution_model="serial",
        label="clang_tidy: bugprone narrowing conversion",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int planted_pn = A.size();\n"
            "  for (size_t k = 0; k < N; ++k) A[k*N+k] = (double)planted_pn;\n"
            "}\n"
        ),
        expect_match="narrowing",
        expect_blocking=True,
    ),
    Case(
        tool="cppcheck",
        execution_model="serial",
        label="cppcheck: array index out of bounds",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int planted_buf[2];\n"
            "  planted_buf[5] = 1;\n"
            "  A[0] = (double)planted_buf[0];\n"
            "  (void)N;\n"
            "}\n"
        ),
        expect_match="bounds",
        expect_blocking=True,
    ),
    Case(
        tool="infer",
        execution_model="serial",
        label="infer: interprocedural null dereference",
        source=(
            "static int planted_deref(int *p) { return *p; }\n"
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int *q = nullptr;\n"
            "  int v = planted_deref(q);\n"
            "  A[0] = (double)v;\n"
            "  (void)N;\n"
            "}\n"
        ),
        expect_match="NULL_DEREFERENCE",
        expect_blocking=True,
    ),
    Case(
        tool="clang_tidy",
        execution_model="mpi",
        label="clang_tidy (Clang SA MPI-Checker): request with no matching wait",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  MPI_Request req;\n"
            "  MPI_Isend(A.data(), (int)N, MPI_DOUBLE, 0, 0, MPI_COMM_WORLD, &req);\n"
            "}\n"
        ),
        expect_match="MPI-Checker",
        expect_blocking=True,
    ),
    Case(
        tool="parcoach",
        execution_model="mpi",
        label="parcoach: rank-conditional collective",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int rank;\n"
            "  MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n"
            "  if (rank == 0)\n"
            "    MPI_Bcast(A.data(), (int)N, MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
            "}\n"
        ),
        expect_match="collective-ordering",
        expect_blocking=True,
    ),
    Case(
        tool="llov",
        execution_model="omp",
        label="llov: loop-carried data race",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  #pragma omp parallel for\n"
            "  for (size_t i = 1; i < N; ++i) A[i] = A[i-1] * 2.0;\n"
            "}\n"
        ),
        expect_match="data-race",
        expect_blocking=True,
    ),
    # ---- dynamic tier (sanitizer-instrumented executions) ----
    Case(
        tool="asan_ubsan",
        execution_model="serial",
        label="asan_ubsan: heap-buffer-overflow at runtime",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int *planted = new int[4];\n"
            "  A[0] = (double)planted[7];\n"
            "  delete[] planted;\n"
            "  (void)N;\n"
            "}\n"
        ),
        expect_match="asan-heap-buffer-overflow",
        expect_blocking=True,
    ),
    Case(
        tool="asan_ubsan",
        execution_model="serial",
        label="asan_ubsan (UBSan): signed integer overflow at runtime",
        source=(
            # <climits> comes in via utilities.hpp
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int planted = INT_MAX;\n"
            "  planted += 1;\n"
            "  A[0] = (double)planted;\n"
            "  (void)N;\n"
            "}\n"
        ),
        expect_match="ubsan-runtime-error",
        expect_blocking=True,
    ),
    Case(
        tool="tsan",
        execution_model="omp",
        label="tsan (archer): OpenMP data race at runtime",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  double planted_sum = 0.0;\n"
            "  #pragma omp parallel for\n"
            "  for (size_t i = 0; i < N; ++i) planted_sum += A[i];\n"
            "  A[0] = planted_sum;\n"
            "}\n"
        ),
        expect_match="tsan-data-race",
        expect_blocking=True,
    ),
    Case(
        tool="memcheck",
        execution_model="serial",
        label="memcheck (valgrind DBI): invalid read at runtime",
        source=(
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int *planted = new int[4];\n"
            "  A[0] = (double)planted[7];\n"
            "  delete[] planted;\n"
            "  (void)N;\n"
            "}\n"
        ),
        expect_match="memcheck-invalid-read",
        expect_blocking=True,
    ),
    Case(
        tool="must",
        execution_model="mpi",
        label="must: rank-conditional MPI deadlock at runtime",
        source=(
            # rank 0 waits for a message that is never sent -> deadlock;
            # terminated deterministically by --must:timeout and reported
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  int rank;\n"
            "  MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n"
            "  if (rank == 0) {\n"
            "    MPI_Recv(A.data(), 1, MPI_DOUBLE, 1, 99, MPI_COMM_WORLD,\n"
            "             MPI_STATUS_IGNORE);\n"
            "  }\n"
            "  (void)N;\n"
            "}\n"
        ),
        expect_match="must-deadlock",
        expect_blocking=True,
    ),
]


# ---------------------------------------------------------------------------
# Clean kernels (false-positive check): correct, bug-free implementations.
# Every applicable tool must report ZERO blocking findings and no tool error.
# Non-blocking style findings (e.g. clang-tidy misc-*) are allowed and shown.
# ---------------------------------------------------------------------------

CLEAN_SOURCES = {
    "serial": (
        "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
        "  for (size_t k = 0; k < N; ++k) {\n"
        "    for (size_t i = k + 1; i < N; ++i) {\n"
        "      A[i * N + k] /= A[k * N + k];\n"
        "      const double factor = A[i * N + k];\n"
        "      for (size_t j = k + 1; j < N; ++j) {\n"
        "        A[i * N + j] -= factor * A[k * N + j];\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    ),
    # row updates for a fixed k are independent; the implicit barrier of
    # `parallel for` orders the k iterations -> race free
    "omp": (
        "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
        "  for (size_t k = 0; k < N; ++k) {\n"
        "    #pragma omp parallel for\n"
        "    for (size_t i = k + 1; i < N; ++i) {\n"
        "      A[i * N + k] /= A[k * N + k];\n"
        "      const double factor = A[i * N + k];\n"
        "      for (size_t j = k + 1; j < N; ++j) {\n"
        "        A[i * N + j] -= factor * A[k * N + j];\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    ),
    # every rank computes the full result redundantly, then a correct
    # unconditional collective: deadlock-free, matching on all ranks
    "mpi": (
        "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
        "  for (size_t k = 0; k < N; ++k) {\n"
        "    for (size_t i = k + 1; i < N; ++i) {\n"
        "      A[i * N + k] /= A[k * N + k];\n"
        "      const double factor = A[i * N + k];\n"
        "      for (size_t j = k + 1; j < N; ++j) {\n"
        "        A[i * N + j] -= factor * A[k * N + j];\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "  MPI_Bcast(A.data(), static_cast<int>(N * N), MPI_DOUBLE, 0,\n"
        "            MPI_COMM_WORLD);\n"
        "}\n"
    ),
}

# ---------------------------------------------------------------------------
# Broken kernel (fail-safe check): does not compile. No tool may look
# "analyzed and clean" on it: required outcome per tool is a blocking
# finding, a tool error, or both. cppcheck is exempt (tolerant parser by
# design; buildability is gated by the compiler tool) — behavior is printed.
# ---------------------------------------------------------------------------

BROKEN_SOURCE = (
    "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
    "  this is deliberately not valid C++ !!\n"
    "}\n"
)

# tool name -> acceptable outcome on the broken kernel
BROKEN_EXPECTATION = {
    "compiler": "blocking",       # must produce a blocking compile error
    "clang_tidy": "blocking_or_error",
    "cppcheck": "exempt",
    "infer": "error",
    "parcoach": "error",
    "llov": "error",
    "asan_ubsan": "error",
    "tsan": "error",
    "memcheck": "error",
    "must": "error",
}

ALL_TOOLS = list(BROKEN_EXPECTATION)

# Tool-specific clean kernels. LLOV is a polyhedral verifier: its clean
# specimen must lie in the affine, provable domain (elementwise parallel
# loop). The generic clean OMP kernel (correct blocked LU) is race-free but
# its row-disjointness is not provable through std::vector pointer
# indirection, so LLOV conservatively reports a race — a documented
# precision limit of the method, not a harness failure.
TOOL_CLEAN_OVERRIDES = {
    "llov": {
        "omp": (
            "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"
            "  #pragma omp parallel for\n"
            "  for (size_t i = 0; i < N; ++i) {\n"
            "    A[i] = A[i] * 2.0;\n"
            "  }\n"
            "}\n"
        ),
    },
}


def make_raw_sample(tmp_dir: str, source: str, execution_model: str, tag: str) -> AssembledSample:
    source_path = Path(tmp_dir) / MODEL_FILE
    source_path.write_text(source, encoding="utf-8")

    return AssembledSample(
        sample_id=f"verify__{tag}__{execution_model}",
        model_id="verify",
        run_id="verify",
        execution_model=execution_model,
        problem_type="dense_la",
        name="00_dense_la_lu_decomp",
        source_path=source_path,
        benchmark_dir=BENCHMARK_DIR,
        model_driver_file="",
        assembly_entry={},
    )


def make_sample(tmp_dir: str, case: Case) -> AssembledSample:
    return make_raw_sample(tmp_dir, case.source, case.execution_model, case.tool)


def is_not_applicable(result) -> bool:
    return not result.ran and "not applicable" in (result.error or "")


def verify_clean(
    context: EvaluationContext, tool_filter: list[str] | None
) -> tuple[int, int, int]:
    """False-positive check: clean kernels through every available tool."""
    print()
    print("Clean-kernel check (no blocking findings, no tool error allowed)")
    print("=" * 66)

    passed = failed = skipped = 0

    for execution_model, source in CLEAN_SOURCES.items():
        for tool_name in ALL_TOOLS:
            if tool_filter and tool_name not in tool_filter:
                continue

            tool = framework.get_tool(tool_name)

            if not tool.is_available():
                skipped += 1
                continue

            tool_source = TOOL_CLEAN_OVERRIDES.get(tool_name, {}).get(
                execution_model, source
            )

            with tempfile.TemporaryDirectory() as tmp:
                sample = make_raw_sample(
                    tmp, tool_source, execution_model, f"clean_{tool_name}"
                )
                result = tool.run(sample, context)

            if is_not_applicable(result):
                continue

            blocking = [f for f in result.findings if f.blocking]
            ok = result.ran and result.error is None and not blocking

            non_blocking = len(result.findings) - len(blocking)
            note = f" ({non_blocking} non-blocking style findings)" if non_blocking else ""

            print(f"  [{'PASS' if ok else 'FAIL'}] clean/{execution_model}: {tool_name}{note}")

            if ok:
                passed += 1
            else:
                failed += 1
                print(f"           ran={result.ran} error={result.error}")
                for f in blocking:
                    print(f"           BLOCKING: {f.check_id} at {f.file}:{f.line} :: {f.message[:80]}")

    return passed, failed, skipped


def verify_broken(context: EvaluationContext) -> tuple[int, int, int]:
    """Fail-safe check: a non-compiling kernel must never look clean."""
    print()
    print("Broken-kernel check (blocking finding or tool error required)")
    print("=" * 66)

    # run each tool under an execution model it applies to
    exec_model_for = {
        "compiler": "serial", "clang_tidy": "serial", "cppcheck": "serial",
        "infer": "serial", "asan_ubsan": "serial", "memcheck": "serial",
        "tsan": "omp", "llov": "omp",
        "parcoach": "mpi", "must": "mpi",
    }

    passed = failed = skipped = 0

    for tool_name, expectation in BROKEN_EXPECTATION.items():
        tool = framework.get_tool(tool_name)

        if not tool.is_available():
            skipped += 1
            continue

        with tempfile.TemporaryDirectory() as tmp:
            sample = make_raw_sample(
                tmp, BROKEN_SOURCE, exec_model_for[tool_name], f"broken_{tool_name}"
            )
            result = tool.run(sample, context)

        if is_not_applicable(result):
            continue

        has_blocking = any(f.blocking for f in result.findings)
        has_error = result.error is not None

        if expectation == "blocking":
            ok = has_blocking
        elif expectation == "error":
            ok = has_error
        elif expectation == "blocking_or_error":
            ok = has_blocking or has_error
        else:  # exempt: report observed behavior, never fail
            print(
                f"  [info] broken: {tool_name} (exempt) -> "
                f"findings={len(result.findings)} error={result.error!r}"
            )
            continue

        print(
            f"  [{'PASS' if ok else 'FAIL'}] broken: {tool_name} "
            f"(expected {expectation}; got blocking={has_blocking} error={has_error})"
        )

        if ok:
            passed += 1
        else:
            failed += 1
            print(f"           exit={result.exit_code} findings={len(result.findings)}")

    return passed, failed, skipped


def main() -> None:
    register_default_tools("g++")
    register_dynamic_tools()

    context = EvaluationContext(
        repo_root=REPO_ROOT,
        drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
        primary_compiler="g++",
        config={},
    )

    print("Detection verification (plant a bug, prove the tool catches it)")
    print("=" * 66)

    verified = 0
    failed = 0
    skipped = 0

    for case in CASES:
        tool = framework.get_tool(case.tool)

        if not tool.is_available():
            print(f"  [skip] {case.label}  (tool '{case.tool}' unavailable here)")
            skipped += 1
            continue

        with tempfile.TemporaryDirectory() as tmp:
            sample = make_sample(tmp, case)
            result = tool.run(sample, context)

        detected = has_expected(result, case.expect_match, case.expect_blocking)
        clean = attribution_clean(result)
        ran_ok = result.ran and result.error is None

        ok = detected and clean and ran_ok

        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {case.label}")

        if not ok:
            failed += 1
            print(f"           ran={result.ran} error={result.error}")
            print(f"           detected={detected} attribution_clean={clean}")
            print(
                "           findings: "
                + (
                    ", ".join(
                        f"{f.check_id}(file={f.file},blk={f.blocking})"
                        for f in result.findings
                    )
                    or "<none>"
                )
            )
        else:
            verified += 1
            hit = next(
                f for f in result.findings
                if case.expect_match is None
                or case.expect_match.lower() in f.check_id.lower()
                or case.expect_match.lower() in f.message.lower()
            )
            print(
                f"           -> {hit.check_id} at {hit.file}:{hit.line} "
                f"(blocking={hit.blocking})"
            )

    print("=" * 66)
    print(f"verified: {verified}, failed: {failed}, skipped (other containers): {skipped}")

    clean_passed, clean_failed, _ = verify_clean(context)
    broken_passed, broken_failed, _ = verify_broken(context)

    print()
    print("=" * 66)
    print(
        f"TOTAL  detection: {verified}/{verified + failed}  "
        f"clean: {clean_passed}/{clean_passed + clean_failed}  "
        f"fail-safe: {broken_passed}/{broken_passed + broken_failed}"
    )

    if failed or clean_failed or broken_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
