"""Dynamic-analysis stage runner (sanitizer-instrumented executions).

Runs every configured dynamic tool over every assembled sample and writes
one record per sample to dynamic_analysis.jsonl, plus a per-model summary.
Structure mirrors run_static_analysis.py; the tools implement the same Tool
protocol and Finding schema (see thesis/evaluation/dynamic_tools.py).

Usage (inside the pareval-thesis container):
    python3 thesis/evaluation/run_dynamic_analysis.py \
        --config thesis/config/config.yaml --profile smoke
    python3 thesis/evaluation/run_dynamic_analysis.py ... \
        --model-id deepseek_v4_pro --tools tsan
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation.dynamic_tools import register_dynamic_tools  # noqa: E402

DYNAMIC_ANALYSIS_SCHEMA_VERSION = "dynamic_analysis.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dynamic analysis on assembled samples.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument(
        "--tools",
        nargs="*",
        default=None,
        help="Override the tool list from config.",
    )
    parser.add_argument("--primary-compiler", default="g++", choices=["g++", "clang++"])
    return parser.parse_args()


def resolve_tool_names(config: dict[str, Any], override: list[str] | None) -> list[str]:
    if override:
        return override

    stage = (config.get("stages") or {}).get("dynamic_analysis") or {}
    return stage.get("tools", ["asan_ubsan", "tsan"])


def run_model(
    context: framework.EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    tool_names: list[str],
    output_file_name: str,
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / output_file_name

    if output_path.exists():
        output_path.unlink()

    available_tools = []
    for name in tool_names:
        tool = framework.get_tool(name)
        if tool.is_available():
            available_tools.append(tool)
        else:
            print(f"[{model_id}] tool '{name}' unavailable in this environment, skipping.")

    per_tool_findings: Counter = Counter()
    per_tool_blocking: Counter = Counter()
    per_tool_errors: Counter = Counter()
    samples_seen = 0
    samples_with_blocking = 0

    for sample in framework.iter_assembled_samples(
        context.repo_root, intermediate_dir, run_id, model_id
    ):
        samples_seen += 1

        record: dict[str, Any] = {
            "schema_version": DYNAMIC_ANALYSIS_SCHEMA_VERSION,
            "run_id": run_id,
            "model_id": model_id,
            "sample_id": sample.sample_id,
            "execution_model": sample.execution_model,
            "created_at_utc": common.utc_now_iso(),
            "tools": {},
        }

        sample_has_blocking = False

        for tool in available_tools:
            result = tool.run(sample, context)
            record["tools"][tool.name] = result.to_dict()

            per_tool_findings[tool.name] += len(result.findings)
            per_tool_blocking[tool.name] += len(result.blocking_findings)

            if result.ran and result.error:
                per_tool_errors[tool.name] += 1

            if result.blocking_findings:
                sample_has_blocking = True

        record["has_blocking_findings"] = sample_has_blocking
        if sample_has_blocking:
            samples_with_blocking += 1

        common.append_jsonl(output_path, record)

    summary = {
        "model_id": model_id,
        "samples": samples_seen,
        "samples_with_blocking": samples_with_blocking,
        "findings_per_tool": dict(per_tool_findings),
        "blocking_per_tool": dict(per_tool_blocking),
        "errors_per_tool": dict(per_tool_errors),
        "tools_run": [t.name for t in available_tools],
    }

    print(
        f"[{model_id}] samples: {samples_seen}, "
        f"with blocking findings: {samples_with_blocking}"
    )
    for name in summary["tools_run"]:
        line = (
            f"    {name}: {per_tool_findings[name]} findings "
            f"({per_tool_blocking[name]} blocking)"
        )
        if per_tool_errors[name]:
            line += f", {per_tool_errors[name]} tool errors"
        print(line)
    print(f"[{model_id}] output: {output_path}")

    return summary


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    run_id = profile["run_id"]

    stage = (config.get("stages") or {}).get("dynamic_analysis") or {}
    output_file_name = stage.get("output_file_name", "dynamic_analysis.jsonl")

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    drivers_cpp_dir = REPO_ROOT / "drivers" / "cpp"

    register_dynamic_tools()

    tool_names = resolve_tool_names(config, args.tools)
    known = []
    for name in tool_names:
        try:
            framework.get_tool(name)
            known.append(name)
        except KeyError:
            print(f"Tool '{name}' configured but not implemented yet, skipping.")

    context = framework.EvaluationContext(
        repo_root=REPO_ROOT,
        drivers_cpp_dir=drivers_cpp_dir,
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

    print(f"Dynamic analysis | run {run_id} | tools: {', '.join(known)}")
    print("=" * 40)

    for model_config in models:
        run_model(
            context=context,
            intermediate_dir=intermediate_dir,
            run_id=run_id,
            model_id=model_config["id"],
            tool_names=known,
            output_file_name=output_file_name,
        )


if __name__ == "__main__":
    main()
