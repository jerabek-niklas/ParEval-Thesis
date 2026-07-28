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
import re
import statistics
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


# InferBO encodes its confidence in the bug_type suffix
# (BUFFER_OVERRUN_L1 .. _L5, _U5, _S2 — L1 most reliable). The scorer uses
# this both for the level breakdown and for the virtual L1/L2 variant.
INFERBO_LEVEL_RE = re.compile(r"_(L[1-5]|U[1-5]|S[1-5])$")

INFERBO_TRUSTED_LEVELS = ("L1", "L2")


def inferbo_level(check_id: str) -> str:
    """'L1'.. for a leveled InferBO bug_type, '' for anything else (the base
    Infer findings that infer_bo also produces carry no level)."""
    match = INFERBO_LEVEL_RE.search(check_id or "")
    return match.group(1) if match else ""


def split_infer_bo(row: dict) -> List[dict]:
    """infer_bo -> itself + the VIRTUAL 'infer_bo_l1l2' row.

    Same run, findings filtered: leveled InferBO reports are kept only at
    L1/L2 (its two most reliable levels); unleveled findings are the base
    Infer analysis that infer_bo also runs and are always kept. Answers "is
    the low-confidence tail worth its false positives?" without a second
    (expensive) run — same pattern as the clang_tidy split.
    """
    findings = row.get("findings", [])

    trusted = dict(row)
    trusted["tool"] = "infer_bo_l1l2"
    trusted["findings"] = [
        f
        for f in findings
        if inferbo_level(f.get("check_id", "")) in ("",) + INFERBO_TRUSTED_LEVELS
    ]

    return [row, trusted]


def row_language(row: dict) -> str:
    """Kernel language from the source path (Juliet ships .c and .cpp
    testcases). Derived here rather than stored, so the split also works on
    result files written before this analysis existed."""
    return "cpp" if str(row.get("path", "")).endswith((".cpp", ".cc", ".cxx")) else "c"


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
                elif row.get("tool") == "infer_bo":
                    rows.extend(split_infer_bo(row))
                else:
                    rows.append(row)

    return rows


def usable(row: dict) -> bool:
    return not row.get("skipped") and row.get("ran") and not row.get("error")


def score(rows: List[dict], language: str = None) -> List[dict]:
    """Per (suite, tool) confusion counts and metrics.

    `language` restricts the population to kernels of that language ("c" /
    "cpp") for the additive language split; None = all kernels (the
    canonical table).
    """
    buckets: Dict[tuple, dict] = defaultdict(
        lambda: {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "tp_strict": 0,
                 "skipped": 0, "errors": 0, "runtimes": []}
    )

    for row in rows:
        if language is not None and row_language(row) != language:
            continue

        key = (row["suite"], row["tool"])
        bucket = buckets[key]

        if row.get("skipped"):
            bucket["skipped"] += 1
            continue

        if not row.get("ran") or row.get("error"):
            bucket["errors"] += 1
            continue

        # cost side of the cost/benefit question (variants are far more
        # expensive than their base tools)
        if isinstance(row.get("runtime_seconds"), (int, float)):
            bucket["runtimes"].append(float(row["runtime_seconds"]))

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

        runtimes = b["runtimes"]

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
                "runtime_mean_s": round(statistics.mean(runtimes), 2) if runtimes else 0.0,
                "runtime_median_s": round(statistics.median(runtimes), 2) if runtimes else 0.0,
            }
        )

    return table


# ---------------------------------------------------------------------------
# Variant analyses (justification measurements: what does the extra
# component contribute, and at what cost?)
# ---------------------------------------------------------------------------

# base tool -> extended variant
VARIANT_PAIRS = (
    ("compiler", "compiler_fanalyzer"),
    ("infer", "infer_bo"),
    ("infer", "infer_bo_l1l2"),
    ("tsan", "tsan_noarcher"),
)


