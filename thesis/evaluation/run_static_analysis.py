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
from thesis.evaluation.tool_config import (  # noqa: E402
    ToolSettings,
    mark_low_confidence,
    resolve_tool_settings,
)
from thesis.evaluation.tools import register_default_tools  # noqa: E402

# v2: per-tool config schema — findings carry low_confidence, per-tool
# entries carry num_low_confidence, records carry low_confidence_count,
# out-of-scope tools are recorded as not-applicable entries.
STATIC_ANALYSIS_SCHEMA_VERSION = "static_analysis.v2"

# Container toolchain manifest (written at image build time). Phase-2
# backfill compares its container against the phase-1 record
# (repair-loop-design.md §6), so the first phase-1 invocation drops a copy
# next to the run's artifacts.
TOOLCHAIN_VERSIONS_FILE = Path("/opt/toolchain-versions.txt")


def record_toolchain_versions(intermediate_dir: Path, run_id: str) -> None:
    target = intermediate_dir / run_id / "toolchain-versions.txt"

    if TOOLCHAIN_VERSIONS_FILE.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            TOOLCHAIN_VERSIONS_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        print(f"Toolchain versions recorded: {target}")


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
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the profile run_id (repair-loop iteration artifacts "
        "use the convention <run>__<variant>__iter<N>).",
    )
    return parser.parse_args()


def resolve_enabled_tools(
    config: dict[str, Any], override: list[str] | None, stage_name: str
) -> "dict[str, ToolSettings]":
    """Enabled tools from the per-tool config schema.

    The --tools CLI override FILTERS the enabled set (container split), it
    cannot enable a config-disabled tool — that is a config decision.
    """
    settings = resolve_tool_settings(config, stage_name)
    enabled = {name: s for name, s in settings.items() if s.enabled}

    if override:
        for name in override:
            if name in settings and name not in enabled:
                print(
                    f"Tool '{name}' requested via --tools but disabled in the "
                    f"config; enable it under stages.{stage_name}.tools first."
                )
        enabled = {name: s for name, s in enabled.items() if name in override}

    return enabled


def not_applicable_entry(tool_name: str, execution_model: str) -> dict[str, Any]:
    """Record entry for a tool whose configured scope excludes this sample."""
    return framework.ToolResult(
        tool=tool_name,
        ran=False,
        exit_code=None,
        duration_seconds=0.0,
        error=f"not applicable: '{execution_model}' outside configured execution_models",
    ).to_dict()


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


def record_low_confidence_count(record: dict[str, Any]) -> int:
    return sum(
        tool_data.get("num_low_confidence", 0)
        for tool_data in record.get("tools", {}).values()
    )


def run_model(
    context: framework.EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    tool_settings: "dict[str, ToolSettings]",
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / "static_analysis.jsonl"

    records = load_existing_records(output_path)

    available_tools = []
    for name in tool_settings:
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
        record["schema_version"] = STATIC_ANALYSIS_SCHEMA_VERSION

        for tool in available_tools:
            settings = tool_settings[tool.name]

            # configured scope (config ∩ hard capability) gates the run;
            # the record still gets an explicit not-applicable entry so
            # downstream consumers see the decision
            if not settings.applies_to(sample.execution_model):
                record["tools"][tool.name] = not_applicable_entry(
                    tool.name, sample.execution_model
                )
                continue

            result = tool.run(sample, context)

            num_low_confidence = mark_low_confidence(result.findings, settings)

            entry = result.to_dict()
            entry["num_low_confidence"] = num_low_confidence
            record["tools"][tool.name] = entry

            per_tool_findings[tool.name] += len(result.findings)
            per_tool_blocking[tool.name] += len(result.blocking_findings)

        # Recompute over ALL tools in the record (merged across invocations).
        record["has_blocking_findings"] = record_has_blocking(record)
        record["low_confidence_count"] = record_low_confidence_count(record)
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
    run_id = args.run_id or profile["run_id"]

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    drivers_cpp_dir = REPO_ROOT / "drivers" / "cpp"

    register_default_tools(primary_compiler=args.primary_compiler, config=config)

    enabled_settings = resolve_enabled_tools(config, args.tools, "static_analysis")

    # Only keep tools the registry actually knows; warn on the rest.
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

    scopes = ", ".join(
        f"{name}[{'/'.join(s.execution_models)}]" for name, s in known.items()
    )
    print(f"Static analysis | run {run_id} | tools: {scopes}")
    print("=" * 40)

    record_toolchain_versions(intermediate_dir, run_id)

    for model_config in models:
        run_model(
            context=context,
            intermediate_dir=intermediate_dir,
            run_id=run_id,
            model_id=model_config["id"],
            tool_settings=known,
        )


if __name__ == "__main__":
    main()
