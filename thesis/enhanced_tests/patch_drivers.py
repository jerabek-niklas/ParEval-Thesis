"""Mechanical patcher: parameterize validate() in the ParEval cpu.cc drivers.

Two transformations, applied ONLY inside the validate() function body:
  1. `const size_t TEST_SIZE = <N>;`
         -> `const size_t TEST_SIZE = ENHANCED_TEST_SIZE_DEFAULT(<N>);`
     (macro from drivers/cpp/enhanced-fill.hpp; without -DENHANCED_TEST_SIZE
      it evaluates to <N>, so default behavior is bit-identical)
  2. `fillRand(`  ->  `ENHANCED_FILL(`
     (macro defaults to fillRand; fillRandString/fillRandWithZeroes are
      deliberately NOT wrapped — patterns don't apply to them)

Benchmarks whose validate() has no canonical TEST_SIZE constant (sizes
inlined in constructors etc.) are logged as non-parameterizable and left
completely untouched — they are excluded from the enhanced-tests stage
rather than hand-edited.

Idempotent: files already containing ENHANCED_TEST_SIZE_DEFAULT are skipped.

MANUALLY PARAMETERIZED EXCEPTIONS (methodology note): 8 benchmarks had no
canonical `const size_t TEST_SIZE = <N>;` — their validate() inlined the
size into the vector constructors. They were brought onto the exact same
macro pattern BY HAND (hoist `const size_t TEST_SIZE =
ENHANCED_TEST_SIZE_DEFAULT(1024);` above the numTries loop, constructors
switched to TEST_SIZE, fillRand -> ENHANCED_FILL), after which this
script's detection recognizes them like the other 52:
    search/35_search_search_for_last_struct_by_key   (two vectors)
    search/36_search_check_if_array_contains_value
    sort/44_sort_sort_non-zero_elements   (custom fillRandWithZeroes kept:
        size parameterized, fill patterns not applicable to that call)
    transform/55_transform_relu
    transform/56_transform_negate_odds
    transform/57_transform_inverse_offset
    transform/58_transform_squaring
    transform/59_transform_map_function

Usage:
    python thesis/enhanced_tests/patch_drivers.py --check   # report only
    python thesis/enhanced_tests/patch_drivers.py           # apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BENCHMARKS_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks"

TEST_SIZE_RE = re.compile(r"(const\s+size_t\s+TEST_SIZE\s*=\s*)(\d+)(\s*;)")
FILL_RE = re.compile(r"\bfillRand\(")


def find_validate_span(lines: list) -> "tuple[int, int] | None":
    """(start, end) line indices of the validate() body, brace-balanced."""
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


def patch_file(path: Path, apply: bool) -> str:
    """Returns one of: 'patched', 'already', 'non_parameterizable', 'no_validate'."""
    text = path.read_text(encoding="utf-8")

    if "ENHANCED_TEST_SIZE_DEFAULT" in text:
        return "already"

    lines = text.splitlines(keepends=True)
    span = find_validate_span(lines)

    if span is None:
        return "no_validate"

    start, end = span
    body = "".join(lines[start : end + 1])

    if not TEST_SIZE_RE.search(body):
        return "non_parameterizable"

    body = TEST_SIZE_RE.sub(r"\1ENHANCED_TEST_SIZE_DEFAULT(\2)\3", body)
    body = FILL_RE.sub("ENHANCED_FILL(", body)

    if apply:
        new_text = "".join(lines[:start]) + body + "".join(lines[end + 1 :])
        path.write_text(new_text, encoding="utf-8")

    return "patched"


def main() -> None:
    parser = argparse.ArgumentParser(description="Parameterize cpu.cc validate() functions.")
    parser.add_argument("--check", action="store_true", help="Report only, write nothing.")
    args = parser.parse_args()

    results = {}

    for path in sorted(BENCHMARKS_DIR.glob("*/*/cpu.cc")):
        benchmark = f"{path.parent.parent.name}/{path.parent.name}"
        results[benchmark] = patch_file(path, apply=not args.check)

    counts = {}
    for status in results.values():
        counts[status] = counts.get(status, 0) + 1

    mode = "CHECK" if args.check else "APPLY"
    print(f"[{mode}] {len(results)} cpu.cc files: {counts}")

    for benchmark, status in sorted(results.items()):
        if status in ("non_parameterizable", "no_validate"):
            print(f"  [{status}] {benchmark}")

    if counts.get("no_validate"):
        sys.exit(1)


if __name__ == "__main__":
    main()