def detected_sets(rows: List[dict]):
    """(suite, tool) -> (kernels detected, kernels usable) over bad kernels."""
    detected: Dict[tuple, set] = defaultdict(set)
    processed: Dict[tuple, set] = defaultdict(set)

    for row in rows:
        if row["label"] != "bad" or not usable(row):
            continue

        key = (row["suite"], row["tool"])
        processed[key].add(row["kernel_id"])

        if matches(row["suite"], row["classes"], row["tool"], row.get("findings", [])):
            detected[key].add(row["kernel_id"])

    return detected, processed


def variant_deltas(rows: List[dict], metrics: List[dict]) -> List[dict]:
    """Per base/variant pair: metric deltas plus the decisive number —
    how many bad kernels ONLY the extended variant finds (unique
    contribution) on the kernels both processed."""
    by_key = {(m["suite"], m["tool"]): m for m in metrics}
    detected, processed = detected_sets(rows)

    result = []

    for base, variant in VARIANT_PAIRS:
        suites = sorted({s for (s, t) in by_key if t in (base, variant)})

        for suite in suites:
            base_m = by_key.get((suite, base))
            var_m = by_key.get((suite, variant))

            if not base_m or not var_m:
                continue

            common = processed[(suite, base)] & processed[(suite, variant)]
            found_base = detected[(suite, base)] & common
            found_var = detected[(suite, variant)] & common

            result.append(
                {
                    "suite": suite,
                    "base": base,
                    "variant": variant,
                    "recall_base": base_m["recall"],
                    "recall_variant": var_m["recall"],
                    "d_recall": round(var_m["recall"] - base_m["recall"], 3),
                    "precision_base": base_m["precision"],
                    "precision_variant": var_m["precision"],
                    "d_precision": round(var_m["precision"] - base_m["precision"], 3),
                    "fp_rate_base": base_m["fp_rate"],
                    "fp_rate_variant": var_m["fp_rate"],
                    "d_fp_rate": round(var_m["fp_rate"] - base_m["fp_rate"], 3),
                    "runtime_mean_base_s": base_m["runtime_mean_s"],
                    "runtime_mean_variant_s": var_m["runtime_mean_s"],
                    "runtime_factor": (
                        round(var_m["runtime_mean_s"] / base_m["runtime_mean_s"], 1)
                        if base_m["runtime_mean_s"] else 0.0
                    ),
                    "common_bad_kernels": len(common),
                    "only_variant": len(found_var - found_base),
                    "only_base": len(found_base - found_var),
                }
            )

    return result


