"""Correctness-test stage runner.

For every assembled sample this stage:
  1. compiles the full benchmark program (model driver + benchmark cpu.cc +
     the assembled generated-code.hpp) exactly as the compile stage does,
  2. runs the binary over the launch grid (serial: once; omp: several
     thread counts; mpi: several rank counts),
  3. parses the driver's AUTHENTICATED verdict line from stdout,
and writes one record per sample to correctness.jsonl plus a per-model
summary.

TRANSPORT (execution contract F1/F2). stdout is shared between harness and
candidate, so a constant marker string carries no authority. Every child
launch gets a FRESH 128-bit token in PAREVAL_BI_NONCE, and the trusted
driver echoes it:

    Validation: PASS nonce=<token>
    BASELINE_INCOMPATIBLE: non_finite_reference nonce=<token>

Only lines carrying THIS launch's token can influence a verdict. A run that
expected authentication and finds only the exact legacy line
(`Validation: PASS`, no token) raises HarnessTransportError: the trusted
driver ran but the token never reached it — a harness defect, not a model
result. Upstream tooling (drivers/run-all.py, test/test-serial.bash) keeps
launching without a token and keeps receiving the byte-identical historical
line; see legacy_parse_validation().

Verdict semantics (per run):
  - The exit code does NOT signal validation: the serial/omp drivers
    `return 0` after printing the FAIL verdict, and the mpi driver calls
    MPI_Abort(comm, 0). Only the authenticated stdout marker is
    authoritative.
  - pass                   -> marker PASS, exit 0, no timeout
  - validation_failed      -> marker FAIL
  - baseline_incompatible  -> the driver announced a NON-FINITE REFERENCE
                              (BASELINE_INCOMPATIBLE marker). The oracle,
                              not the model, is out of domain: this is never
                              a model failure, never a pass, produces no
                              correctness feedback and no repair iteration,
                              and is excluded from every pass/fail
                              denominator (execution contract A1).
  - timeout                -> run hit the time limit (for omp/mpi a possible
                              deadlock/livelock signal)
  - runtime_error          -> anything else (crash, missing marker, non-zero
                              exit)

Per-sample verdict: "pass" iff every run passed, "build_failed" if the
compile failed, "baseline_incompatible" if ANY grid point reported a
non-finite reference (it outranks a model failure, contract A1b case 1),
otherwise the verdict of the first failing run in grid order. Per-category
counts are stored alongside so no information is lost.

Usage (inside the pareval-thesis container):
    python3 thesis/evaluation/run_correctness.py \
        --config thesis/config/config.yaml --profile smoke
    # single model / custom timeout:
    python3 thesis/evaluation/run_correctness.py ... \
        --model-id deepseek_v4_pro --run-timeout 60
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation.build_config import (  # noqa: E402
    get_build_config,
    get_launch_config,
    missing_toolchain,
)
from thesis.evaluation.framework import (  # noqa: E402
    AssembledSample,
    EvaluationContext,
    run_command,
)
from thesis.evaluation.tools import DRIVER_PROBLEM_SIZE_DEFINE  # noqa: E402

CORRECTNESS_SCHEMA_VERSION = "correctness.v1"

# Iterations of the drivers' timing loops (validation is unaffected; this
# only keeps runs short). The omp driver has no niter argument (fixed 5).
DEFAULT_NITER = 1

DEFAULT_BUILD_TIMEOUT = 120.0
DEFAULT_RUN_TIMEOUT = 120.0

# Cap persisted process output; full output is reproducible by re-running.
OUTPUT_CAP = 4000

VALIDATION_MARKER = "Validation:"

# Execution contract A1e: the driver's comparator announces a NON-FINITE
# REFERENCE (NaN/+-Inf produced by the ORACLE) on its own stdout line. That
# is a property of the baseline, never a model failure, so it must not
# arrive here as "Validation: FAIL".
#
# EMISSION SEMANTICS (corrected, contract F3.4 — the earlier "root rank only"
# comment here was stale):
#   BI          is a LOCAL ORACLE DISCOVERY. It is emitted at most once per
#               PROCESS, i.e. once per MPI RANK, deliberately WITHOUT a
#               root-only filter — a non-root rank that sees a non-finite
#               reference must be able to say so. Several BI lines under MPI
#               are normal (drivers/cpp/utilities.hpp,
#               mismatchNoteNonFiniteReference).
#   Validation  is the FINAL DRIVER VERDICT and is emitted EXACTLY ONCE per
#               `mpirun` execution, from the mpi driver's root verdict path
#               (drivers/cpp/harness-markers.hpp, parevalEmitValidation).
BASELINE_INCOMPATIBLE_MARKER = "BASELINE_INCOMPATIBLE:"
BASELINE_INCOMPATIBLE = "baseline_incompatible"

# Contract C2b: the marker is AUTHENTICATED with a per-execution nonce the
# runner generates and hands to the binary through this environment variable.
# The driver prints it as "BASELINE_INCOMPATIBLE: <reason> nonce=<hex>"
# (drivers/cpp/utilities.hpp, mismatchNoteNonFiniteReference); only a line
# carrying THIS process's nonce may influence a verdict.
#
# Threat model: this defeats an UNINTENTIONAL collision — a candidate that
# happens to print the marker string cannot guess 128 random bits. It is NOT
# forgery-proof against a candidate that deliberately reads its environment;
# with a shared process and a shared stdout that is not solvable here and no
# cryptographic guarantee is claimed.
BASELINE_INCOMPATIBLE_NONCE_ENV = "PAREVAL_BI_NONCE"

BASELINE_INCOMPATIBLE_LINE = re.compile(
    r"^BASELINE_INCOMPATIBLE:\s*(?P<reason>\S+)"
    r"(?:\s+nonce=(?P<nonce>\S+))?\s*$"
)


def new_marker_nonce() -> str:
    """A fresh 128-bit hex token for exactly ONE child execution.

    Contract F2.1 — "one execution" means one launched child process group:
      serial   one launched benchmark binary
      omp      one launched binary for one grid point
      mpi      one `mpirun ...` invocation; ALL of its ranks share this token
      enhanced one launched spec process
      gates    one launched probe process

    There is deliberately NO module-level production token any more. A token
    reused across children would still not be guessable (128 random bits), so
    this is not primarily a new security property — it is transport hygiene:
    exactly one launch is bound to exactly one parser, nothing is reused
    across runs, and the transport fails closed.

    The token is never persisted; it only authenticates the local parser
    against the local child process.
    """
    return secrets.token_hex(16)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run correctness tests on assembled samples.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument("--primary-compiler", default="g++", choices=["g++", "clang++"])
    parser.add_argument(
        "--run-timeout",
        type=float,
        default=None,
        help="Per-run timeout in seconds (default from config or "
        f"{DEFAULT_RUN_TIMEOUT}).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the profile run_id (repair-loop iteration artifacts "
        "use the convention <run>__<variant>__iter<N>).",
    )
    return parser.parse_args()


class HarnessTransportError(RuntimeError):
    """The trusted harness ran, but its AUTHENTICATED marker never arrived.

    Raised when a thesis run expected authentication and stdout carries only
    the exact LEGACY verdict line (contract F1.6 rule 7). That combination is
    strong evidence that the trusted driver executed while the execution
    token never reached the child — a harness/transport defect. It is never a
    model result and must not be silently degraded into `runtime_error`.

    The same signal also fires if a candidate printed exactly the legacy line
    while the driver died before validating. Both are conditions under which
    no model verdict may be derived, so failing loudly is correct for both.
    """


# Contract F1.6 rule 6: the verdict is parsed from the COMPLETE, explicit
# marker format — never from a substring "PASS" anywhere in the line.
VALIDATION_MARKER_LINE = re.compile(
    r"^Validation:\s+(?P<verdict>PASS|FAIL)"
    r"(?:\s+nonce=(?P<nonce>\S+))?\s*$"
)


def legacy_parse_validation(stdout: str) -> "bool | None":
    """LEGACY, NON-AUTHENTICATED verdict parse (contract F1.7).

    Accepts ONLY the exact historical line `Validation: PASS|FAIL` without a
    token. It exists for upstream/read-only paths that run a driver without an
    execution token (drivers/run-all.py, test/test-serial.bash, hand analysis
    of frozen stdout).

    It must NOT be used by the thesis evaluation pipeline: a candidate shares
    stdout with the harness and can print this line itself. Production paths
    use parse_authenticated_validation().
    """
    for line in stdout.splitlines():
        match = VALIDATION_MARKER_LINE.match(line.strip())
        if match and match.group("nonce") is None:
            return match.group("verdict") == "PASS"

    return None


def parse_authenticated_validation(
    stdout: str, nonce: "str | None"
) -> "tuple[bool | None, list[str]]":
    """(validation, anomalies) for ONE authenticated child execution.

    `validation` is True (PASS), False (FAIL) or None. `anomalies` are
    human-readable strings the caller reports as WARN; they never change the
    verdict.

    Rules (contract F1.6):
      1. EXACTLY ONE authentic marker      -> its verdict
      2. no authentic marker, no trusted   -> None (existing missing-marker /
         legacy line                          process semantics apply)
      3. MORE THAN ONE authentic marker    -> transport ANOMALY, None. Never
         "first line wins".
      4. unauthenticated lines ALONGSIDE an authentic one -> the authentic one
         decides, the others are reported. Candidate output must not be able
         to turn a valid trusted verdict into a harness error.
      7. no authentic marker BUT an exact trusted LEGACY line -> the token did
         not reach the child: HarnessTransportError.

    Passing no nonce is a PROGRAMMING ERROR in a production path (contract
    F2.3) and raises ValueError — never a silent "no authentic marker".
    """
    if not nonce:
        raise ValueError(
            "parse_authenticated_validation requires the execution token this "
            "child was launched with. A production path must never parse "
            "authenticated output without one; use legacy_parse_validation() "
            "for explicitly legacy/read-only stdout."
        )

    authentic: "list[bool]" = []
    legacy_trusted = 0
    wrong_nonce = 0

    for line in stdout.splitlines():
        match = VALIDATION_MARKER_LINE.match(line.strip())
        if not match:
            continue

        seen = match.group("nonce")

        if seen == nonce:
            authentic.append(match.group("verdict") == "PASS")
        elif seen is None:
            legacy_trusted += 1
        else:
            wrong_nonce += 1

    anomalies: "list[str]" = []
    if legacy_trusted:
        anomalies.append(
            "%d Validation line(s) without a token" % legacy_trusted
        )
    if wrong_nonce:
        anomalies.append(
            "%d Validation line(s) with a foreign token" % wrong_nonce
        )

    if len(authentic) == 1:
        # rule 4: extra candidate lines are reported, never verdict-relevant
        return authentic[0], anomalies

    if len(authentic) > 1:
        anomalies.append(
            "%d AUTHENTIC Validation markers (expected exactly one) — "
            "transport anomaly, no verdict derived" % len(authentic)
        )
        return None, anomalies

    if legacy_trusted:
        # rule 7
        raise HarnessTransportError(
            "authenticated run, but stdout carries %d trusted-looking "
            "Validation line(s) WITHOUT the expected token and no "
            "authenticated marker. The execution token did not reach the "
            "child process (wrapper dropped the environment, env -i, "
            "container/MPI launcher did not forward it). This is a harness "
            "defect, not a model verdict." % legacy_trusted
        )

    return None, anomalies


def count_baseline_incompatible(stdout: str) -> int:
    """Number of BASELINE_INCOMPATIBLE marker lines in driver stdout,
    REGARDLESS of authenticity.

    Returns the COUNT, not a bool, because contract A1g requires the parser
    to tell "marker missing" (0) from "marker more than once" (>1) apart.
    This raw count never decides a verdict on its own — see
    classify_baseline_incompatible, which splits it into authentic and
    unauthenticated lines (contract C2b).
    """
    return sum(
        1
        for line in stdout.splitlines()
        if line.strip().startswith(BASELINE_INCOMPATIBLE_MARKER)
    )


def classify_baseline_incompatible(
    stdout: str, nonce: "str | None"
) -> "tuple[int, int]":
    """(authentic, unauthenticated) BASELINE_INCOMPATIBLE lines.

    AUTHENTIC means the line carries exactly the token this child was
    launched with (contract C2b/F1.2). Everything else — a missing token, a
    foreign token, a line a candidate printed itself — is UNAUTHENTICATED and
    must never influence a verdict; the caller reports it as an anomaly.

    Under MPI SEVERAL authentic lines are normal: BI is a LOCAL ORACLE
    DISCOVERY, emitted once per RANK, deliberately without a root-only filter
    and without a collective (contract C2.2/C2.4). This is the intended
    asymmetry to the Validation line, which the mpi driver emits exactly once
    from its root verdict path.

    Contract F2.3: a production path must never call this without the token
    it handed to the child. A missing token is a PROGRAMMING ERROR and raises
    ValueError — it is not silently answered with "no authentic marker".
    Explicitly legacy/read-only analysis uses
    legacy_count_baseline_incompatible().
    """
    if not nonce:
        raise ValueError(
            "classify_baseline_incompatible requires the execution token this "
            "child was launched with. Use legacy_count_baseline_incompatible() "
            "for explicitly legacy or read-only stdout."
        )

    authentic = 0
    unauthenticated = 0

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith(BASELINE_INCOMPATIBLE_MARKER):
            continue

        match = BASELINE_INCOMPATIBLE_LINE.match(line)
        seen = match.group("nonce") if match else None

        if seen is not None and seen == nonce:
            authentic += 1
        else:
            unauthenticated += 1

    return authentic, unauthenticated


def legacy_count_baseline_incompatible(stdout: str) -> int:
    """LEGACY, NON-AUTHENTICATED count of BASELINE_INCOMPATIBLE lines
    (contract F2.5).

    Only for read-only analysis of stored stdout and for explicitly legacy
    tooling. No production path may derive a verdict from it.
    """
    return count_baseline_incompatible(stdout)


# rel= is OPTIONAL (backward compatible: records produced before the field
# existed, and integral/bool comparisons which never carry it, stay parseable)
MISMATCH_LINE = re.compile(
    r"^MISMATCH(?:\s+index=(?P<index>\d+))?"
    r"\s+expected=(?P<expected>\S+)\s+got=(?P<got>\S+)"
    r"(?:\s+rel=(?P<rel>\S+))?"
    r"(?:\s+input=(?P<input>\S+))?\s*$"
)

MISMATCH_SUMMARY_LINE = re.compile(
    r"^MISMATCH_SUMMARY\s+shown=(?P<shown>\d+)\s+total=(?P<total>\d+)\s*$"
)


def parse_mismatch_output(stdout: str) -> "tuple[list[dict[str, Any]], int | None]":
    """Parse the drivers' bounded mismatch report (reportAndCompare in
    utilities.hpp) into structured entries.

    Returns (mismatches, mismatch_total). `mismatch_total` sums the totals
    of all MISMATCH_SUMMARY lines (compound verdicts can emit one summary
    per failing comparison); None when no summary appeared. fillRand draws
    from UNSEEDED rand() (as if srand(1)), so the inputs behind these
    numbers are identical across runs and iterations (verified 2026-08-06:
    two runs byte-identical); only the draw order within a process shifts
    between call sites (repair-loop-design.md §4). `rel` is the relative
    difference printed by the driver (optional field; absent on integral
    comparisons and on records predating it). The verdict marker stays
    authoritative; this parse never influences verdict logic.
    """
    mismatches: "list[dict[str, Any]]" = []
    total: "int | None" = None

    for line in stdout.splitlines():
        line = line.strip()

        match = MISMATCH_LINE.match(line)
        if match:
            entry: "dict[str, Any]" = {
                "expected": match.group("expected"),
                "got": match.group("got"),
            }
            if match.group("index") is not None:
                entry["index"] = int(match.group("index"))
            if match.group("rel") is not None:
                # float("nan")/float("inf") parse fine — a nan rel IS the
                # diagnosis (nan operand in the comparison)
                try:
                    entry["rel"] = float(match.group("rel"))
                except ValueError:
                    pass
            if match.group("input") is not None:
                entry["input"] = match.group("input")
            mismatches.append(entry)
            continue

        summary = MISMATCH_SUMMARY_LINE.match(line)
        if summary:
            total = (total or 0) + int(summary.group("total"))

    return mismatches, total


def run_verdict(
    validation: bool | None,
    exit_code: int,
    timed_out: bool,
    baseline_incompatible: bool = False,
) -> str:
    """Verdict of ONE grid point.

    Contract A1b, case 1 is decided FIRST: a non-finite REFERENCE outranks
    every other outcome, so a run whose oracle produced NaN/Inf never
    becomes "validation_failed" (a model failure) and never becomes "pass".

    Contract C3b.2 makes it outrank the PROCESS STATE as well — including a
    timeout, a crash and a non-zero exit. Once an AUTHENTIC marker proves
    the reference for this validation case was not evaluable, a later fault
    on that invalid basis must not re-enter the correctness pass/fail
    denominator as a model failure. `timeout` and `runtime_error` are
    fail-side outcomes in every denominator, so leaving them ahead of
    baseline_incompatible would do exactly that. The exclusion is
    symmetric: it removes a possible pass and a possible fail alike.

    The secondary process state is NOT lost — the caller stores `timed_out`
    and `exit_code` on the run entry, so the record still says the process
    hung or died. No schema change, no new verdict value.
    """
    if baseline_incompatible:
        return BASELINE_INCOMPATIBLE

    if timed_out:
        return "timeout"

    if validation is False:
        return "validation_failed"

    if validation is True and exit_code == 0:
        return "pass"

    return "runtime_error"


def compile_sample(
    sample: AssembledSample,
    context: EvaluationContext,
    exec_path: Path,
    build_timeout: float,
) -> dict[str, Any]:
    config = get_build_config(
        sample.execution_model, primary_compiler=context.primary_compiler
    )

    model_driver = context.drivers_cpp_dir / config.model_driver_file
    benchmark_driver = sample.benchmark_dir / "cpu.cc"

    missing = [
        str(p)
        for p in (model_driver, benchmark_driver, sample.source_path)
        if not p.exists()
    ]

    if missing:
        return {"ok": False, "exit_code": None, "error": f"missing inputs: {', '.join(missing)}"}

    # MISMATCH_REPORT_MAX: single config source is
    # stages.repair.feedback.mismatch_report_max_indices — the same value
    # feedback.py uses for rendering (repair-loop-design.md §4)
    mismatch_k = (
        ((context.config.get("stages") or {}).get("repair") or {})
        .get("feedback", {})
        .get("mismatch_report_max_indices", 3)
    )

    argv = config.base_command(
        sources=[str(model_driver), str(benchmark_driver)],
        output_path=str(exec_path),
        include_dirs=context.include_dirs(sample),
        extra_flags=[
            f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
            f"-DMISMATCH_REPORT_MAX={int(mismatch_k)}",
        ],
    )

    result = run_command(argv, timeout=build_timeout)

    return {
        "ok": result.returncode == 0 and not result.timed_out,
        "exit_code": result.returncode,
        "timed_out": result.timed_out,
        "duration_seconds": round(result.duration_seconds, 3),
        "stderr": result.stderr[:OUTPUT_CAP],
    }


def run_sample(
    sample: AssembledSample,
    context: EvaluationContext,
    launch_overrides: dict[str, Any] | None,
    niter: int,
    build_timeout: float,
    run_timeout: float,
    marker_nonce: "str | None" = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": CORRECTNESS_SCHEMA_VERSION,
        "run_id": sample.run_id,
        "model_id": sample.model_id,
        "sample_id": sample.sample_id,
        "execution_model": sample.execution_model,
        "created_at_utc": common.utc_now_iso(),
    }

    with tempfile.TemporaryDirectory() as tmp:
        exec_path = Path(tmp) / "benchmark.out"

        compile_result = compile_sample(sample, context, exec_path, build_timeout)
        record["compile"] = compile_result

        if not compile_result.get("ok"):
            record["runs"] = []
            record["verdict"] = "build_failed"
            record["run_verdicts"] = {}
            return record

        launch = get_launch_config(sample.execution_model, overrides=launch_overrides)

        runs: list[dict[str, Any]] = []
        verdicts: Counter = Counter()
        sample_verdict = "pass"

        for params in launch.params:
            argv, extra_env = launch.command(str(exec_path), params, niter=niter)

            # Contract F2.1/F2.2: a FRESH token per CHILD EXECUTION. One grid
            # point is one launch; for mpi one `mpirun` invocation, whose ranks
            # all inherit this single token (verified in-container: Open MPI
            # forwards the launch environment to every rank). `marker_nonce`
            # exists only so tests can pin a deterministic value — production
            # never passes it.
            nonce = marker_nonce or new_marker_nonce()

            extra_env = dict(extra_env or {})
            extra_env[BASELINE_INCOMPATIBLE_NONCE_ENV] = nonce

            result = run_command(
                argv, timeout=run_timeout, cwd=tmp, extra_env=extra_env
            )

            # Contract F1.6: only an AUTHENTICATED verdict line counts. A
            # trusted-looking legacy line without the token raises
            # HarnessTransportError — the driver ran but the token never
            # reached it, which is a harness defect, not a model result.
            validation, validation_anomalies = parse_authenticated_validation(
                result.stdout, nonce
            )

            for anomaly in validation_anomalies:
                print(
                    "    WARN %s %s: %s — ignored for the verdict"
                    % (sample.sample_id, params, anomaly)
                )

            marker_count, spoofed_markers = classify_baseline_incompatible(
                result.stdout, nonce
            )

            # contract C2.4: under MPI the marker legitimately appears once
            # per RANK, so its COUNT is not an anomaly there. Under
            # serial/omp there is exactly one process, so more than one
            # authentic marker means the once-per-process guard did not hold.
            if marker_count > 1 and sample.execution_model != "mpi":
                print(
                    "    WARN %s %s: authentic BASELINE_INCOMPATIBLE marker "
                    "seen %d times (expected exactly once per process)"
                    % (sample.sample_id, params, marker_count)
                )

            if spoofed_markers:
                # contract C2b: a BASELINE_INCOMPATIBLE line WITHOUT this
                # process's nonce never influences the verdict. It is either
                # candidate output or a runner that forgot the nonce —
                # both must be visible, neither may be silent.
                print(
                    "    WARN %s %s: %d unauthenticated BASELINE_INCOMPATIBLE "
                    "line(s) in stdout (wrong or missing nonce) — ignored for "
                    "the verdict" % (sample.sample_id, params, spoofed_markers)
                )

            verdict = run_verdict(
                validation,
                result.returncode,
                result.timed_out,
                baseline_incompatible=marker_count > 0,
            )
            verdicts[verdict] += 1

            # contract A1b: a non-finite reference outranks a model failure,
            # so it wins the per-sample aggregation too and is never
            # overwritten by a later failing grid point
            if verdict == BASELINE_INCOMPATIBLE:
                sample_verdict = BASELINE_INCOMPATIBLE
            elif verdict != "pass" and sample_verdict == "pass":
                sample_verdict = verdict

            run_entry: dict[str, Any] = {
                "params": params,
                "argv": argv,
                "exit_code": result.returncode,
                "timed_out": result.timed_out,
                "duration_seconds": round(result.duration_seconds, 3),
                "validation": (
                    None if validation is None else ("PASS" if validation else "FAIL")
                ),
                "verdict": verdict,
                "stdout": result.stdout[:OUTPUT_CAP],
                "stderr": result.stderr[:OUTPUT_CAP],
            }

            # bounded mismatch report (parsed from UNCAPPED stdout; verdict
            # logic untouched — the marker above stays authoritative)
            mismatches, mismatch_total = parse_mismatch_output(result.stdout)
            if mismatches:
                run_entry["mismatches"] = mismatches
                run_entry["mismatch_total"] = (
                    mismatch_total if mismatch_total is not None else len(mismatches)
                )

            runs.append(run_entry)

        record["runs"] = runs
        record["run_verdicts"] = dict(verdicts)
        record["verdict"] = sample_verdict

    return record


def run_model(
    context: EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    output_file_name: str,
    launch_overrides: dict[str, Any] | None,
    niter: int,
    build_timeout: float,
    run_timeout: float,
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / output_file_name

    if output_path.exists():
        output_path.unlink()

    samples_seen = 0
    verdicts: Counter = Counter()

    for sample in framework.iter_assembled_samples(
        context.repo_root, intermediate_dir, run_id, model_id
    ):
        samples_seen += 1

        record = run_sample(
            sample, context, launch_overrides, niter, build_timeout, run_timeout
        )
        verdicts[record["verdict"]] += 1

        common.append_jsonl(output_path, record)

    summary = {
        "model_id": model_id,
        "samples": samples_seen,
        "verdicts": dict(verdicts),
    }

    print(f"[{model_id}] samples: {samples_seen}")
    for verdict, count in sorted(verdicts.items()):
        print(f"    {verdict}: {count}")
    print(f"[{model_id}] output: {output_path}")

    return summary


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    run_id = args.run_id or profile["run_id"]

    stage = (config.get("stages") or {}).get("correctness_tests") or {}
    output_file_name = stage.get("output_file_name", "correctness.jsonl")
    launch_overrides = stage.get("launch_overrides")
    niter = int(stage.get("niter", DEFAULT_NITER))
    build_timeout = float(stage.get("build_timeout_seconds", DEFAULT_BUILD_TIMEOUT))
    run_timeout = float(
        args.run_timeout
        if args.run_timeout is not None
        else stage.get("run_timeout_seconds", DEFAULT_RUN_TIMEOUT)
    )

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])

    # environment gate BEFORE any record is written (2026-08-08, same
    # rationale as the dynamic preflight gate): a missing compiler/mpirun
    # would otherwise produce a FULL dataset of build_failed records that
    # reads like model failures — an expensive silent loss. Scope: the
    # configured sample universe (prompts.execution_models).
    scoped_models = list(
        (config.get("prompts") or {}).get("execution_models")
        or ("serial", "omp", "mpi")
    )
    missing = missing_toolchain(scoped_models, args.primary_compiler)
    if missing:
        print(
            "ENVIRONMENT GATE FAILED — aborting before any record is "
            "written. Missing toolchain for execution models "
            f"{'/'.join(scoped_models)}: " + ", ".join(missing)
            + ". The correctness stage runs inside the pareval-thesis "
            "container."
        )
        sys.exit(2)

    # freeze the run configuration / record config drift (run_manifest.py)
    from thesis.evaluation.run_manifest import ensure_run_manifest

    ensure_run_manifest(
        config, run_id, stage="correctness_tests", profile=args.profile,
        primary_compiler=args.primary_compiler,
    )

    context = EvaluationContext(
        repo_root=REPO_ROOT,
        drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
        primary_compiler=args.primary_compiler,
        config=config,
    )

    models = [
        model
        for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    print(f"Correctness tests | run {run_id} | niter={niter} | run timeout {run_timeout}s")
    print("=" * 40)

    for model_config in models:
        run_model(
            context=context,
            intermediate_dir=intermediate_dir,
            run_id=run_id,
            model_id=model_config["id"],
            output_file_name=output_file_name,
            launch_overrides=launch_overrides,
            niter=niter,
            build_timeout=build_timeout,
            run_timeout=run_timeout,
        )


if __name__ == "__main__":
    main()
