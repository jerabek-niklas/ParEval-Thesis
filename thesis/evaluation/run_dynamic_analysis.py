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
from thesis.evaluation.tool_config import (  # noqa: E402
    ToolSettings,
    mark_low_confidence,
    resolve_tool_settings,
)

# v2: per-tool config schema — findings carry low_confidence, per-tool
# entries carry num_low_confidence, records carry low_confidence_count,
# out-of-scope tools are recorded as not-applicable entries.
DYNAMIC_ANALYSIS_SCHEMA_VERSION = "dynamic_analysis.v2"


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
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the profile run_id (repair-loop iteration artifacts "
        "use the convention <run>__<variant>__iter<N>).",
    )
    return parser.parse_args()


def resolve_enabled_tools(
    config: dict[str, Any], override: list[str] | None
) -> "dict[str, ToolSettings]":
    """Enabled tools from the per-tool config schema; --tools FILTERS the
    enabled set (container split), it cannot enable a config-disabled tool."""
    settings = resolve_tool_settings(config, "dynamic_analysis")
    enabled = {name: s for name, s in settings.items() if s.enabled}

    if override:
        for name in override:
            if name in settings and name not in enabled:
                print(
                    f"Tool '{name}' requested via --tools but disabled in the "
                    f"config; enable it under stages.dynamic_analysis.tools first."
                )
        enabled = {name: s for name, s in enabled.items() if name in override}

    return enabled


def run_model(
    context: framework.EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    tool_settings: "dict[str, ToolSettings]",
    output_file_name: str,
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / output_file_name

    if output_path.exists():
        output_path.unlink()

    available_tools = []
    for name in tool_settings:
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
        sample_low_confidence = 0

        for tool in available_tools:
            settings = tool_settings[tool.name]

            # configured scope (config INTERSECT hard capability) gates the
            # run; the record gets an explicit not-applicable entry
            if not settings.applies_to(sample.execution_model):
                record["tools"][tool.name] = framework.ToolResult(
                    tool=tool.name,
                    ran=False,
                    exit_code=None,
                    duration_seconds=0.0,
                    error=(
                        f"not applicable: '{sample.execution_model}' outside "
                        "configured execution_models"
                    ),
                ).to_dict()
                continue

            result = tool.run(sample, context)

            num_low_confidence = mark_low_confidence(result.findings, settings)
            sample_low_confidence += num_low_confidence

            entry = result.to_dict()
            entry["num_low_confidence"] = num_low_confidence
            record["tools"][tool.name] = entry

            per_tool_findings[tool.name] += len(result.findings)
            per_tool_blocking[tool.name] += len(result.blocking_findings)

            if result.ran and result.error:
                per_tool_errors[tool.name] += 1

            if result.blocking_findings:
                sample_has_blocking = True

        record["has_blocking_findings"] = sample_has_blocking
        record["low_confidence_count"] = sample_low_confidence
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
    run_id = args.run_id or profile["run_id"]

    stage = (config.get("stages") or {}).get("dynamic_analysis") or {}
    output_file_name = stage.get("output_file_name", "dynamic_analysis.jsonl")

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    drivers_cpp_dir = REPO_ROOT / "drivers" / "cpp"

    register_dynamic_tools()

    enabled_settings = resolve_enabled_tools(config, args.tools)
    known: dict[str, ToolSettings] = {}
    for name, settings in enabled_settings.items():
        try:
            framework.get_tool(name)
            known[name] = settings
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

    print(f"Dynamic analysis | run {run_id} | tools: " + ", ".join(f"{n}[{chr(47).join(s.execution_models)}]" for n, s in known.items()))
    print("=" * 40)

    for model_config in models:
        run_model(
            context=context,
            intermediate_dir=intermediate_dir,
            run_id=run_id,
            model_id=model_config["id"],
            tool_settings=known,
            output_file_name=output_file_name,
        )


if __name__ == "__main__":
    main()
