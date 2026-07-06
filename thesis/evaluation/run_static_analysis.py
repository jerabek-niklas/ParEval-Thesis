"""Static-analysis stage runner.

Runs every configured tool over every assembled sample and writes one
record per sample to static_analysis.jsonl, plus a per-model summary.

Usage:
    python thesis/evaluation/run_static_analysis.py \
        --config thesis/config/config.yaml --profile smoke
    python thesis/evaluation/run_static_analysis.py \
        --config thesis/config/config.yaml --profile smoke --model-id claude_fable_5
    # restrict to specific tools (otherwise uses stages.static_analysis.tools):
    python thesis/evaluation/run_static_analysis.py ... --tools compiler cppcheck

The runner is tool-agnostic: it asks the registry for each configured tool
and skips (with a logged warning) any tool whose binary is unavailable, so
a partial toolchain still produces partial results instead of crashing.
"""

from __future__ import annotations

import argparse
import json
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
from thesis.evaluation.tools import register_default_tools  # noqa: E402

STATIC_ANALYSIS_SCHEMA_VERSION = "static_analysis.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run static analysis on assembled samples.")
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

    stage = (config.get("stages") or {}).get("static_analysis") or {}
    return stage.get("tools", ["compiler", "cppcheck"])


def load_existing_records(output_path: Path) -> dict[str, dict[str, Any]]:
    """Load prior static_analysis.jsonl records keyed by sample_id.

    Re-runs merge per tool instead of discarding the file: the pipeline runs
    different tool subsets in different containers (main toolchain image vs.
    the PARCOACH image), and each invocation must not destroy the results of
    the other.
    """
    records: dict[str, dict[str, Any]] = {}

    if not output_path.exists():
        return records

    with output_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                entry = json.loads(line)
                records[entry["sample_id"]] = entry

    return records


def record_has_blocking(record: dict[str, Any]) -> bool:
    return any(
        tool_data.get("num_blocking", 0) > 0
        for tool_data in record.get("tools", {}).values()
    )


def run_model(
    context: framework.EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    tool_names: list[str],
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / "static_analysis.jsonl"

    records = load_existing_records(output_path)

    available_tools = []
    for name in tool_names:
        tool = framework.get_tool(name)
        if tool.is_available():
            available_tools.append(tool)
        else:
            print(f"[{model_id}] tool '{name}' unavailable in this environment, skipping.")

    per_tool_findings: Counter = Counter()
    per_tool_blocking: Counter = Counter()
    samples_seen = 0
    samples_with_blocking = 0

    for sample in framework.iter_assembled_samples(
        context.repo_root, intermediate_dir, run_id, model_id
    ):
        samples_seen += 1

        record = records.get(sample.sample_id)

        if record is None:
            record = {
                "schema_version": STATIC_ANALYSIS_SCHEMA_VERSION,
                "run_id": run_id,
                "model_id": model_id,
                "sample_id": sample.sample_id,
                "execution_model": sample.execution_model,
                "tools": {},
            }
            records[sample.sample_id] = record

        record["created_at_utc"] = common.utc_now_iso()

        for tool in available_tools:
            result = tool.run(sample, context)
            record["tools"][tool.name] = result.to_dict()

            per_tool_findings[tool.name] += len(result.findings)
            per_tool_blocking[tool.name] += len(result.blocking_findings)

        # Recompute over ALL tools in the record (merged across invocations).
        record["has_blocking_findings"] = record_has_blocking(record)
        if record["has_blocking_findings"]:
            samples_with_blocking += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for entry in records.values():
            file.write(json.dumps(entry) + "\n")

    summary = {
        "model_id": model_id,
        "samples": samples_seen,
        "samples_with_blocking": samples_with_blocking,
        "findings_per_tool": dict(per_tool_findings),
        "blocking_per_tool": dict(per_tool_blocking),
        "tools_run": [t.name for t in available_tools],
    }

    print(
        f"[{model_id}] samples: {samples_seen}, "
        f"with blocking findings: {samples_with_blocking}"
    )
    for name in summary["tools_run"]:
        print(
            f"    {name}: {per_tool_findings[name]} findings "
            f"({per_tool_blocking[name]} blocking)"
        )
    print(f"[{model_id}] output: {output_path}")

    return summary


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    run_id = profile["run_id"]

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    drivers_cpp_dir = REPO_ROOT / "drivers" / "cpp"

    register_default_tools(primary_compiler=args.primary_compiler)

    tool_names = resolve_tool_names(config, args.tools)
    # Only keep tool names the registry actually knows; warn on the rest
    # (e.g. 'infer' is configured but not yet implemented).
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

    print(f"Static analysis | run {run_id} | tools: {', '.join(known)}")
    print("=" * 40)

    for model_config in models:
        run_model(
            context=context,
            intermediate_dir=intermediate_dir,
            run_id=run_id,
            model_id=model_config["id"],
            tool_names=known,
        )


if __name__ == "__main__":
    main()
