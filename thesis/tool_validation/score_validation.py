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

from thesis.tool_validation.cwe_map import matches  # noqa: E402

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
        lambda: {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "skipped": 0, "errors": 0}
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
        else:
            bucket["fp" if found else "tn"] += 1

    table = []

    for (suite, tool), b in sorted(buckets.items()):
        tp, fn, fp, tn = b["tp"], b["fn"], b["fp"], b["tn"]
        recall = tp / (tp + fn) if tp + fn else 0.0
        fpr = fp / (fp + tn) if fp + tn else 0.0
        precision = tp / (tp + fp) if tp + fp else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

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


def markdown_table(rows: List[dict]) -> str:
    if not rows:
        return "_keine Daten_\n"

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
    summary.append("## Metriken (pro Suite und Tool)\n")
    summary.append(markdown_table(metrics))
    summary.append("\n## Paarweiser Overlap (bad-Kernels, beide Tools gelaufen)\n")
    summary.append(markdown_table(overlaps))
    summary.append(
        "\n_Hinweis: skipped = Kernel kompiliert nicht; errors = Tool-Fehler. "
        "Beide sind aus allen Metriken ausgeschlossen._\n"
    )
    summary.append(
        "\n_Fußnote Dynamik-Semantik: asan_ubsan und memcheck (Juliet) sowie "
        "tsan/tsan_noarcher (DRB) melden einen Bug nur, wenn der Testlauf ihn "
        "auslöst. Ihre Recall-Werte sind daher NICHT direkt mit den statischen "
        "Tools vergleichbar (andere Detektions-Semantik: beobachtete Ausführung "
        "vs. alle möglichen Pfade)._\n"
    )
    summary.append(
        "\n_Virtuelle Tools: clang_sa (clang-analyzer-*) und clang_tidy_ast "
        "sind der methodenbasierte Split EINER clang-tidy-Invocation (Symbolic "
        "Execution vs. AST-Matcher) — kein separater Lauf._\n"
    )

    (RESULTS_DIR / "summary.md").write_text("\n".join(summary), encoding="utf-8")

    print("\n".join(summary))
    print("written: %s, %s, %s" % (
        RESULTS_DIR / "summary.md", RESULTS_DIR / "metrics.csv", RESULTS_DIR / "overlap.csv"
    ))


if __name__ == "__main__":
    main()
