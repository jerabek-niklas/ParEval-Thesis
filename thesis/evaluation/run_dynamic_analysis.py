"""Dynamic-analysis stage runner (sanitizer-instrumented executions).

Runs every configured dynamic tool over every assembled sample and writes
one record per sample to dynamic_analysis.jsonl, plus a per-model summary
(dynamic_analysis_summary.json). Structure mirrors run_static_analysis.py;
the tools implement the same Tool protocol and Finding schema (see
thesis/evaluation/dynamic_tools.py).

ENVIRONMENT PREFLIGHT GATE (2026-08-08): before ANY record is written, every
enabled tool is preflighted ONCE — tools with their own preflight() (TSan:
compile+run a trivial sanitized binary; catches the WSL2 vm.mmap_rnd_bits
SIGSEGV) reuse it, the rest are checked via is_available(). A failing tool
ABORTS the run with the cause and the concrete remedy command. Rationale
(measured on smoke_003): TSan silently produced `ran: false` for ALL 11
models' omp samples after a VM reboot reset vm.mmap_rnd_bits — visible only
as n/a in the overview, noticed days later. In a pilot/full run that is an
expensive silent loss of a whole tool dimension. --skip-unavailable-tools
opts into running WITHOUT the failing tools; the drop is then WARNed per
tool and persisted as `tools_skipped` in the summary artifact, so the gap
is documented in the artifacts, not just in the terminal. The per-SAMPLE
`ran: false` semantics are untouched — a tool failing on one concrete
sample is a data point; the gate only addresses "this tool cannot run in
this environment at all".

MERGE SEMANTICS (2026-08-08, aligned with run_static_analysis): re-runs
merge PER TOOL into existing records instead of deleting the file — a
`--tools tsan` invocation refreshes only the tsan entries and preserves
asan/memcheck/must results (previously the runner unlinked the output, so
a partial rerun would have destroyed the other tools' data). The file is
rewritten atomically after every sample; `has_blocking_findings` and
`low_confidence_count` are recomputed over ALL entries of the merged
record.

Usage (inside the pareval-thesis container):
    python3 thesis/evaluation/run_dynamic_analysis.py \
        --config thesis/config/config.yaml --profile smoke
    python3 thesis/evaluation/run_dynamic_analysis.py ... \
        --model-id deepseek_v4_pro --tools tsan
"""

