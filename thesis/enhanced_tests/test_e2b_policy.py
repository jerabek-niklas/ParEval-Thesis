#!/usr/bin/env python3
"""E2-B tests: declared-domain enforcement, size-zero policy, extreme/spike
semantics, resolved false-fail reachability, adapter decisions and the policy
freeze itself.

E2-A/E2-A.1 made the enhanced inputs technically safe. E2-B decides whether
they are legitimate BENCHMARK inputs: enhanced tests exist to probe model
behaviour on unusual but semantically valid inputs, not to probe whether the
harness survives C++ numeric_limits.

Run:  python thesis/enhanced_tests/test_e2b_policy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests import generate_test_specs as gen  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    DEFAULT_SETTINGS,
    PATTERNS,
    _mutants_of,
    build_benchmark_specs,
    validate_spec,
)

FAILURES = []

# domain [-1,1]; the contract's worked example
DOMAIN_PM1 = "fft/05_fft_inverse_fft"
DOMAIN_0_100 = "reduce/28_reduce_smallest_odd_number"      # int, [0,100]
DOMAIN_M10_10 = "dense_la/00_dense_la_lu_decomp"           # double, [-10,10]
MULTI_SAME = "dense_la/03_dense_la_axpy"                   # 2 sites, both [-1,1]
MULTI_SPLIT = "sort/43_sort_sort_an_array_of_structs_by_key"  # 3 different domains
NARROWED = "stencil/54_stencil_game_of_life"               # declared [0,1] < call site [0,2]
NO_HOOK = "graph/15_graph_edge_count"
SIZE0_ALLOWED = "reduce/28_reduce_smallest_odd_number"
SIZE0_DISALLOWED = "reduce/27_reduce_average"
SIZE_MIN2 = "graph/19_graph_shortest_path"
SIZE_POW2 = "fft/05_fft_inverse_fft"


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


def spec(benchmark, pattern="random", size=8, params=None, **extra):
    out = {
        "benchmark": benchmark,
        "size": size,
        "pattern": pattern,
        "pattern_params": dict(params or {}),
        "source": "llm",
        "rationale": "e2b test",
    }
    out.update(extra)
    return out


def accepted(spec_dict):
    ok, why = validate_spec(spec_dict, {spec_dict["benchmark"]})
    return ok, why


def rejected(spec_dict):
    ok, why = validate_spec(spec_dict, {spec_dict["benchmark"]})
    return (not ok), why


# ---------------------------------------------------------------------------
# 1. the eight policies are frozen
# ---------------------------------------------------------------------------

def group_policy_freeze():
    print("the eight E2-B policies are frozen")
    policy = capabilities.load_policy()
    frozen = (policy.get("_meta") or {}).get("frozen_e2b_policies") or {}
    expected = {
        "EXTREME_PATTERN_SEMANTICS": "DECLARED_FILL_DOMAIN_EXTREMA",
        "SPIKE_AT_SEMANTICS": "DECLARED_DOMAIN_UPPER_EXTREME",
        "VALUE_RANGE_DOMAIN_POLICY": "SUBSET_OF_DECLARED_BENCHMARK_FILL_DOMAIN",
        "SIZE_ZERO_SPEC_POLICY": "BENCHMARK_SEMANTICS_DEPENDENT",
        "TOLERANCE_POLICY": "KEEP_FROZEN_COMPARATOR_AND_CONSTRAIN_ENHANCED_INPUTS",
        "GRAPH_ADAPTER_VOCABULARY": "NO_NEW_ADAPTER_FOR_PILOT_002",
        "SPARSE_ADAPTER_POLICY": "NO_NEW_ADAPTER_FOR_PILOT_002",
        "SORT44_ADAPTER_POLICY": "NO_NEW_ADAPTER_FOR_PILOT_002",
        "LARGE_SIZE_POLICY": "KEEP_MAX_SPEC_SIZE_4096_FOR_PILOT_002",
    }
    for name, value in expected.items():
        check("%s = %s" % (name, value), frozen.get(name) == value,
              str(frozen.get(name)))
    check("no policy is left open",
          (policy.get("_meta") or {}).get("open_policies_not_decided_here") == [])

    summary = capabilities.policy_summary()
    check("no pattern case is left deferred",
          summary["deferred_policy_pattern_cases"] == 0)
    check("no active oracle-unsafe pattern remains",
          summary["reason_distribution"].get("unsafe_pattern_for_benchmark", 0) == 0)
    check("every benchmark has a decided size-zero policy",
          len(summary["size_zero_allowed"]) + len(summary["size_zero_disallowed"])
          + len(summary["size_zero_not_applicable"]) == 60)


# ---------------------------------------------------------------------------
# 2. declared-domain enforcement
# ---------------------------------------------------------------------------

def group_declared_domain():
    print("value_range must be a subset of the declared fill domain")

    check("the worked-example benchmark declares [-1, 1]",
          capabilities.declared_domain(DOMAIN_PM1) == (-1.0, 1.0),
          str(capabilities.declared_domain(DOMAIN_PM1)))

    ok, why = accepted(spec(DOMAIN_PM1, "ascending", params={"value_range": [-1.0, 1.0]}))
    check("[-1,1] accepted", ok, why)
    ok, why = accepted(spec(DOMAIN_PM1, "ascending", params={"value_range": [-0.5, 0.5]}))
    check("[-0.5,0.5] accepted", ok, why)
    for bounds in ([-2.0, 1.0], [-1.0, 2.0], [-2.0, 2.0]):
        bad, why = rejected(spec(DOMAIN_PM1, "ascending", params={"value_range": bounds}))
        check("%s rejected" % bounds,
              bad and capabilities.REASON_RANGE_OUTSIDE_DOMAIN in why, why)

    # multi-fill benchmark whose sites agree: one common domain
    check("a multi-site benchmark with identical site domains keeps a global range",
          capabilities.global_value_range_supported(MULTI_SAME))
    ok, why = accepted(spec(MULTI_SAME, "ascending", params={"value_range": [-1.0, 1.0]}))
    check("multi-site common domain accepted", ok, why)
    bad, why = rejected(spec(MULTI_SAME, "ascending", params={"value_range": [-3.0, 3.0]}))
    check("multi-site out-of-domain rejected",
          bad and capabilities.REASON_RANGE_OUTSIDE_DOMAIN in why, why)

    # multi-fill benchmark whose sites disagree: NO global range at all
    check("a benchmark with different site domains supports no global range",
          not capabilities.global_value_range_supported(MULTI_SPLIT))
    for bounds in ([0.0, 1.0], [-1.0, 1.0], [1.0, 10.0]):
        bad, why = rejected(spec(MULTI_SPLIT, "ascending", params={"value_range": bounds}))
        check("split-domain benchmark rejects %s" % bounds,
              bad and capabilities.REASON_RANGE_UNSUPPORTED in why, why)
    ok, why = accepted(spec(MULTI_SPLIT, "ascending"))
    check("split-domain benchmark still accepts a spec without a range", ok, why)

    # nothing is clipped
    offending = spec(DOMAIN_PM1, "ascending", params={"value_range": [-5.0, 5.0]})
    before = list(offending["pattern_params"]["value_range"])
    rejected(offending)
    check("an out-of-domain range is rejected, not clipped",
          offending["pattern_params"]["value_range"] == before)

    # explicit values are domain-bound too
    bad, why = rejected(spec("reduce/27_reduce_average", "explicit_values", size=3,
                             values=[1.0, 2.0, 500.0]))
    check("an explicit value outside the domain is rejected",
          bad and capabilities.REASON_VALUE_OUTSIDE_DOMAIN in why, why)
    ok, why = accepted(spec("reduce/27_reduce_average", "explicit_values", size=3,
                            values=[1.0, 2.0, 99.0]))
    check("explicit values inside the domain are accepted", ok, why)


# ---------------------------------------------------------------------------
# 3. extreme / spike semantics at the policy layer
# ---------------------------------------------------------------------------

def group_extreme_and_spike():
    print("extreme and spike semantics")

    leaked = [b for b in capabilities.policy_benchmarks()
              if "extreme_values" in capabilities.supported_patterns(b)]
    check("extreme_values is unsupported on every benchmark", not leaked,
          str(leaked[:3]))
    check("it is unsupported for the DUPLICATE reason, not a safety reason",
          all(capabilities.pattern_status(b, "extreme_values")[1]
              in ("duplicate_of_alternating_under_domain_extrema",
                  "no_pattern_effect")
              for b in capabilities.policy_benchmarks()))

    check("extreme_values now reads the value_range (domain endpoints)",
          capabilities.pattern_uses("extreme_values", "value_range"))
    check("spike_at reads the value_range and k",
          capabilities.pattern_uses("spike_at", "value_range")
          and capabilities.pattern_uses("spike_at", "k"))

    # spike stays available where it stays in domain
    ok, why = accepted(spec(DOMAIN_0_100, "spike_at", size=8, params={"k": 3}))
    check("spike_at still available on an in-domain benchmark", ok, why)

    # ... and is gone where the declared domain is narrower than the call site
    bad, why = rejected(spec(NARROWED, "spike_at", size=8, params={"k": 3}))
    check("spike_at unsupported where its value would leave the declared domain",
          bad and "reaches_value_outside_declared_fill_domain" in why, why)

    # all_zeros is out of domain where 0 is
    bad, why = rejected(spec("transform/56_transform_negate_odds", "all_zeros"))
    check("all_zeros unsupported where 0 is outside the declared domain",
          bad and "constant_outside_declared_fill_domain" in why, why)
    ok, why = accepted(spec(DOMAIN_0_100, "all_zeros"))
    check("all_zeros still available where 0 is inside the domain", ok, why)


# ---------------------------------------------------------------------------
# 4. size-zero policy
# ---------------------------------------------------------------------------

def group_size_zero():
    print("size-zero policy is per benchmark, never global")

    ok, why = accepted(spec(SIZE0_ALLOWED, "random", size=0))
    check("size 0 accepted where the frozen prompt defines the empty case",
          ok, why)
    check("...and that benchmark records ALLOWED",
          capabilities.size_zero_policy(SIZE0_ALLOWED)["policy"] == "ALLOWED")

    bad, why = rejected(spec(SIZE0_DISALLOWED, "random", size=0))
    check("size 0 rejected where the oracle yields no graded verdict",
          bad and capabilities.REASON_INVALID_SIZE in why, why)
    check("...and that benchmark records DISALLOWED",
          capabilities.size_zero_policy(SIZE0_DISALLOWED)["policy"] == "DISALLOWED")
    ok, why = accepted(spec(SIZE0_DISALLOWED, "random", size=1))
    check("size 1 is unaffected there", ok, why)

    # the pre-existing benchmark-local constraints are untouched and separate
    bad, _ = rejected(spec(SIZE_MIN2, "random", size=1))
    check("graph/19 keeps its technical min_size 2", bad)
    ok, _ = accepted(spec(SIZE_MIN2, "random", size=2))
    check("graph/19 accepts size 2", ok)
    bad, _ = rejected(spec(SIZE_POW2, "random", size=7))
    check("fft keeps its power-of-two predicate", bad)
    ok, _ = accepted(spec(SIZE_POW2, "random", size=8))
    check("fft accepts a power of two", ok)
    bad, why = rejected(spec(DOMAIN_0_100, "spike_at", size=1, params={"k": 0}))
    check("a k-pattern still needs size >= 2", bad and "size >= 2" in why, why)

    # no global rule: both answers occur
    summary = capabilities.policy_summary()
    check("size 0 is allowed for some and disallowed for others (no global rule)",
          len(summary["size_zero_allowed"]) > 0
          and len(summary["size_zero_disallowed"]) > 0)


# ---------------------------------------------------------------------------
# 5. previously-definitive false-fail cases are unreachable
# ---------------------------------------------------------------------------

# every pattern case E2-A recorded as unsafe or deferred, with the E2-B verdict
UNREACHABLE_AFTER_E2B = [
    ("search/37_search_find_the_closest_number_to_pi", "all_zeros"),
    ("stencil/54_stencil_game_of_life", "ascending"),
    ("stencil/54_stencil_game_of_life", "descending"),
    ("stencil/54_stencil_game_of_life", "sorted_except_one"),
    ("stencil/54_stencil_game_of_life", "spike_at"),
]


def group_false_fail_unreachable():
    print("resolved / excluded false-fail cases are unreachable everywhere")

    settings = dict(DEFAULT_SETTINGS)
    for benchmark, pattern in UNREACHABLE_AFTER_E2B:
        params = {"k": 1} if pattern in capabilities.K_PATTERNS else {}
        bad, why = rejected(spec(benchmark, pattern, size=8, params=params))
        check("validation rejects %s / %s" % (benchmark.split("_")[0], pattern),
              bad, why)
        check("the generator never offers %s / %s" % (benchmark.split("_")[0], pattern),
              pattern not in gen.effective_patterns_for(benchmark, settings))

    produced = []
    for benchmark, _pattern in UNREACHABLE_AFTER_E2B:
        produced.extend(build_benchmark_specs(
            benchmark, [], {"stages": {"enhanced_tests": {}}}))
    offenders = [s for s in produced
                 if (s["benchmark"], s["pattern"]) in set(UNREACHABLE_AFTER_E2B)]
    check("mutation never produces one either", not offenders, str(offenders[:2]))

    # the two audit risk flags, evaluated over the ACTIVE pattern set
    import json as _json
    catalog = _json.loads(
        (REPO_ROOT / "thesis" / "enhanced_tests" / "enhanced_capabilities.json")
        .read_text(encoding="utf-8"))
    resolved = ("RESOLVED_BY_DOMAIN_POLICY", "RESOLVED_BY_FROZEN_PROMPT",
                "NO_LONGER_REACHABLE")
    active_ffr, active_bias, unreviewed = [], [], []
    for bench in catalog["benchmarks"]:
        supported = set(capabilities.supported_patterns(bench["benchmark"]))
        for pattern, entry in (bench.get("pattern_audit") or {}).items():
            if pattern not in supported:
                continue
            status = (entry.get("e2b_reevaluation") or {}).get("status")
            if entry.get("verdict_outcome_class") == "FALSE_FAIL_RISK":
                if status not in resolved:
                    active_ffr.append((bench["benchmark"], pattern))
                elif status is None:
                    unreviewed.append((bench["benchmark"], pattern))
            if entry.get("parallel_bias_risk") is True and status not in resolved:
                active_bias.append((bench["benchmark"], pattern))
    check("ACTIVE_FALSE_FAIL_RISK = 0", not active_ffr, str(active_ffr[:3]))
    check("no active parallel_bias_risk is left unresolved", not active_bias,
          str(active_bias[:3]))
    check("every active flagged case carries an explicit E2-B verdict",
          not unreviewed, str(unreviewed[:3]))

    # the whole suite: nothing the policy refuses may come out of generation
    leaks = []
    for benchmark in capabilities.policy_benchmarks():
        for produced_spec in build_benchmark_specs(
                benchmark, [], {"stages": {"enhanced_tests": {}}}):
            if capabilities.full_spec_rejection(produced_spec) is not None:
                leaks.append((benchmark, produced_spec["pattern"]))
    check("no generated/mutated spec violates the frozen policy", not leaks,
          str(leaks[:3]))


# ---------------------------------------------------------------------------
# 6. generator and mutation follow the domain
# ---------------------------------------------------------------------------

def group_generator_and_mutation():
    print("generator and mutation use the same domain source")

    settings = dict(DEFAULT_SETTINGS)
    rules = gen._parameter_rules_block(DOMAIN_PM1, settings)
    check("the prompt names the benchmark's allowed value_range",
          "allowed value_range: [-1, 1]" in rules, rules[:200])
    rules_split = gen._parameter_rules_block(MULTI_SPLIT, settings)
    check("the prompt says value_range is unavailable where it is",
          "value_range not available" in rules_split, rules_split[:200])
    rules_zero = gen._parameter_rules_block(SIZE0_DISALLOWED, settings)
    check("the prompt states where size 0 is not a valid test size",
          "size 0 is NOT a valid test size" in rules_zero, rules_zero[:200])
    check("the no-hook benchmark is still offered no fill parameters",
          "NO fill hook" in gen._parameter_rules_block(NO_HOOK, settings))

    # mutation must not leave the domain
    seed = spec(DOMAIN_PM1, "ascending", size=8,
                params={"value_range": [-1.0, 1.0]})
    seed["source"] = "llm"
    out_of_domain = [
        m for m in _mutants_of(seed, 4096)
        if capabilities.value_range_domain_rejection(
            m["benchmark"], m["pattern"],
            (m.get("pattern_params") or {}).get("value_range")) is not None]
    check("no mutant leaves the declared domain", not out_of_domain,
          str([m.get("pattern_params") for m in out_of_domain[:2]]))

    # a shift that WOULD leave the domain is dropped, not clamped
    narrow = spec(DOMAIN_PM1, "ascending", size=8,
                  params={"value_range": [-1.0, 1.0]})
    shifted = [m for m in _mutants_of(narrow, 4096)
               if (m.get("pattern_params") or {}).get("value_range") == [0.0, 2.0]]
    check("the out-of-domain shift mutant is not produced at all", not shifted)


# ---------------------------------------------------------------------------
# 7. adapter and large-size decisions
# ---------------------------------------------------------------------------

def group_adapters_and_size_cap():
    print("adapter decisions and the large-size freeze")

    for benchmark in ("graph/15_graph_edge_count", "graph/19_graph_shortest_path",
                      "sparse_la/45_sparse_la_sparse_solve",
                      "sparse_la/49_sparse_la_sparse_lu_decomp",
                      "sort/44_sort_sort_non-zero_elements"):
        decision = capabilities.adapter_policy(benchmark)
        check("%s records an explicit no-adapter decision" % benchmark.split("_")[0],
              decision is not None
              and decision.get("decision") == "NO_NEW_ADAPTER_FOR_PILOT_002"
              and decision.get("pattern_variation") == "unavailable",
              str(decision))
        check("%s keeps only the canonical pattern" % benchmark.split("_")[0],
              capabilities.supported_patterns(benchmark) == ["random"],
              str(capabilities.supported_patterns(benchmark)))

    # size variation survives where the size policy allows it
    produced = build_benchmark_specs(
        "graph/15_graph_edge_count", [], {"stages": {"enhanced_tests": {}}})
    check("a no-adapter benchmark still varies size",
          len({s["size"] for s in produced}) > 1,
          str(sorted({s["size"] for s in produced})))

    check("max_spec_size is still 4096", int(DEFAULT_SETTINGS["max_spec_size"]) == 4096)
    ok, why = accepted(spec(DOMAIN_M10_10, "random", size=4096))
    check("size 4096 is still accepted", ok, why)
    ok, why = validate_spec(spec(DOMAIN_M10_10, "random", size=4097),
                            {DOMAIN_M10_10}, max_size=4096)
    check("size 4097 is still rejected by max_spec_size",
          not ok and "max_spec_size" in why, why)

    check("the implemented pattern library is unchanged (11 labels)",
          len(PATTERNS) == 11)


def main():
    groups = (
        group_policy_freeze,
        group_declared_domain,
        group_extreme_and_spike,
        group_size_zero,
        group_false_fail_unreachable,
        group_generator_and_mutation,
        group_adapters_and_size_cap,
    )
    for group in groups:
        group()
        print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All %d E2-B policy test groups passed." % len(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
