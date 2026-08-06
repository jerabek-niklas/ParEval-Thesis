"""Phase-2 backfill runner (repair-loop-design.md §6).

After the loops terminate, every persisted iteration artifact is missing
the analyses its variant did NOT need at loop time: static tools on
test_feedback artifacts, correctness + dynamic on static_feedback
artifacts, enhanced tests on EVERYTHING (iteration 0 included). This
runner fills those gaps locally (no API cost). It calls the EXISTING
stage runners (direct import / subprocess) and reimplements nothing —
their per-sample merge/resume logic is the completeness mechanism.

Discovery uses the orchestrator's run-id convention: the base run is
iteration 0 (shared across variants), iteration N of a variant lives
under <base_run>__<variant>__iter<N>.

Container split is the usual one: main-container stages run in-process
here; parcoach/llov commands follow stages.repair.external_tools_mode —
manual prints them (and writes backfill_pending.txt next to the base
run's model dir), docker executes the configured templates.

HELD-OUT ORDERING (design §3/§6): enhanced tests run ONLY once every
configured loop variant of the model has terminated (state.jsonl has no
active samples). Otherwise the enhanced stage refuses with a clear
message — the held-out principle stays structurally enforced even during
backfill. The other backfill stages are loop-time tools and may proceed.

Toolchain consistency (design §6): the phase-1 runs record
/opt/toolchain-versions.txt next to the base run's artifacts
(run_static_analysis.record_toolchain_versions); the backfill compares
its own container manifest against that record and WARNS on any
difference (--strict-toolchain turns the warning into an error). If no
record exists (pre-record runs), the backfill stores the current
manifest and says so — the comparison then only covers later phases.

Usage (inside the pareval-thesis container):
    python3 thesis/repair/run_backfill.py --config thesis/config/config.yaml \
        --profile smoke [--model-id X] [--variant static_feedback]
    python3 thesis/repair/run_backfill.py ... --status
    python3 thesis/repair/run_backfill.py ... --strict-toolchain

Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation.tool_config import (  # noqa: E402
    ToolSettings,
    resolve_tool_settings,
)
from thesis.enhanced_tests.specs import (  # noqa: E402
    stage_settings as enhanced_stage_settings,
)
from thesis.repair import orchestrator  # noqa: E402

TOOLCHAIN_VERSIONS_FILE = Path("/opt/toolchain-versions.txt")

# marker the enhanced runner requires in a benchmark's cpu.cc; used ONLY to
# classify enhanced coverage (the runner itself performs the same check)
ENHANCED_MARKER = "ENHANCED_TEST_SIZE_DEFAULT"

STAGE_ORDER = ("static", "correctness", "dynamic", "enhanced")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase-2 backfill over loop artifacts.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument(
        "--variant",
        default=None,
        choices=list(orchestrator.VARIANTS),
        help="Restrict to one variant's iteration runs (iteration 0 is "
        "shared and always included).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the coverage table per (model, variant, iteration) and exit.",
    )
    parser.add_argument(
        "--strict-toolchain",
        action="store_true",
        help="Treat a toolchain-versions mismatch as an error instead of a warning.",
    )
    parser.add_argument(
        "--skip-enhanced",
        action="store_true",
        help="Skip the enhanced-tests stage (e.g. when only the tool "
        "backfill should run in this container session).",
    )
    parser.add_argument("--primary-compiler", default="g++", choices=["g++", "clang++"])
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Shared loaders
# ---------------------------------------------------------------------------


def load_jsonl_by_sample(path: Path) -> "Dict[str, Dict[str, Any]]":
    records: Dict[str, Dict[str, Any]] = {}

    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["sample_id"]] = record

    return records


def load_assembly(intermediate_root: Path, run_id: str, model_id: str
                  ) -> "Dict[str, Dict[str, Any]]":
    return load_jsonl_by_sample(intermediate_root / run_id / model_id / "assembly.jsonl")


def assembled_sample_ids(assembly: "Dict[str, Dict[str, Any]]") -> List[str]:
    return sorted(s for s, e in assembly.items() if e.get("assembled"))


# ---------------------------------------------------------------------------
# Discovery (run-id convention)
# ---------------------------------------------------------------------------


def discover_runs(
    config: Dict[str, Any],
    base_run_id: str,
    model_id: str,
    variant_filter: Optional[str] = None,
) -> "List[Dict[str, Any]]":
    """All runs of a base run for one model, in analysis order:
    the shared base run (iteration 0) first, then every discovered
    <base>__<variant>__iter<N> that has assembly artifacts."""
    intermediate_root = Path(config["outputs"]["intermediate_dir"])

    runs: List[Dict[str, Any]] = []

    if (intermediate_root / base_run_id / model_id / "assembly.jsonl").exists():
        runs.append({"variant": "shared", "iteration": 0, "run_id": base_run_id})

    variants = orchestrator.repair_settings(config)["variants"]

    for variant in variants:
        if variant_filter and variant != variant_filter:
            continue

        prefix = "%s__%s__iter" % (base_run_id, variant)
        found: List[Tuple[int, str]] = []

        for entry in sorted(intermediate_root.glob(prefix + "*")):
            suffix = entry.name[len(prefix):]
            if not suffix.isdigit():
                continue
            if not (entry / model_id / "assembly.jsonl").exists():
                continue
            found.append((int(suffix), entry.name))

        for iteration, run_id in sorted(found):
            runs.append({"variant": variant, "iteration": iteration, "run_id": run_id})

    return runs


# ---------------------------------------------------------------------------
# Coverage checks (per run; the stage runners' resume does the real work —
# these checks only decide whether an invocation is needed at all)
# ---------------------------------------------------------------------------


def full_static_settings(config: Dict[str, Any]) -> "Dict[str, ToolSettings]":
    """ALL enabled static tools minus the external-container ones (those
    go through external_tools_mode). Unlike the loop-time minimum this is
    variant-independent — backfill completes every artifact equally."""
    settings = resolve_tool_settings(config, "static_analysis")
    external = set(orchestrator.repair_settings(config)["external_tools"])
    return {
        name: s for name, s in settings.items()
        if s.enabled and name not in external
    }


def enabled_dynamic_settings(config: Dict[str, Any]) -> "Dict[str, ToolSettings]":
    settings = resolve_tool_settings(config, "dynamic_analysis")
    return {name: s for name, s in settings.items() if s.enabled}


def stage_coverage(
    records: "Dict[str, Dict[str, Any]]",
    samples: List[str],
    required_tools: Optional[List[str]] = None,
) -> str:
    """'ok' | 'partial' | 'missing' for one stage file against the
    assembled samples (and, for static, the required tool entries)."""
    if not samples:
        return "ok"

    def covered(sample_id: str) -> bool:
        record = records.get(sample_id)
        if record is None:
            return False
        if required_tools:
            present = set((record.get("tools") or {}).keys())
            return set(required_tools).issubset(present)
        return True

    hits = sum(1 for s in samples if covered(s))

    if hits == len(samples):
        return "ok"
    if hits == 0:
        return "missing"
    return "partial"


def external_pending(
    config: Dict[str, Any],
    static_records: "Dict[str, Dict[str, Any]]",
    samples: List[str],
) -> "List[Tuple[str, int]]":
    """(tool, missing-count) for enabled external static tools, honoring
    each tool's execution-model scope (a tool with no in-scope sample is
    never waited for)."""
    settings = resolve_tool_settings(config, "static_analysis")
    pending: List[Tuple[str, int]] = []

    for name in orchestrator.repair_settings(config)["external_tools"]:
        tool = settings.get(name)
        if tool is None or not tool.enabled:
            continue

        relevant = [
            s for s in samples
            if orchestrator.execution_model_of(s) in tool.execution_models
        ]
        missing = [
            s for s in relevant
            if name not in ((static_records.get(s) or {}).get("tools") or {})
        ]

        if missing:
            pending.append((name, len(missing)))

    return pending


def enhanced_spec_coverage(
    config: Dict[str, Any],
    enhanced_path: Path,
    expected_samples: List[str],
) -> str:
    """'ok' | 'partial' | 'missing' at (sample_id, spec) GRANULARITY.

    Sample-level presence was the bug: a sample with 8 of 20 spec records
    counted as covered, the runner was never re-invoked, and its
    (sample, spec)-level resume never got the chance to fill the gaps.
    Present pairs are counted against the benchmark's DETERMINISTIC
    expected spec list (build_benchmark_specs: static base + LLM seeds +
    mutation fill — the same list the runner executes, including the
    under-target case where mutation space is exhausted). Gated records
    (baseline_incompatible / numerically_unstable) are records and count
    as present.
    """
    from thesis.enhanced_tests.specs import build_benchmark_specs, spec_key
    from thesis.evaluation.run_enhanced_tests import load_llm_specs

    if not expected_samples:
        return "ok"

    pairs = set()
    if enhanced_path.exists():
        with enhanced_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    pairs.add((row["sample_id"], spec_key(row["spec"])))
                except (ValueError, KeyError):
                    continue

    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    specs_path = Path(
        stage.get("specs_file")
        or REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"
    )
    llm_specs = load_llm_specs(specs_path)

    expected_keys_cache: "Dict[str, List[Any]]" = {}
    covered = 0

    for sample_id in expected_samples:
        parts = sample_id.split("__")
        benchmark = (
            "%s/%s" % (parts[-4], parts[-3]) if len(parts) >= 4 else ""
        )

        if benchmark not in expected_keys_cache:
            expected_keys_cache[benchmark] = [
                spec_key(spec)
                for spec in build_benchmark_specs(
                    benchmark, llm_specs.get(benchmark, []), config
                )
            ]

        expected_keys = expected_keys_cache[benchmark]
        if expected_keys and all(
            (sample_id, key) in pairs for key in expected_keys
        ):
            covered += 1

    if covered == len(expected_samples):
        return "ok"

    return "partial" if pairs else "missing"


def enhanced_expected_samples(
    assembly: "Dict[str, Dict[str, Any]]",
    repo_root: Path,
    marker_cache: "Dict[str, bool]",
    execution_models: "Optional[List[str]]" = None,
) -> List[str]:
    """Samples the enhanced runner would cover: execution model in the
    CONFIGURED stages.enhanced_tests.execution_models (default [serial] =
    historical behavior) AND a parameterizable benchmark driver — the same
    two eligibility checks the runner itself applies. Passing the models
    explicitly keeps this free of a second default logic (the caller reads
    them via specs.stage_settings)."""
    if execution_models is None:
        execution_models = ["serial"]

    expected: List[str] = []

    for sample_id, entry in assembly.items():
        if not entry.get("assembled"):
            continue
        if orchestrator.execution_model_of(sample_id) not in execution_models:
            continue

        benchmark_dir = (entry.get("drivers") or {}).get("benchmark_dir", "")
        benchmark_dir = benchmark_dir.replace("\\", "/")
        if not benchmark_dir:
            continue

        if benchmark_dir not in marker_cache:
            cpu_cc = repo_root / benchmark_dir / "cpu.cc"
            marker_cache[benchmark_dir] = (
                cpu_cc.exists()
                and ENHANCED_MARKER in cpu_cc.read_text(encoding="utf-8")
            )

        if marker_cache[benchmark_dir]:
            expected.append(sample_id)

    return sorted(expected)


def plan_run(
    config: Dict[str, Any],
    run: Dict[str, Any],
    model_id: str,
    repo_root: Path,
    marker_cache: "Dict[str, bool]",
) -> Dict[str, Any]:
    """Coverage plan for one run: which stages need an invocation."""
    intermediate_root = Path(config["outputs"]["intermediate_dir"])
    run_id = run["run_id"]

    assembly = load_assembly(intermediate_root, run_id, model_id)
    samples = assembled_sample_ids(assembly)

    static_records = load_jsonl_by_sample(
        intermediate_root / run_id / model_id
        / orchestrator.stage_output_file(config, "static_analysis")
    )
    correctness_records = load_jsonl_by_sample(
        intermediate_root / run_id / model_id
        / orchestrator.stage_output_file(config, "correctness_tests")
    )
    dynamic_records = load_jsonl_by_sample(
        intermediate_root / run_id / model_id
        / orchestrator.stage_output_file(config, "dynamic_analysis")
    )

    enhanced_stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    enhanced_path = (
        intermediate_root / run_id / model_id
        / enhanced_stage.get("output_file_name", "enhanced_tests.jsonl")
    )
    # the configured coverage decides applicability — specs.stage_settings
    # is the single source for the [serial] default. not_applicable only
    # when NO sample of the iteration falls under the configured models;
    # SPEC-level coverage below then makes partial samples `pending` while
    # existing records stay valid (the runner resumes per (sample, spec)
    # and only adds the missing ones).
    enhanced_expected = enhanced_expected_samples(
        assembly, repo_root, marker_cache,
        execution_models=list(enhanced_stage_settings(config)["execution_models"]),
    )

    plan = dict(run)
    plan["samples"] = len(samples)
    plan["static"] = stage_coverage(
        static_records, samples, required_tools=list(full_static_settings(config))
    )
    plan["external"] = external_pending(config, static_records, samples)
    plan["correctness"] = stage_coverage(correctness_records, samples)
    plan["dynamic"] = stage_coverage(dynamic_records, samples)
    plan["enhanced"] = (
        "not_applicable"
        if not enhanced_expected
        else enhanced_spec_coverage(config, enhanced_path, enhanced_expected)
    )

    return plan


# ---------------------------------------------------------------------------
# Held-out gate: enhanced only after ALL configured loops terminated
# ---------------------------------------------------------------------------


def loops_terminated(
    config: Dict[str, Any], base_run_id: str, model_id: str
) -> "Tuple[bool, List[str]]":
    """(terminated, reasons). Terminated means: every configured variant
    has a state.jsonl and no sample in it is still active. A variant whose
    loop never started counts as NOT terminated — running enhanced then
    would break the held-out ordering for its later iterations."""
    reasons: List[str] = []

    for variant in orchestrator.repair_settings(config)["variants"]:
        paths = orchestrator.LoopPaths(config, base_run_id, model_id, variant)

        if not paths.state_path.exists():
            reasons.append("%s: loop has not run (no state.jsonl)" % variant)
            continue

        states = orchestrator.load_sample_states(paths.state_path)
        active = [
            s for s, record in states.items()
            if record.get("status") == orchestrator.STATUS_ACTIVE
        ]

        if active:
            reasons.append(
                "%s: %d sample(s) still active" % (variant, len(active))
            )

    return (not reasons), reasons


# ---------------------------------------------------------------------------
# Toolchain consistency (design §6)
# ---------------------------------------------------------------------------


def check_toolchain(
    current_path: Path,
    stored_path: Path,
    strict: bool,
) -> str:
    """'match' | 'recorded' | 'mismatch' | 'unavailable'. Mismatch prints
    both manifests as a warning; strict raises instead (comparability of
    backfilled findings is at stake, design §6)."""
    if not current_path.exists():
        print(
            "TOOLCHAIN: %s not found — not running inside an analysis "
            "container? Comparison skipped." % current_path
        )
        return "unavailable"

    current = current_path.read_text(encoding="utf-8")

    if not stored_path.exists():
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_text(current, encoding="utf-8")
        print(
            "TOOLCHAIN: no phase-1 record found — recorded the CURRENT "
            "manifest at %s (comparison only covers later phases)." % stored_path
        )
        return "recorded"

    stored = stored_path.read_text(encoding="utf-8")

    if stored.strip() == current.strip():
        return "match"

    message = (
        "TOOLCHAIN MISMATCH between the phase-1 record and this container "
        "— backfilled findings may not be comparable (design §6).\n"
        "--- phase-1 record (%s) ---\n%s\n"
        "--- current container (%s) ---\n%s"
        % (stored_path, stored.strip(), current_path, current.strip())
    )

    if strict:
        raise RuntimeError(message)

    print("WARNING: " + message)
    return "mismatch"


# ---------------------------------------------------------------------------
# Stage execution (existing runners; direct import like the orchestrator)
# ---------------------------------------------------------------------------


class StageExecutor:
    """Runs the missing stages via the existing runners. Overridable in
    unit tests (which must not need the container toolchain)."""

    def __init__(self, config: Dict[str, Any], config_path: str,
                 profile_name: str, primary_compiler: str) -> None:
        self.config = config
        self.config_path = config_path
        self.profile_name = profile_name
        self.primary_compiler = primary_compiler
        self.intermediate_root = Path(config["outputs"]["intermediate_dir"])
        self.context = framework.EvaluationContext(
            repo_root=REPO_ROOT,
            drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
            primary_compiler=primary_compiler,
            config=config,
        )

    def _check_tools_available(self, names: List[str]) -> None:
        unavailable = [
            name for name in names if not framework.get_tool(name).is_available()
        ]
        if unavailable:
            raise RuntimeError(
                "Required tools unavailable in this environment: %s — run "
                "the backfill inside the pareval-thesis container."
                % ", ".join(unavailable)
            )

    def run_static(self, run_id: str, model_id: str) -> None:
        from thesis.evaluation import run_static_analysis
        from thesis.evaluation.tools import register_default_tools

        register_default_tools(primary_compiler=self.primary_compiler)
        settings = full_static_settings(self.config)
        self._check_tools_available(list(settings))

        run_static_analysis.run_model(
            context=self.context,
            intermediate_dir=self.intermediate_root,
            run_id=run_id,
            model_id=model_id,
            tool_settings=settings,
        )

    def run_correctness(self, run_id: str, model_id: str) -> None:
        from thesis.evaluation import run_correctness

        if not framework.binary_available(self.primary_compiler):
            raise RuntimeError(
                "Compiler '%s' unavailable — run the backfill inside the "
                "pareval-thesis container." % self.primary_compiler
            )

        stage = (self.config.get("stages") or {}).get("correctness_tests") or {}

        run_correctness.run_model(
            context=self.context,
            intermediate_dir=self.intermediate_root,
            run_id=run_id,
            model_id=model_id,
            output_file_name=orchestrator.stage_output_file(
                self.config, "correctness_tests"
            ),
            launch_overrides=stage.get("launch_overrides"),
            niter=int(stage.get("niter", run_correctness.DEFAULT_NITER)),
            build_timeout=float(
                stage.get("build_timeout_seconds", run_correctness.DEFAULT_BUILD_TIMEOUT)
            ),
            run_timeout=float(
                stage.get("run_timeout_seconds", run_correctness.DEFAULT_RUN_TIMEOUT)
            ),
        )

    def run_dynamic(self, run_id: str, model_id: str) -> None:
        from thesis.evaluation import run_dynamic_analysis
        from thesis.evaluation.dynamic_tools import register_dynamic_tools

        register_dynamic_tools()
        settings = enabled_dynamic_settings(self.config)
        self._check_tools_available(list(settings))

        run_dynamic_analysis.run_model(
            context=self.context,
            intermediate_dir=self.intermediate_root,
            run_id=run_id,
            model_id=model_id,
            tool_settings=settings,
            output_file_name=orchestrator.stage_output_file(
                self.config, "dynamic_analysis"
            ),
        )

    def run_enhanced(self, run_id: str, model_id: str) -> None:
        """Subprocess call of the existing runner — its (sample, spec)
        resume makes repeated invocations cheap."""
        argv = [
            sys.executable,
            str(REPO_ROOT / "thesis" / "evaluation" / "run_enhanced_tests.py"),
            "--config", self.config_path,
            "--profile", self.profile_name,
            "--run-id", run_id,
            "--model-id", model_id,
        ]

        result = subprocess.run(argv)

        if result.returncode != 0:
            raise RuntimeError(
                "run_enhanced_tests.py exited %d for run %s"
                % (result.returncode, run_id)
            )


# ---------------------------------------------------------------------------
# Driving
# ---------------------------------------------------------------------------


def pending_file_path(config: Dict[str, Any], base_run_id: str, model_id: str) -> Path:
    return (
        Path(config["outputs"]["intermediate_dir"]) / base_run_id / model_id
        / "backfill_pending.txt"
    )


def handle_external(
    config: Dict[str, Any],
    config_path: str,
    profile_name: str,
    base_run_id: str,
    model_id: str,
    pending_by_run: "List[Tuple[str, List[Tuple[str, int]]]]",
) -> None:
    """manual: print + persist the container commands; docker: execute the
    configured templates (same config keys as the orchestrator)."""
    settings = orchestrator.repair_settings(config)
    pending_path = pending_file_path(config, base_run_id, model_id)

    if not pending_by_run:
        if pending_path.exists():
            pending_path.unlink()
        return

    commands: List[Tuple[str, str, int, str]] = []  # (run_id, tool, count, command)
    for run_id, pending in pending_by_run:
        for tool, count in pending:
            commands.append((
                run_id, tool, count,
                orchestrator.build_external_command(
                    settings, config_path, profile_name, run_id, model_id, tool
                ),
            ))

    if settings["external_tools_mode"] == "docker":
        for run_id, tool, count, command in commands:
            template = settings["external_tool_commands"].get(tool)
            if not template:
                raise ValueError(
                    "external_tools_mode is 'docker' but stages.repair."
                    "external_tool_commands has no template for '%s'" % tool
                )
            print("[%s] external %s (%d sample(s)): %s" % (run_id, tool, count, command))
            result = subprocess.run(command, shell=True)
            if result.returncode != 0:
                raise RuntimeError(
                    "External tool command for '%s' exited %d" % (tool, result.returncode)
                )
        if pending_path.exists():
            pending_path.unlink()
        return

    lines = [
        "# Backfill waiting for external static tools (model %s, base run %s)." % (model_id, base_run_id),
        "# Run each command inside the tool's container (parcoach ->",
        "# parcoach-demo:2.4.1, llov -> pareval-llov; repo mounted), then",
        "# re-run run_backfill.py — the coverage check picks the records up.",
    ]
    for run_id, tool, count, command in commands:
        lines.append("# %s | %s: %d sample(s) missing" % (run_id, tool, count))
        lines.append(command)

    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("[%s] external tools pending (see %s):" % (model_id, pending_path))
    for line in lines:
        print("    " + line)


def print_status(plans_by_model: "Dict[str, List[Dict[str, Any]]]",
                 gates: "Dict[str, Tuple[bool, List[str]]]") -> None:
    columns = [
        ("model", 22), ("variant", 18), ("iter", 4), ("samples", 7),
        ("static", 8), ("external", 22), ("correctness", 11),
        ("dynamic", 8), ("enhanced", 20),
    ]
    header = "  ".join(name.ljust(width) for name, width in columns)
    print(header)
    print("-" * len(header))

    for model_id, plans in plans_by_model.items():
        terminated, _ = gates[model_id]

        for plan in plans:
            external = (
                ", ".join("%s:%d" % (t, c) for t, c in plan["external"]) or "-"
            )
            enhanced = plan["enhanced"]
            if enhanced != "ok" and not terminated:
                enhanced = "blocked:loop-active"

            values = [
                model_id, plan["variant"], str(plan["iteration"]),
                str(plan["samples"]), plan["static"], external,
                plan["correctness"], plan["dynamic"], enhanced,
            ]
            print("  ".join(v.ljust(w) for v, (_, w) in zip(values, columns)))


def backfill_model(
    config: Dict[str, Any],
    config_path: str,
    profile_name: str,
    base_run_id: str,
    model_id: str,
    executor: StageExecutor,
    variant_filter: Optional[str],
    skip_enhanced: bool,
) -> None:
    marker_cache: Dict[str, bool] = {}
    runs = discover_runs(config, base_run_id, model_id, variant_filter)

    if not runs:
        print("[%s] no runs discovered for base run %s" % (model_id, base_run_id))
        return

    pending_by_run: List[Tuple[str, List[Tuple[str, int]]]] = []

    for run in runs:
        plan = plan_run(config, run, model_id, REPO_ROOT, marker_cache)
        run_id = run["run_id"]

        print(
            "[%s] %s (variant %s, iteration %d): static=%s correctness=%s "
            "dynamic=%s enhanced=%s external=%s"
            % (
                model_id, run_id, plan["variant"], plan["iteration"],
                plan["static"], plan["correctness"], plan["dynamic"],
                plan["enhanced"], plan["external"] or "-",
            )
        )

        if plan["static"] != "ok":
            executor.run_static(run_id, model_id)
        if plan["correctness"] != "ok":
            executor.run_correctness(run_id, model_id)
        if plan["dynamic"] != "ok":
            executor.run_dynamic(run_id, model_id)

        # re-check external AFTER the static run (it may have merged into
        # an existing file)
        intermediate_root = Path(config["outputs"]["intermediate_dir"])
        static_records = load_jsonl_by_sample(
            intermediate_root / run_id / model_id
            / orchestrator.stage_output_file(config, "static_analysis")
        )
        assembly = load_assembly(intermediate_root, run_id, model_id)
        pending = external_pending(
            config, static_records, assembled_sample_ids(assembly)
        )
        if pending:
            pending_by_run.append((run_id, pending))

    handle_external(
        config, config_path, profile_name, base_run_id, model_id, pending_by_run
    )

    if skip_enhanced:
        print("[%s] enhanced tests skipped (--skip-enhanced)" % model_id)
        return

    terminated, reasons = loops_terminated(config, base_run_id, model_id)

    if not terminated:
        print(
            "[%s] ENHANCED TESTS REFUSED — held-out ordering (design §3/§6): "
            "enhanced runs only after ALL configured loops terminated. "
            "Blocking: %s" % (model_id, "; ".join(reasons))
        )
        return

    for run in runs:
        plan = plan_run(config, run, model_id, REPO_ROOT, marker_cache)
        if plan["enhanced"] in ("ok", "not_applicable"):
            continue
        print("[%s] enhanced tests for %s" % (model_id, run["run_id"]))
        executor.run_enhanced(run["run_id"], model_id)


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    base_run_id = profile["run_id"]

    models = [
        model for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    intermediate_root = Path(config["outputs"]["intermediate_dir"])

    if args.status:
        marker_cache: Dict[str, bool] = {}
        plans_by_model = {}
        gates = {}
        for model_config in models:
            model_id = model_config["id"]
            runs = discover_runs(config, base_run_id, model_id, args.variant)
            plans_by_model[model_id] = [
                plan_run(config, run, model_id, REPO_ROOT, marker_cache)
                for run in runs
            ]
            gates[model_id] = loops_terminated(config, base_run_id, model_id)
        print_status(plans_by_model, gates)
        return

    check_toolchain(
        current_path=TOOLCHAIN_VERSIONS_FILE,
        stored_path=intermediate_root / base_run_id / "toolchain-versions.txt",
        strict=args.strict_toolchain,
    )

    executor = StageExecutor(
        config, str(Path(args.config)), args.profile, args.primary_compiler
    )

    for model_config in models:
        backfill_model(
            config=config,
            config_path=str(Path(args.config)),
            profile_name=args.profile,
            base_run_id=base_run_id,
            model_id=model_config["id"],
            executor=executor,
            variant_filter=args.variant,
            skip_enhanced=args.skip_enhanced,
        )


if __name__ == "__main__":
    main()
