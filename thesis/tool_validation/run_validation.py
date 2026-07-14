"""Validation runner: suite kernels through the pipeline-configured tools.

One JSONL per (suite, tool) under results/<suite>/<tool>.jsonl, so container
runs never clobber each other (same pattern as the pipeline's per-container
--tools filtering).

Usage (see README.md for the container assignment):
    python3 thesis/tool_validation/run_validation.py --suite juliet \
        --tools compiler clang_tidy cppcheck infer
    python3 thesis/tool_validation/run_validation.py --suite drb --tools llov
    # smoke: --limit 10

Kernels that do not compile in this environment are logged as skipped for
every requested tool and excluded from all metrics (they are not negatives).

Python 3.8 compatible (LLOV container).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.framework import binary_available, run_command  # noqa: E402
from thesis.tool_validation.suite_kernels import (  # noqa: E402
    SUITE_ITERATORS,
    ValidationKernel,
    load_kernels,
)
from thesis.tool_validation.validation_tools import (  # noqa: E402
    VALIDATION_TOOLS,
    base_flags,
    host_compiler,
    std_flag,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"

PREFLIGHT_TIMEOUT = 60.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run tool validation on a suite.")
    parser.add_argument("--suite", required=True, choices=sorted(SUITE_ITERATORS))
    parser.add_argument(
        "--tools",
        nargs="*",
        default=None,
        help="Subset of tools to run (default: all suite-applicable, available ones).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Smoke mode: N kernels, STRATIFIED (N/2 bad + N/2 good).",
    )
    parser.add_argument(
        "--juliet-per-class",
        type=int,
        default=50,
        help="Juliet: testcase files per CWE class (deterministic first-N "
        "subset; the full 37k-kernel suite adds runtime, not insight).",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Substring filter on kernel ids (canary checks).",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Ignore existing results and rewrite them (default: resume — "
        "already-processed (kernel, tool) pairs are skipped).",
    )
    return parser.parse_args()


def preflight_compiler(kernel: ValidationKernel) -> Optional[List[str]]:
    """Syntax-only compile to gate uncompilable kernels uniformly.

    Returns the argv, or None if no suitable compiler exists in this
    container (then no gating happens — the tools' own error paths apply).
    """
    if kernel.execution_model == "mpi" and binary_available("mpicc"):
        return ["mpicc", "-fsyntax-only", str(kernel.path)]

    compiler = host_compiler(kernel)

    if not binary_available(compiler):
        return None

    argv = [compiler, std_flag(kernel), "-fsyntax-only", *base_flags(kernel)]

    if kernel.execution_model == "omp":
        argv.append("-fopenmp")

    argv.append(str(kernel.path))
    return argv


def kernel_compiles(kernel: ValidationKernel) -> bool:
    argv = preflight_compiler(kernel)

    if argv is None:
        return True  # no gating possible in this container

    result = run_command(argv, timeout=PREFLIGHT_TIMEOUT)
    return result.returncode == 0 and not result.timed_out


def row_base(kernel: ValidationKernel, tool_name: str) -> dict:
    return {
        "suite": kernel.suite,
        "kernel_id": kernel.kernel_id,
        "path": str(kernel.path),
        "label": kernel.label,
        "classes": kernel.classes,
        "execution_model": kernel.execution_model,
        "tool": tool_name,
    }


def load_done(out_path: Path) -> "set[str]":
    """kernel_ids already present in an existing results file (resume)."""
    import json as _json

    done = set()

    if out_path.exists():
        with out_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        done.add(_json.loads(line)["kernel_id"])
                    except (ValueError, KeyError):
                        continue

    return done


def main() -> None:
    args = parse_args()

    # --only searches the FULL suite (no per-class cap): canary kernels are
    # picked for detectability, not for being alphabetically early
    kernels = load_kernels(
        args.suite,
        args.limit,
        juliet_per_class=None if args.only else args.juliet_per_class,
    )

    if args.only:
        kernels = [k for k in kernels if args.only in k.kernel_id]

    if not kernels:
        raise SystemExit(
            "No kernels found for suite '%s' — run setup_suites.py first "
            "(and for MBI check that gencodes/ was generated)." % args.suite
        )

    applicable = [
        name for name, tool in VALIDATION_TOOLS.items() if args.suite in tool.suites
    ]
    requested = args.tools if args.tools else applicable

    tools = []
    for name in requested:
        if name not in VALIDATION_TOOLS:
            raise SystemExit("Unknown tool '%s'. Known: %s" % (name, ", ".join(VALIDATION_TOOLS)))
        if args.suite not in VALIDATION_TOOLS[name].suites:
            print("[skip] %s is not assigned to suite %s" % (name, args.suite))
            continue
        if not VALIDATION_TOOLS[name].is_available():
            print("[skip] %s unavailable in this container" % name)
            continue
        tools.append(VALIDATION_TOOLS[name])

    if not tools:
        raise SystemExit("No requested tool is available in this container.")

    out_dir = RESULTS_DIR / args.suite
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        "Validation | suite %s | %d kernels | tools: %s"
        % (args.suite, len(kernels), ", ".join(t.name for t in tools))
    )

    # preflight once per kernel, shared across tools
    compilable = {}
    skipped = 0
    for kernel in kernels:
        ok = kernel_compiles(kernel)
        compilable[kernel.kernel_id] = ok
        if not ok:
            skipped += 1

    print("preflight: %d/%d kernels compile (rest -> skipped)" % (len(kernels) - skipped, len(kernels)))

    for tool in tools:
        out_path = out_dir / (tool.name + ".jsonl")

        if args.restart and out_path.exists():
            out_path.unlink()

        already_done = load_done(out_path)

        if already_done:
            print(
                "[%s] resume: %d kernels already processed, skipping those"
                % (tool.name, len(already_done))
            )

        with out_path.open("a", encoding="utf-8") as out:
            done = 0

            for kernel in kernels:
                done += 1

                if kernel.kernel_id in already_done:
                    continue

                row = row_base(kernel, tool.name)

                if not compilable[kernel.kernel_id]:
                    row.update({"skipped": True, "skip_reason": "does not compile"})
                else:
                    result = tool.run(kernel)
                    row.update({"skipped": False})
                    row.update(result.to_dict())

                out.write(json.dumps(row) + "\n")
                out.flush()

                if done % 25 == 0:
                    print("  [%s] %d/%d" % (tool.name, done, len(kernels)))

        print("[%s] done -> %s" % (tool.name, out_path))


if __name__ == "__main__":
    main()
