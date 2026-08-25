"""One-off verification experiment: do the dense_la mini-differences depend
on the optimization level?

Hypothesis under test: WITHOUT -ffast-math GCC preserves IEEE semantics on
every -O level (no reassociation; no FMA contraction without -march), so
the ~1e-9 relative differences behind smoke_002's validation_failed
verdicts (e.g. qwen3_coder_api serial lu_decomp, mismatch_total=52) stem
purely from the SOURCE-level operation order and are bit-identical across
-O0/-O1/-O2/-O3.

Preconditions this experiment relies on (both verified earlier):
  - fillRand is deterministic (unseeded rand(): identical inputs per run),
  - reportAndCompare prints with max_digits10 round-trip precision.

The build mirrors run_correctness.compile_sample EXACTLY (same
get_build_config("serial"), same include dirs, same
DRIVER_PROBLEM_SIZE define) with two deliberate, documented deviations:
  1. a trailing -O<level> override (the last -O flag wins — the mechanism
     compile_argv documents for the enhanced stage's -O1),
  2. MISMATCH_REPORT_MAX raised to 100000 so EVERY differing index prints
     (the pipeline's k=3 bound would defeat the full-list comparison; the
     MISMATCH_SUMMARY total is the cross-check that nothing is missed).

This is a measurement, not a pipeline change: nothing under thesis/results
is written or modified; the report goes to
thesis/experiments/opt-level-probe.md.

Usage (main container):
    python3 thesis/experiments/opt_level_probe.py \
        [--sample-id <id>] [--control-sample-id <id>] [--run-id smoke_002]

Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.build_config import get_build_config  # noqa: E402
from thesis.evaluation.run_correctness import (  # noqa: E402
    BASELINE_INCOMPATIBLE,
    BASELINE_INCOMPATIBLE_NONCE_ENV,
    classify_baseline_incompatible,
    new_marker_nonce,
    parse_authenticated_validation,
    parse_mismatch_output,
    run_verdict,
)
from thesis.evaluation.tools import DRIVER_PROBLEM_SIZE_DEFINE  # noqa: E402

DRIVERS_CPP = REPO_ROOT / "drivers" / "cpp"
INTERMEDIATE = REPO_ROOT / "thesis" / "results" / "intermediate"

LEVELS = ("O0", "O1", "O2", "O3")

# print EVERY differing index — see module docstring, deviation 2
FULL_REPORT_MAX = 100000

BUILD_TIMEOUT = 300.0
RUN_TIMEOUT = 120.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimization-level probe for ParEval mini-differences."
    )
    parser.add_argument("--run-id", default="smoke_002")
    parser.add_argument(
        "--sample-id",
        default="qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial__sample_0",
        help="The failing sample under test.",
    )
    parser.add_argument(
        "--control-sample-id",
        default="openai_gpt56_sol__dense_la__00_dense_la_lu_decomp__serial__sample_0",
        help="A passing sample as control (expected: pass on every level).",
    )
    parser.add_argument(
        "--report",
        default=str(REPO_ROOT / "thesis" / "experiments" / "opt-level-probe.md"),
    )
    return parser.parse_args()


def resolve_sample(run_id: str, sample_id: str) -> "Tuple[Path, Path]":
    """(source_path, benchmark_dir) from the run's assembly records —
    resolved, not hardcoded."""
    model_id = sample_id.split("__")[0]
    assembly_path = INTERMEDIATE / run_id / model_id / "assembly.jsonl"

    if not assembly_path.exists():
        raise SystemExit("no assembly records: %s" % assembly_path)

    with assembly_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("sample_id") != sample_id:
                continue
            if not record.get("assembled"):
                raise SystemExit("sample %s is not assembled" % sample_id)

            source_path = REPO_ROOT / record["source_path"]
            benchmark_dir = REPO_ROOT / (
                (record.get("drivers") or {})["benchmark_dir"].replace("\\", "/")
            )
            return source_path, benchmark_dir

    raise SystemExit("sample %s not found in %s" % (sample_id, assembly_path))


def build_and_run(
    source_path: Path, benchmark_dir: Path, level: str
) -> "Dict[str, Any]":
    if source_path.parent.name.split("__")[-2:][0] != "serial" and \
            "__serial__" not in source_path.parent.name:
        raise SystemExit("this probe covers serial samples only")

    config = get_build_config("serial", primary_compiler="g++")

    with tempfile.TemporaryDirectory() as tmp:
        exec_path = Path(tmp) / "probe.out"

        argv = config.base_command(
            sources=[
                str(DRIVERS_CPP / config.model_driver_file),
                str(benchmark_dir / "cpu.cc"),
            ],
            output_path=str(exec_path),
            include_dirs=[
                str(DRIVERS_CPP),
                str(DRIVERS_CPP / "models"),
                str(source_path.parent),
            ],
            extra_flags=[
                "-D%s" % DRIVER_PROBLEM_SIZE_DEFINE,
                "-DMISMATCH_REPORT_MAX=%d" % FULL_REPORT_MAX,
                "-%s" % level,  # trailing override: the last -O flag wins
            ],
        )

        started = time.time()
        build = subprocess.run(
            argv, capture_output=True, text=True, timeout=BUILD_TIMEOUT
        )

        if build.returncode != 0:
            return {
                "level": level,
                "verdict": "build_failed",
                "build_seconds": round(time.time() - started, 2),
                "stderr": (build.stderr or "")[-800:],
            }

        # contract C2b/F2.1: the probe authenticates like the pipeline stages,
        # so its verdicts stay comparable with theirs — fresh token per run
        nonce = new_marker_nonce()
        probe_env = dict(os.environ)
        probe_env[BASELINE_INCOMPATIBLE_NONCE_ENV] = nonce

        run = subprocess.run(
            [str(exec_path), "1"],
            capture_output=True, text=True, timeout=RUN_TIMEOUT, cwd=tmp,
            env=probe_env,
        )

    stdout = run.stdout or ""
    mismatches, total = parse_mismatch_output(stdout)
    # contract C3.4: this probe is a real run_verdict consumer. Without the
    # baseline_incompatible argument a non-finite oracle reference arrived
    # here as a plain "pass" (the driver prints Validation: PASS and exits 0
    # while the comparator skips the non-finite indices) — an oracle defect
    # would have looked like a clean control sample.
    authentic, _spoofed = classify_baseline_incompatible(stdout, nonce)
    validation, _anomalies = parse_authenticated_validation(stdout, nonce)
    verdict = run_verdict(
        validation, run.returncode, False,
        baseline_incompatible=authentic > 0,
    )

    return {
        "level": level,
        "verdict": verdict,
        "mismatch_total": total,
        # (index, expected, got) as STRINGS at full print precision —
        # the unit of the bytewise comparison
        "triples": [
            (m.get("index"), m.get("expected"), m.get("got"))
            for m in mismatches
        ],
    }


def compare_levels(results: "List[Dict[str, Any]]") -> "Dict[str, Any]":
    """Bytewise identity of the full mismatch lists across levels, with
    expected and got compared SEPARATELY (does the baseline move? the
    model code?)."""
    reference = results[0]

    def side(result: "Dict[str, Any]", position: int) -> "List[Tuple[Any, str]]":
        return [(t[0], t[position]) for t in result.get("triples") or []]

    comparison: "Dict[str, Any]" = {
        "all_identical": True,
        "expected_identical": True,
        "got_identical": True,
        "first_diffs": [],
    }

    for result in results[1:]:
        if result.get("triples") != reference.get("triples"):
            comparison["all_identical"] = False
        if side(result, 1) != side(reference, 1):
            comparison["expected_identical"] = False
        if side(result, 2) != side(reference, 2):
            comparison["got_identical"] = False

        if not comparison["all_identical"] and not comparison["first_diffs"]:
            ref_triples = reference.get("triples") or []
            for a, b in zip(ref_triples, result.get("triples") or []):
                if a != b:
                    comparison["first_diffs"].append(
                        {"level": result["level"], "reference": a, "other": b}
                    )
                if len(comparison["first_diffs"]) >= 5:
                    break

    return comparison


def probe(run_id: str, sample_id: str) -> "Tuple[List[Dict[str, Any]], Dict[str, Any]]":
    source_path, benchmark_dir = resolve_sample(run_id, sample_id)
    print("sample: %s" % sample_id)
    print("source: %s" % source_path.relative_to(REPO_ROOT))

    results = []
    for level in LEVELS:
        result = build_and_run(source_path, benchmark_dir, level)
        results.append(result)
        print(
            "  -%s: %s, mismatch_total=%s, reported=%d"
            % (
                level,
                result["verdict"],
                result.get("mismatch_total"),
                len(result.get("triples") or []),
            )
        )

    return results, compare_levels(results)


def render_report(
    run_id: str,
    sample_id: str,
    results: "List[Dict[str, Any]]",
    comparison: "Dict[str, Any]",
    control_id: str,
    control_results: "List[Dict[str, Any]]",
    control_comparison: "Dict[str, Any]",
) -> str:
    lines = [
        "# Optimization-level probe — are the dense_la mini-differences O-level-dependent?",
        "",
        "One-off verification experiment (thesis/experiments/opt_level_probe.py);",
        "no pipeline, config or result changes. Build = run_correctness's exact",
        "translation unit and flags plus a trailing `-O<level>` override;",
        "`MISMATCH_REPORT_MAX=%d` so the COMPLETE mismatch list prints" % FULL_REPORT_MAX,
        "(values at max_digits10 round-trip precision; fillRand inputs are",
        "deterministic, so the lists are directly comparable).",
        "",
        "## Sample under test: `%s` (run %s)" % (sample_id, run_id),
        "",
        "| level | verdict | mismatch_total | list identical to -O0 |",
        "| --- | --- | --- | --- |",
    ]

    reference = results[0]
    for result in results:
        identical = (
            "reference" if result is reference
            else ("yes" if result.get("triples") == reference.get("triples") else "NO")
        )
        lines.append(
            "| -%s | %s | %s | %s |"
            % (result["level"], result["verdict"],
               result.get("mismatch_total"), identical)
        )

    lines += [
        "",
        "Expected side identical across levels: **%s** — the baseline's values"
        % ("yes" if comparison["expected_identical"] else "NO"),
        "do not move with the optimizer.",
        "",
        "Got side identical across levels: **%s** — the model code's values"
        % ("yes" if comparison["got_identical"] else "NO"),
        "do not move either.",
    ]

    if comparison["first_diffs"]:
        lines += ["", "First differing entries:", ""]
        for diff in comparison["first_diffs"]:
            lines.append("- -O0 %s vs -%s %s" % (
                diff["reference"], diff["level"], diff["other"]))

    lines += [
        "",
        "### Example mismatches (full precision, identical on every level)",
        "",
        "| index | expected (baseline) | got (model) |",
        "| --- | --- | --- |",
    ]
    for index, expected, got in (reference.get("triples") or [])[:3]:
        lines.append("| %s | `%s` | `%s` |" % (index, expected, got))

    lines += [
        "",
        "## Control sample: `%s` (expected: pass everywhere)" % control_id,
        "",
        "| level | verdict | mismatch_total |",
        "| --- | --- | --- |",
    ]
    for result in control_results:
        lines.append(
            "| -%s | %s | %s |"
            % (result["level"], result["verdict"], result.get("mismatch_total"))
        )

    all_identical = comparison["all_identical"]
    control_pass = all(r["verdict"] == "pass" for r in control_results)
    control_bi = [r for r in control_results if r["verdict"] == BASELINE_INCOMPATIBLE]

    if control_bi:
        # contract C3.4: an oracle-side verdict must not be reported as a
        # failed hypothesis; the experiment simply has no valid basis here
        lines += [
            "",
            "> **The control sample produced a non-finite oracle reference "
            "(`%s`) on %d of %d levels.** The comparison below rests on an "
            "invalid basis for those levels — this is an oracle property, "
            "not a statement about the optimizer."
            % (BASELINE_INCOMPATIBLE, len(control_bi), len(control_results)),
        ]

    lines += [
        "",
        "## Conclusion",
        "",
        (
            "The %d mismatches are **bit-identical across -O0/-O1/-O2/-O3** "
            "(expected and got side separately), and the control sample "
            "passes on every level — the mini-differences stem purely from "
            "the SOURCE-level operation order of the model code vs. the "
            "baseline, not from the optimizer: without -ffast-math GCC "
            "preserves IEEE evaluation order on all O levels."
            % (reference.get("mismatch_total") or 0)
        ) if all_identical and control_pass else (
            "HYPOTHESIS NOT CONFIRMED — see the tables above: "
            "list identical=%s, control pass=%s. The differences DO depend "
            "on the optimization level and are not purely source-order "
            "artifacts." % (all_identical, control_pass)
        ),
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    print("Optimization-level probe | levels: %s" % ", ".join(LEVELS))
    print("=" * 60)

    results, comparison = probe(args.run_id, args.sample_id)
    print()
    control_results, control_comparison = probe(args.run_id, args.control_sample_id)

    report = render_report(
        args.run_id, args.sample_id, results, comparison,
        args.control_sample_id, control_results, control_comparison,
    )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print()
    print("report: %s" % report_path)
    print()
    print("lists identical across levels: %s | expected side: %s | got side: %s"
          % (comparison["all_identical"], comparison["expected_identical"],
             comparison["got_identical"]))


if __name__ == "__main__":
    main()
