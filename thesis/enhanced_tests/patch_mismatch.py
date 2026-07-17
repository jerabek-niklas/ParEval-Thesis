"""Mechanical patcher: mismatch reporting at the validate() verdict sites.

Rewrites the comparison calls inside validate() onto the reportAndCompare
helpers from utilities.hpp (repair-loop-design.md §4), so a Validation-FAIL
prints bounded MISMATCH/MISMATCH_SUMMARY lines that run_correctness.py
parses into the run records:

    !fequal(A, B, tol)                          -> !reportAndCompare(A, B, tol[, input])
    !std::equal(C.begin(), C.end(), T.begin())  -> !reportAndCompareEq(C, T[, input])
    IS_ROOT(rank) && X != Y                     -> IS_ROOT(rank) && !reportAndCompareScalar(expected, got)
    std::abs|fabs(X - Y) > tol                  -> !reportAndCompareScalar(X, Y, tol)

The optional input argument is attached when it can be derived mechanically:
  1. validate() declares a local `std::vector<...> input(` -> pass `input`
  2. the compared names look like `X_correct` / `X_test` and a local
     vector `X` exists -> pass `X`
Otherwise the field is simply omitted (the helpers and the renderer both
degrade gracefully).

Scalar sites order (expected, got) by which name contains "correct" —
2 of the 14 scalar verdicts are written `test != correct`.

Non-patchable validate() structures are logged and left untouched (they
stay at plain PASS/FAIL; feedback.py degrades automatically). Idempotent
(files already containing reportAndCompare are skipped); --check mode.

PASS-path guarantee: the helpers print ONLY on mismatch, so a passing run's
stdout is byte-identical (verified after patching; see task notes).

Usage:
    python thesis/enhanced_tests/patch_mismatch.py --check
    python thesis/enhanced_tests/patch_mismatch.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BENCHMARKS_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks"

FEQUAL_RE = re.compile(r"!fequal\(\s*(\w+)\s*,\s*(\w+)\s*,\s*([^)]+?)\s*\)")
STD_EQUAL_RE = re.compile(
    r"!std::equal\(\s*(\w+)\.begin\(\)\s*,\s*\1\.end\(\)\s*,\s*(\w+)\.begin\(\)\s*\)"
)
SCALAR_NEQ_RE = re.compile(r"(IS_ROOT\(rank\)\s*&&\s*)(\w+)\s*!=\s*(\w+)")
SCALAR_ABS_RE = re.compile(
    r"std::f?abs\(\s*(\w+)\s*-\s*(\w+)\s*\)\s*>\s*([0-9eE.+-]+)"
)


def find_validate_span(lines: list) -> "tuple[int, int] | None":
    start = None

    for index, line in enumerate(lines):
        if "bool validate(" in line:
            start = index
            break

    if start is None:
        return None

    depth = 0
    seen_open = False

    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if "{" in lines[index]:
            seen_open = True
        if seen_open and depth == 0:
            return (start, index)

    return None


def derive_input_var(body: str, first_arg: str) -> "str | None":
    """Input vector for the `input=` field, mechanically derived."""
    if re.search(r"std::vector<[^>]+>\s+input\s*\(", body):
        return "input"

    match = re.match(r"(\w+)_(?:correct|test)$", first_arg)
    if match:
        stem = match.group(1)
        if re.search(r"std::vector<[^>]+>\s+%s\s*\(" % re.escape(stem), body):
            return stem

    return None


def ordered_expected_got(a: str, b: str) -> "tuple[str, str]":
    """(expected, got): the name containing 'correct' is the expected one."""
    if "correct" in b.lower() and "correct" not in a.lower():
        return b, a
    return a, b


def patch_body(body: str) -> "tuple[str, int]":
    replaced = 0

    def sub_fequal(match: "re.Match") -> str:
        nonlocal replaced
        replaced += 1
        a, b, tol = match.group(1), match.group(2), match.group(3)
        input_var = derive_input_var(body, a)
        if input_var:
            return "!reportAndCompare(%s, %s, %s, %s)" % (a, b, tol, input_var)
        return "!reportAndCompare(%s, %s, %s)" % (a, b, tol)

    def sub_equal(match: "re.Match") -> str:
        nonlocal replaced
        replaced += 1
        a, b = match.group(1), match.group(2)
        input_var = derive_input_var(body, a)
        if input_var:
            return "!reportAndCompareEq(%s, %s, %s)" % (a, b, input_var)
        return "!reportAndCompareEq(%s, %s)" % (a, b)

    def sub_scalar_neq(match: "re.Match") -> str:
        nonlocal replaced
        replaced += 1
        expected, got = ordered_expected_got(match.group(2), match.group(3))
        return "%s!reportAndCompareScalar(%s, %s)" % (match.group(1), expected, got)

    def sub_scalar_abs(match: "re.Match") -> str:
        nonlocal replaced
        replaced += 1
        expected, got = ordered_expected_got(match.group(1), match.group(2))
        return "!reportAndCompareScalar(%s, %s, %s)" % (expected, got, match.group(3))

    body = FEQUAL_RE.sub(sub_fequal, body)
    body = STD_EQUAL_RE.sub(sub_equal, body)
    body = SCALAR_NEQ_RE.sub(sub_scalar_neq, body)
    body = SCALAR_ABS_RE.sub(sub_scalar_abs, body)

    return body, replaced


def patch_file(path: Path, apply: bool) -> "tuple[str, int]":
    text = path.read_text(encoding="utf-8")

    if "reportAndCompare" in text:
        return "already", 0

    lines = text.splitlines(keepends=True)
    span = find_validate_span(lines)

    if span is None:
        return "no_validate", 0

    start, end = span
    body = "".join(lines[start : end + 1])

    new_body, replaced = patch_body(body)

    if replaced == 0:
        return "not_patchable", 0

    if apply:
        path.write_text(
            "".join(lines[:start]) + new_body + "".join(lines[end + 1 :]),
            encoding="utf-8",
        )

    return "patched", replaced


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch validate() verdicts to reportAndCompare.")
    parser.add_argument("--check", action="store_true", help="Report only, write nothing.")
    args = parser.parse_args()

    results = {}
    total_sites = 0

    for path in sorted(BENCHMARKS_DIR.glob("*/*/cpu.cc")):
        benchmark = "%s/%s" % (path.parent.parent.name, path.parent.name)
        status, replaced = patch_file(path, apply=not args.check)
        results[benchmark] = status
        total_sites += replaced

    counts = {}
    for status in results.values():
        counts[status] = counts.get(status, 0) + 1

    mode = "CHECK" if args.check else "APPLY"
    print("[%s] %d cpu.cc files: %s | comparison sites rewritten: %d"
          % (mode, len(results), counts, total_sites))

    for benchmark, status in sorted(results.items()):
        if status in ("not_patchable", "no_validate"):
            print("  [%s] %s" % (status, benchmark))

    if counts.get("no_validate"):
        sys.exit(1)


if __name__ == "__main__":
    main()
