"""Enhanced-tests stage runner: differential testing on spec-defined inputs.

For every assembled SERIAL sample and every spec of its benchmark (static
base set + LLM seeds + one deterministic mutation round, capped per
benchmark) this compiles the sample with the spec's defines and runs the
benchmark's validate() differentially against the baseline.

BASELINE GATE (runs first, cached per spec): the baseline itself — as a
forwarding generated-code.hpp — is executed under every spec. If the
baseline crashes, hangs or fails to build, the spec is baseline_incompatible
for this benchmark and is never counted against a model. This consumes the
same machinery as thesis/enhanced_tests/baseline_selftest.py.

Statuses per (sample, spec): pass | fail | crash | timeout | build_failed |
baseline_incompatible. Output: enhanced_tests.jsonl per model (schema
enhanced_tests.v1) + per-model summary, same layout as the other stages.

Scope: serial only for now (omp/mpi follow once serial is proven; they add
the correctness launch grids). Non-parameterizable benchmarks are skipped.

Usage (main container):
    python3 thesis/evaluation/run_enhanced_tests.py \
        --config thesis/config/config.yaml --profile smoke [--model-id X]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.evaluation import framework  # noqa: E402
from thesis.enhanced_tests.baseline_selftest import (  # noqa: E402
    build_wrapper,
    compile_and_run,
    load_serial_signatures,
    stability_probe,
)
from thesis.enhanced_tests.specs import (  # noqa: E402
    DEFAULT_MAX_CASES_PER_BENCHMARK,
    build_benchmark_specs,
    spec_defines,
    spec_key,
)

ENHANCED_SCHEMA_VERSION = "enhanced_tests.v1"

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
    return parser.parse_args()


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


def compile_sample(sample: framework.AssembledSample, defines: "list[str]", out_path: str) -> "tuple[bool, float]":
    argv = [
        "g++", "-std=c++17", "-O1",
        "-DUSE_SERIAL", "-DDRIVER_PROBLEM_SIZE=(1<<4)",
        *[f"-D{d}" for d in defines],
        "-I", str(DRIVERS_CPP), "-I", str(DRIVERS_CPP / "models"),
        "-I", str(sample.source_path.parent),
        str(DRIVERS_CPP / "models" / "serial-driver.cc"),
        str(sample.benchmark_dir / "cpu.cc"),
        "-o", out_path,
    ]

    started = time.time()

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, time.time() - started

    return result.returncode == 0, time.time() - started


def run_binary(binary: str, cwd: str, timeout: float) -> "tuple[str, int | None, float]":
    started = time.time()

    try:
        result = subprocess.run(
            [binary, "1"], capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
    except subprocess.TimeoutExpired:
        return "timeout", None, time.time() - started

    duration = time.time() - started

    if result.returncode != 0:
        return "crash", result.returncode, duration

    if "Validation: PASS" in result.stdout:
        return "pass", result.returncode, duration

    return "fail", result.returncode, duration


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    run_id = profile["run_id"]

    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    max_cases = int(stage.get("max_cases_per_benchmark", DEFAULT_MAX_CASES_PER_BENCHMARK))
    run_timeout = float(stage.get("run_timeout_seconds", DEFAULT_RUN_TIMEOUT))
    output_name = stage.get("output_file_name", "enhanced_tests.jsonl")

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])

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

    print(f"Enhanced tests | run {run_id} | max {max_cases} specs/benchmark | serial only")
    print(f"LLM specs: {sum(len(v) for v in llm_specs.values())} from {args.specs}")
    print("=" * 50)

    # (spec_key) -> gate status, shared across models
    gate_cache: "dict[tuple, str]" = {}
    # benchmark -> wrapper text (or None if not buildable)
    wrapper_cache: "dict[str, str | None]" = {}

    for model_config in models:
        model_id = model_config["id"]
        output_path = intermediate_dir / run_id / model_id / output_name

        if output_path.exists():
            output_path.unlink()

        counts: Counter = Counter()
        samples_seen = 0

        for sample in framework.iter_assembled_samples(
            REPO_ROOT, intermediate_dir, run_id, model_id
        ):
            if sample.execution_model != "serial":
                continue

            benchmark = f"{sample.problem_type}/{sample.name}"
            cpu_cc = sample.benchmark_dir / "cpu.cc"

            if not cpu_cc.exists() or "ENHANCED_TEST_SIZE_DEFAULT" not in cpu_cc.read_text(
                encoding="utf-8"
            ):
                counts["benchmark_not_parameterizable"] += 1
                continue

            samples_seen += 1

            if benchmark not in wrapper_cache:
                prompt_text = signatures.get(sample.name)
                wrapper_cache[benchmark] = (
                    build_wrapper(sample.benchmark_dir, prompt_text) if prompt_text else None
                )

            wrapper = wrapper_cache[benchmark]
            specs = build_benchmark_specs(benchmark, llm_specs.get(benchmark, []), max_cases)

            for spec in specs:
                key = spec_key(spec)
                defines = spec_defines(spec)

                # baseline gate (cached), two probes per spec:
                #   1. crash/hang: a crashing oracle never counts against a
                #      model (baseline_incompatible)
                #   2. numerical stability (two-TU probe): a second oracle
                #      instance compiled with perturbed FP flags in its OWN
                #      translation unit must still validate against the
                #      normal oracle. If not, the input is degenerate for the
                #      differential comparison (e.g. descending ramp -> exactly
                #      singular matrix for pivot-free LU: two CORRECT
                #      implementations diverge via rounding order alone) ->
                #      numerically_unstable, never counted against a model.
                if key not in gate_cache:
                    prompt_text = signatures.get(sample.name)

                    if wrapper is None or prompt_text is None:
                        gate_cache[key] = "wrapper_failed"
                    else:
                        plain = compile_and_run(sample.benchmark_dir, wrapper, defines)

                        if plain != "pass":
                            gate_cache[key] = plain
                        else:
                            perturbed = stability_probe(
                                sample.benchmark_dir, prompt_text, defines
                            )
                            gate_cache[key] = (
                                "pass" if perturbed == "pass" else "numerically_unstable"
                            )

                record: dict[str, Any] = {
                    "schema_version": ENHANCED_SCHEMA_VERSION,
                    "run_id": run_id,
                    "model_id": model_id,
                    "sample_id": sample.sample_id,
                    "benchmark": benchmark,
                    "spec": spec,
                    "created_at_utc": common.utc_now_iso(),
                }

                gate = gate_cache[key]

                if gate != "pass":
                    record["status"] = (
                        "numerically_unstable"
                        if gate == "numerically_unstable"
                        else "baseline_incompatible"
                    )
                    record["baseline_gate"] = gate
                    counts[record["status"]] += 1
                    common.append_jsonl(output_path, record)
                    continue

                with tempfile.TemporaryDirectory() as tmp:
                    binary = str(Path(tmp) / "enhanced.out")
                    built, build_seconds = compile_sample(sample, defines, binary)

                    if not built:
                        record["status"] = "build_failed"
                        record["duration_seconds"] = round(build_seconds, 3)
                        counts["build_failed"] += 1
                        common.append_jsonl(output_path, record)
                        continue

                    status, exit_code, run_seconds = run_binary(binary, tmp, run_timeout)

                record["status"] = status
                record["exit_code"] = exit_code
                record["duration_seconds"] = round(build_seconds + run_seconds, 3)
                counts[status] += 1
                common.append_jsonl(output_path, record)

        print(f"[{model_id}] serial samples: {samples_seen}")
        for status in (
            "pass", "fail", "crash", "timeout", "build_failed",
            "baseline_incompatible", "numerically_unstable",
        ):
            if counts.get(status):
                print(f"    {status}: {counts[status]}")
        print(f"[{model_id}] output: {output_path}")


if __name__ == "__main__":
    main()
