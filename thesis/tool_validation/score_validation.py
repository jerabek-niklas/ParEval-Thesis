"""Scorer: metrics + pairwise overlap from the validation JSONL files.

Reads results/<suite>/<tool>.jsonl, computes per (suite, tool):
    Recall    = TP / (TP + FN)          over bad-labeled kernels
    FP-Rate   = FP / (FP + TN)          over good-labeled kernels
    Precision = TP / (TP + FP)
    F1        = 2 * P * R / (P + R)
and the pairwise overlap matrix per suite (over bad kernels that BOTH tools
processed: both found / only A / only B / neither, plus Jaccard).

Rows that are skipped (kernel does not compile) or carry a tool error are
excluded from the metrics and reported separately — a tool failure is not
a negative result.

Output: results/summary.md, results/metrics.csv, results/overlap.csv.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.tool_validation.cwe_map import matches, matches_strict  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


CLANG_SA_PREFIX = "clang-analyzer-"


def split_clang_tidy(row: dict) -> List[dict]:
    """Split a clang_tidy row into two VIRTUAL tool rows.

    Redundancy in the thesis is defined over the detection METHOD, and one
    clang-tidy invocation bundles two independent methods: AST matchers
    (bugprone-*, mpi-*, ... -> "clang_tidy_ast") and the Clang Static
    Analyzer's symbolic execution (clang-analyzer-* -> "clang_sa"). No
    second run needed — same engine invocation, findings partitioned by
    check_id prefix. Both appear as separate rows in metrics and overlap.
    """
    findings = row.get("findings", [])

    sa_row = dict(row)
    sa_row["tool"] = "clang_sa"
    sa_row["findings"] = [f for f in findings if f.get("check_id", "").startswith(CLANG_SA_PREFIX)]

    ast_row = dict(row)
    ast_row["tool"] = "clang_tidy_ast"
    ast_row["findings"] = [
        f for f in findings if not f.get("check_id", "").startswith(CLANG_SA_PREFIX)
    ]

    return [sa_row, ast_row]


def load_rows() -> List[dict]:
    rows: List[dict] = []

    for path in sorted(RESULTS_DIR.glob("*/*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue

                row = json.loads(line)

                if row.get("tool") == "clang_tidy":
                    rows.extend(split_clang_tidy(row))
                else:
                    rows.append(row)

    return rows


def usable(row: dict) -> bool:
    return not row.get("skipped") and row.get("ran") and not row.get("error")


def score(rows: List[dict]) -> List[dict]:
    """Per (suite, tool) confusion counts and metrics."""
    buckets: Dict[tuple, dict] = defaultdict(
        lambda: {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "tp_strict": 0,
                 "skipped": 0, "errors": 0}
    )

    for row in rows:
        key = (row["suite"], row["tool"])
        bucket = buckets[key]

        if row.get("skipped"):
            bucket["skipped"] += 1
            continue

        if not row.get("ran") or row.get("error"):
            bucket["errors"] += 1
            continue

        found = matches(row["suite"], row["classes"], row["tool"], row.get("findings", []))

        if row["label"] == "bad":
            bucket["tp" if found else "fn"] += 1

            # ADDITIVE strict view (category-aware TP; == lax for juliet/drb,
            # see cwe_map.matches_strict). Existing columns stay untouched.
            if matches_strict(
                row["suite"], row["classes"], row["tool"], row.get("findings", [])
            ):
                bucket["tp_strict"] += 1
        else:
            bucket["fp" if found else "tn"] += 1

    table = []

    for (suite, tool), b in sorted(buckets.items()):
        tp, fn, fp, tn = b["tp"], b["fn"], b["fp"], b["tn"]
        recall = tp / (tp + fn) if tp + fn else 0.0
        fpr = fp / (fp + tn) if fp + tn else 0.0
        precision = tp / (tp + fp) if tp + fp else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        tp_strict = b["tp_strict"]
        recall_strict = tp_strict / (tp + fn) if tp + fn else 0.0

        table.append(
            {
                "suite": suite,
                "tool": tool,
                "tp": tp,
                "fn": fn,
                "fp": fp,
                "tn": tn,
                "recall": round(recall, 3),
                "fp_rate": round(fpr, 3),
                "precision": round(precision, 3),
                "f1": round(f1, 3),
                "tp_strict": tp_strict,
                "recall_strict": round(recall_strict, 3),
                "skipped": b["skipped"],
                "errors": b["errors"],
            }
        )

    return table


def overlap(rows: List[dict]) -> List[dict]:
    """Pairwise overlap per suite over bad kernels both tools processed."""
    detected: Dict[tuple, set] = defaultdict(set)   # (suite, tool) -> kernels found
    processed: Dict[tuple, set] = defaultdict(set)  # (suite, tool) -> kernels usable

    for row in rows:
        if row["label"] != "bad" or not usable(row):
            continue

        key = (row["suite"], row["tool"])
        processed[key].add(row["kernel_id"])

        if matches(row["suite"], row["classes"], row["tool"], row.get("findings", [])):
            detected[key].add(row["kernel_id"])

    suites = sorted({suite for suite, _ in processed})
    result = []

    for suite in suites:
        tools = sorted(tool for s, tool in processed if s == suite)

        for tool_a, tool_b in combinations(tools, 2):
            common = processed[(suite, tool_a)] & processed[(suite, tool_b)]
            found_a = detected[(suite, tool_a)] & common
            found_b = detected[(suite, tool_b)] & common

            both = len(found_a & found_b)
            only_a = len(found_a - found_b)
            only_b = len(found_b - found_a)
            union = len(found_a | found_b)

            result.append(
                {
                    "suite": suite,
                    "tool_a": tool_a,
                    "tool_b": tool_b,
                    "common_kernels": len(common),
                    "both": both,
                    "only_a": only_a,
                    "only_b": only_b,
                    "neither": len(common) - both - only_a - only_b,
                    "jaccard": round(both / union, 3) if union else 0.0,
                }
            )

    return result


def write_csv(path: Path, rows: List[dict]) -> None:
    if not rows:
        return

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


DEFINITIONS = """## Definitions