def inferbo_levels(rows: List[dict]) -> List[dict]:
    """InferBO confidence-level breakdown: per level, how many bad kernels
    it contributes a class-relevant finding on (TP side) and how many good
    kernels it fires on (FP side).

    Answers "from which level on is it noise?" empirically instead of
    guessing a threshold. Counted per KERNEL (a kernel counts for a level if
    that level produced a class-relevant finding on it).
    """
    tp_counts: Dict[str, set] = defaultdict(set)
    fp_counts: Dict[str, set] = defaultdict(set)

    for row in rows:
        if row.get("tool") != "infer_bo" or not usable(row):
            continue

        for finding in row.get("findings", []):
            level = inferbo_level(finding.get("check_id", ""))
            if not level:
                continue

            # only class-relevant findings count, same rule as the metrics
            if not matches(row["suite"], row["classes"], row["tool"], [finding]):
                continue

            (tp_counts if row["label"] == "bad" else fp_counts)[level].add(
                row["kernel_id"]
            )

    levels = sorted(set(tp_counts) | set(fp_counts))

    table = []
    for level in levels:
        tp = len(tp_counts[level])
        fp = len(fp_counts[level])
        table.append(
            {
                "level": level,
                "bad_kernels_flagged": tp,
                "good_kernels_flagged": fp,
                "precision_of_level": round(tp / (tp + fp), 3) if tp + fp else 0.0,
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
- `tsan_noarcher`, `helgrind`, `drd`, `compiler_fanalyzer`, `infer_bo`,
  `infer_bo_l1l2` are inclusion/exclusion-justification measurements, NOT
  pipeline tools. The last three are VARIANT measurements: the pipeline
  tool plus one extra analysis component (`-fanalyzer`, `--bufferoverrun`),
  measured so the inclusion decision rests on numbers — see the
  "Variant deltas" section.
- `infer_bo_l1l2` is a VIRTUAL variant of `infer_bo` (same run, InferBO
  findings kept only at confidence levels L1/L2).
- `runtime_mean_s` / `runtime_median_s` are per-kernel analysis wall-clock
  seconds over the kernels that entered the metrics (skipped/error rows
  excluded). CAVEAT: tools measured in DIFFERENT run sessions are not
  comparable on this column (machine load, warm caches) — a cross-tool
  cost comparison needs a same-session measurement; see the runtime note
  in the "Variant deltas" section.
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
    deltas = variant_deltas(rows, metrics)
    levels = inferbo_levels(rows)

    # additive language split (Juliet ships .c and .cpp testcases)
    by_language = []
    for language in ("c", "cpp"):
        for entry in score(rows, language=language):
            entry = dict(entry)
            entry["language"] = language
            by_language.append(entry)

    write_csv(RESULTS_DIR / "metrics.csv", metrics)
    write_csv(RESULTS_DIR / "overlap.csv", overlaps)
    write_csv(RESULTS_DIR / "metrics_by_language.csv", by_language)
    write_csv(RESULTS_DIR / "variant_deltas.csv", deltas)
    write_csv(RESULTS_DIR / "inferbo_levels.csv", levels)

    summary = ["# Tool-Validation Summary\n"]
    summary.append(DEFINITIONS)
    summary.append("\n## Metrics (per suite and tool)\n")
    summary.append(markdown_table(metrics))
    summary.append("\n## Pairwise overlap (bad kernels processed by both tools)\n")
    summary.append(markdown_table(overlaps))

    summary.append("\n## Variant deltas (justification measurements)\n")
    summary.append(
        "Each row compares a base tool with the same tool plus one extra "
        "analysis component. `only_variant` — bad kernels that ONLY the "
        "extended variant detects, over kernels both processed — is the "
        "decisive number: it is the variant's unique contribution, "
        "independent of metric arithmetic.\n"
    )
    summary.append(
        "**Do not read `runtime_factor` as the cost of the extra analysis.** "
        "Base and variant were measured in separate run sessions, so the "
        "column mixes in machine load and cache state (it can even come out "
        "below 1). A same-session back-to-back measurement over 60 Juliet "
        "kernels (2026-07-21) gives the real per-kernel surcharge: compiler "
        "0.29s -> compiler_fanalyzer 0.30s (1.03x), infer 0.43s -> infer_bo "
        "0.47s (1.09x). On these small single-file kernels both extra "
        "analyses are nearly free; that does not extrapolate to large "
        "translation units.\n"
    )
    summary.append(markdown_table(deltas))

    if levels:
        summary.append("\n### InferBO confidence levels\n")
        summary.append(
            "InferBO encodes its certainty in the bug_type suffix "
            "(`BUFFER_OVERRUN_L1` .. `_L5`, L1 = most reliable). Per level: "
            "on how many bad / good kernels it produces a class-relevant "
            "finding. `infer_bo_l1l2` in the tables above is the virtual "
            "variant restricted to L1/L2 (same run, findings filtered).\n"
        )
        summary.append(markdown_table(levels))

    summary.append("\n## Metrics by kernel language (additive view)\n")
    summary.append(
        "Juliet ships C and C++ testcases. GCC documents `-fanalyzer` as "
        "targeting C, so the C/C++ split is the empirical answer to how "
        "viable it is on C++ — the open question behind its exclusion. "
        "Reported for every tool as a comparison baseline.\n"
    )
    summary.append(markdown_table(by_language))

    summary.append(
        "\n_See the Definitions section above for metric semantics, the "
        "kernel-level overlap caveat, and the dynamic-tool / virtual-tool "
        "footnotes. Measurement methodology: docs/measurement-definitions.md._\n"
    )

    (RESULTS_DIR / "summary.md").write_text("\n".join(summary), encoding="utf-8")

    print("\n".join(summary))
    print("written: summary.md, metrics.csv, overlap.csv, "
          "metrics_by_language.csv, variant_deltas.csv, inferbo_levels.csv "
          "(in %s)" % RESULTS_DIR)


if __name__ == "__main__":
    main()
