#!/usr/bin/env python3
"""Prompt-vs-oracle consistency check across all ParEval-thesis benchmarks.

For every benchmark whose generation prompt contains a worked example
(a concrete input -> output pair), this script compiles a minimal fixture
harness against the benchmark's grading oracle (baseline.hpp), feeds the
example input to the oracle, and compares the oracle's output against the
example output the models were shown.  A disagreement means the models are
being taught one semantics and graded by another — the bug class behind
pilot_001's stencil/50 result (prompt example: 8-neighbour Moore; oracle:
4-neighbour von Neumann; 31/33 samples graded wrong).

Design notes
- The harness is deliberately NOT the enhanced-tests machinery: that
  machinery drives pattern-based fills (ENHANCED_FILL_*) and cannot feed an
  arbitrary explicit example (explicit values exist only for benchmarks with
  fill sites, and never for struct/complex/COO inputs).  A per-benchmark
  fixture — the example input transcribed into a tiny main() that calls the
  baseline directly — is the only mechanism that works for all 60.
- Each fixture mirrors the comparison semantics of the benchmark's own
  cpu.cc::validate() (element order, canonicalisation such as sorting,
  float tolerance) so that a benign ordering difference is not reported as
  an inconsistency.  The `compare` spec records those choices per fixture.
- Fixtures were extracted and individually execution-verified during the
  Phase-0 audit (2026-08); the prompt lines they encode are quoted in each
  fixture's `example_source` so a reviewer can diff them against
  thesis/prompts/generation-prompts-thesis.json without running anything.

Usage (inside the analysis container, repo mounted at /workspace):
    docker run --rm -u 0 -v "<host_repo>:/workspace" -w /workspace \
        pareval-thesis python3 thesis/evaluation/check_prompt_oracle_consistency.py
Exit code 0 = every fixtured benchmark consistent; 1 = at least one
inconsistency; 2 = infrastructure failure (compile/run error).

Python 3.8 compatible (runs in the LLOV py3.8 container too, though it
needs a g++ on PATH to actually execute fixtures).
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRIVERS_CPP = os.path.join(REPO_ROOT, "drivers", "cpp")
PROMPTS_JSON = os.path.join(REPO_ROOT, "thesis", "prompts", "generation-prompts-thesis.json")

# --------------------------------------------------------------------------
# FIXTURES live in the sibling data file prompt_oracle_fixtures.json:
#   benchmark-short-name -> {
#     problem_type   : driver subdirectory,
#     harness_cpp    : complete main.cpp; includes "baseline.hpp"; prints the
#                      oracle's output for the example input as ONE JSON value
#                      on stdout (canonicalised the way validate() compares),
#     expected_json  : the prompt's example output as the matching JSON value,
#     compare        : {"float_rel": r, "float_abs": a} leaf tolerances,
#     example_source : the example lines quoted verbatim from the prompt,
#     canonicalization: how the fixture mirrors validate()'s comparison.
#   }
# As of 2026-08 every one of the 60 prompts carries a worked example, so
# NO_WORKED_EXAMPLE is empty; a future benchmark without an example belongs
# there (its absence from FIXTURES is then not an error).
# --------------------------------------------------------------------------
FIXTURES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_oracle_fixtures.json")

NO_WORKED_EXAMPLE = []  # benchmark names whose prompts carry no example

DEFAULT_FLOAT_REL = 1e-9
DEFAULT_FLOAT_ABS = 1e-9


def load_benchmarks():
    with open(PROMPTS_JSON, "r", encoding="utf-8") as fh:
        prompts = json.load(fh)
    pairs = sorted({(p["problem_type"], p["name"]) for p in prompts})
    return pairs


def leaves_equal(a, b, rel, abs_tol):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not (
        isinstance(a, bool) or isinstance(b, bool)
    ):
        fa, fb = float(a), float(b)
        if math.isnan(fa) or math.isnan(fb):
            return math.isnan(fa) == math.isnan(fb)
        return abs(fa - fb) <= max(abs_tol, rel * max(abs(fa), abs(fb)))
    return a == b


def compare_json(actual, expected, rel, abs_tol, path="$"):
    """Recursive compare; returns list of mismatch strings (empty = equal)."""
    mismatches = []
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            mismatches.append(
                "%s: length %d != expected %d" % (path, len(actual), len(expected))
            )
            return mismatches
        for i, (av, ev) in enumerate(zip(actual, expected)):
            mismatches.extend(compare_json(av, ev, rel, abs_tol, "%s[%d]" % (path, i)))
        return mismatches
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(list(actual.keys()) + list(expected.keys()))):
            if key not in actual:
                mismatches.append("%s.%s: missing in actual" % (path, key))
            elif key not in expected:
                mismatches.append("%s.%s: unexpected in actual" % (path, key))
            else:
                mismatches.extend(
                    compare_json(actual[key], expected[key], rel, abs_tol, "%s.%s" % (path, key))
                )
        return mismatches
    if not leaves_equal(actual, expected, rel, abs_tol):
        mismatches.append("%s: actual %r != expected %r" % (path, actual, expected))
    return mismatches


def run_fixture(problem_type, name, fixture, workdir, gxx):
    bench_dir = os.path.join(DRIVERS_CPP, "benchmarks", problem_type, name)
    src = os.path.join(workdir, "fixture_%s.cpp" % name)
    exe = os.path.join(workdir, "fixture_%s" % name)
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(fixture["harness_cpp"])
    argv = [
        gxx, "-std=c++17", "-O2",
        "-I", bench_dir,
        "-I", DRIVERS_CPP,
        src, "-o", exe,
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return ("infra_error", "compile failed:\n" + proc.stderr[-2000:], None)
    proc = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return (
            "infra_error",
            "run failed (exit %d): %s" % (proc.returncode, proc.stderr[-500:]),
            None,
        )
    try:
        actual = json.loads(proc.stdout.strip())
    except ValueError as exc:
        return ("infra_error", "output not JSON (%s): %r" % (exc, proc.stdout[:300]), None)
    compare = fixture.get("compare", {})
    rel = float(compare.get("float_rel", DEFAULT_FLOAT_REL))
    abs_tol = float(compare.get("float_abs", DEFAULT_FLOAT_ABS))
    mismatches = compare_json(actual, json.loads(fixture["expected_json"]), rel, abs_tol)
    if mismatches:
        return ("INCONSISTENT", "; ".join(mismatches[:20]), actual)
    return ("consistent", "", actual)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--benchmark", default=None, help="run a single benchmark")
    parser.add_argument("--gxx", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if shutil.which(args.gxx) is None:
        print("FATAL: no C++ compiler (%r) on PATH - run inside the analysis container." % args.gxx)
        return 2

    with open(FIXTURES_JSON, "r", encoding="utf-8") as fh:
        fixtures = json.load(fh)

    benchmarks = load_benchmarks()
    if args.benchmark:
        benchmarks = [(t, n) for (t, n) in benchmarks if n == args.benchmark]
        if not benchmarks:
            print("FATAL: unknown benchmark %r" % args.benchmark)
            return 2

    workdir = tempfile.mkdtemp(prefix="prompt_oracle_check_")
    rows = []
    worst = 0
    try:
        for problem_type, name in benchmarks:
            if name in NO_WORKED_EXAMPLE:
                rows.append((name, "no_worked_example", ""))
                continue
            fixture = fixtures.get(name)
            if fixture is None:
                rows.append((name, "not_covered", "no fixture recorded"))
                worst = max(worst, 2)
                continue
            status, detail, _actual = run_fixture(problem_type, name, fixture, workdir, args.gxx)
            rows.append((name, status, detail))
            if status == "INCONSISTENT":
                worst = max(worst, 1)
            elif status == "infra_error":
                worst = max(worst, 2)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if args.json:
        print(json.dumps([{"benchmark": n, "status": s, "detail": d} for n, s, d in rows], indent=2))
    else:
        width = max(len(n) for n, _s, _d in rows)
        for name, status, detail in rows:
            line = "%-*s  %-18s" % (width, name, status)
            if detail:
                line += "  " + detail
            print(line)
        counts = {}
        for _n, status, _d in rows:
            counts[status] = counts.get(status, 0) + 1
        print("\nSummary: " + ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
    return worst


if __name__ == "__main__":
    sys.exit(main())