**Row unit.** One row of the underlying data is one (kernel, tool) run.
A *kernel* is one labeled testcase variant (Juliet: bad/good compile of one
testcase file; DRB: one `-yes`/`-no` micro-benchmark; MBI: one generated
program).

**Confusion counts.** `tp`/`fn` are counted over bad-labeled kernels,
`fp`/`tn` over good-labeled kernels. What makes a finding count ("the tool
detected it") is suite-specific:

- *Juliet*: a finding counts only if its check_id is mapped to the
  testcase's CWE class (type-aware matching, `cwe_map.py`) — unrelated
  findings on a bad kernel do NOT count.
- *DRB*: a race-family finding (`tsan-data-race`, `llov-data-race`,
  `helgrind-race`, `drd-conflicting-access`, `parcoach-*`) on the kernel
  counts; DRB has a single defect category, so this is equivalent to
  category-aware matching.
- *MBI*: any defect-identifying finding of the tool's family counts
  (capability markers like `must-unsupported` never count). This lax view
  is category-BLIND: a tool reporting e.g. a request leak on a kernel
  labeled `callmatching` still counts as tp. See `tp_strict` below.

**Metrics.**
- `recall = tp / (tp + fn)` — share of known-bad kernels the tool flags.
- `fp_rate = fp / (fp + tn)` — alarm rate on known-clean kernels.
- `precision = tp / (tp + fp)` — trustworthiness of a single report.
- `f1` — harmonic mean of precision and recall.
- `tp_strict`, `recall_strict` — ADDITIVE category-aware view: the finding
  must identify the kernel's labeled defect category (mapping justified
  per check_id in `cwe_map.py`). For Juliet and DRB strict == lax by
  construction; the columns differ only on MBI. Both views are reportable:
  lax = "tool raises a defect report on a defective kernel", strict =
  "tool identifies the labeled defect class".

**skipped / errors.** `skipped` = kernel does not compile in this
environment; `errors` = the tool itself failed (timeout, crash, missing
report). Both are excluded from every metric — a tool failure is not a
negative result.

**Overlap table.** Computed over bad-labeled kernels that BOTH tools
processed without error (`common_kernels`), using the lax detection view:
`both` / `only_a` / `only_b` / `neither`, and
`jaccard = both / (both + only_a + only_b)`.
IMPORTANT: overlap is KERNEL-level — "both tools flagged something
class-relevant on the same kernel", NOT "both tools reported the same
defect at the same location". On Juliet (one CWE per kernel) kernel-level
closely approximates bug-level; on DRB a line-level sample shows the tools
report the same code region (same or ±2 lines), so the approximation holds
there too; on MBI tools may report different manifestations of the same
labeled defect.

**Footnotes.**
- Dynamic tools (asan_ubsan, memcheck, tsan*, must) only detect a bug if
  the test execution triggers it; their recall is not directly comparable
  to static tools.
- `clang_sa` and `clang_tidy_ast` are VIRTUAL tools: one clang-tidy run,
  findings partitioned by check_id prefix (`clang-analyzer-*` = symbolic
  execution vs. AST matchers) — redundancy is defined over detection
  methods, and clang-tidy bundles two.
- `tsan_noarcher`, `helgrind`, `drd` are inclusion/exclusion-justification
  measurements, not pipeline tools.
"""


def markdown_table(rows: List[dict]) -> str:
    if not rows:
        return "_no data_\n"

    headers = list(rows[0])
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")

    return "\n".join(lines) + "\n"


def main() -> None:
    rows = load_rows()

    if not rows:
        raise SystemExit("No results found under %s — run run_validation.py first." % RESULTS_DIR)

    metrics = score(rows)
    overlaps = overlap(rows)

    write_csv(RESULTS_DIR / "metrics.csv", metrics)
    write_csv(RESULTS_DIR / "overlap.csv", overlaps)

    summary = ["# Tool-Validation Summary\n"]
    summary.append(DEFINITIONS)
    summary.append("\n## Metrics (per suite and tool)\n")
    summary.append(markdown_table(metrics))
    summary.append("\n## Pairwise overlap (bad kernels processed by both tools)\n")
    summary.append(markdown_table(overlaps))
    summary.append(
        "\n_See the Definitions section above for metric semantics, the "
        "kernel-level overlap caveat, and the dynamic-tool / virtual-tool "
        "footnotes. Measurement methodology: docs/measurement-definitions.md._\n"
    )

    (RESULTS_DIR / "summary.md").write_text("\n".join(summary), encoding="utf-8")

    print("\n".join(summary))
    print("written: %s, %s, %s" % (
        RESULTS_DIR / "summary.md", RESULTS_DIR / "metrics.csv", RESULTS_DIR / "overlap.csv"
    ))


if __name__ == "__main__":
    main()
