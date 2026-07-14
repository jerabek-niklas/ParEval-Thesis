"""Correctness-test stage runner.

For every assembled sample this stage:
  1. compiles the full benchmark program (model driver + benchmark cpu.cc +
     the assembled generated-code.hpp) exactly as the compile stage does,
  2. runs the binary over the launch grid (serial: once; omp: several
     thread counts; mpi: several rank counts),
  3. parses the driver's "Validation: PASS|FAIL" marker from stdout,
and writes one record per sample to correctness.jsonl plus a per-model
summary.

Verdict semantics (per run):
  - The exit code does NOT signal validation: the serial/omp drivers
    `return 0` after printing "Validation: FAIL", and the mpi driver calls
    MPI_Abort(comm, 0). Only the stdout marker is authoritative.
  - pass              -> marker PASS, exit 0, no timeout
  - validation_failed -> marker FAIL
  - timeout           -> run hit the time limit (for omp/mpi a possible
                         deadlock/livelock signal)
  - runtime_error     -> anything else (crash, missing marker, non-zero exit)

Per-sample verdict: "pass" iff every run passed, "build_failed" if the
compile failed, otherwise the verdict of the first failing run in grid
order. Per-category counts are stored alongside so no information is lost.

Usage (inside the pareval-thesis container):
    python3 thesis/evaluation/run_correctness.py \
        --config thesis/config/config.yaml --profile smoke
    # single model / custom timeout:
    python3 thesis/evaluation/run_correctness.py ... \
        --model-id deepseek_v4_pro --run-timeout 60
"""

from __future__ import annotations

import argparse
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
    return parser.parse_args()


def parse_validation(stdout: str) -> bool | None:
    """Extract the validation verdict from driver stdout.

    Returns True (PASS), False (FAIL) or None (marker missing, i.e. the
    program crashed or hung before printing it).
    """
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(VALIDATION_MARKER):
            return "PASS" in line

    return None


def run_verdict(validation: bool | None, exit_code: int, timed_out: bool) -> str:
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

    argv = config.base_command(
        sources=[str(model_driver), str(benchmark_driver)],
        output_path=str(exec_path),
        include_dirs=context.include_dirs(sample),
        extra_flags=[f"-D{DRIVER_PROBLEM_SIZE_DEFINE}"],
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

            result = run_command(
                argv, timeout=run_timeout, cwd=tmp, extra_env=extra_env
            )

            validation = parse_validation(result.stdout)
            verdict = run_verdict(validation, result.returncode, result.timed_out)
            verdicts[verdict] += 1

            if verdict != "pass" and sample_verdict == "pass":
                sample_verdict = verdict

            runs.append(
                {
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
            )

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
    run_id = profile["run_id"]

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
