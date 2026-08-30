#!/usr/bin/env python3
"""Derive the PRODUCTIVE enhanced capability policy from the E1 audit catalog.

    thesis/enhanced_tests/enhanced_capabilities.json   (AUDIT metadata)
        --[ the explicit rules below ]-->
    thesis/enhanced_tests/enhanced_policy.json         (ENFORCED policy)

The catalog is an audit document and stays AUDIT_ONLY_NOT_ENFORCED. Only the
findings that are UNAMBIGUOUS, POLICY-INDEPENDENT and SOURCE-BACKED become
enforced policy; everything whose resolution needs one of the open E2-B
policies is carried over as `deferred_policy` and is NOT silently supported.

Derivation rules (E2-A, extended by E2-A.1):

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

  R4b explicit_values / value_range technical representability  (E2-A.1)
      `fill_type_capability` is derived from the ONE normalized type source
      `fill_sites[].container_value_type_normalized`. It carries the technical
      bounds of the benchmark's fill containers and the largest span the
      current fill arithmetic can compute in them. validate_spec REJECTS a
      spec whose explicit values or value_range fall outside them instead of
      clipping: an out-of-range floating->integral (or double->float)
      conversion is undefined behaviour, and clipping would be a
      VALUE_RANGE_DOMAIN_POLICY decision, which stays open.
      This is a TECHNICAL REPRESENTABILITY statement only ("can the harness
      hold this value / compute this span in this container?"), never a
      statement about which values are semantically meaningful for the task.

  R5  benchmark-specific size safety  (E2-A.1: single source)
      taken VERBATIM from the catalog's normalized `enforced_size_safety`
      block. Before E2-A.1 the same nine rules also lived in a manual table in
      THIS file; that duplicate was removed so audit truth and productive size
      policy cannot drift apart. These are per-benchmark technical
      constraints, NOT a global size-0 rule: SIZE_ZERO_SPEC_POLICY stays open
      and every benchmark without an entry keeps accepting size 0.

Precedence: R2 (unsupported) wins over R3/R4 (deferred), which win over
supported. R1 applies to the whole benchmark.

Run with --check to verify the committed policy still matches the catalog.
`policy_matches_derivation()` is the same check as an importable function; it
is what the runtime preflight (capabilities.policy_preflight) calls, so there
is no subprocess duplicate of this logic.

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

# Bumped whenever the derivation RULES change, so a policy produced by an older
# derivation is detectable even if the catalog is unchanged.
DERIVATION_VERSION = "e2a1.1"

# Technical limits of the fill container element types the suite actually uses.
# (lowest, max, is_integral). This table describes the C++ TYPES, not any
# benchmark domain.
TYPE_LIMITS = OrderedDict([
    ("int", (-2147483648.0, 2147483647.0, True)),
    ("long", (-9223372036854775808.0, 9223372036854775807.0, True)),
    ("unsigned long", (0.0, 18446744073709551615.0, True)),
    ("size_t", (0.0, 18446744073709551615.0, True)),
    ("float", (-3.4028234663852886e38, 3.4028234663852886e38, False)),
    ("double", (-1.7976931348623157e308, 1.7976931348623157e308, False)),
    ("complex<double>", (-1.7976931348623157e308, 1.7976931348623157e308, False)),
])

FILL_TYPE_REASON = (
    "technical representability of the benchmark's ENHANCED_FILL containers "
    "(derived from fill_sites[].container_value_type_normalized). value_min / "
    "value_max bound the values the container can hold; max_finite_span bounds "
    "the span the current fill arithmetic can compute in it without signed "
    "overflow (integral: hi-lo and span+1 must both fit) or a non-finite "
    "intermediate (floating: hi-lo must stay finite). A spec outside these "
    "bounds is REJECTED, never clipped - clipping would decide "
    "VALUE_RANGE_DOMAIN_POLICY, which stays open. This says nothing about "
    "which values are semantically meaningful for the benchmark."
)

NO_HOOK_REASON = (
    "the benchmark has no reachable ENHANCED_FILL hook in validate(), so there "
    "is no container to represent a fill value in and every fill parameter is "
    "inert"
)


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _fill_type_capability(bench):
    """R4b: ONE technical type description per benchmark, from the ONE
    normalized type field in the catalog."""
    types = []
    for site in bench.get("fill_sites") or []:
        vtype = site.get("container_value_type_normalized")
        if vtype is None:
            raise ValueError(
                "%s: fill site is missing container_value_type_normalized - the "
                "catalog has not been normalized (E2-A.1)" % bench["benchmark"])
        if vtype not in TYPE_LIMITS:
            raise ValueError(
                "%s: unknown normalized fill type %r (known: %s)"
                % (bench["benchmark"], vtype, ", ".join(TYPE_LIMITS)))
        if vtype not in types:
            types.append(vtype)

    entry = OrderedDict()
    entry["element_types"] = sorted(types)

    if not types:
        entry["has_fill_hook"] = False
        entry["reason"] = NO_HOOK_REASON
        return entry

    entry["has_fill_hook"] = True
    value_min = max(TYPE_LIMITS[t][0] for t in types)
    value_max = min(TYPE_LIMITS[t][1] for t in types)
    spans = []
    all_integral = True
    for t in types:
        low, high, integral = TYPE_LIMITS[t]
        if integral:
            # hi - lo must fit in the type AND span + 1 must fit (the ramp uses
            # `position % (span + 1)`), so the largest admissible span is max-1.
            spans.append(high - 1.0)
        else:
            # hi - lo must stay finite in the type
            spans.append(high)
            all_integral = False
    entry["value_min"] = value_min
    entry["value_max"] = value_max
    entry["max_finite_span"] = min(spans)
    entry["all_integral"] = all_integral
    entry["reason"] = FILL_TYPE_REASON
    return entry


def derive(catalog):
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

        entry = OrderedDict()
        entry["pattern_effect"] = effect
        entry["fill_type_capability"] = _fill_type_capability(bench)
        entry["supported_patterns"] = sorted(supported)
        entry["unsupported_patterns"] = OrderedDict(sorted(unsupported.items()))
        entry["deferred_policy_patterns"] = OrderedDict(sorted(deferred.items()))

        # R5: verbatim from the catalog's normalized block - no second table
        size_safety = bench.get("enforced_size_safety")
        if size_safety:
            entry["size_constraint"] = OrderedDict(sorted(size_safety.items()))

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
        ("generated_by", "thesis/enhanced_tests/derive_enhanced_policy.py (E2-A, E2-A.1)"),
        ("derivation_version", DERIVATION_VERSION),
        ("derived_from", "thesis/enhanced_tests/enhanced_capabilities.json"),
        ("derived_from_audit_commit", catalog["_meta"].get("normalized_at_commit")),
        ("relationship_to_audit", (
            "The capability CATALOG is audit metadata and stays "
            "AUDIT_ONLY_NOT_ENFORCED. THIS file is the productive policy that "
            "validation, LLM spec generation and mutation all enforce through "
            "thesis/enhanced_tests/capabilities.py. Only unambiguous, "
            "policy-independent, source-backed audit findings become policy; "
            "everything else is carried as deferred_policy.")),
        ("single_source_of_truth", OrderedDict([
            ("size_safety", "benchmarks[].enforced_size_safety in the catalog "
                            "(E2-A.1 removed the duplicate manual table in "
                            "derive_enhanced_policy.py)"),
            ("fill_types", "benchmarks[].fill_sites[].container_value_type_normalized "
                           "in the catalog; both explicit_values and value_range "
                           "validation read the derived fill_type_capability"),
        ])),
        ("rules", OrderedDict([
            ("R1", "pattern_effect NONE/NOT_APPLICABLE -> only 'random' supported (no_pattern_effect)"),
            ("R2", "oracle_execution_safe == false -> unsupported (unsafe_pattern_for_benchmark)"),
            ("R3", "fill_type_safe == false in the audit -> deferred (extreme_semantics_deferred); E2-A fixed the conversion, the domain question is EXTREME_PATTERN_SEMANTICS"),
            ("R4", "verdict_outcome_class == FALSE_FAIL_RISK -> deferred (false_fail_risk_deferred)"),
            ("R4b", "fill_type_capability: explicit values and value_range endpoints/spans outside the fill containers' TECHNICAL representability are REJECTED, never clipped"),
            ("R5", "benchmark-specific size constraints verbatim from the catalog's enforced_size_safety; NOT a global size-0 rule"),
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


def derived_document():
    """The policy the current catalog implies, as plain JSON-comparable data."""
    return json.loads(json.dumps(derive(load_catalog())))


def policy_matches_derivation():
    """(matches, differing_benchmark_names_or_reason).

    The importable twin of --check: the runtime preflight calls THIS, so the
    exactness rule exists exactly once.
    """
    if not POLICY.is_file():
        return False, ["<missing enhanced_policy.json>"]
    try:
        current = json.loads(POLICY.read_text(encoding="utf-8"))
    except ValueError as error:
        return False, ["<enhanced_policy.json is not valid JSON: %s>" % error]
    derived = derived_document()
    if current == derived:
        return True, []
    cur_b = current.get("benchmarks") or {}
    new_b = derived["benchmarks"]
    differing = [n for n in sorted(set(cur_b) | set(new_b))
                 if cur_b.get(n) != new_b.get(n)]
    if not differing:
        differing = ["<metadata/header differs; benchmark entries are equal>"]
    return False, differing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed policy matches the catalog; write nothing")
    args = ap.parse_args()

    if args.check:
        matches, differing = policy_matches_derivation()
        if matches:
            print("CHECK: enhanced_policy.json matches the derivation.")
            return 0
        print("CHECK FAILED: enhanced_policy.json differs from the derivation.")
        for name in differing:
            print("  differs: %s" % name)
        return 1

    derived = derive(load_catalog())
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
