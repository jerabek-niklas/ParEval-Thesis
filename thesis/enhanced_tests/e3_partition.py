#!/usr/bin/env python3
"""E3 retention partition: split the existing enhanced spec cache into the three
disjoint sets E3 acts on, and derive the per-benchmark replacement budget.

    RETAINED_UNCHANGED   valid under the frozen E2-B policy, input unchanged
                         -> kept byte-for-byte, same spec_key

    DUPLICATE_ROW        a SECOND serialization of a spec_key that already
                         occurs earlier in the file. The historical cache
                         contains 12 such rows (5 of them valid), differing
                         only in the free-text `rationale`, which is part of
                         neither spec_key, spec_defines nor spec_runtime_env.
                         build_benchmark_specs already dropped them at run time
                         (it dedupes on spec_key), so they never produced a test
                         case. They are redundant ROWS of an existing spec, not
                         additional specs: the population baseline is therefore
                         DISTINCT spec identities, and keeping the first
                         occurrence loses no spec.
    RETAINED_DRIFTED     valid under the frozen policy, but the harness now
                         builds a DIFFERENT input for it
                         -> kept byte-for-byte, same spec_key, marked
                            requires_reexecution
    INVALID_TO_REPLACE   no longer accepted by validate_spec
                         -> removed from the final cache; a replacement may be
                            generated within the per-benchmark budget

The budget is the number of INVALID specs of that benchmark, so E3 is a
policy-driven REPLACEMENT and can never inflate the population:

    final_count <= old_count   for every benchmark

Read-only. Output: a JSON report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests.classify_specs_e2b import drift_reason  # noqa: E402
from thesis.enhanced_tests.specs import spec_key, validate_spec  # noqa: E402

DEFAULT_SPECS = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"


def load_specs(path):
    specs = []
    with open(path, "r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            line = line.strip()
            if line:
                specs.append((index, json.loads(line)))
    return specs


def partition(indexed_specs):
    known = {s["benchmark"] for _i, s in indexed_specs}
    retained_unchanged, retained_drifted, invalid, duplicate_rows = [], [], [], []
    seen_keys = set()
    for index, spec in indexed_specs:
        benchmark = spec["benchmark"]
        ok, reason = validate_spec(spec, known)
        drift = drift_reason(benchmark, spec.get("pattern"))
        key = spec_key(spec)
        row = OrderedDict([
            ("benchmark", benchmark),
            ("spec_key", repr(key)),
            ("original_index", index),
            ("pattern", spec.get("pattern")),
            ("size", spec.get("size")),
            ("source", spec.get("source")),
        ])
        if key in seen_keys:
            # a redundant serialization of a spec already in the file; the
            # runner already discarded it. Recorded, never counted as a spec.
            row["duplicate_of_earlier_row"] = True
            row["valid"] = bool(ok)
            duplicate_rows.append(row)
            continue
        seen_keys.add(key)
        if not ok:
            row["invalid_reason"] = reason.split(":")[0]
            row["invalid_detail"] = reason
            if drift:
                row["drift_reason"] = drift
            invalid.append(row)
        elif drift:
            row["drift_reason"] = drift
            retained_drifted.append(row)
        else:
            retained_unchanged.append(row)
    return retained_unchanged, retained_drifted, invalid, duplicate_rows


def budgets(indexed_specs, retained_unchanged, retained_drifted, invalid,
            duplicate_rows):
    old_counts = Counter(s["benchmark"] for _i, s in indexed_specs)
    dup_counts = Counter(r["benchmark"] for r in duplicate_rows)
    retained_counts = Counter(
        r["benchmark"] for r in retained_unchanged + retained_drifted)
    invalid_counts = Counter(r["benchmark"] for r in invalid)

    out = OrderedDict()
    for benchmark in sorted(set(capabilities.policy_benchmarks()) | set(old_counts)):
        old = old_counts.get(benchmark, 0)
        dup = dup_counts.get(benchmark, 0)
        distinct = old - dup
        retained = retained_counts.get(benchmark, 0)
        bad = invalid_counts.get(benchmark, 0)
        assert retained + bad == distinct, benchmark
        out[benchmark] = OrderedDict([
            ("old_row_count", old),
            ("duplicate_rows", dup),
            ("old_count", distinct),
            ("retained_unchanged", sum(
                1 for r in retained_unchanged if r["benchmark"] == benchmark)),
            ("retained_drifted", sum(
                1 for r in retained_drifted if r["benchmark"] == benchmark)),
            ("retained_total", retained),
            ("invalid_count", bad),
            ("replacement_budget", bad),
            ("max_final_count", distinct),
            ("zero_valid_old", retained == 0),
            ("removed_reasons", dict(Counter(
                r["invalid_reason"] for r in invalid
                if r["benchmark"] == benchmark))),
        ])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default=str(DEFAULT_SPECS))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    indexed = load_specs(args.specs)
    unchanged, drifted, invalid, duplicate_rows = partition(indexed)
    per_benchmark = budgets(indexed, unchanged, drifted, invalid, duplicate_rows)

    keys_all = [r["spec_key"] for r in unchanged + drifted + invalid]
    summary = OrderedDict([
        ("OLD_TOTAL_ROWS", len(indexed)),
        ("OLD_DUPLICATE_ROWS", len(duplicate_rows)),
        ("OLD_DUPLICATE_ROWS_VALID", sum(1 for r in duplicate_rows if r["valid"])),
        ("OLD_TOTAL_SPECS", len(indexed) - len(duplicate_rows)),
        ("OLD_BENCHMARK_COUNT", len({s["benchmark"] for _i, s in indexed})),
        ("RETAINED_UNCHANGED", len(unchanged)),
        ("RETAINED_DRIFTED", len(drifted)),
        ("OLD_VALID_SPECS", len(unchanged) + len(drifted)),
        ("INVALID_TO_REPLACE", len(invalid)),
        ("partition_disjoint_and_total",
         len(unchanged) + len(drifted) + len(invalid) + len(duplicate_rows)
         == len(indexed) and len(set(keys_all)) == len(keys_all)),
        ("REPLACEMENT_BUDGET_TOTAL",
         sum(b["replacement_budget"] for b in per_benchmark.values())),
        ("zero_valid_old_benchmarks",
         sorted(n for n, b in per_benchmark.items() if b["zero_valid_old"])),
        ("benchmarks_needing_replacement",
         sum(1 for b in per_benchmark.values() if b["replacement_budget"] > 0)),
    ])

    print(json.dumps(summary, indent=1))
    if args.out:
        doc = OrderedDict([
            ("_meta", {"generated_by": "thesis/enhanced_tests/e3_partition.py",
                       "wave": "E3", "specs_file": args.specs,
                       "note": "read-only partition; no spec was modified"}),
            ("summary", summary),
            ("per_benchmark", per_benchmark),
            ("retained_unchanged", unchanged),
            ("retained_drifted", drifted),
            ("invalid_to_replace", invalid),
            ("duplicate_rows", duplicate_rows),
        ])
        Path(args.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
