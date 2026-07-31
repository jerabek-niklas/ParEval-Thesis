"""Derive the input SHAPE of every benchmark from its validate() body.

Writes thesis/enhanced_tests/benchmark_shapes.json — a CHECKED artifact,
not a by-product: the explicit_values validation depends on it (how many
values does a spec need?), and the evaluation later needs it to interpret
what a "size" means per benchmark (n elements vs. an n x n matrix).

Reuses patch_drivers.find_validate_span (single source for locating the
validate() body); everything else is a small declaration parser:

    ENHANCED_FILL(A, ...)   with   std::vector<double> A(TEST_SIZE*TEST_SIZE)
        -> that fill site covers n*n elements  ("n2")
    ENHANCED_FILL(x, ...)   with   std::vector<double> x(TEST_SIZE)
        -> n elements                          ("n")
    ENHANCED_FILL(v, ...)   with   std::vector<int> v(64)
        -> a fixed count                       ("const:64")

Schema (one entry per benchmark):
    {
      "fill_sites": <int>,             # ENHANCED_FILL call sites in validate()
      "elements_per_site": [<form>],   # one entry per site, in source order
      "total_elements": "<expr>",      # human-readable total, e.g. "n*n"
      "explicit_values_supported": <bool>,
      "notes": "<string>"
    }

`elements_per_site` uses an ENUM + factor ("n" | "n2" | "const:<int>"),
never a free expression, so consumers never evaluate strings.

Usage:
    python thesis/enhanced_tests/derive_shapes.py            # write
    python thesis/enhanced_tests/derive_shapes.py --check    # verify only
    python thesis/enhanced_tests/derive_shapes.py --evidence # print sources

Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests.patch_drivers import find_validate_span  # noqa: E402

BENCHMARKS_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks"
SHAPES_PATH = Path(__file__).resolve().parent / "benchmark_shapes.json"

FILL_SITE_RE = re.compile(r"\bENHANCED_FILL\s*\(\s*([A-Za-z_]\w*)")

# `std::vector<...> name(expr)` / `, name(expr)` — one declaration line can
# declare several vectors (dense_la/03: `std::vector<double> x(N), y(N);`)
DECL_RE = re.compile(r"([A-Za-z_]\w*)\s*\(\s*([^()]*?)\s*\)")

VECTOR_LINE_RE = re.compile(r"\bstd::vector\s*<")

TEST_SIZE_SQUARED_RE = re.compile(r"TEST_SIZE\s*\*\s*TEST_SIZE")
TEST_SIZE_RE = re.compile(r"\bTEST_SIZE\b")
INT_LITERAL_RE = re.compile(r"^\d+$")


def classify_extent(expr: str) -> str:
    """Size expression of a vector declaration -> shape enum."""
    compact = expr.replace(" ", "")

    if TEST_SIZE_SQUARED_RE.search(compact):
        return "n2"
    if TEST_SIZE_RE.search(compact):
        # TEST_SIZE, TEST_SIZE+1, ... — all linear in n; anything with a
        # different structure is flagged by the caller as unknown
        return "n" if compact == "TEST_SIZE" else "n:" + compact
    if INT_LITERAL_RE.match(compact):
        return "const:" + compact

    return "unknown:" + compact


def declared_extents(body: str) -> "dict":
    """variable name -> shape enum, for every std::vector declared in the
    validate() body (handles multi-declarations on one line)."""
    extents = {}

    for line in body.splitlines():
        if not VECTOR_LINE_RE.search(line):
            continue

        # strip the type part so the parser does not see vector<...>(...)
        after = line.split(">", 1)[-1]

        for name, expr in DECL_RE.findall(after):
            if expr.strip():
                extents.setdefault(name, classify_extent(expr))

    return extents


def derive_benchmark(path: Path) -> "dict":
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    span = find_validate_span(lines)
    if span is None:
        return {
            "fill_sites": 0,
            "elements_per_site": [],
            "total_elements": "0",
            "explicit_values_supported": False,
            "notes": "no validate() found",
        }

    start, end = span
    body = "".join(lines[start : end + 1])

    sites = FILL_SITE_RE.findall(body)
    extents = declared_extents(body)

    per_site = []
    unresolved = []

    for name in sites:
        shape = extents.get(name)
        if shape is None:
            shape = "unknown:undeclared"
            unresolved.append(name)
        per_site.append(shape)

    notes = []

    if not sites:
        if "fillRandWithZeroes" in body:
            notes.append(
                "no ENHANCED_FILL site: uses fillRandWithZeroes (deliberately "
                "not wrapped — fill patterns do not apply)"
            )
        elif "fillRandString" in body:
            notes.append(
                "no ENHANCED_FILL site: uses fillRandString (deliberately not "
                "wrapped)"
            )
        else:
            notes.append("no ENHANCED_FILL site")

    if unresolved:
        notes.append("could not resolve declaration of: " + ", ".join(unresolved))

    for shape in per_site:
        if shape.startswith("unknown") or shape.startswith("n:"):
            notes.append("non-canonical extent: " + shape)

    # DECISION (documented): explicit_values is only supported for a SINGLE
    # fill site. With several sites (e.g. axpy fills x and y) the mapping
    # "which value goes into which vector" is ambiguous — the C++ side would
    # fill BOTH vectors from the same list, which is a silent
    # reinterpretation of the spec rather than the case the generator meant.
    # We reject it explicitly instead of guessing.
    supported = len(per_site) == 1 and per_site[0] in ("n", "n2")

    if len(per_site) > 1:
        notes.append(
            "explicit_values disabled: %d fill sites — value-to-vector "
            "mapping would be ambiguous (every site would receive the SAME "
            "list)" % len(per_site)
        )
    elif per_site and not supported:
        notes.append("explicit_values disabled: extent not canonical (%s)" % per_site[0])
    elif not per_site:
        notes.append("explicit_values disabled: nothing to fill")

    if per_site == ["n"]:
        total = "n"
    elif per_site == ["n2"]:
        total = "n*n"
    else:
        total = " + ".join(per_site) if per_site else "0"

    return {
        "fill_sites": len(per_site),
        "elements_per_site": per_site,
        "total_elements": total,
        "explicit_values_supported": supported,
        "notes": "; ".join(notes),
    }


def derive_all() -> "dict":
    shapes = {}

    for path in sorted(BENCHMARKS_DIR.glob("*/*/cpu.cc")):
        benchmark = "%s/%s" % (path.parent.parent.name, path.parent.name)
        shapes[benchmark] = derive_benchmark(path)

    return shapes


def evidence(benchmark: str) -> str:
    """Source lines that justify a benchmark's entry (for the manual check)."""
    path = BENCHMARKS_DIR / benchmark / "cpu.cc"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    span = find_validate_span(lines)
    if span is None:
        return "(no validate)"

    body = "".join(lines[span[0] : span[1] + 1])

    keep = [
        line.strip()
        for line in body.splitlines()
        if "ENHANCED_FILL" in line or VECTOR_LINE_RE.search(line) or "TEST_SIZE =" in line
    ]
    return "\n".join("      " + line for line in keep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive benchmark input shapes.")
    parser.add_argument("--check", action="store_true",
                        help="Compare against the stored file, write nothing.")
    parser.add_argument("--evidence", action="store_true",
                        help="Print the source lines behind every entry.")
    args = parser.parse_args()

    shapes = derive_all()

    counts = {}
    for entry in shapes.values():
        key = entry["total_elements"] if entry["fill_sites"] else "none"
        counts[key] = counts.get(key, 0) + 1

    print("benchmarks: %d" % len(shapes))
    print("shape distribution: %s" % counts)
    print("explicit_values supported: %d / %d"
          % (sum(1 for e in shapes.values() if e["explicit_values_supported"]), len(shapes)))

    flagged = {b: e for b, e in shapes.items() if e["notes"]}
    if flagged:
        print("\nentries with notes (%d):" % len(flagged))
        for benchmark, entry in sorted(flagged.items()):
            print("  %-52s sites=%d %s" % (benchmark, entry["fill_sites"], entry["notes"]))

    if args.evidence:
        print("\n=== evidence ===")
        for benchmark, entry in sorted(shapes.items()):
            print("\n%s -> sites=%d per_site=%s supported=%s"
                  % (benchmark, entry["fill_sites"], entry["elements_per_site"],
                     entry["explicit_values_supported"]))
            print(evidence(benchmark))

    if args.check:
        if not SHAPES_PATH.exists():
            raise SystemExit("no stored shapes at %s" % SHAPES_PATH)
        stored = json.loads(SHAPES_PATH.read_text(encoding="utf-8"))
        if stored == shapes:
            print("\nCHECK: stored shapes match the derivation.")
        else:
            differing = [b for b in shapes if stored.get(b) != shapes[b]]
            raise SystemExit("CHECK FAILED, differing: %s" % differing)
        return

    SHAPES_PATH.write_text(
        json.dumps(shapes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("\nwritten: %s" % SHAPES_PATH)


if __name__ == "__main__":
    main()
