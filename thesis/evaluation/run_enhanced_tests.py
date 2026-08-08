"""Enhanced-tests stage runner: differential testing on spec-defined inputs.

For every assembled sample and every spec of its benchmark (static base set
+ LLM seeds + one deterministic mutation round, capped per benchmark) this
runs the benchmark's validate() differentially against the baseline.

BUILD GROUPING (2026-08-08): specs are grouped per (sample, size) and each
group is compiled ONCE with -DENHANCED_RUNTIME_FILL — the fill pattern and
its parameters travel as environment variables into a FRESH process per
spec (see drivers/cpp/enhanced-fill.hpp, runtime-fill mode). Measured
motivation: ~20 near-identical builds per sample spread over only ~6-8
distinct sizes; at equal size ONLY the fill pattern differs, which lives
entirely in enhanced-fill.hpp, not in the driver. ENHANCED_TEST_SIZE stays
a compile define. Process isolation per spec is fully preserved — there is
NO spec loop inside the binary (a crash at spec 7 cannot affect spec 8).
A group build failure produces a normal build_failed record (with
build_stderr) for EVERY spec of the group.

TIMING SEMANTICS (versioned, no schema break): enhanced_tests.jsonl keeps
its record format. Since the grouping change, `duration_seconds` on a run
record means precisely the RUN duration of the spec's process; build_failed
records carry NO duration_seconds (nothing ran — the compile time lives in
the group row). Compile times are recorded per group in
enhanced_build_groups.jsonl ({sample_id, execution_model, size, spec_count,
compile_seconds, build_status, build_stderr}); a resume that re-compiles a
partially-done group appends a SECOND group row — every row is a real
compile that happened, the sum stays the true compile cost. The per-model
summary carries `timing_semantics: "run_only_plus_build_groups"` and
`build_groups_file`; build_overview.py evaluates BOTH semantics (legacy
runs without the marker: duration_seconds = build+run mixed).

PARALLELISM (2026-08-08): a worker pool over SAMPLES, configured PER
EXECUTION MODEL via stages.enhanced_tests.jobs ({serial, omp, mpi};
built-in default 1/1/1 = the historical serial behavior) and overridden by
--jobs (highest priority). serial/omp/mpi are EXECUTION models, not LLM
models. All baseline/stability gates are precomputed SERIALLY before the
pool (the lazy gate cache is shared across models — two workers on the
same gate would race; precomputing is simpler and more reproducible than
locks); workers only read the finished cache. Workers return records and
ONLY the main thread appends to the JSONL files. Resume semantics are
unchanged. Operational rules for combining --jobs with manual multi-model
parallelism: docs/parallel-execution.md.

BASELINE GATE (cached per spec): the baseline itself — as a forwarding
generated-code.hpp — is executed under every spec. If the baseline crashes,
hangs or fails to build, the spec is baseline_incompatible for this
benchmark and is never counted against a model. This consumes the same
machinery as thesis/enhanced_tests/baseline_selftest.py. The gates keep
the COMPILE-DEFINE path (one TU per spec — natural there, since every gate
probe is a distinct oracle build).

Statuses per (sample, spec): pass | fail | crash | timeout | build_failed |
baseline_incompatible. Output: enhanced_tests.jsonl per model (schema
enhanced_tests.v1) + per-model summary, same layout as the other stages.
--output-file-name redirects ALL outputs of a run (records, build groups,
summary) to derived sibling names — used by verification probe runs so the
reference files are never touched.

Scope: stages.enhanced_tests.execution_models selects which samples run
(default ["serial"] = the historical behavior; the pilot sets all three).
Parallel samples build with their own BuildConfig (-fopenmp / mpicxx) and
launch at ONE fixed grid point (enhanced_launch: omp_threads / mpi_ranks)
via the correctness stage's LaunchConfig — no launch grid; that axis stays
with the correctness stage. Non-parameterizable benchmarks are skipped.

THE GATES STAY SERIAL in every case (pilot decision — documented, not
solved; see docs/enhanced-tests-parallel.md): the baseline-selftest gate
and the fast-math stability probe run the SERIAL oracle TU, and their
per-spec verdict (baseline_incompatible / numerically_unstable) is applied
to samples of ALL execution models. spec_key and the gate cache are
unchanged. Two documented residual risks of this simplification:
  (a) driver divergence: a spec that passes the serial gate can still
      crash in the omp/mpi DRIVER path (different code: BCAST, IS_ROOT
      distribution). Such cases surface as crash/timeout on the MODEL run
      and must be sighted MANUALLY in the pilot before being read as model
      errors.
  (b) parallel rounding: the oracle is serial; parallel model code reduces
      in a different order. The fast-math stability probe catches part of
      that serially (reassociation), but not all of it. Expectation:
      small relative deviations at many indices = rounding signature, not
      a model error.

Usage (main container):
    python3 thesis/evaluation/run_enhanced_tests.py \
        --config thesis/config/config.yaml --profile smoke [--model-id X] \
        [--jobs 2 | --jobs serial=2,omp=1,mpi=1] \
        [--output-file-name enhanced_tests_runtime_fill_probe.jsonl]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from thesis.evaluation.run_correctness import parse_mismatch_output  # noqa: E402
from thesis.enhanced_tests.baseline_selftest import (  # noqa: E402
    build_wrapper,
    compile_and_run,
    load_serial_signatures,
    stability_probe,
)
from thesis.enhanced_tests.specs import (  # noqa: E402
    ENHANCED_EXECUTION_MODELS,
    build_benchmark_specs,
    explicit_values_file_text,
    explicit_values_header,
    spec_defines,
    spec_key,
    spec_runtime_env,
    stage_settings,
)

ENHANCED_SCHEMA_VERSION = "enhanced_tests.v1"

# marker the overview keys on to classify a run's timing semantics; legacy
# summaries without it mean duration_seconds = build+run mixed
TIMING_SEMANTICS = "run_only_plus_build_groups"

DRIVERS_CPP = REPO_ROOT / "drivers" / "cpp"

BUILD_TIMEOUT = 120.0
DEFAULT_RUN_TIMEOUT = 30.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run enhanced differential tests.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument(
        "--specs",
        default=str(REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"),
        help="LLM spec JSONL (optional; static base set + mutations always run).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rerun everything (default: resume — existing (sample_id, "
        "spec) rows are skipped). Also removes the build-groups file.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the profile run_id (repair-loop iteration artifacts "
        "use the convention <run>__<variant>__iter<N>; phase-2 backfill).",
    )
    parser.add_argument(
        "--jobs",
        default=None,
        help="Worker-pool width over samples, per EXECUTION model "
        "(serial/omp/mpi — these are execution models, NOT LLM model ids). "
        "Forms: '--jobs 2' (all execution models) or "
        "'--jobs serial=2,omp=1,mpi=1' (partial allowed; unnamed models "
        "keep the config value). Highest priority; default: config "
        "stages.enhanced_tests.jobs, built-in 1/1/1.",
    )
    parser.add_argument(
        "--output-file-name",
        default=None,
        help="Records file name (default: config "
        "stages.enhanced_tests.output_file_name, enhanced_tests.jsonl). "
        "Build-groups and summary names are derived from it, so a probe "
        "run with a distinct name never touches the reference run's files.",
    )
    return parser.parse_args()


def parse_jobs_arg(text: str) -> "dict[str, int]":
    """Parse --jobs. '2' -> all EXECUTION models; 'serial=2,omp=1' ->
    per-model (partial: unnamed models keep their config value). Raises
    ValueError with a precise message on anything else."""
    text = (text or "").strip()

    if not text:
        raise ValueError("--jobs: empty value")

    if "=" not in text:
        try:
            count = int(text)
        except ValueError:
            raise ValueError(
                "--jobs: %r is neither an integer nor a serial=N,omp=N,mpi=N list"
                % text
            )
        if count < 1:
            raise ValueError("--jobs must be >= 1 (got %d)" % count)
        return {model: count for model in ENHANCED_EXECUTION_MODELS}

    parsed: "dict[str, int]" = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ValueError("--jobs: empty segment in %r" % text)
        name, _, value = part.partition("=")
        name = name.strip()
        if name not in ENHANCED_EXECUTION_MODELS:
            raise ValueError(
                "--jobs: unknown execution model %r — serial/omp/mpi are "
                "EXECUTION models, not LLM model ids" % name
            )
        try:
            count = int(value.strip())
        except ValueError:
            raise ValueError("--jobs: %r is not an integer (in %r)" % (value, part))
        if count < 1:
            raise ValueError("--jobs: %s must be >= 1 (got %d)" % (name, count))
        parsed[name] = count

    return parsed


def resolve_jobs(settings: "dict[str, Any]", cli_jobs: "dict[str, int] | None") -> "dict[str, int]":
    """Priority: built-in default 1/1/1 < config stages.enhanced_tests.jobs
    (already merged into settings) < CLI --jobs."""
    jobs = dict(settings["jobs"])

    if cli_jobs:
        jobs.update(cli_jobs)

    return {model: int(jobs.get(model, 1)) for model in ENHANCED_EXECUTION_MODELS}


def derived_file_names(output_name: str) -> "tuple[str, str]":
    """(build_groups_name, summary_name) derived from the records name.
    The default keeps the documented/historical names; any other
    --output-file-name derives prefixed siblings so a probe run never
    touches the reference run's files (including its summary). Names
    without the .jsonl extension are REJECTED: 'enhanced_tests' would
    derive 'enhanced_tests_summary.json' — the reference summary name —
    and silently clobber it (review finding 2026-08-08)."""
    if not output_name.endswith(".jsonl"):
        raise ValueError(
            "enhanced output file name must end with .jsonl (got %r): the "
            "derived summary/build-groups names would otherwise collide "
            "with the reference run's files" % output_name
        )

    if output_name == "enhanced_tests.jsonl":
        return "enhanced_build_groups.jsonl", "enhanced_tests_summary.json"

    stem = output_name[: -len(".jsonl")]
    return stem + "_build_groups.jsonl", stem + "_summary.json"


def load_llm_specs(path: Path) -> "dict[str, list[dict]]":
    by_benchmark: "dict[str, list[dict]]" = {}

    if not path.exists():
        return by_benchmark

    import json

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                spec = json.loads(line)
                by_benchmark.setdefault(spec["benchmark"], []).append(spec)

    return by_benchmark


def compile_argv(
    sample: framework.AssembledSample,
    defines: "list[str]",
    out_path: str,
    extra_include_dir: "str | None" = None,
    execution_model: str = "serial",
) -> "list[str]":
    """Compile command for the sample's TU via get_build_config (single
    source of build truth: serial = g++, omp = g++ -fopenmp, mpi = mpicxx).
    Builds at the BuildConfig's -O3, exactly like the correctness stage —
    the stage's historical -O1 override was removed 2026-08-08. Risk
    evidence for the change: thesis/experiments/opt-level-probe.md —
    verdicts AND full mismatch lists are optimization-level-invariant
    (bit-identical across -O0..-O3; without -ffast-math GCC preserves IEEE
    evaluation order), so records from before and after the change remain
    comparable."""
    config = get_build_config(execution_model, primary_compiler="g++")

    include_dirs = [
        str(DRIVERS_CPP),
        str(DRIVERS_CPP / "models"),
        str(sample.source_path.parent),
    ]
    if extra_include_dir:
        include_dirs.append(extra_include_dir)

    return config.base_command(
        sources=[
            str(DRIVERS_CPP / config.model_driver_file),
            str(sample.benchmark_dir / "cpu.cc"),
        ],
        output_path=out_path,
        include_dirs=include_dirs,
        extra_flags=[
            "-DDRIVER_PROBLEM_SIZE=(1<<4)",
            *["-D%s" % d for d in defines],
        ],
    )


def group_defines(size: int, mismatch_k: int) -> "list[str]":
    """Compile defines for ONE (sample, size) build group: the size stays a
    compile define, the fill configuration moves to the environment
    (runtime-fill mode) — deliberately NO ENHANCED_FILL_PATTERN define."""
    return [
        "ENHANCED_TEST_SIZE=%d" % int(size),
        "MISMATCH_REPORT_MAX=%d" % int(mismatch_k),
        "ENHANCED_RUNTIME_FILL",
    ]


def group_specs_by_size(specs: "list[dict]") -> "dict[int, list[dict]]":
    """Order-preserving (size -> specs) grouping; insertion order of both
    the groups and the specs within a group follows the spec list."""
    groups: "dict[int, list[dict]]" = {}

    for spec in specs:
        groups.setdefault(int(spec["size"]), []).append(spec)

    return groups


def compile_sample(
    sample: framework.AssembledSample,
    defines: "list[str]",
    out_path: str,
    extra_include_dir: "str | None" = None,
    execution_model: str = "serial",
) -> "tuple[bool, float, str]":
    """(built, seconds, stderr tail). The stderr tail is persisted on
    build_failed records (analog to static_analysis raw_stderr): without
    it a harness divergence — an artifact that compiles in the normal
    pipeline but not under the enhanced defines — is undiagnosable from
    the records."""
    argv = compile_argv(sample, defines, out_path, extra_include_dir, execution_model)

    started = time.time()

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, time.time() - started, "build timeout after %ds" % BUILD_TIMEOUT

    return (
        result.returncode == 0,
        time.time() - started,
        (result.stderr or "")[-2000:],
    )


def launch_command(
    binary: str,
    execution_model: str,
    launch_settings: "dict[str, Any]",
) -> "tuple[list[str], dict[str, str]]":
    """(argv, extra_env) for ONE fixed launch point, via the correctness
    stage's LaunchConfig — the container details solved there (OMP thread
    count via env AND argv, `mpirun -np`) are inherited, not duplicated.
    Deliberately no grid: serial runs as before ([binary, "1"]), omp runs
    at enhanced_launch.omp_threads, mpi at enhanced_launch.mpi_ranks."""
    launch = get_launch_config(execution_model)

    if execution_model == "omp":
        params: "dict[str, Any]" = {
            "num_threads": int(launch_settings["omp_threads"])
        }
    elif execution_model == "mpi":
        params = {"num_procs": int(launch_settings["mpi_ranks"])}
    else:
        params = {}

    return launch.command(binary, params, niter=1)


def sanitized_child_env(
    launch_env: "dict[str, str]",
    fill_env: "dict[str, str] | None",
) -> "dict[str, str]":
    """Child environment for a spec process: the inherited environment is
    stripped of ALL ENHANCED_FILL_* keys BEFORE the spec's own fill env is
    applied. Stale operator exports (e.g. from hand-driving a runtime-fill
    binary in the same shell) would otherwise silently override call-site
    ranges for every no-range spec — both range variables being present is
    a VALID header configuration, so no abort would fire (review finding
    2026-08-08). The define path was immune to environment pollution; the
    runtime path must be too."""
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("ENHANCED_FILL_")
    }
    env.update(launch_env)
    if fill_env:
        env.update(fill_env)
    return env


def run_binary(
    binary: str,
    cwd: str,
    timeout: float,
    execution_model: str = "serial",
    launch_settings: "dict[str, Any] | None" = None,
    extra_env: "dict[str, str] | None" = None,
) -> "tuple[str, int | None, float, str, str]":
    """Verdicts aligned with run_correctness.run_verdict: the validation
    MARKER decides fail vs pass; exit 0 without any marker is a
    runtime_error (not a fail). Returns stdout as well so the caller can
    parse the bounded mismatch report — parse_mismatch_output runs
    unchanged over omp/mpi output, because the expected/got values are the
    basis of the pilot's rounding-vs-bug classification. For mpi the
    timeout covers the mpirun startup overhead as well
    (run_timeout_seconds stays configurable). extra_env carries the
    runtime-fill spec configuration (ENHANCED_FILL_*) into the fresh
    process — one process per spec, no spec loop inside the binary.
    stderr is returned so a runtime-fill config abort (SIGABRT with a
    clear message) stays diagnosable from the records instead of looking
    like a genuine model crash."""
    argv, launch_env = launch_command(
        binary, execution_model, launch_settings or {}
    )

    env = sanitized_child_env(launch_env, extra_env)

    started = time.time()

    popen_kwargs: "dict[str, Any]" = {}
    if hasattr(os, "setsid"):
        # own process group, so a timeout can kill mpirun AND its ranks:
        # a plain timeout kill reaches only the direct child, orphaning
        # ranks hung in generated model code — they would keep occupying
        # cores for the rest of the run and turn later runs into cascading
        # spurious timeouts (amplified by the worker pool)
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=cwd, env=env, **popen_kwargs
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if popen_kwargs:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        process.kill()
        process.communicate()
        return "timeout", None, time.time() - started, "", ""

    duration = time.time() - started
    stdout = stdout or ""
    stderr = stderr or ""

    if "Validation: FAIL" in stdout:
        return "fail", process.returncode, duration, stdout, stderr

    if process.returncode != 0:
        return "crash", process.returncode, duration, stdout, stderr

    if "Validation: PASS" in stdout:
        return "pass", process.returncode, duration, stdout, stderr

    return "runtime_error", process.returncode, duration, stdout, stderr


def precompute_gates(
    worklist: "list[tuple]",
    gate_cache: "dict[tuple, str]",
    wrapper_cache: "dict[str, str | None]",
    signatures: "dict[str, str]",
    mismatch_k: int,
) -> int:
    """Fill the per-spec gate cache SERIALLY for every pending spec before
    the worker pool starts. The cache is lazy and shared across models AND
    execution models — two workers computing the same gate would race;
    precomputing keeps the pool read-only on it (simpler and more
    reproducible than locks). Gate semantics are unchanged: two probes per
    spec (crash/hang on the serial oracle, then the fast-math stability
    probe), compile-define path, same defines as before the grouping
    change. Returns the number of newly computed gates."""
    computed = 0

    for sample, benchmark, pending in worklist:
        if benchmark not in wrapper_cache:
            prompt_text = signatures.get(sample.name)
            wrapper_cache[benchmark] = (
                build_wrapper(sample.benchmark_dir, prompt_text) if prompt_text else None
            )

        wrapper = wrapper_cache[benchmark]

        for spec in pending:
            key = spec_key(spec)

            if key in gate_cache:
                continue

            computed += 1

            defines = spec_defines(spec) + ["MISMATCH_REPORT_MAX=%d" % int(mismatch_k)]

            extra_headers = None
            header_text = explicit_values_header(spec)
            if header_text is not None:
                extra_headers = {"enhanced-explicit-values.hpp": header_text}

            prompt_text = signatures.get(sample.name)

            # baseline gate, two probes per spec:
            #   1. crash/hang: a crashing oracle never counts against a
            #      model (baseline_incompatible)
            #   2. numerical stability (single-TU probe): a second oracle
            #      instance compiled with perturbed FP flags must still
            #      validate against the normal oracle. If not, the input is
            #      degenerate for the differential comparison (e.g.
            #      descending ramp -> exactly singular matrix for pivot-free
            #      LU: two CORRECT implementations diverge via rounding
            #      order alone) -> numerically_unstable, never counted
            #      against a model.
            if wrapper is None or prompt_text is None:
                gate_cache[key] = "wrapper_failed"
                continue

            plain = compile_and_run(
                sample.benchmark_dir, wrapper, defines,
                extra_headers=extra_headers,
            )

            if plain != "pass":
                gate_cache[key] = plain
            else:
                perturbed = stability_probe(
                    sample.benchmark_dir, prompt_text, defines,
                    extra_headers=extra_headers,
                )
                gate_cache[key] = (
                    "pass" if perturbed == "pass" else "numerically_unstable"
                )

    return computed


def process_sample(
    sample: framework.AssembledSample,
    benchmark: str,
    pending: "list[dict]",
    gate_cache: "dict[tuple, str]",
    run_id: str,
    model_id: str,
    mismatch_k: int,
    run_timeout: float,
    launch_settings: "dict[str, Any]",
) -> "tuple[list[dict], list[dict]]":
    """One sample's pending specs: gate records from the (read-only,
    precomputed) cache, then ONE compile per size group and a fresh
    process per spec. Returns (records, group_rows) — the caller (main
    thread) does all file appends."""
    records: "list[dict]" = []
    group_rows: "list[dict]" = []

    def base_record(spec: dict) -> "dict[str, Any]":
        return {
            "schema_version": ENHANCED_SCHEMA_VERSION,
            "run_id": run_id,
            "model_id": model_id,
            "sample_id": sample.sample_id,
            # explicit field so evaluations never have to parse the
            # sample_id for it
            "execution_model": sample.execution_model,
            "benchmark": benchmark,
            "spec": spec,
            "created_at_utc": common.utc_now_iso(),
        }

    runnable: "list[dict]" = []

    for spec in pending:
        gate = gate_cache[spec_key(spec)]

        if gate == "pass":
            runnable.append(spec)
            continue

        record = base_record(spec)
        record["status"] = (
            "numerically_unstable"
            if gate == "numerically_unstable"
            else "baseline_incompatible"
        )
        record["baseline_gate"] = gate
        records.append(record)

    for size, group in group_specs_by_size(runnable).items():
        with tempfile.TemporaryDirectory() as tmp:
            binary = str(Path(tmp) / "enhanced.out")

            built, build_seconds, build_stderr = compile_sample(
                sample, group_defines(size, mismatch_k), binary,
                execution_model=sample.execution_model,
            )

            group_rows.append({
                "sample_id": sample.sample_id,
                "execution_model": sample.execution_model,
                "size": int(size),
                "spec_count": len(group),
                "compile_seconds": round(build_seconds, 3),
                "build_status": "success" if built else "build_failed",
                "build_stderr": "" if built else build_stderr,
            })

            if not built:
                for spec in group:
                    record = base_record(spec)
                    record["status"] = "build_failed"
                    # additive field: the compile error text is the only
                    # way to diagnose enhanced-harness divergence. NO
                    # duration_seconds: nothing ran — the compile time is
                    # in the group row.
                    record["build_stderr"] = build_stderr
                    records.append(record)
                continue

            for index, spec in enumerate(group):
                values_file = None
                values_text = explicit_values_file_text(spec)
                if values_text is not None:
                    values_file = Path(tmp) / ("values_%d.txt" % index)
                    values_file.write_text(values_text, encoding="ascii")

                fill_env = spec_runtime_env(
                    spec, str(values_file) if values_file is not None else None
                )

                status, exit_code, run_seconds, run_stdout, run_stderr = run_binary(
                    binary, tmp, run_timeout,
                    execution_model=sample.execution_model,
                    launch_settings=launch_settings,
                    extra_env=fill_env,
                )

                record = base_record(spec)
                record["status"] = status
                record["exit_code"] = exit_code
                # RUN duration of the spec's process only (grouping change
                # 2026-08-08; legacy records mixed build+run — the summary's
                # timing_semantics marker tells the overview apart)
                record["duration_seconds"] = round(run_seconds, 3)

                if status == "crash" and run_stderr:
                    # additive diagnosability field (build_stderr
                    # precedent): a runtime-fill config abort prints its
                    # reason to stderr and would otherwise be
                    # indistinguishable from a genuine model crash
                    record["runtime_stderr"] = run_stderr[-2000:]

                # diagnostic only: enhanced results stay held out of repair
                # feedback (repair-loop-design.md §3)
                mismatches, mismatch_total = parse_mismatch_output(run_stdout)
                if mismatches:
                    record["mismatches"] = mismatches
                    record["mismatch_total"] = (
                        mismatch_total if mismatch_total is not None else len(mismatches)
                    )

                records.append(record)

    return records, group_rows


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    run_id = args.run_id or profile["run_id"]

    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    settings = stage_settings(config)
    target_cases = int(settings["target_cases_per_benchmark"])
    run_timeout = float(stage.get("run_timeout_seconds", DEFAULT_RUN_TIMEOUT))
    output_name = args.output_file_name or stage.get(
        "output_file_name", "enhanced_tests.jsonl"
    )
    groups_name, summary_name = derived_file_names(output_name)
    execution_models = list(settings["execution_models"])
    launch_settings = dict(settings["enhanced_launch"])

    cli_jobs = parse_jobs_arg(args.jobs) if args.jobs else None
    jobs = resolve_jobs(settings, cli_jobs)

    # environment gate BEFORE any record is written (2026-08-08, same
    # rationale as the dynamic preflight gate): without a compiler every
    # sample would become build_failed — a full dataset of records that
    # reads like model failures. Scope: the stage's configured execution
    # models; the compiler is fixed to g++ here (compile_argv and the
    # serial gates both use it).
    missing = missing_toolchain(execution_models, primary_compiler="g++")
    if missing:
        print(
            "ENVIRONMENT GATE FAILED — aborting before any record is "
            "written. Missing toolchain for execution models "
            f"{'/'.join(execution_models)}: " + ", ".join(missing)
            + ". The enhanced stage runs inside the pareval-thesis "
            "container."
        )
        sys.exit(2)

    # MISMATCH_REPORT_MAX from the single config source
    # (stages.repair.feedback.mismatch_report_max_indices)
    mismatch_k = int(
        ((config.get("stages") or {}).get("repair") or {})
        .get("feedback", {})
        .get("mismatch_report_max_indices", 3)
    )

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])

    # freeze the run configuration / record config drift (run_manifest.py)
    from thesis.evaluation.run_manifest import ensure_run_manifest

    ensure_run_manifest(
        config, run_id, stage="enhanced_tests", profile=args.profile,
        primary_compiler="g++",
    )

    llm_specs = load_llm_specs(Path(args.specs))
    signatures = load_serial_signatures()

    models = [
        model
        for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    print(
        f"Enhanced tests | run {run_id} | target {target_cases} specs/benchmark "
        f"| execution models: {'/'.join(execution_models)} "
        "(gates stay serial) | jobs: "
        + ",".join("%s=%d" % (m, jobs[m]) for m in execution_models)
    )
    print(f"LLM specs: {sum(len(v) for v in llm_specs.values())} from {args.specs}")
    print("=" * 50)

    # (spec_key) -> gate status, shared across models; READ-ONLY inside the
    # worker pool (precomputed serially per model before the pool starts)
    gate_cache: "dict[tuple, str]" = {}
    # benchmark -> wrapper text (or None if not buildable)
    wrapper_cache: "dict[str, str | None]" = {}

    for model_config in models:
        model_id = model_config["id"]
        output_path = intermediate_dir / run_id / model_id / output_name
        groups_path = output_path.parent / groups_name

        if args.force:
            # the summary must go too: a stale marker-less summary from a
            # legacy run next to new-format records would assert legacy
            # timing semantics to the overview (review finding 2026-08-08)
            for path in (output_path, groups_path,
                         output_path.parent / summary_name):
                if path.exists():
                    path.unlink()

        # resume: (sample_id, spec_key) pairs already recorded are skipped
        done: "set" = set()
        if output_path.exists():
            import json as _json

            with output_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = _json.loads(line)
                        done.add((row["sample_id"], spec_key(row["spec"])))
                    except (ValueError, KeyError):
                        continue

            if done:
                print(f"[{model_id}] resume: {len(done)} (sample, spec) rows exist, skipping those")

        # A resume over a LEGACY file (pre-grouping records: no groups
        # file, no marker in the summary) mixes duration semantics per
        # record — old rows are build+run, new rows run-only. The SUM
        # stays correct (legacy build+run + new run + new group compiles
        # = the true total), but per-record duration analyses cannot tell
        # the rows apart afterwards, so the mix is RECORDED instead of
        # silent: legacy_mixed_rows in the summary + a console warning.
        # This path is real — phase-2 backfill invokes the runner on any
        # legacy run with partial spec coverage. (All-gated legacy files
        # without durations are counted too — conservative, harmless.)
        legacy_mixed_rows = 0
        if done and not groups_path.exists():
            marker = None
            summary_file = output_path.parent / summary_name
            if summary_file.exists():
                try:
                    marker = json.loads(
                        summary_file.read_text(encoding="utf-8")
                    ).get("timing_semantics")
                except (ValueError, OSError):
                    pass
            if marker is None:
                legacy_mixed_rows = len(done)
                print(
                    f"[{model_id}] WARNING: resuming over {legacy_mixed_rows} "
                    "legacy (build+run) rows — this file now mixes duration "
                    "semantics per record (sum stays correct; recorded as "
                    "legacy_mixed_rows in the summary)"
                )

        counts: Counter = Counter()
        samples_seen = 0
        specs_by_benchmark: "dict[str, list[dict]]" = {}
        worklist: "list[tuple]" = []  # (sample, benchmark, pending specs)

        for sample in framework.iter_assembled_samples(
            REPO_ROOT, intermediate_dir, run_id, model_id
        ):
            if sample.execution_model not in execution_models:
                continue

            benchmark = f"{sample.problem_type}/{sample.name}"
            cpu_cc = sample.benchmark_dir / "cpu.cc"

            if not cpu_cc.exists() or "ENHANCED_TEST_SIZE_DEFAULT" not in cpu_cc.read_text(
                encoding="utf-8"
            ):
                counts["benchmark_not_parameterizable"] += 1
                continue

            samples_seen += 1

            if benchmark not in specs_by_benchmark:
                specs_by_benchmark[benchmark] = build_benchmark_specs(
                    benchmark, llm_specs.get(benchmark, []), config
                )
            specs = specs_by_benchmark[benchmark]

            if len(specs) < target_cases:
                print(
                    f"  [{benchmark}] under_target: {len(specs)}/{target_cases} "
                    "specs (mutation space exhausted)"
                )

            pending = [
                spec for spec in specs
                if (sample.sample_id, spec_key(spec)) not in done
            ]

            if pending:
                worklist.append((sample, benchmark, pending))

        new_gates = precompute_gates(
            worklist, gate_cache, wrapper_cache, signatures, mismatch_k
        )
        if new_gates:
            print(f"[{model_id}] gates: {new_gates} new spec gate(s) precomputed serially")

        for execution_model in execution_models:
            entries = [
                entry for entry in worklist
                if entry[0].execution_model == execution_model
            ]
            if not entries:
                continue

            workers = int(jobs.get(execution_model, 1))
            if execution_model == "omp":
                ranks = int(launch_settings["omp_threads"])
            elif execution_model == "mpi":
                ranks = int(launch_settings["mpi_ranks"])
            else:
                ranks = 1

            # best-effort core count: sched_getaffinity sees cpuset limits
            # inside the container, os.cpu_count does not (cgroup --cpus
            # CFS quotas stay invisible to both — the hint cannot catch
            # those); clamped to the samples actually submitted
            if hasattr(os, "sched_getaffinity"):
                cores = len(os.sched_getaffinity(0)) or 1
            else:
                cores = os.cpu_count() or 1
            effective_workers = min(workers, len(entries))
            if effective_workers * ranks > cores:
                # hint, never an abort (docs/parallel-execution.md): the
                # user may knowingly overcommit, but timeouts caused by
                # overcommit would enter the RESULTS as <tool>_timed_out
                print(
                    f"[{model_id}] INFO: {execution_model} "
                    f"jobs={effective_workers} x {ranks} threads/ranks = "
                    f"{effective_workers * ranks} > {cores} cores — "
                    "overcommit can turn into timeouts in the results; "
                    "see docs/parallel-execution.md"
                )

            phase_started = time.time()

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        process_sample, sample, benchmark, pending, gate_cache,
                        run_id, model_id, mismatch_k, run_timeout, launch_settings,
                    )
                    for sample, benchmark, pending in entries
                ]

                # ONLY the main thread appends (both files); workers return
                # records. Append order is completion order — resume keys on
                # (sample_id, spec_key), not on row order.
                try:
                    for future in as_completed(futures):
                        records, group_rows = future.result()

                        for row in group_rows:
                            common.append_jsonl(groups_path, row)

                        for record in records:
                            counts[record["status"]] += 1
                            common.append_jsonl(output_path, record)
                except BaseException:
                    # a worker exception or Ctrl-C must not let the pool
                    # silently DRAIN the queue: without cancellation,
                    # shutdown(wait=True) executes every still-queued
                    # sample and discards its records (hours of wasted
                    # compiles). Cancel the queue, let the with-block wait
                    # only for the <= jobs already-running workers; their
                    # unconsumed results are redone on resume.
                    # (cancel_futures= is py3.9+; explicit cancel keeps
                    # the 3.8 compatibility contract.)
                    for pending_future in futures:
                        pending_future.cancel()
                    raise

            print(
                f"[{model_id}] {execution_model}: {len(entries)} sample(s) in "
                f"{time.time() - phase_started:.1f}s wall (jobs={workers})"
            )

        print(
            f"[{model_id}] samples ({'/'.join(execution_models)}): {samples_seen}"
        )
        for status in (
            "pass", "fail", "crash", "timeout", "runtime_error",
            "build_failed", "baseline_incompatible", "numerically_unstable",
        ):
            if counts.get(status):
                print(f"    {status}: {counts[status]}")
        print(f"[{model_id}] output: {output_path}")

        # summary incl. the EFFECTIVE enhanced_tests config so that runs
        # with different configurations stay distinguishable; the
        # timing_semantics marker is what build_overview.py keys on to
        # interpret duration_seconds correctly for THIS run's files
        summary = {
            "schema_version": ENHANCED_SCHEMA_VERSION + ".summary",
            "run_id": run_id,
            "model_id": model_id,
            "created_at_utc": common.utc_now_iso(),
            "counts": dict(counts),
            "samples_seen": samples_seen,
            "resumed_rows": len(done),
            "timing_semantics": TIMING_SEMANTICS,
            "build_groups_file": groups_name,
            # >0 marks a resume over pre-grouping rows: THOSE rows carry
            # build+run mixed durations while all newer rows are run-only
            # (sum stays correct; per-record splits must exclude this run)
            "legacy_mixed_rows": legacy_mixed_rows,
            "effective_config": {
                **settings,
                "jobs": jobs,
                "run_timeout_seconds": run_timeout,
                "specs_file": str(args.specs),
            },
        }
        common.write_json(output_path.parent / summary_name, summary)


if __name__ == "__main__":
    main()
