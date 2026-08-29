#!/usr/bin/env python3
"""Derive the PRODUCTIVE enhanced capability policy from the E1 audit catalog.

    thesis/enhanced_tests/enhanced_capabilities.json   (AUDIT metadata)
        --[ the explicit rules below ]-->
    thesis/enhanced_tests/enhanced_policy.json         (ENFORCED policy)

The catalog is an audit document and stays AUDIT_ONLY_NOT_ENFORCED. Only the
findings that are UNAMBIGUOUS, POLICY-INDEPENDENT and SOURCE-BACKED become
enforced policy; everything whose resolution needs one of the open E2-B
policies is carried over as `deferred_policy` and is NOT silently supported.

Derivation rules (E2-A):

  R1  no pattern effect
      benchmark pattern_effect in {NONE, NOT_APPLICABLE}
      -> only the canonical label "random" stays supported; the other ten are
         unsupported with reason `no_pattern_effect`.
      Rationale: the benchmark has no reachable ENHANCED_FILL hook, so a
      different pattern label produces the SAME input. Counting those labels as
      test diversity is the fake-diversity defect (E1 §5). Size variation is
      untouched.

  R2  oracle execution unsafe
      pattern with oracle_execution_safe == false
      -> unsupported, reason `unsafe_pattern_for_benchmark`.
      Rationale: the frozen oracle would execute C/C++ undefined behaviour
      (signed overflow, heap OOB, out-of-range conversion) on that input. Hard
      pre-pilot_002 blocker, independent of every open policy.

  R3  fill-layer UB in the E1 audit (now type-fixed) but domain still open
      pattern with fill_type_safe == false in the catalog
      -> deferred_policy, reason `extreme_semantics_deferred`.
      Rationale: E2-A fixed the CONVERSION (the value type is now the
      container's element type), so the fill no longer executes UB. Whether
      element-type extrema are an admissible INPUT for that benchmark is
      EXTREME_PATTERN_SEMANTICS, which stays open. Not silently supported.

  R4  demonstrated false-fail risk
      pattern with verdict_outcome_class == FALSE_FAIL_RISK
      -> deferred_policy, reason `false_fail_risk_deferred`.
      Rationale: a semantically acceptable candidate can be graded FAIL. The
      fix needs the tolerance/domain policy (E2-B), so the case is parked, not
      declared permanently unsupported.

  R4b explicit_values representability
      For a benchmark whose fill container element type cannot represent every
      double a spec may carry (int and float containers), the policy records
      `explicit_values_bounds`. validate_spec REJECTS a spec whose values fall
      outside them instead of clipping: an out-of-range floating->integral (or
      double->float) conversion is undefined behaviour, and clipping would be a
      VALUE_RANGE_DOMAIN_POLICY decision, which stays open.

  R5  benchmark-specific size safety
      taken from the size-triggered hazards recorded in the catalog's
      oracle_hazards plus the frozen prompt domain; expressed per benchmark as
      min_size and/or a size predicate. These are per-benchmark technical
      constraints, NOT a global size-0 rule: SIZE_ZERO_SPEC_POLICY stays open
      and every other benchmark keeps accepting size 0.

Precedence: R2 (unsupported) wins over R3/R4 (deferred), which win over
supported. R1 applies to the whole benchmark.

Run with --check to verify the committed policy still matches the catalog.
Read-only apart from writing enhanced_policy.json (and nothing at all under
--check).
"""

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "enhanced_capabilities.json"
POLICY = HERE / "enhanced_policy.json"

CANONICAL_PATTERN = "random"

