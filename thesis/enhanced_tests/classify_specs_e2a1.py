#!/usr/bin/env python3
"""Re-classify the EXISTING enhanced specs against the E2-A.1 harness (read-only).

E2-A.1 tightens WHICH specs are valid; it does not change what a still-valid
spec executes. The two axes therefore stay strictly separate, exactly as in
E2-A:

  INVALID_BY_POLICY   the spec is no longer accepted by validate_spec. Under
                      E2-A.1 that now also covers a parameter the pattern never
                      reads, an unknown pattern_params key, a fill parameter on
                      a benchmark with no fill hook, a non-finite value_range or
                      explicit value, an endpoint outside the fill container's
                      representable range, and a span the fill arithmetic cannot
                      compute. Such a spec must be REPLACED / REGENERATED (E3).

  INPUT_DRIFTED       the spec stays formally valid - same spec_key, size,
                      pattern and params - but the corrected harness builds a
                      DIFFERENT actual input for it. It must be RE-EXECUTED,
                      not regenerated.

The drift map is imported UNCHANGED from the E2-A classification: E2-A.1 adds
no new drift source. Its two harness changes are

  * widened-unsigned integral span/midpoint arithmetic, which is value-identical
    for every range the validator admits (and only reachable at all for ranges
    it now rejects), and
  * the removal of the define path's `(decltype(lo))` pre-cast, which is
    value-identical because no fill site in the suite pairs integral call-site
    literals with a floating container, and truncate-then-saturate reproduces
    the constant-folded cast exactly for integral containers.

Both are proven by the E2-A.1 parity and regression probes; the drift map is
therefore not extended here rather than being extended "just in case", which
would overstate the re-execution set.

The fixes-13 partition (65 / 7 / 4 / 407) is explicitly NOT assumed. Everything
below is recomputed.

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

from thesis.enhanced_tests.classify_specs_e2a import DRIFT_MAP  # noqa: E402
from thesis.enhanced_tests.specs import spec_key, validate_spec  # noqa: E402

DEFAULT_SPECS = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"

# Cases the E2-A.1 contract requires to be checked by name. Each is a claim
# about the CURRENT cache; a claim whose specs are not in the cache is reported
# as "not present", never silently as "passed".
REQUIRED_CASES = OrderedDict([
    ("dense_la03_huge_range", {
        "note": "dense_la/03 ascending value_range [-1e308, 1e308] must no "
                "longer be valid (the span is not finite in double)",
        "match": lambda r: (r["benchmark"].startswith("dense_la/03")
                            and r["pattern"] == "ascending"
                            and r["has_huge_range"]),
    }),
    ("sort41_irrelevant_k", {
        "note": "sort/41 specs carrying k on a pattern that never reads it",
        "match": lambda r: (r["benchmark"].startswith("sort/41")
                            and r["has_k"]
                            and r["pattern"] not in ("duplicate_at",
                                                     "sorted_except_one",
                                                     "spike_at")),
    }),
    ("sort44_inert_range", {
        "note": "sort/44 (no fill hook) specs carrying an inert value_range",
        "match": lambda r: (r["benchmark"].startswith("sort/44")
                            and r["has_range"]),
    }),
    ("sparse49_inert_range", {
        "note": "sparse_la/49 (no fill hook) specs carrying an inert value_range",
        "match": lambda r: (r["benchmark"].startswith("sparse_la/49")
                            and r["has_range"]),
    }),
])


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
        params = s.get("pattern_params") or {}
        value_range = params.get("value_range")
        ok, reason = validate_spec(s, known)
        drift_reason = (DRIFT_MAP.get(benchmark) or {}).get(pattern)
        span = None
        if value_range:
            try:
                span = float(value_range[1]) - float(value_range[0])
            except (TypeError, ValueError, OverflowError):
                span = None
        rows.append({
            "benchmark": benchmark,
            "spec_key": repr(spec_key(s)),
            "size": s.get("size"),
            "pattern": pattern,
            "source": s.get("source"),
            "has_range": value_range is not None,
            "has_k": params.get("k") is not None,
            "has_values": bool(s.get("values")),
            "has_huge_range": bool(value_range) and span is not None and span > 1e307,
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
    summary["partition_sums_to_total"] = (
        len(invalid_only) + len(drifted_valid) + len(both) + len(unchanged) == len(rows))
    summary["ENHANCED_SPECS_REGENERATION_REQUIRED"] = bool(invalid_only or both)
    summary["ENHANCED_SPECS_REGENERATION_COUNT"] = len(invalid_only) + len(both)
    summary["ENHANCED_SPECS_REEXECUTION_REQUIRED"] = bool(drifted_valid or both)
    summary["ENHANCED_SPECS_REEXECUTION_COUNT"] = len(drifted_valid)
    summary["invalid_reason_distribution"] = OrderedDict(
        sorted(Counter(r["invalid_reason"] for r in rows if not r["valid"]).items()))
    summary["invalid_benchmarks"] = bench_list(invalid_only + both)
    summary["drifted_benchmarks"] = bench_list(drifted_valid + both)
    summary["historical_input_reproducible_under_e2a1"] = OrderedDict(
        (b, False) for b in bench_list(drifted_valid + both))

    cases = OrderedDict()
    for name, spec in REQUIRED_CASES.items():
        matched = [r for r in rows if spec["match"](r)]
        cases[name] = OrderedDict([
            ("note", spec["note"]),
            ("present_in_cache", len(matched)),
            ("valid_after_e2a1", sum(1 for r in matched if r["valid"])),
            ("invalid_after_e2a1", sum(1 for r in matched if not r["valid"])),
            ("reasons", sorted({r["invalid_reason"] for r in matched if not r["valid"]})),
            ("benchmarks", sorted({r["benchmark"] for r in matched})),
        ])
    summary["required_case_checks"] = cases

    # capability-limited honesty: how far the per-benchmark counts now fall
    # below the target, WITHOUT padding them back up with inert parameters
    per_benchmark = Counter(r["benchmark"] for r in rows if r["valid"])
    summary["capability_limited_spec_count"] = OrderedDict(
        sorted((b, n) for b, n in per_benchmark.items() if n < 20))
    summary["benchmarks_with_no_valid_spec_left"] = sorted(
        {r["benchmark"] for r in rows} - set(per_benchmark))

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
            "generated_by": "thesis/enhanced_tests/classify_specs_e2a1.py",
            "wave": "E2-A.1",
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
