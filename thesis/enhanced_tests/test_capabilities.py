#!/usr/bin/env python3
"""E2-A capability-enforcement tests.

Proves that validation, LLM spec generation and the deterministic mutation all
enforce the SAME benchmark capability policy, that fake pattern diversity can no
longer be produced, and that no unsafe or policy-deferred pattern can enter the
pipeline through any of the three paths.

Python 3.8 compatible. Run:  python3 thesis/enhanced_tests/test_capabilities.py
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
    build_benchmark_specs,
    spec_key,
    static_base_specs,
    validate_spec,
)

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" — " + detail) if detail else ""))
        FAILURES.append(label)


def spec(benchmark, pattern, size=7, **extra):
    out = {
        "benchmark": benchmark,
        "size": size,
        "pattern": pattern,
        "pattern_params": {},
        "source": "llm",
        "rationale": "capability test",
    }
    out.update(extra)
    return out


# representative benchmarks, one per capability class
NO_EFFECT = "graph/15_graph_edge_count"          # pattern_effect NONE
NOT_APPLICABLE = "histogram/23_histogram_first_letter_counts"
EFFECTIVE = "stencil/50_stencil_xor_kernel"      # pattern_effect EFFECTIVE
PARTIAL = "dense_la/02_dense_la_gemm"            # pattern_effect PARTIAL
ORACLE_UNSAFE = "stencil/54_stencil_game_of_life"  # extreme_values unsafe
FILL_DEFERRED = "reduce/28_reduce_smallest_odd_number"
SIZE_MIN = "graph/19_graph_shortest_path"        # min_size 2
SIZE_POW2 = "fft/05_fft_inverse_fft"             # power of two or <= 1

ALL_BENCHMARKS = set((capabilities.load_policy().get("benchmarks") or {}).keys())


def group_policy_shape():
    print("policy artifact")
    policy = capabilities.load_policy()
    check("policy is the ENFORCED artifact", policy.get("status") == "ENFORCED")
    check("policy covers 60 benchmarks", len(ALL_BENCHMARKS) == 60,
          "got %d" % len(ALL_BENCHMARKS))
    every_known = all(
        set(entry.get("supported_patterns") or []) <= set(PATTERNS)
        for entry in policy["benchmarks"].values())
    check("enforced patterns are a subset of the implemented library", every_known)
    disjoint = True
    for name, entry in policy["benchmarks"].items():
        sup = set(entry.get("supported_patterns") or [])
        uns = set(entry.get("unsupported_patterns") or {})
        dfr = set(entry.get("deferred_policy_patterns") or {})
        if sup & uns or sup & dfr or uns & dfr:
            disjoint = False
        if sup | uns | dfr != set(PATTERNS):
            disjoint = False
    check("supported/unsupported/deferred partition all 11 patterns", disjoint)


def group_validation():
    print("validate_spec enforces benchmark capability")
    ok, why = validate_spec(spec(NO_EFFECT, "ascending"), {NO_EFFECT})
    check("no-effect pattern rejected", not ok and "no_pattern_effect" in why, why)

    ok, _ = validate_spec(spec(NO_EFFECT, "random"), {NO_EFFECT})
    check("canonical random still accepted on a no-effect benchmark", ok)

    ok, why = validate_spec(spec(NOT_APPLICABLE, "extreme_values"), {NOT_APPLICABLE})
    check("string benchmark rejects numeric pattern",
          not ok and "no_pattern_effect" in why, why)

    ok, why = validate_spec(spec(ORACLE_UNSAFE, "extreme_values"), {ORACLE_UNSAFE})
    check("oracle-unsafe pattern rejected",
          not ok and "unsafe_pattern_for_benchmark" in why, why)

    ok, why = validate_spec(spec(FILL_DEFERRED, "extreme_values"), {FILL_DEFERRED})
    check("policy-deferred pattern rejected as deferred",
          not ok and "deferred_policy_pattern" in why, why)

    ok, _ = validate_spec(spec(EFFECTIVE, "ascending"), {EFFECTIVE})
    check("supported pattern on an EFFECTIVE benchmark accepted", ok)

    ok, _ = validate_spec(spec(PARTIAL, "ascending"), {PARTIAL})
    check("PARTIAL benchmark keeps its working patterns", ok)

    ok, why = validate_spec(spec(SIZE_MIN, "random", size=1), {SIZE_MIN})
    check("benchmark-specific min size enforced",
          not ok and "invalid_size_for_benchmark" in why, why)
    ok, _ = validate_spec(spec(SIZE_MIN, "random", size=2), {SIZE_MIN})
    check("size at the safe minimum accepted", ok)

    ok, why = validate_spec(spec(SIZE_POW2, "random", size=7), {SIZE_POW2})
    check("non-power-of-two size rejected for the fft oracle",
          not ok and "invalid_size_for_benchmark" in why, why)
    for good in (0, 1, 8, 4096):
        ok, why = validate_spec(spec(SIZE_POW2, "random", size=good), {SIZE_POW2})
        check("power-of-two size %d accepted" % good, ok, why)

    # size 0 stays legal where no benchmark-specific hazard was proven:
    # SIZE_ZERO_SPEC_POLICY is still open and must not be decided here.
    ok, _ = validate_spec(spec(EFFECTIVE, "random", size=0), {EFFECTIVE})
    check("size 0 still accepted where no hazard is documented (policy open)", ok)


def group_generation():
    print("LLM generation offers only effective patterns")
    settings = dict(DEFAULT_SETTINGS)

    eff_no_effect = gen.effective_patterns_for(NO_EFFECT, settings)
    check("no-effect benchmark is offered only 'random'", eff_no_effect == ["random"],
          str(eff_no_effect))

    eff_string = gen.effective_patterns_for(NOT_APPLICABLE, settings)
    check("string benchmark is offered only 'random'", eff_string == ["random"],
          str(eff_string))

    eff_effective = gen.effective_patterns_for(EFFECTIVE, settings)
    check("EFFECTIVE benchmark keeps several real patterns", len(eff_effective) >= 5,
          str(eff_effective))

    eff_partial = gen.effective_patterns_for(PARTIAL, settings)
    check("PARTIAL benchmark is not blanket-disabled", len(eff_partial) >= 5,
          str(eff_partial))

    check("oracle-unsafe pattern is never offered",
          "extreme_values" not in gen.effective_patterns_for(ORACLE_UNSAFE, settings))
    check("deferred pattern is never offered",
          "extreme_values" not in gen.effective_patterns_for(FILL_DEFERRED, settings))

    block = gen._pattern_block(NO_EFFECT, settings)
    check("prompt states pattern variation is unavailable",
          "NOT available" in block, block[:80])
    check("prompt does not list a numeric pattern for the string benchmark",
          "ascending" not in gen._pattern_block(NOT_APPLICABLE, settings))

    # every offered pattern must survive validation for that benchmark
    leaked = []
    for benchmark in sorted(ALL_BENCHMARKS):
        for pattern in gen.effective_patterns_for(benchmark, settings):
            if capabilities.pattern_rejection(benchmark, pattern) is not None:
                leaked.append((benchmark, pattern))
    check("no offered pattern is rejected by validation", not leaked, str(leaked[:3]))


def group_mutation():
    print("mutation cannot manufacture fake or unsafe patterns")
    settings = dict(DEFAULT_SETTINGS)

    produced = build_benchmark_specs(NO_EFFECT, [], {"stages": {"enhanced_tests": {}}})
    patterns = {s["pattern"] for s in produced}
    check("no-effect benchmark yields only the canonical pattern",
          patterns == {"random"}, str(patterns))
    sizes = [s["size"] for s in produced]
    check("size variation still happens there", len(set(sizes)) > 1, str(sorted(set(sizes))))
    check("spec_keys stay unique", len({spec_key(s) for s in produced}) == len(produced))

    offenders = []
    for benchmark in sorted(ALL_BENCHMARKS):
        specs_out = build_benchmark_specs(benchmark, [], {"stages": {"enhanced_tests": {}}})
        for s in specs_out:
            if capabilities.spec_rejection(benchmark, s["size"], s["pattern"]) is not None:
                offenders.append((benchmark, s["size"], s["pattern"]))
    check("no generated spec violates the capability policy on any benchmark",
          not offenders, str(offenders[:3]))


def group_no_fake_padding():
    print("capability-limited counts are honest")
    produced = build_benchmark_specs(NO_EFFECT, [], {"stages": {"enhanced_tests": {}}})
    target = int(DEFAULT_SETTINGS["target_cases_per_benchmark"])
    check("count is not padded with duplicate pattern labels to hit the target",
          len(produced) <= target)
    keys = [spec_key(s) for s in produced]
    check("no duplicate specs", len(keys) == len(set(keys)))
    # the only axis left on this benchmark is size, so every spec must differ in it
    check("every spec differs in size", len({s["size"] for s in produced}) == len(produced))


def group_size_constrained_base():
    print("static base set respects benchmark size constraints")
    base = static_base_specs(SIZE_MIN, DEFAULT_SETTINGS["static_base_sizes"])
    check("unsafe base sizes dropped for the constrained benchmark",
          all(s["size"] >= 2 for s in base), str([s["size"] for s in base]))
    base_open = static_base_specs(EFFECTIVE, DEFAULT_SETTINGS["static_base_sizes"])
    check("unconstrained benchmark keeps its full base set",
          [s["size"] for s in base_open] == list(DEFAULT_SETTINGS["static_base_sizes"]))


def group_single_source():
    print("one capability source, three consumers")
    import thesis.enhanced_tests.specs as specs_mod
    check("specs.py imports the capability module",
          getattr(specs_mod, "capabilities", None) is capabilities)
    check("generate_test_specs.py imports the same module",
          getattr(gen, "capabilities", None) is capabilities)
    summary = capabilities.policy_summary()
    check("policy summary reports all 60 benchmarks", summary["benchmarks"] == 60)
    check("unsafe cases are enforced as unsupported",
          summary["reason_distribution"].get("unsafe_pattern_for_benchmark", 0) > 0)
    check("deferred cases are reported separately",
          summary["deferred_policy_pattern_cases"] > 0)


def main():
    for group in (group_policy_shape, group_validation, group_generation,
                  group_mutation, group_no_fake_padding,
                  group_size_constrained_base, group_single_source):
        group()
        print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All capability-enforcement test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
