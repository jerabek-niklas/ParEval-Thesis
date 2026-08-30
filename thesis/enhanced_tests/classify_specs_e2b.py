#!/usr/bin/env python3
"""Re-classify the EXISTING enhanced specs against the E2-B policy (read-only).

The two axes stay strictly separate, exactly as in E2-A and E2-A.1 - policy
invalidity is NOT input drift, and a spec can be either, both or neither:

  INVALID_BY_POLICY   validate_spec no longer accepts the spec. E2-B adds five
                      new grounds: a pattern that is now a duplicate label
                      (extreme_values), a constant or ramp value outside the
                      declared fill domain, a value_range outside it, a
                      value_range on a benchmark whose sites declare different
                      domains, and a size 0 the benchmark semantics do not
                      define. Such a spec must be REPLACED (E3).

  INPUT_DRIFTED       the spec stays formally valid - same spec_key, size,
                      pattern and params - but the harness now builds a
                      DIFFERENT input for it. It must be RE-EXECUTED.

The E2-B drift sources are computed from the harness semantics, NOT inherited:

  * the E2-A DType drift (four fill sites whose deduced value type changed) is
    carried over unchanged - it is a property of those sites, not of a policy;
  * NEW: `extreme_values` no longer writes numeric_limits::lowest()/max() but
    alternates the effective domain endpoints, so EVERY historical
    extreme_values spec on a benchmark with a fill hook builds a different
    input;
  * NEW: `spike_at` no longer writes numeric_limits::max()/2 but the effective
    domain `hi`, so every historical spike_at spec on such a benchmark drifts.

E2-B's other changes (the value_range domain rule, the size-zero decisions, the
degenerate-range rule) change WHICH specs are valid, not what a still-valid spec
executes, so they contribute invalidity and no drift.

The E2-A.1 partition (76 / 7 / 4 / 396) is explicitly NOT assumed. Everything
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

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests.classify_specs_e2a import DRIFT_MAP as DTYPE_DRIFT  # noqa: E402
from thesis.enhanced_tests.specs import spec_key, validate_spec  # noqa: E402

DEFAULT_SPECS = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"

E2B_SEMANTICS_CHANGED = {
    "extreme_values": ("E2-B EXTREME_PATTERN_SEMANTICS: the pattern alternated "
                       "numeric_limits::lowest()/max() and now alternates the "
                       "effective declared-domain endpoints"),
    "spike_at": ("E2-B SPIKE_AT_SEMANTICS: the spike was "
                 "numeric_limits::max()/2 and is now the effective declared-"
                 "domain upper extreme hi"),
}


def load_specs(path):
    specs = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                specs.append(json.loads(line))
    return specs


def drift_reason(benchmark, pattern):
    """None, or why the harness now builds a different input for this spec."""
    reasons = []
    dtype = (DTYPE_DRIFT.get(benchmark) or {}).get(pattern)
    if dtype:
        reasons.append("E2-A DType fix: " + dtype)
    if pattern in E2B_SEMANTICS_CHANGED and capabilities.has_fill_hook(benchmark):
        reasons.append(E2B_SEMANTICS_CHANGED[pattern])
    return " || ".join(reasons) if reasons else None


def classify(specs):
    known = {s["benchmark"] for s in specs}
    rows = []
    for s in specs:
        benchmark = s["benchmark"]
        pattern = s.get("pattern")
        params = s.get("pattern_params") or {}
        ok, reason = validate_spec(s, known)
        drift = drift_reason(benchmark, pattern)
        rows.append({
            "benchmark": benchmark,
            "spec_key": repr(spec_key(s)),
            "size": s.get("size"),
            "pattern": pattern,
            "source": s.get("source"),
            "has_range": params.get("value_range") is not None,
            "value_range": params.get("value_range"),
            "valid": bool(ok),
            "invalid_reason": "" if ok else reason.split(":")[0],
            "invalid_detail": "" if ok else reason,
            "input_drifted": drift is not None,
            "drift_reason": drift or "",
        })
    return rows


def summarize(rows):
    invalid_only = [r for r in rows if not r["valid"] and not r["input_drifted"]]
    drifted_valid = [r for r in rows if r["valid"] and r["input_drifted"]]
    both = [r for r in rows if not r["valid"] and r["input_drifted"]]
    unchanged = [r for r in rows if r["valid"] and not r["input_drifted"]]
    assert len(invalid_only) + len(drifted_valid) + len(both) + len(unchanged) == len(rows)

    def benches(subset):
        return sorted({r["benchmark"] for r in subset})

    summary = OrderedDict()
    summary["TOTAL_EXISTING_SPECS"] = len(rows)
    summary["INVALID_BY_POLICY_ONLY"] = len(invalid_only)
    summary["INPUT_DRIFTED_BUT_STILL_VALID"] = len(drifted_valid)
    summary["INVALID_AND_DRIFTED"] = len(both)
    summary["UNCHANGED_AND_VALID"] = len(unchanged)
    summary["partition_sums_to_total"] = True
    summary["ENHANCED_SPECS_REGENERATION_REQUIRED"] = bool(invalid_only or both)
    summary["ENHANCED_SPECS_REGENERATION_COUNT"] = len(invalid_only) + len(both)
    summary["ENHANCED_SPECS_REEXECUTION_REQUIRED"] = bool(drifted_valid)
    summary["ENHANCED_SPECS_REEXECUTION_COUNT"] = len(drifted_valid)
    summary["invalid_reason_distribution"] = OrderedDict(
        sorted(Counter(r["invalid_reason"] for r in rows if not r["valid"]).items()))
    summary["drift_source_distribution"] = OrderedDict(sorted(Counter(
        ("dtype+e2b_semantics" if "||" in r["drift_reason"]
         else "e2b_semantics" if r["drift_reason"].startswith("E2-B")
         else "dtype")
        for r in rows if r["input_drifted"]).items()))
    summary["drifted_by_pattern"] = OrderedDict(sorted(Counter(
        r["pattern"] for r in rows if r["input_drifted"]).items()))
    summary["invalid_benchmarks"] = benches(invalid_only + both)
    summary["drifted_benchmarks"] = benches(drifted_valid + both)
    summary["historical_input_reproducible_under_e2b"] = OrderedDict(
        (b, False) for b in benches(drifted_valid + both))

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
            "generated_by": "thesis/enhanced_tests/classify_specs_e2b.py",
            "wave": "E2-B",
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
