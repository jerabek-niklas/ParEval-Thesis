#!/usr/bin/env python3
"""Fixture harness for the tool-state model (tool_state.v1).

Runs planted kernels through the REAL tools of the current container and
asserts the analysis_state each must yield - the fail-closed guarantees of
the Static/Repair tool-state wave:

  * a tool that produced no complete verdict (TIMEOUT / TOOL_ERROR /
    NOT_ANALYZED / PARTIAL) never looks like a clean COMPLETED run,
  * a toolchain failure (compiler timeout, missing binary) never becomes a
    synthetic model compile error,
  * a front-end rejection by a specialised tool is a gap (or, when the
    authoritative compiler also failed, subsumed as NOT_ANALYZED), never a
    second model defect,
  * LLOV "Region/Directive Not Analyzed" is never "Race Free",
  * the reduced-TU preamble makes std::sort-style kernels analyzable by
    PARCOACH and LLOV (they build with the authoritative g++).

Run inside each container with the repository mounted at /workspace:

  pareval-thesis:      python3 thesis/evaluation/verify_tool_states.py \
                           --tools compiler gcc_analyzer clang_tidy cppcheck infer
  parcoach-demo:2.4.1: python3 thesis/evaluation/verify_tool_states.py --tools parcoach
  pareval-llov:        python3 thesis/evaluation/verify_tool_states.py --tools llov

`--json PATH` writes the measured evidence (versions, per-fixture state,
details, pass/fail). Exit status 1 when any expectation fails.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation import tools  # noqa: E402
from thesis.evaluation.framework import (  # noqa: E402
    STATE_COMPLETED,
    STATE_NOT_ANALYZED,
    STATE_NOT_APPLICABLE,
    STATE_PARTIAL,
    STATE_TIMEOUT,
    STATE_TOOL_ERROR,
    CommandResult,
    EvaluationContext,
)
from thesis.evaluation.tool_config import mark_low_confidence, resolve_tool_settings  # noqa: E402
from thesis.evaluation.tools import register_default_tools  # noqa: E402
from thesis.evaluation.verify_detection import (  # noqa: E402
    BROKEN_SOURCE,
    CASES,
    CLEAN_SOURCES,
    make_raw_sample,
)

SIG = "void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {\n"


def case_source(tool: str, label_fragment: str) -> str:
    for case in CASES:
        if case.tool == tool and label_fragment in case.label:
            return case.source
    raise KeyError((tool, label_fragment))


# ---------------------------------------------------------------------------
# fixture kernels (measured in the tool-state audits, see the readiness report)
# ---------------------------------------------------------------------------

GCC_MULTISTEP_NULL = (
    "static double *pick_buffer(std::vector<double> &A, size_t N) {\n"
    "  if (N % 2 == 0) {\n"
    "    return nullptr;\n"
    "  }\n"
    "  return A.data();\n"
    "}\n"
    "\n"
    "static double sum_buffer(double *buf, size_t N) {\n"
    "  double s = 0.0;\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    s += buf[i];\n"
    "  }\n"
    "  return s;\n"
    "}\n"
    "\n"
    + SIG
    + "  double *buf = pick_buffer(A, N);\n"
    "  if (buf == nullptr) {\n"
    "    A[0] = 0.0;\n"
    "  }\n"
    "  A[1] = sum_buffer(buf, N);\n"
    "}\n"
)

GCC_TOO_COMPLEX = (
    "#include <numeric>\n"
    + SIG
    + "  std::vector<double> work(N * N, 0.0);\n"
    "  std::vector<size_t> perm(N);\n"
    "  std::iota(perm.begin(), perm.end(), 0);\n"
    "  for (size_t k = 0; k < N; ++k) {\n"
    "    size_t piv = k;\n"
    "    for (size_t i = k + 1; i < N; ++i) if (std::abs(A[i*N+k]) > std::abs(A[piv*N+k])) piv = i;\n"
    "    if (piv != k) { std::swap(perm[piv], perm[k]); for (size_t j = 0; j < N; ++j) std::swap(A[piv*N+j], A[k*N+j]); }\n"
    "    for (size_t i = k + 1; i < N; ++i) {\n"
    "      A[i*N+k] /= A[k*N+k];\n"
    "      for (size_t j = k + 1; j < N; ++j) work[i*N+j] = A[i*N+j] - A[i*N+k] * A[k*N+j];\n"
    "      for (size_t j = k + 1; j < N; ++j) A[i*N+j] = work[i*N+j];\n"
    "    }\n"
    "  }\n"
    "}\n"
)

# STL-heavy kernel with a planted null dereference: measured in the audit,
# gcc -fanalyzer bails out early on the STL code and MISSES the planted
# defect. The fail-closed requirement is only that the record must not read
# as a clean COMPLETED run.
GCC_BAILOUT_WITH_PLANTED_DEFECT = (
    "#include <algorithm>\n"
    + SIG
    + "  std::vector<double> t1(A);\n"
    "  std::vector<double> t2(N, 1.0);\n"
    "  std::vector<double> t3(N * N, 0.0);\n"
    "  std::sort(t1.begin(), t1.end(), [](double a, double b) { return a < b; });\n"
    "  for (size_t k = 0; k < N; ++k) t3[k] = t1[k] + t2[k];\n"
    "  int *planted = nullptr;\n"
    "  *planted = 7;\n"
    "  A[0] = t3[0];\n"
    "}\n"
)

# GCC-only builtin: builds with the authoritative g++, rejected by clang's
# front-end -> clang_tidy gap, never a model defect
CLANG_GCC_ONLY_BUILTIN = (
    SIG
    + "  typedef int v4si __attribute__((vector_size(16)));\n"
    "  v4si a = {1, 2, 3, 4};\n"
    "  v4si m = {3, 2, 1, 0};\n"
    "  v4si r = __builtin_shuffle(a, m);\n"
    "  A[0] = (double)r[0];\n"
    "  (void)N;\n"
    "}\n"
)

CPPCHECK_ERROR_DIRECTIVE = (
    SIG
    + "#error planted_error_directive\n"
    "  A[0] = 1.0; (void)N;\n"
    "}\n"
)

CPPCHECK_PROSE_APOSTROPHE = (
    SIG
    + "  A[0] = 1.0; (void)N;\n"
    "So that's good.\n"
    "}\n"
)

PARCOACH_A_UNCONDITIONAL = (
    SIG
    + "  MPI_Bcast(A.data(), static_cast<int>(N), MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
    "}\n"
)
PARCOACH_B_RANK_CONDITIONAL = (
    SIG
    + "  int rank;\n"
    "  MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n"
    "  if (rank == 0)\n"
    "    MPI_Bcast(A.data(), (int)N, MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
    "}\n"
)
PARCOACH_C_BOTH_BRANCHES = (
    SIG
    + "  int rank;\n"
    "  MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n"
    "  if (rank == 0) {\n"
    "    A[0] = 1.0;\n"
    "    MPI_Bcast(A.data(), (int)N, MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
    "  } else {\n"
    "    A[0] = 2.0;\n"
    "    MPI_Bcast(A.data(), (int)N, MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
    "  }\n"
    "}\n"
)
PARCOACH_STD_SORT_NO_INCLUDE = (
    SIG
    + "  std::sort(A.begin(), A.end());\n"
    "  MPI_Bcast(A.data(), static_cast<int>(N), MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
    "}\n"
)
# histogram/20 shape: cpu.cc includes <array>; pilot_001 recorded these as
# reduced-TU compile failures, with the preamble they complete (measured)
PARCOACH_STD_ARRAY_NO_INCLUDE = (
    SIG
    + "  std::array<double, 4> bins{};\n"
    "  bins[0] = A.empty() ? 0.0 : A[0];\n"
    "  MPI_Bcast(bins.data(), 4, MPI_DOUBLE, 0, MPI_COMM_WORLD);\n"
    "  A[0] = bins[0]; (void)N;\n"
    "}\n"
)

LLOV_RACE_FREE = (
    SIG
    + "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    A[i] = A[i] * 2.0;\n"
    "  }\n"
    "}\n"
)
LLOV_RACE_SHARED_SCALAR = (
    SIG
    + "  double s = 0.0;\n"
    "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    s += A[i];\n"
    "  }\n"
    "  A[0] = s;\n"
    "}\n"
)
LLOV_NOT_ANALYZED_CALL = (
    "double helper(double v);\n"
    + SIG
    + "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    A[i] = helper(A[i]);\n"
    "  }\n"
    "}\n"
)
LLOV_MIXED = (
    "double helper(double v);\n"
    + SIG
    + "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    A[i] = A[i] * 2.0;\n"
    "  }\n"
    "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    A[i] = helper(A[i]);\n"
    "  }\n"
    "}\n"
)
LLOV_COMPILE_ERROR = (
    SIG
    + "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    A[i] = undefined_symbol(A[i]);\n"
    "  }\n"
    "}\n"
)
LLOV_STD_SORT_NO_INCLUDE = (
    SIG
    + "  std::sort(A.begin(), A.end());\n"
    "  #pragma omp parallel for\n"
    "  for (size_t i = 0; i < N; ++i) {\n"
    "    A[i] = A[i] * 2.0;\n"
    "  }\n"
    "}\n"
)
LLOV_TASKS_NO_REGION_VERDICT = (
    SIG
    + "  #pragma omp parallel\n"
    "  {\n"
    "    #pragma omp single\n"
    "    {\n"
    "      for (size_t i = 0; i < N; ++i) {\n"
    "        #pragma omp task firstprivate(i)\n"
    "        A[i] = A[i] * 2.0;\n"
    "      }\n"
    "    }\n"
    "  }\n"
    "}\n"
)


# ---------------------------------------------------------------------------
# fixture model
# ---------------------------------------------------------------------------

@dataclass
class Fixture:
    name: str
    tool: str
    execution_model: str
    source: str
    expect_state: str | None = None          # exact state, or None for a custom check
    blocking: tuple[str, int] | None = None  # ("==", 0) / (">=", 1)
    details: dict[str, Any] = field(default_factory=dict)  # analysis_details subset
    forbid_check_id: str | None = None       # a finding id that must NOT appear
    path_events: bool = False                # at least one finding must carry path events
    tool_setup: Callable[[Any], Any] | None = None  # returns the tool instance to run
    patch_run_command: Callable[..., CommandResult] | None = None
    custom: Callable[[Any], tuple[bool, str]] | None = None
    note: str = ""
    benchmark: str | None = None             # "<problem>/<dir>" under drivers/cpp/benchmarks


def with_attr(**attrs):
    def setup(tool):
        clone = copy.copy(tool)
        for key, value in attrs.items():
            setattr(clone, key, value)
        return clone
    return setup


def fake_command(stdout: str = "", stderr: str = "", returncode: int = 0):
    def run(argv, timeout, cwd=None, extra_env=None, **kwargs):
        return CommandResult(
            returncode=returncode, stdout=stdout, stderr=stderr,
            timed_out=False, duration_seconds=0.01,
        )
    return run


def state_of(result) -> str:
    resolved = result.resolved_state()
    return resolved[0] if isinstance(resolved, tuple) else resolved


def not_clean(result) -> tuple[bool, str]:
    """fail-closed: a run may be anything EXCEPT a clean COMPLETED verdict"""
    state = state_of(result)
    clean = state == STATE_COMPLETED and not result.blocking_findings
    return (not clean), "state=%s blocking=%d" % (state, len(result.blocking_findings))


def low_confidence_marked(result) -> tuple[bool, str]:
    settings = resolve_tool_settings({}, "static_analysis")["parcoach"]
    marked = mark_low_confidence(list(result.findings), settings)
    ok = state_of(result) == STATE_COMPLETED and marked >= 1 and all(
        f.low_confidence for f in result.findings if f.blocking
    )
    return ok, "state=%s marked=%d" % (state_of(result), marked)


def compiles_in_reduced_tu(result) -> tuple[bool, str]:
    """preamble regression: the reduced TU must COMPILE (no TOOL_ERROR from
    the compile step); the analysis itself may then complete or hit the
    tool's own genuine timeout (PARCOACH hangs on std::sort instantiations,
    measured on the sort benchmarks of pilot_001 as well)"""
    state = state_of(result)
    details = result.analysis_details or {}
    ok = state in (STATE_COMPLETED, STATE_TIMEOUT) and not details.get("tu_rejected")
    if state == STATE_TIMEOUT and "compile" in (result.analysis_gap_reason or ""):
        ok = False
    return ok, "state=%s reason=%s" % (state, result.analysis_gap_reason)


def build_fixtures(primary_compiler: str) -> list[Fixture]:
    clean_serial = CLEAN_SOURCES["serial"]
    fx: list[Fixture] = []

    # ---- compiler -------------------------------------------------------
    fx += [
        Fixture("compiler clean", "compiler", "serial", clean_serial,
                STATE_COMPLETED, ("==", 0), {"build_ok": True}),
        Fixture("compiler model compile error", "compiler", "serial", BROKEN_SOURCE,
                STATE_COMPLETED, (">=", 1), {"build_ok": False},
                note="the model's own build failure is a COMPLETED verdict"),
        Fixture("compiler timeout", "compiler", "serial", clean_serial,
                STATE_TIMEOUT, ("==", 0), forbid_check_id="compile-failed",
                tool_setup=with_attr(build_timeout=0.01),
                note="no synthetic compile-failed finding"),
        Fixture("compiler binary missing", "compiler", "serial", clean_serial,
                STATE_TOOL_ERROR, ("==", 0), {"toolchain_failure": True},
                forbid_check_id="compile-failed",
                tool_setup=with_attr(primary_compiler="/nonexistent/bin/g++")),
    ]

    # ---- gcc_analyzer ---------------------------------------------------
    fx += [
        Fixture("gcc_analyzer clean", "gcc_analyzer", "serial", clean_serial,
                STATE_COMPLETED, ("==", 0), {"bailed_out_early": False}),
        Fixture("gcc_analyzer multi-step null path", "gcc_analyzer", "serial",
                GCC_MULTISTEP_NULL, STATE_COMPLETED, (">=", 1), path_events=True,
                note="one defect = one finding with attached path events"),
        Fixture("gcc_analyzer too-complex (PARTIAL)", "gcc_analyzer", "serial",
                GCC_TOO_COMPLEX, STATE_PARTIAL),
        Fixture("gcc_analyzer bail-out with planted defect never clean", "gcc_analyzer",
                "serial", GCC_BAILOUT_WITH_PLANTED_DEFECT, custom=not_clean,
                note="measured false negative; must be PARTIAL or carry the finding"),
        Fixture("gcc_analyzer broken TU", "gcc_analyzer", "serial", BROKEN_SOURCE,
                STATE_TOOL_ERROR, ("==", 0), {"tu_rejected": True}),
        Fixture("gcc_analyzer timeout", "gcc_analyzer", "serial", clean_serial,
                STATE_TIMEOUT, ("==", 0), tool_setup=with_attr(timeout=0.01)),
    ]

    # ---- clang_tidy -----------------------------------------------------
    fx += [
        Fixture("clang_tidy clean", "clang_tidy", "serial", clean_serial,
                STATE_COMPLETED, ("==", 0)),
        Fixture("clang_tidy narrowing", "clang_tidy", "serial",
                case_source("clang_tidy", "narrowing"), STATE_COMPLETED, (">=", 1)),
        Fixture("clang_tidy GCC-only builtin (front-end gap, not a defect)", "clang_tidy",
                "serial", CLANG_GCC_ONLY_BUILTIN, STATE_TOOL_ERROR, ("==", 0),
                {"tu_rejected": True}),
        Fixture("clang_tidy broken TU", "clang_tidy", "serial", BROKEN_SOURCE,
                STATE_TOOL_ERROR, ("==", 0), {"tu_rejected": True}),
        Fixture("clang_tidy timeout", "clang_tidy", "serial", clean_serial,
                STATE_TIMEOUT, ("==", 0), tool_setup=with_attr(timeout=0.01)),
    ]

    # ---- cppcheck -------------------------------------------------------
    fx += [
        Fixture("cppcheck clean", "cppcheck", "serial", clean_serial,
                STATE_COMPLETED, ("==", 0), {"xml": "ok"}),
        Fixture("cppcheck bounds", "cppcheck", "serial",
                case_source("cppcheck", "out of bounds"), STATE_COMPLETED, (">=", 1)),
        Fixture("cppcheck broken TU (tool-side syntaxError)", "cppcheck", "serial",
                BROKEN_SOURCE, STATE_PARTIAL, ("==", 0), {"tu_rejected": True}),
        Fixture("cppcheck genuine #error stays a defect", "cppcheck", "serial",
                CPPCHECK_ERROR_DIRECTIVE, STATE_COMPLETED, (">=", 1)),
        Fixture("cppcheck prose apostrophe (lexer failure, not a defect)", "cppcheck",
                "serial", CPPCHECK_PROSE_APOSTROPHE, STATE_PARTIAL, ("==", 0)),
        Fixture("cppcheck malformed XML", "cppcheck", "serial", clean_serial,
                STATE_TOOL_ERROR, ("==", 0),
                patch_run_command=fake_command(stderr="<?xml version=\"1.0\"?><results version=\"2\"><errors><error id=\"x\"")),
        Fixture("cppcheck no XML at all (CLI error)", "cppcheck", "serial", clean_serial,
                STATE_TOOL_ERROR, ("==", 0),
                patch_run_command=fake_command(stdout="cppcheck: error: unrecognized command line option", returncode=1)),
        Fixture("cppcheck timeout", "cppcheck", "serial", clean_serial,
                STATE_TIMEOUT, ("==", 0), tool_setup=with_attr(timeout=0.01)),
    ]

    # ---- infer ----------------------------------------------------------
    fx += [
        Fixture("infer clean", "infer", "serial", clean_serial,
                STATE_COMPLETED, ("==", 0), {"report_present": True}),
        Fixture("infer OpenMP kernel: frontend abort is never clean", "infer", "omp",
                CLEAN_SOURCES["omp"], STATE_NOT_ANALYZED, ("==", 0),
                note="infer's clang-11 drops the whole kernel method (measured on 130/130 pilot_001 OMP records)"),
        Fixture("infer null dereference", "infer", "serial",
                case_source("infer", "null"), STATE_COMPLETED, (">=", 1)),
        Fixture("infer broken TU", "infer", "serial", BROKEN_SOURCE,
                STATE_TOOL_ERROR, ("==", 0)),
        Fixture("infer report missing", "infer", "serial", clean_serial,
                STATE_TOOL_ERROR, ("==", 0), {"report_present": False},
                patch_run_command=fake_command(stdout="", stderr="Capturing in make/cc mode...")),
        Fixture("infer timeout", "infer", "serial", clean_serial,
                STATE_TIMEOUT, ("==", 0), tool_setup=with_attr(timeout=0.01)),
    ]

    # ---- parcoach -------------------------------------------------------
    fx += [
        Fixture("parcoach A unconditional collective", "parcoach", "mpi",
                PARCOACH_A_UNCONDITIONAL, STATE_COMPLETED, ("==", 0)),
        Fixture("parcoach B rank-conditional collective (low confidence)", "parcoach",
                "mpi", PARCOACH_B_RANK_CONDITIONAL, custom=low_confidence_marked),
        Fixture("parcoach C same collective in both branches", "parcoach", "mpi",
                PARCOACH_C_BOTH_BRANCHES, STATE_COMPLETED, ("==", 0)),
        Fixture("parcoach std::sort without include (preamble regression)", "parcoach",
                "mpi", PARCOACH_STD_SORT_NO_INCLUDE, custom=compiles_in_reduced_tu,
                note="pilot_001 recorded this shape as a reduced-TU compile failure; "
                     "with the preamble it compiles and PARCOACH then hits its own "
                     "genuine timeout on the std::sort instantiation"),
        Fixture("parcoach std::array without include (preamble regression)", "parcoach",
                "mpi", PARCOACH_STD_ARRAY_NO_INCLUDE, STATE_COMPLETED, ("==", 0),
                note="histogram/20 shape (cpu.cc includes <array>); pilot_001 recorded "
                     "it as a reduced-TU compile failure",
                benchmark="histogram/20_histogram_pixel_histogram"),
        Fixture("parcoach broken TU", "parcoach", "mpi", BROKEN_SOURCE,
                STATE_TOOL_ERROR, ("==", 0)),
        Fixture("parcoach D timeout", "parcoach", "mpi", PARCOACH_A_UNCONDITIONAL,
                STATE_TIMEOUT, ("==", 0), tool_setup=with_attr(timeout=0.01)),
        Fixture("parcoach not applicable (omp)", "parcoach", "omp", LLOV_RACE_FREE,
                STATE_NOT_APPLICABLE, ("==", 0)),
    ]

    # ---- llov -----------------------------------------------------------
    fx += [
        Fixture("llov race free", "llov", "omp", LLOV_RACE_FREE,
                STATE_COMPLETED, ("==", 0)),
        Fixture("llov data race", "llov", "omp", LLOV_RACE_SHARED_SCALAR,
                STATE_COMPLETED, (">=", 1)),
        Fixture("llov region not analyzed (never race free)", "llov", "omp",
                LLOV_NOT_ANALYZED_CALL, STATE_NOT_ANALYZED, ("==", 0)),
        Fixture("llov mixed free + not analyzed (PARTIAL)", "llov", "omp",
                LLOV_MIXED, STATE_PARTIAL, ("==", 0)),
        Fixture("llov compile error", "llov", "omp", LLOV_COMPILE_ERROR,
                STATE_TOOL_ERROR, ("==", 0)),
        Fixture("llov std::sort without include (preamble regression)", "llov", "omp",
                LLOV_STD_SORT_NO_INCLUDE, STATE_COMPLETED, ("==", 0),
                note="pilot_001 recorded this shape as an LLOV compile failure"),
        Fixture("llov no region verdict at all (tasks)", "llov", "omp",
                LLOV_TASKS_NO_REGION_VERDICT, STATE_NOT_ANALYZED, ("==", 0)),
        Fixture("llov timeout", "llov", "omp", LLOV_RACE_FREE,
                STATE_TIMEOUT, ("==", 0), tool_setup=with_attr(timeout=0.001)),
        Fixture("llov not applicable (serial)", "llov", "serial", clean_serial,
                STATE_NOT_APPLICABLE, ("==", 0)),
    ]
    return fx


# ---------------------------------------------------------------------------
# parser unit checks that need no container (LLOV wording / location forms)
# ---------------------------------------------------------------------------

LLOV_SYNTHETIC = (
    "Directive Not Analyzed by the verifier. Loop -> <unnamed loop>\n"
    "File : /tmp/x/generated-code.hpp:16:3\n"
    "Data Race detected.\n"
    "Source : /tmp/x/generated-code.hpp:20:5\n"
    "Sink : /tmp/x/generated-code.hpp:20:5\n"
    "Region is Data Race Free.\n"
)


def parser_checks() -> list[dict[str, Any]]:
    out = []
    regions = tools.parse_llov_regions(LLOV_SYNTHETIC)
    out.append({
        "name": "llov parser counts 'Directive Not Analyzed' and line:col forms",
        "passed": regions == {"race": 1, "free": 1, "not_analyzed": 1},
        "measured": regions,
    })
    findings = tools.findings_in_model_file(tools.parse_llov_output(LLOV_SYNTHETIC), "generated-code.hpp")
    ids = sorted((f.check_id, f.line) for f in findings)
    out.append({
        "name": "llov parser keeps line:col race and not-analyzed findings in the model file",
        "passed": ids == [("llov-data-race", 20), ("llov-region-not-analyzed", 16)],
        "measured": ids,
    })
    return out


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def compare(op: str, value: int, bound: int) -> bool:
    return value == bound if op == "==" else value >= bound


def run_fixture(fx: Fixture, context: EvaluationContext) -> dict[str, Any]:
    base = framework.get_tool(fx.tool)
    tool = fx.tool_setup(base) if fx.tool_setup else base

    original = tools.run_command
    if fx.patch_run_command is not None:
        tools.run_command = fx.patch_run_command
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sample = make_raw_sample(tmp, fx.source, fx.execution_model,
                                     fx.name.replace(" ", "_")[:40])
            if fx.benchmark:
                problem, name = fx.benchmark.split("/", 1)
                sample.benchmark_dir = REPO_ROOT / "drivers" / "cpp" / "benchmarks" / problem / name
                sample.problem_type = problem
                sample.name = name
            result = tool.run(sample, context)
    finally:
        tools.run_command = original

    state = state_of(result)
    blocking = len(result.blocking_findings)
    details = dict(result.analysis_details or {})
    problems: list[str] = []

    if fx.custom is not None:
        ok, text = fx.custom(result)
        if not ok:
            problems.append("custom check failed: %s" % text)
    if fx.expect_state is not None and state != fx.expect_state:
        problems.append("state %s != expected %s" % (state, fx.expect_state))
    if fx.blocking is not None and not compare(fx.blocking[0], blocking, fx.blocking[1]):
        problems.append("blocking %d not %s %d" % (blocking, fx.blocking[0], fx.blocking[1]))
    for key, value in fx.details.items():
        if details.get(key) != value:
            problems.append("analysis_details[%s]=%r != %r" % (key, details.get(key), value))
    if fx.forbid_check_id and any(f.check_id == fx.forbid_check_id for f in result.findings):
        problems.append("forbidden finding %s present" % fx.forbid_check_id)
    if fx.path_events and not any(f.path for f in result.findings):
        problems.append("no finding carries path events")
    verdict = framework.tool_verdict(state, blocking)

    return {
        "name": fx.name,
        "tool": fx.tool,
        "execution_model": fx.execution_model,
        "expected_state": fx.expect_state,
        "measured_state": state,
        "tool_verdict": verdict,
        "gap_reason": result.analysis_gap_reason,
        "exit_code": result.exit_code,
        "error": result.error,
        "duration_seconds": round(result.duration_seconds, 3),
        "num_findings": len(result.findings),
        "num_blocking": blocking,
        "findings": [
            {"check_id": f.check_id, "line": f.line, "blocking": f.blocking,
             "path_events": len(f.path or [])}
            for f in result.findings
        ][:12],
        "analysis_details": details,
        "note": fx.note,
        "passed": not problems,
        "problems": problems,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tools", nargs="+", required=True)
    ap.add_argument("--primary-compiler", default="g++")
    ap.add_argument("--json", default=None, help="write the evidence JSON here")
    ap.add_argument("--only", default=None, help="substring filter on fixture names")
    args = ap.parse_args()

    register_default_tools(primary_compiler=args.primary_compiler, config=None)
    context = EvaluationContext(
        repo_root=REPO_ROOT,
        drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
        primary_compiler=args.primary_compiler,
        config={},
    )

    versions = {name: tools.tool_runtime_identity(name) for name in args.tools}
    print("tool identities:", json.dumps(versions))

    results = []
    for fx in build_fixtures(args.primary_compiler):
        if fx.tool not in args.tools:
            continue
        if args.only and args.only not in fx.name:
            continue
        tool = framework.get_tool(fx.tool)
        if fx.patch_run_command is None and fx.execution_model != "serial" \
                and not tool.is_available() and fx.expect_state != STATE_NOT_APPLICABLE:
            results.append({"name": fx.name, "tool": fx.tool, "passed": False,
                            "problems": ["tool not available in this container"]})
            print("  [SKIP-FAIL] %s: tool not available" % fx.name)
            continue
        row = run_fixture(fx, context)
        results.append(row)
        print("  [%s] %-62s -> %-14s blocking=%d %s" % (
            "ok" if row["passed"] else "FAIL", fx.name, row["measured_state"],
            row["num_blocking"], "; ".join(row["problems"])))

    parser_rows = parser_checks() if "llov" in args.tools else []
    for row in parser_rows:
        print("  [%s] %s -> %s" % ("ok" if row["passed"] else "FAIL", row["name"], row["measured"]))

    failed = [r for r in results + parser_rows if not r["passed"]]
    evidence = {
        "schema_version": "tool_state_fixtures.v1",
        "tools": args.tools,
        "primary_compiler": args.primary_compiler,
        "tool_identities": versions,
        "hostname": os.environ.get("HOSTNAME"),
        "fixtures": results,
        "parser_checks": parser_rows,
        "passed": len(results) + len(parser_rows) - len(failed),
        "failed": len(failed),
    }
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print("evidence written to", args.json)

    print("\n%d fixture(s) passed, %d failed" % (evidence["passed"], evidence["failed"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