from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument(
        "--skip-unavailable-tools",
        action="store_true",
        help="Escape hatch for the environment preflight gate: knowingly "
        "run WITHOUT tools that fail their preflight, instead of aborting. "
        "Each drop is WARNed and persisted as tools_skipped in the "
        "per-model summary artifact.",
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


def preflight_failures(tool_names: "list[str]") -> "list[tuple[str, str]]":
    """(tool, reason) for every tool that cannot run IN THIS ENVIRONMENT.

    Tools exposing their own preflight() (TSan) are asked for the real
    thing — a trivial compile+run whose failure text already carries the
    remedy command (e.g. the vm.mmap_rnd_bits sysctl for WSL2). Everything
    else gets the cheap availability check. One check per tool per
    process; the per-sample run path is untouched."""
    failures: "list[tuple[str, str]]" = []

    for name in tool_names:
        tool = framework.get_tool(name)

        if not tool.is_available():
            failures.append((
                name,
                "required binary/toolchain not found (is_available() failed) "
                "— wrong host or container? The dynamic stage runs inside "
                "the pareval-thesis container.",
            ))
            continue

        preflight = getattr(tool, "preflight", None)
        if callable(preflight):
            reason = preflight()
            if reason:
                failures.append((name, reason))

    return failures


def apply_preflight_gate(
    tool_settings: "dict[str, ToolSettings]",
    skip_unavailable: bool,
) -> "tuple[dict[str, ToolSettings], list[dict[str, str]]]":
    """Enforce the environment gate BEFORE any record is written.

    Returns (usable settings, skipped notes). Aborts the process (exit 2)
    on any failure unless --skip-unavailable-tools was given."""
    failures = preflight_failures(list(tool_settings))

    if not failures:
        return tool_settings, []

    if not skip_unavailable:
        print("ENVIRONMENT PREFLIGHT FAILED — aborting before any record is written:")
        for name, reason in failures:
            print(f"  [{name}] {reason}")
        print(
            "Fix the environment, or rerun with --skip-unavailable-tools to "
            "knowingly drop these tools (the run summary will then record "
            "tools_skipped)."
        )
        sys.exit(2)

    skipped = []
    for name, reason in failures:
        print(f"WARNING: skipping tool '{name}' for this ENTIRE run — {reason}")
        skipped.append({"tool": name, "reason": reason})

    usable = {
        name: settings for name, settings in tool_settings.items()
        if name not in {f[0] for f in failures}
    }
    return usable, skipped


def load_existing_records(output_path: Path) -> "dict[str, dict[str, Any]]":
    """Prior dynamic_analysis.jsonl records keyed by sample_id.

    Re-runs merge per tool instead of discarding the file (same contract
    as run_static_analysis): a --tools subset invocation must not destroy
    the other tools' results."""
    records: "dict[str, dict[str, Any]]" = {}

    if not output_path.exists():
        return records

    with output_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                entry = json.loads(line)
                records[entry["sample_id"]] = entry

    return records


def record_has_blocking(record: "dict[str, Any]") -> bool:
    return any(
        tool_data.get("num_blocking", 0) > 0
        for tool_data in record.get("tools", {}).values()
    )


def record_low_confidence_count(record: "dict[str, Any]") -> int:
    return sum(
        tool_data.get("num_low_confidence", 0)
        for tool_data in record.get("tools", {}).values()
    )


def write_records_atomic(output_path: Path, records: "dict[str, dict[str, Any]]") -> None:
    """Rewrite the full record file via a temp file + replace, so a hard
    kill mid-write can never truncate existing data (dynamic runs are the
    longest in the pipeline — memcheck/MUST)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(output_path.parent),
        prefix=output_path.name + ".", suffix=".tmp", delete=False,
    )
    try:
        with handle as file:
            for entry in records.values():
                file.write(json.dumps(entry) + "\n")
        os.replace(handle.name, str(output_path))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def run_model(
    context: framework.EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    tool_settings: "dict[str, ToolSettings]",
    output_file_name: str,
    tools_skipped: "list[dict[str, str]]",
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / output_file_name

    records = load_existing_records(output_path)

    tools = [framework.get_tool(name) for name in tool_settings]

    per_tool_findings: Counter = Counter()
    per_tool_blocking: Counter = Counter()
    per_tool_errors: Counter = Counter()
    samples_seen = 0
    samples_with_blocking = 0

    for sample in framework.iter_assembled_samples(
        context.repo_root, intermediate_dir, run_id, model_id
    ):
        samples_seen += 1

        record = records.get(sample.sample_id)

        if record is None:
            record = {
                "schema_version": DYNAMIC_ANALYSIS_SCHEMA_VERSION,
                "run_id": run_id,
                "model_id": model_id,
                "sample_id": sample.sample_id,
                "execution_model": sample.execution_model,
                "tools": {},
            }
            records[sample.sample_id] = record

        record["created_at_utc"] = common.utc_now_iso()
        record["schema_version"] = DYNAMIC_ANALYSIS_SCHEMA_VERSION

        for tool in tools:
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

            entry = result.to_dict()
            entry["num_low_confidence"] = num_low_confidence
            record["tools"][tool.name] = entry

            per_tool_findings[tool.name] += len(result.findings)
            per_tool_blocking[tool.name] += len(result.blocking_findings)

            if result.ran and result.error:
                per_tool_errors[tool.name] += 1

        # recompute over ALL tools of the merged record (a --tools subset
        # invocation must account for entries from earlier invocations)
        record["has_blocking_findings"] = record_has_blocking(record)
        record["low_confidence_count"] = record_low_confidence_count(record)
        if record["has_blocking_findings"]:
            samples_with_blocking += 1

        write_records_atomic(output_path, records)

    summary = {
        "model_id": model_id,
        "samples": samples_seen,
        "samples_with_blocking": samples_with_blocking,
        "findings_per_tool": dict(per_tool_findings),
        "blocking_per_tool": dict(per_tool_blocking),
        "errors_per_tool": dict(per_tool_errors),
        "tools_run": [t.name for t in tools],
        # environment-gate drops (--skip-unavailable-tools): persisted so
        # the gap is visible in the ARTIFACTS, not only in the terminal
        "tools_skipped": tools_skipped,
        "created_at_utc": common.utc_now_iso(),
    }
    common.write_json(
        output_path.parent / "dynamic_analysis_summary.json", summary
    )

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

    # environment gate ONCE, before any model/record — see module docstring
    known, tools_skipped = apply_preflight_gate(known, args.skip_unavailable_tools)

    if not known:
        print("No usable dynamic tools after the environment gate — nothing to run.")
        sys.exit(2)

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
            tools_skipped=tools_skipped,
        )


if __name__ == "__main__":
    main()
