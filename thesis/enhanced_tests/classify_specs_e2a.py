#!/usr/bin/env python3
"""Classify the EXISTING enhanced specs against the E2-A harness (read-only).

E2-A changed two independent things, and a spec can be hit by either, both or
neither. They must never be collapsed into one "specs are stale" notion:

  INVALID_BY_POLICY        the spec is no longer accepted by validate_spec under
                           the enforced capability policy (unsupported pattern,
                           no pattern effect, unsafe pattern, benchmark-specific
                           size violation, non-representable explicit value, or
                           a policy-deferred pattern). It must be REPLACED /
                           REGENERATED later (E3).
  INPUT_DRIFTED            the spec stays formally valid — same spec_key, size,
                           pattern and params — but the corrected harness builds
                           a DIFFERENT actual input for it, because the fill
                           site's pattern value type changed. It must be
                           RE-EXECUTED, not regenerated.

The drift map below comes from the E2-A blast-radius probe: only the four fill
sites whose deduced value type changed can drift, and per site only the patterns
whose values actually differ (measured old-vs-new for the non-UB patterns; the
two extreme patterns are drift by construction because the old path executed
undefined behaviour and is not a comparable reference).

This script never writes a spec file. Output: a JSON report.
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

from thesis.enhanced_tests.specs import spec_key, validate_spec  # noqa: E402

DEFAULT_SPECS = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"

# benchmark -> {pattern: reason}, measured by the E2-A drift probe
DRIFT_MAP = {
    "reduce/28_reduce_smallest_odd_number": {
        "random": "value type int instead of double: fillRand takes its integral "
                  "branch (rand() %% span, hi-exclusive) instead of the scaled "
                  "double branch",
        "duplicate_at": "same integral fillRand branch as random",
        "spike_at": "old path executed out-of-range double->int conversion "
                    "(undefined behaviour); the random part additionally moves to "
                    "the integral fillRand branch",
        "ascending": "integral ramp (lo + position %% (span+1)) instead of a "
                     "truncated double ramp",
        "descending": "integral ramp instead of a truncated double ramp",
        "sorted_except_one": "integral ramp instead of a truncated double ramp",
        "extreme_values": "old path executed out-of-range double->int conversion "
                          "(undefined behaviour); values are now INT_MIN/INT_MAX",
    },
    "scan/31_scan_scan_with_min_function": {
        "ascending": "ramp arithmetic in float instead of double, rounded once",
        "descending": "ramp arithmetic in float instead of double, rounded once",
        "sorted_except_one": "ramp arithmetic in float instead of double",
        "extreme_values": "old path executed out-of-range double->float conversion "
                          "(undefined behaviour); values are now +/-FLT_MAX",
        "spike_at": "old path executed out-of-range double->float conversion "
                    "(undefined behaviour); spike is now FLT_MAX/2",
    },
}
DRIFT_MAP["sort/42_sort_sorted_ranks"] = dict(DRIFT_MAP["scan/31_scan_scan_with_min_function"])
DRIFT_MAP["sort/43_sort_sort_an_array_of_structs_by_key"] = dict(
    DRIFT_MAP["scan/31_scan_scan_with_min_function"])

# patterns proven IDENTICAL old-vs-new at the changed sites (probe evidence)
NO_DRIFT_EVIDENCE = {
    "reduce/28_reduce_smallest_odd_number": ["all_zeros", "all_same", "alternating",
                                             "explicit_values"],
    "scan/31_scan_scan_with_min_function": ["random", "all_zeros", "all_same",
                                            "alternating", "duplicate_at",
                                            "explicit_values"],
}
NO_DRIFT_EVIDENCE["sort/42_sort_sorted_ranks"] = list(
    NO_DRIFT_EVIDENCE["scan/31_scan_scan_with_min_function"])
NO_DRIFT_EVIDENCE["sort/43_sort_sort_an_array_of_structs_by_key"] = list(
    NO_DRIFT_EVIDENCE["scan/31_scan_scan_with_min_function"])


def load_specs(path):
    specs = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                specs.append(json.loads(line))
    return specs


def classify(specs):
    known = {s["benchmark"] for s in specs}
    rows = []
    for s in specs:
        benchmark = s["benchmark"]
        pattern = s.get("pattern")
        ok, reason = validate_spec(s, known)
        drift_reason = (DRIFT_MAP.get(benchmark) or {}).get(pattern)
        rows.append({
            "benchmark": benchmark,
            "spec_key": repr(spec_key(s)),
            "size": s.get("size"),
            "pattern": pattern,
            "valid": bool(ok),
            "invalid_reason": "" if ok else reason.split(":")[0],
            "invalid_detail": "" if ok else reason,
            "input_drifted": drift_reason is not None,
            "drift_reason": drift_reason or "",
        })
    return rows


def summarize(rows):
    invalid_only = [r for r in rows if not r["valid"] and not r["input_drifted"]]
    drifted_valid = [r for r in rows if r["valid"] and r["input_drifted"]]
    both = [r for r in rows if not r["valid"] and r["input_drifted"]]
    unchanged = [r for r in rows if r["valid"] and not r["input_drifted"]]

    assert len(invalid_only) + len(drifted_valid) + len(both) + len(unchanged) == len(rows)

    def bench_list(subset):
        return sorted({r["benchmark"] for r in subset})

    summary = OrderedDict()
    summary["TOTAL_EXISTING_SPECS"] = len(rows)
    summary["INVALID_BY_POLICY_ONLY"] = len(invalid_only)
    summary["INPUT_DRIFTED_BUT_STILL_VALID"] = len(drifted_valid)
    summary["INVALID_AND_DRIFTED"] = len(both)
    summary["UNCHANGED_AND_VALID"] = len(unchanged)
    summary["partition_sums_to_total"] = True
    summary["ENHANCED_SPECS_REGENERATION_REQUIRED"] = bool(invalid_only or both)
    summary["ENHANCED_SPECS_REEXECUTION_REQUIRED"] = bool(drifted_valid or both)
    summary["invalid_reason_distribution"] = OrderedDict(
        sorted(Counter(r["invalid_reason"] for r in rows if not r["valid"]).items()))
    summary["invalid_benchmarks"] = bench_list(invalid_only + both)
    summary["drifted_benchmarks"] = bench_list(drifted_valid + both)
    summary["historical_input_reproducible_under_e2a"] = OrderedDict(
        (b, False) for b in bench_list(drifted_valid + both))
    return summary, {
        "invalid_by_policy_only": invalid_only,
        "input_drifted_but_still_valid": drifted_valid,
        "invalid_and_drifted": both,
        "unchanged_and_valid": unchanged,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default=str(DEFAULT_SPECS))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = classify(load_specs(args.specs))
    summary, parts = summarize(rows)

    print(json.dumps(summary, indent=1))
    if args.out:
        doc = OrderedDict()
        doc["_meta"] = {
            "generated_by": "thesis/enhanced_tests/classify_specs_e2a.py",
            "specs_file": args.specs,
            "note": "read-only classification; no spec was modified or regenerated",
        }
        doc["summary"] = summary
        doc["partitions"] = parts
        Path(args.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
