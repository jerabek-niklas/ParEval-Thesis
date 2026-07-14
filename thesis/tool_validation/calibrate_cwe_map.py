"""Empirical calibration of the Juliet CWE->check_id mapping (cwe_map.py).

Runs a small stratified sample (N simple `_01` flow-variant pairs per CWE
class) through the generic tools and reports, per class and tool:
  - how many bad kernels were matched by the CURRENT mapping (proto-recall)
  - every check_id that appeared on bad kernels but is NOT in the mapping
    (candidate mapping gaps -> silent recall under-counting)
  - every mapped check_id that appeared on good kernels (FP behavior)

This guards against the known failure mode of class-based matching: a tool
detects the defect but emits a check_id the mapping does not know, and the
scorer counts a miss. Run before the full measurement; extend
JULIET_MATCHERS with any clearly defect-relevant unmapped id it reports.

Usage (main container):
    python3 thesis/tool_validation/calibrate_cwe_map.py [--pairs-per-class 2]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.tool_validation.cwe_map import JULIET_MATCHERS  # noqa: E402
from thesis.tool_validation.suite_kernels import load_kernels  # noqa: E402
from thesis.tool_validation.validation_tools import VALIDATION_TOOLS  # noqa: E402

GENERIC_TOOLS = ("compiler", "clang_tidy", "cppcheck", "infer")

# ids that are ubiquitous style/hygiene noise on Juliet scaffolding; not
# defect candidates, suppressed from the gap report for readability
NOISE_PREFIXES = (
    "-Wunused",
    "misc-",
    "performance-",
    "bugprone-macro-parentheses",
    "bugprone-branch-clone",
    "bugprone-narrowing-conversions",
    "clang-analyzer-deadcode",
    "clang-analyzer-security.insecureAPI",
    "DEAD_STORE",
    # gcc note-severity continuation lines (no -W flag)
    "note",
    # Juliet scaffolding uses rand()/reserved identifiers everywhere
    "concurrency-mt-unsafe",
    "bugprone-reserved-identifier",
)


def is_noise(check_id: str) -> bool:
    return any(check_id.startswith(p) for p in NOISE_PREFIXES)


def pick_sample(pairs_per_class: int):
    kernels = load_kernels("juliet")
    by_class = defaultdict(list)

    for kernel in kernels:
        # simple control-flow variant only: baseline detectability
        if kernel.kernel_id.split("#")[0].endswith(("_01.c", "_01.cpp")):
            by_class[kernel.classes[0]].append(kernel)

    sample = []
    for cwe in sorted(by_class):
        # kernels come in bad/good adjacency from discovery order
        sample.extend(by_class[cwe][: 2 * pairs_per_class])

    return sample


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the Juliet CWE mapping.")
    parser.add_argument("--pairs-per-class", type=int, default=2)
    args = parser.parse_args()

    sample = pick_sample(args.pairs_per_class)
    print("calibration sample: %d kernels" % len(sample))

    tools = {
        name: VALIDATION_TOOLS[name]
        for name in GENERIC_TOOLS
        if VALIDATION_TOOLS[name].is_available()
    }

    # (cwe, tool) -> counts and id sets
    matched_bad = defaultdict(int)
    total_bad = defaultdict(int)
    unmapped_on_bad = defaultdict(set)
    mapped_on_good = defaultdict(set)

    for index, kernel in enumerate(sample, 1):
        cwe = kernel.classes[0]

        for name, tool in tools.items():
            result = tool.run(kernel)
            ids = {f.check_id for f in result.findings}
            prefixes = JULIET_MATCHERS.get(cwe, {}).get(name, ())
            hit = any(i.startswith(p) for i in ids for p in prefixes)

            if kernel.label == "bad":
                total_bad[(cwe, name)] += 1
                if hit:
                    matched_bad[(cwe, name)] += 1
                for check_id in ids:
                    if not is_noise(check_id) and not any(
                        check_id.startswith(p) for p in prefixes
                    ):
                        unmapped_on_bad[(cwe, name)].add(check_id)
            elif hit:
                mapped_on_good[(cwe, name)].update(
                    i for i in ids if any(i.startswith(p) for p in prefixes)
                )

        if index % 10 == 0:
            print("  %d/%d kernels done" % (index, len(sample)))

    print()
    print("%-8s %-11s %-7s %s" % ("CWE", "tool", "matched", "unmapped ids on bad kernels (gap candidates)"))
    print("-" * 100)

    for cwe in sorted({c for c, _ in total_bad}):
        for name in GENERIC_TOOLS:
            if (cwe, name) not in total_bad:
                continue
            gaps = sorted(unmapped_on_bad.get((cwe, name), ()))
            print(
                "%-8s %-11s %d/%d     %s"
                % (cwe, name, matched_bad[(cwe, name)], total_bad[(cwe, name)],
                   ", ".join(gaps) if gaps else "-")
            )

    fps = {k: v for k, v in mapped_on_good.items() if v}
    if fps:
        print()
        print("mapped ids appearing on GOOD kernels (FP behavior):")
        for (cwe, name), ids in sorted(fps.items()):
            print("  %-8s %-11s %s" % (cwe, name, ", ".join(sorted(ids))))


if __name__ == "__main__":
    main()
