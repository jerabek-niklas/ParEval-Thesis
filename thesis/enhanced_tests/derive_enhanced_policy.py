#!/usr/bin/env python3
"""Derive the PRODUCTIVE enhanced capability policy from the E1 audit catalog.

    thesis/enhanced_tests/enhanced_capabilities.json   (AUDIT metadata)
        --[ the explicit rules below ]-->
    thesis/enhanced_tests/enhanced_policy.json         (ENFORCED policy)

The catalog is an audit document and stays AUDIT_ONLY_NOT_ENFORCED. Only the
findings that are UNAMBIGUOUS, POLICY-INDEPENDENT and SOURCE-BACKED become
enforced policy. Before E2-B, everything whose resolution needed one of the
then-open E2-B policies was carried over as `deferred_policy`; E2-B froze all
eight of them, so no case is deferred any more (see R6-R10 and
`_meta.frozen_e2b_policies`).

Derivation rules (E2-A, extended by E2-A.1 and E2-B):

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

  R3  fill-layer UB in the E1 audit (now type-fixed); domain frozen by E2-B
      pattern with fill_type_safe == false in the catalog
      -> deferred_policy, reason `extreme_semantics_deferred`.
      Rationale: E2-A fixed the CONVERSION (the value type is now the
      container's element type), so the fill no longer executes UB. Whether
      element-type extrema are an admissible INPUT for that benchmark was
      EXTREME_PATTERN_SEMANTICS, which E2-B froze as
      DECLARED_FILL_DOMAIN_EXTREMA. R3 is therefore superseded for every
      case the catalog re-evaluates (see the precedence note below); it is
      kept as the rule that governed the pre-E2-B findings.

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
      VALUE_RANGE_DOMAIN_POLICY decision. E2-B froze that policy as
      SUBSET_OF_DECLARED_BENCHMARK_FILL_DOMAIN (R6); this rule remains the
      TECHNICAL half and is enforced in addition to it.
      This is a TECHNICAL REPRESENTABILITY statement only ("can the harness
      hold this value / compute this span in this container?"), never a
      statement about which values are semantically meaningful for the task.

  R5  benchmark-specific size safety  (E2-A.1: single source)
      taken VERBATIM from the catalog's normalized `enforced_size_safety`
      block. Before E2-A.1 the same nine rules also lived in a manual table in
      THIS file; that duplicate was removed so audit truth and productive size
      policy cannot drift apart. These are per-benchmark technical
      constraints, NOT a global size-0 rule. E2-B froze SIZE_ZERO_SPEC_POLICY
      as BENCHMARK_SEMANTICS_DEPENDENT and R7 merges its per-benchmark
      decision into this constraint; there is still no global size-0 rule.

  R6  declared fill domain  (E2-B)
      `fill_domain_capability` is derived from the ONE domain source
      `fill_sites[].declared_fill_domain`. It carries each site's legitimate
      fill range and, when ALL pattern-relevant sites declare the SAME domain,
      the benchmark's global allowed value_range. Where the sites disagree
      (sort/43: startTime / duration / value) a single global value_range has
      no unambiguous meaning, so `global_value_range_supported` is false and
      validate_spec rejects any value_range for that benchmark rather than
      inventing a common domain.
      This is the DOMAIN question ("is this a legitimate benchmark input?"),
      strictly separate from E2-A.1's `fill_type_capability`, which answers the
      TECHNICAL question ("can the container hold it and can the arithmetic
      compute with it"). Both must hold.

  R7  benchmark-specific size-zero policy  (E2-B)
      taken VERBATIM from the catalog's `e2b_size_zero`. DISALLOWED is
      materialized as a benchmark-local `min_size >= 1`, merged with the
      technical `enforced_size_safety` minimum (the larger wins) so the two
      reasons stay distinguishable. NOT a global rule: 44 benchmarks keep
      accepting size 0.

  R8  extreme_values collapses into alternating  (E2-B)
      Under R6 `extreme_values` alternates between the effective domain
      endpoints - which is exactly what `alternating` already does
      (enhanced-fill.hpp case 5). Two labels for a byte-identical input is the
      fake-diversity defect E2-A froze out, so `extreme_values` is unsupported
      on every benchmark with reason
      `duplicate_of_alternating_under_domain_extrema`. The harness keeps
      implementing the domain semantics so define/runtime parity and historical
      reproducibility stay provable.

  R9  all_zeros outside the declared domain  (E2-B)
      `all_zeros` writes the constant 0 regardless of lo/hi. Where 0 lies
      outside a site's declared domain the pattern would construct an
      out-of-domain input, so it is unsupported for that benchmark.

  R10 patterns that reach a call-site hi above the declared domain  (E2-B)
      Where the frozen prompt declares a NARROWER domain than the call site
      (stencil/54: cells are 0 or 1, the call site says [0,2]), the patterns
      whose construction reaches the call-site `hi` - alternating, ascending,
      descending, sorted_except_one, spike_at - would produce an undefined
      value and are unsupported for that benchmark.

Precedence: R2 (unsupported) wins over R3/R4 (deferred), which win over
supported. R1 applies to the whole benchmark. R2/R3/R4 are SUPERSEDED for any
pattern case the catalog re-evaluates under E2-B (`e2b_reevaluation`): the
finding was made under the pre-E2-B out-of-domain semantics and no longer
describes the enforced input. R8/R9/R10 then decide those cases on their own
terms, so a case re-evaluated as NO_LONGER_REACHABLE really does end up
unsupported.

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
DERIVATION_VERSION = "e2b.1"

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
    "bounds is REJECTED, never clipped. This is the TECHNICAL bound only; the "
    "separate question whether a value is a legitimate benchmark input is "
    "answered by fill_domain_capability, which E2-B froze as "
    "VALUE_RANGE_DOMAIN_POLICY = SUBSET_OF_DECLARED_BENCHMARK_FILL_DOMAIN. "
    "Both bounds are enforced; neither replaces the other."
)

# R8/R9/R10 vocabulary
REASON_EXTREME_DUPLICATE = "duplicate_of_alternating_under_domain_extrema"
REASON_CONSTANT_OUT_OF_DOMAIN = "constant_outside_declared_fill_domain"
REASON_REACHES_OUT_OF_DOMAIN_HI = "reaches_value_outside_declared_fill_domain"

# R10: the patterns whose construction assigns the effective `hi` itself
PATTERNS_REACHING_HI = ("alternating", "ascending", "descending",
                        "sorted_except_one", "spike_at")

# E2-B re-evaluation verdicts that SUPERSEDE an E2-A R2/R3/R4 finding
E2B_SUPERSEDING_STATUSES = ("RESOLVED_BY_DOMAIN_POLICY",
                            "RESOLVED_BY_FROZEN_PROMPT",
                            "NO_LONGER_REACHABLE")

DOMAIN_REASON_GLOBAL = (
    "every pattern-relevant fill site of this benchmark declares the SAME "
    "legitimate domain, so a single global value_range has an unambiguous "
    "meaning and is allowed as a SUBSET of it. Endpoints outside it are "
    "rejected, never clipped: clipping would be a different policy than the "
    "one E2-B froze."
)
DOMAIN_REASON_SPLIT = (
    "the fill sites of this benchmark declare DIFFERENT legitimate domains for "
    "semantically different inputs, so one global value_range would have no "
    "unambiguous meaning. E2-B refuses to invent a common domain: value_range "
    "is not supported for this benchmark. Pattern and size variation are "
    "unaffected."
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


def _fill_domain_capability(bench):
    """R6: ONE semantic domain description per benchmark, from the ONE domain
    field in the catalog."""
    sites = bench.get("fill_sites") or []
    entry = OrderedDict()

    if not sites:
        entry["has_fill_hook"] = False
        entry["global_value_range_supported"] = False
        entry["site_domains"] = []
        entry["reason"] = NO_HOOK_REASON
        return entry

    site_domains = []
    for site in sites:
        declared = site.get("declared_fill_domain")
        if declared is None:
            raise ValueError(
                "%s: fill site %s is missing declared_fill_domain - the catalog "
                "has not been normalized (E2-B)"
                % (bench["benchmark"], site.get("line")))
        site_domains.append(OrderedDict([
            ("line", site.get("line")),
            ("container_expr", site.get("container_expr")),
            ("element_type", site.get("container_value_type_normalized")),
            ("semantic_role", declared.get("semantic_role")),
            ("lo", float(declared["lo"])),
            ("hi", float(declared["hi"])),
            ("call_site_lo", float(declared["call_site_lo"])),
            ("call_site_hi", float(declared["call_site_hi"])),
            ("narrower_than_call_site", bool(declared.get("narrower_than_call_site"))),
            ("evidence", declared.get("evidence")),
        ]))

    entry["has_fill_hook"] = True
    entry["site_domains"] = site_domains

    distinct = {(d["lo"], d["hi"]) for d in site_domains}
    if len(distinct) == 1:
        lo, hi = next(iter(distinct))
        entry["global_value_range_supported"] = True
        entry["domain_lo"] = lo
        entry["domain_hi"] = hi
        entry["reason"] = DOMAIN_REASON_GLOBAL
    else:
        entry["global_value_range_supported"] = False
        entry["reason"] = DOMAIN_REASON_SPLIT

    entry["zero_in_every_site_domain"] = all(
        d["lo"] <= 0.0 <= d["hi"] for d in site_domains)
    entry["any_site_narrower_than_call_site"] = any(
        d["narrower_than_call_site"] for d in site_domains)
    return entry


def _size_constraint(bench):
    """R5 + R7: the technical minimum and the semantic size-zero decision,
    merged into ONE enforced constraint whose two provenances stay visible."""
    technical = bench.get("enforced_size_safety") or {}
    size_zero = bench.get("e2b_size_zero") or {}
    if not size_zero:
        raise ValueError("%s: missing e2b_size_zero (E2-B)" % bench["benchmark"])

    entry = OrderedDict()
    tech_min = technical.get("min_size")
    semantic_min = 1 if size_zero.get("policy") == "DISALLOWED" else None

    effective = None
    for candidate in (tech_min, semantic_min):
        if candidate is not None:
            effective = candidate if effective is None else max(effective, candidate)
    if effective is not None:
        entry["min_size"] = int(effective)
    if technical.get("size_predicate"):
        entry["size_predicate"] = technical["size_predicate"]
    if not entry:
        return None

    reasons = []
    if tech_min is not None or technical.get("size_predicate"):
        reasons.append("technical (E2-A): %s" % technical.get("reason", ""))
    if semantic_min is not None:
        reasons.append("size-zero policy (E2-B): %s" % size_zero.get("reason", ""))
    entry["reason"] = " || ".join(reasons)
    entry["technical_min_size"] = tech_min
    entry["size_zero_policy"] = size_zero.get("policy")
    entry["evidence"] = " || ".join(
        [t for t in (technical.get("evidence"), size_zero.get("evidence")) if t])
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

        domain = _fill_domain_capability(bench)

        for pattern, entry in audit.items():
            # R1
            if no_effect and pattern != CANONICAL_PATTERN:
                unsupported[pattern] = "no_pattern_effect"
                continue

            # R8: extreme_values is now byte-identical to alternating
            if pattern == "extreme_values":
                unsupported[pattern] = REASON_EXTREME_DUPLICATE
                continue

            # R9: all_zeros writes 0 regardless of lo/hi
            if pattern == "all_zeros" and domain["has_fill_hook"] and not domain[
                    "zero_in_every_site_domain"]:
                unsupported[pattern] = REASON_CONSTANT_OUT_OF_DOMAIN
                continue

            # R10: constructions that assign the call-site hi itself
            if (pattern in PATTERNS_REACHING_HI and domain["has_fill_hook"]
                    and domain["any_site_narrower_than_call_site"]):
                unsupported[pattern] = REASON_REACHES_OUT_OF_DOMAIN_HI
                continue

            # E2-B supersession: an E2-A finding made under the pre-E2-B
            # out-of-domain semantics no longer describes the enforced input
            reevaluated = (entry.get("e2b_reevaluation") or {}).get("status")
            if reevaluated in E2B_SUPERSEDING_STATUSES:
                supported.append(pattern)
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
        entry["fill_domain_capability"] = domain
        entry["size_zero_policy"] = OrderedDict(
            sorted((bench.get("e2b_size_zero") or {}).items()))
        adapter = bench.get("e2b_adapter_policy")
        if adapter:
            entry["adapter_policy"] = OrderedDict(sorted(adapter.items()))
        entry["supported_patterns"] = sorted(supported)
        entry["unsupported_patterns"] = OrderedDict(sorted(unsupported.items()))
        entry["deferred_policy_patterns"] = OrderedDict(sorted(deferred.items()))

        # R5 + R7: technical minimum and size-zero decision, one merged
        # constraint derived from the catalog - no second table
        constraint = _size_constraint(bench)
        if constraint:
            entry["size_constraint"] = constraint

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
        ("generated_by", "thesis/enhanced_tests/derive_enhanced_policy.py (E2-A, E2-A.1, E2-B)"),
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
            ("fill_domains", "benchmarks[].fill_sites[].declared_fill_domain in the "
                             "catalog; both explicit_values and value_range domain "
                             "validation read the derived fill_domain_capability"),
            ("size_zero", "benchmarks[].e2b_size_zero in the catalog; merged with "
                          "enforced_size_safety into the single enforced "
                          "size_constraint"),
        ])),
        ("rules", OrderedDict([
            ("R1", "pattern_effect NONE/NOT_APPLICABLE -> only 'random' supported (no_pattern_effect)"),
            ("R2", "oracle_execution_safe == false -> unsupported (unsafe_pattern_for_benchmark)"),
            ("R3", "fill_type_safe == false in the audit -> deferred (extreme_semantics_deferred); E2-A fixed the conversion, the domain question is EXTREME_PATTERN_SEMANTICS"),
            ("R4", "verdict_outcome_class == FALSE_FAIL_RISK -> deferred (false_fail_risk_deferred)"),
            ("R4b", "fill_type_capability: explicit values and value_range endpoints/spans outside the fill containers' TECHNICAL representability are REJECTED, never clipped"),
            ("R5", "benchmark-specific size constraints verbatim from the catalog's enforced_size_safety; NOT a global size-0 rule"),
            ("R6", "fill_domain_capability: a value_range must be a SUBSET of the declared fill domain; benchmarks whose sites declare different domains support no global value_range"),
            ("R7", "the catalog's per-benchmark e2b_size_zero decision, materialized as a benchmark-local min_size >= 1 where DISALLOWED"),
            ("R8", "extreme_values is byte-identical to alternating under domain extrema -> unsupported everywhere (duplicate_of_alternating_under_domain_extrema)"),
            ("R9", "all_zeros writes the constant 0 -> unsupported where 0 is outside a site's declared domain"),
            ("R10", "alternating/ascending/descending/sorted_except_one/spike_at assign the call-site hi -> unsupported where the declared domain is narrower than the call site"),
        ])),
        ("frozen_e2b_policies", OrderedDict([
            ("EXTREME_PATTERN_SEMANTICS", "DECLARED_FILL_DOMAIN_EXTREMA"),
            ("SPIKE_AT_SEMANTICS", "DECLARED_DOMAIN_UPPER_EXTREME"),
            ("VALUE_RANGE_DOMAIN_POLICY", "SUBSET_OF_DECLARED_BENCHMARK_FILL_DOMAIN"),
            ("SIZE_ZERO_SPEC_POLICY", "BENCHMARK_SEMANTICS_DEPENDENT"),
            ("TOLERANCE_POLICY", "KEEP_FROZEN_COMPARATOR_AND_CONSTRAIN_ENHANCED_INPUTS"),
            ("GRAPH_ADAPTER_VOCABULARY", "NO_NEW_ADAPTER_FOR_PILOT_002"),
            ("SPARSE_ADAPTER_POLICY", "NO_NEW_ADAPTER_FOR_PILOT_002"),
            ("SORT44_ADAPTER_POLICY", "NO_NEW_ADAPTER_FOR_PILOT_002"),
            ("LARGE_SIZE_POLICY", "KEEP_MAX_SPEC_SIZE_4096_FOR_PILOT_002"),
        ])),
        ("open_policies_not_decided_here", []),
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