# R5: benchmark-specific size constraints. Every entry names the concrete
# technical hazard it avoids; nothing here generalizes to other benchmarks.
SIZE_CONSTRAINTS = {
    "dense_la/01_dense_la_solve": {
        "min_size": 1,
        "reason": "size 0 makes correctSolveLinearSystem's forward-elimination "
                  "bound `i < N - 1` underflow on size_t and read an empty "
                  "vector (heap out-of-bounds, baseline.hpp)",
    },
    "graph/19_graph_shortest_path": {
        "min_size": 2,
        "reason": "size 0 underflows the `i < N-1` spanning-path loop bound; "
                  "size 1 makes `rand() % (N - 1)` a division by zero and the "
                  "destination draw non-terminating (cpu.cc)",
    },
    "search/36_search_check_if_array_contains_value": {
        "min_size": 1,
        "reason": "size 0 evaluates input[rand() % input.size()] on an empty "
                  "vector: modulo by zero plus an out-of-bounds read (cpu.cc)",
    },
    "search/37_search_find_the_closest_number_to_pi": {
        "min_size": 1,
        "reason": "size 0 runs `rand() % TEST_SIZE` (modulo by zero) and the "
                  "frozen oracle dereferences x[0] before any size check "
                  "(cpu.cc, baseline.hpp)",
    },
    "search/39_search_xor_contains": {
        "min_size": 1,
        "reason": "size 0 evaluates x[rand() % x.size()] and y[rand() % y.size()] "
                  "on empty vectors: modulo by zero plus out-of-bounds reads "
                  "(cpu.cc)",
    },
    "fft/05_fft_inverse_fft": {
        "size_predicate": "power_of_two_or_below_two",
        "reason": "the iterative Rosetta fft() oracle computes the butterfly "
                  "partner as b = a + k without bounding b by N, so any N >= 3 "
                  "that is not a power of two reads and writes past the end "
                  "(heap out-of-bounds, baseline.hpp). The frozen prompt states "
                  "the size is always a power of two.",
    },
    "fft/07_fft_fft_conjugate": {
        "size_predicate": "power_of_two_or_below_two",
        "reason": "the recursive oracle floor-halves N at every level, so for a "
                  "non-power-of-two size it silently computes something that is "
                  "not the transform and grades correct candidates against a "
                  "wrong reference. The frozen prompt states the size is always "
                  "a power of two.",
    },
    "fft/08_fft_split_fft": {
        "size_predicate": "power_of_two_or_below_two",
        "reason": "same floor-halving oracle as fft/07; the frozen prompt states "
                  "the length of x is a power of two",
    },
    "fft/09_fft_fft_out_of_place": {
        "size_predicate": "power_of_two_or_below_two",
        "reason": "same floor-halving oracle as fft/07; the frozen prompt states "
                  "the size of x is always a power of two",
    },
}


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def derive(catalog):
    offered = list(catalog["_meta"]["pipeline_findings"].get("offered_patterns_note", []))
    benchmarks = OrderedDict()

    for bench in catalog["benchmarks"]:
        name = bench["benchmark"]
        audit = bench.get("pattern_audit") or {}
        effect = bench.get("pattern_effect")

        supported = []
        unsupported = OrderedDict()
        deferred = OrderedDict()

        no_effect = effect in ("NONE", "NOT_APPLICABLE")

        for pattern, entry in audit.items():
            # R1
            if no_effect and pattern != CANONICAL_PATTERN:
                unsupported[pattern] = "no_pattern_effect"
                continue
            # R2
            if entry.get("oracle_execution_safe") is False:
                unsupported[pattern] = "unsafe_pattern_for_benchmark"
                continue
            # R3
            if entry.get("fill_type_safe") is False:
                deferred[pattern] = "extreme_semantics_deferred"
                continue
            # R4
            if entry.get("verdict_outcome_class") == "FALSE_FAIL_RISK":
                deferred[pattern] = "false_fail_risk_deferred"
                continue
            supported.append(pattern)

        # explicit_values additionally needs the shape gate that already exists
        # in validate_spec; keep it out of `supported` where the shape data says
        # the benchmark has no single canonical fill site.
        if not bench.get("explicit_values_supported_currently", False):
            if "explicit_values" in supported:
                supported.remove("explicit_values")
                unsupported["explicit_values"] = "no_single_canonical_fill_site"

        # R4b: representable range of the benchmark's fill containers. Only
        # recorded where it actually constrains anything (int/float elements).
        bounds = None
        for site in bench.get("fill_sites") or []:
            vtype = (site.get("container_value_type") or "").strip().lower()
            site_bounds = None
            if vtype.startswith("int") and "int" in vtype:
                site_bounds = (-2147483648.0, 2147483647.0)
            elif vtype.startswith("float"):
                site_bounds = (-3.4028234663852886e38, 3.4028234663852886e38)
            if site_bounds is not None:
                bounds = site_bounds if bounds is None else (
                    max(bounds[0], site_bounds[0]), min(bounds[1], site_bounds[1]))

        entry = OrderedDict()
        entry["pattern_effect"] = effect
        if bounds is not None:
            entry["explicit_values_bounds"] = OrderedDict([
                ("min", bounds[0]), ("max", bounds[1]),
                ("reason", "the benchmark's ENHANCED_FILL container cannot "
                           "represent values outside this range; converting one "
                           "would be undefined behaviour, and clipping would be a "
                           "VALUE_RANGE_DOMAIN_POLICY decision (still open), so "
                           "such a spec is rejected"),
            ])
        entry["supported_patterns"] = sorted(supported)
        entry["unsupported_patterns"] = OrderedDict(sorted(unsupported.items()))
        entry["deferred_policy_patterns"] = OrderedDict(sorted(deferred.items()))
        if name in SIZE_CONSTRAINTS:
            entry["size_constraint"] = OrderedDict(sorted(SIZE_CONSTRAINTS[name].items()))
        if effect == "PARTIAL":
            entry["pattern_coverage"] = "partial"
            entry["pattern_coverage_note"] = (
                "some validate() inputs are built outside the ENHANCED_FILL axis, "
                "so a pattern does NOT cover the full input; the patterns that do "
                "apply stay supported (E1 pattern_rationale)")
        benchmarks[name] = entry

    doc = OrderedDict()
    doc["status"] = "ENFORCED"
    doc["_meta"] = OrderedDict([
        ("generated_by", "thesis/enhanced_tests/derive_enhanced_policy.py (E2-A)"),
        ("derived_from", "thesis/enhanced_tests/enhanced_capabilities.json"),
        ("derived_from_audit_commit", catalog["_meta"].get("normalized_at_commit")),
        ("relationship_to_audit", (
            "The capability CATALOG is audit metadata and stays "
            "AUDIT_ONLY_NOT_ENFORCED. THIS file is the productive policy that "
            "validation, LLM spec generation and mutation all enforce through "
            "thesis/enhanced_tests/capabilities.py. Only unambiguous, "
            "policy-independent, source-backed audit findings become policy; "
            "everything else is carried as deferred_policy.")),
        ("rules", OrderedDict([
            ("R1", "pattern_effect NONE/NOT_APPLICABLE -> only 'random' supported (no_pattern_effect)"),
            ("R2", "oracle_execution_safe == false -> unsupported (unsafe_pattern_for_benchmark)"),
            ("R3", "fill_type_safe == false in the audit -> deferred (extreme_semantics_deferred); E2-A fixed the conversion, the domain question is EXTREME_PATTERN_SEMANTICS"),
            ("R4", "verdict_outcome_class == FALSE_FAIL_RISK -> deferred (false_fail_risk_deferred)"),
            ("R4b", "explicit_values values outside the fill container's representable range are REJECTED, never clipped"),
            ("R5", "benchmark-specific size constraints for technically unambiguous size hazards; NOT a global size-0 rule"),
        ])),
        ("open_policies_not_decided_here", [
            "EXTREME_PATTERN_SEMANTICS", "VALUE_RANGE_DOMAIN_POLICY",
            "SIZE_ZERO_SPEC_POLICY", "TOLERANCE_POLICY",
            "GRAPH_ADAPTER_VOCABULARY", "SPARSE_ADAPTER_POLICY",
            "SORT44_ADAPTER_POLICY", "LARGE_SIZE_POLICY",
        ]),
        ("canonical_pattern_for_no_effect_benchmarks", CANONICAL_PATTERN),
    ])
    doc["benchmarks"] = benchmarks
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed policy matches the catalog; write nothing")
    args = ap.parse_args()

    derived = derive(load_catalog())

    if args.check:
        if not POLICY.is_file():
            print("MISSING: %s" % POLICY)
            return 1
        current = json.loads(POLICY.read_text(encoding="utf-8"))
        if current == json.loads(json.dumps(derived)):
            print("CHECK: enhanced_policy.json matches the derivation.")
            return 0
        print("CHECK FAILED: enhanced_policy.json differs from the derivation.")
        cur_b = current.get("benchmarks", {})
        new_b = derived["benchmarks"]
        for name in sorted(set(cur_b) | set(new_b)):
            if cur_b.get(name) != new_b.get(name):
                print("  differs: %s" % name)
        return 1

    POLICY.write_text(
        json.dumps(derived, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_sup = sum(len(v["supported_patterns"]) for v in derived["benchmarks"].values())
    n_uns = sum(len(v["unsupported_patterns"]) for v in derived["benchmarks"].values())
    n_def = sum(len(v["deferred_policy_patterns"]) for v in derived["benchmarks"].values())
    print("wrote %s" % POLICY)
    print("benchmarks: %d | supported %d | unsupported %d | deferred %d"
          % (len(derived["benchmarks"]), n_sup, n_uns, n_def))
    return 0


if __name__ == "__main__":
    sys.exit(main())
