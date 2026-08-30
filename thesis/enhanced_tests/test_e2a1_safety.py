#!/usr/bin/env python3
"""E2-A.1 tests: range safety, non-finite rejection, pattern-parameter
relevance, fail-closed policy integrity and side-effect ordering.

Complements test_capabilities.py (E2-A: which PATTERNS a benchmark supports)
with the three gaps a read-only audit found after E2-A:

  1. a syntactically valid spec could still drive the fill layer into signed
     overflow, modulo/division by zero, an FPE or a deterministic NaN/Inf,
  2. an irrelevant value_range / k / values could still create a second spec
     identity for an identical input (parameter-level fake diversity),
  3. the capability policy failed OPEN - a missing or incomplete policy
     silently disabled enforcement and the consistency checker went green.

Run:  python thesis/enhanced_tests/test_e2a1_safety.py
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests import check_enhanced_capabilities as checker  # noqa: E402
from thesis.enhanced_tests import derive_enhanced_policy as derivation  # noqa: E402
from thesis.enhanced_tests import generate_test_specs as gen  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    PATTERNS,
    build_benchmark_specs,
    spec_key,
    validate_spec,
)

FAILURES = []

# one benchmark per fill container element type, plus one without a fill hook
DOUBLE_BENCH = "dense_la/00_dense_la_lu_decomp"
INT_BENCH = "reduce/28_reduce_smallest_odd_number"
FLOAT_BENCH = "scan/31_scan_scan_with_min_function"
NO_HOOK_BENCH = "graph/15_graph_edge_count"

DBL_MAX = 1.7976931348623157e308
FLT_MAX = 3.4028234663852886e38
INT_MIN = -2147483648.0
INT_MAX = 2147483647.0


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


def spec(benchmark=DOUBLE_BENCH, pattern="random", size=8, params=None, **extra):
    out = {
        "benchmark": benchmark,
        "size": size,
        "pattern": pattern,
        "pattern_params": dict(params or {}),
        "source": "llm",
        "rationale": "e2a1 test",
    }
    out.update(extra)
    return out


def rejected(spec_dict):
    ok, why = validate_spec(spec_dict, {spec_dict["benchmark"]})
    return (not ok), why


# ---------------------------------------------------------------------------
# 1. value_range technical safety
# ---------------------------------------------------------------------------

def group_range_safety():
    print("value_range technical safety")

    safe = [
        ("int [0,100]", INT_BENCH, [0.0, 100.0]),
        ("int [5,5]", INT_BENCH, [5.0, 5.0]),
        ("float [-100,100]", FLOAT_BENCH, [-100.0, 100.0]),
        ("double [-100,100]", DOUBLE_BENCH, [-100.0, 100.0]),
    ]
    range_patterns = [p for p in capabilities.RANGE_PATTERNS]
    for label, bench, bounds in safe:
        for pattern in range_patterns:
            if capabilities.pattern_rejection(bench, pattern) is not None:
                continue  # pattern not supported here for an unrelated reason
            params = {"value_range": bounds}
            if pattern in capabilities.K_PATTERNS:
                params["k"] = 1
            ok, why = validate_spec(spec(bench, pattern, params=params),
                                    {bench})
            check("%s accepted for %s" % (label, pattern), ok, why)

    unsafe = [
        ("int [INT_MIN, INT_MAX] span overflows", INT_BENCH,
         [INT_MIN, INT_MAX], capabilities.REASON_UNSAFE_SPAN),
        ("int [-1e300, 1e300] not representable", INT_BENCH,
         [-1e300, 1e300], capabilities.REASON_RANGE_NOT_REPRESENTABLE),
        ("float [-FLT_MAX, FLT_MAX] span not finite", FLOAT_BENCH,
         [-FLT_MAX, FLT_MAX], capabilities.REASON_UNSAFE_SPAN),
        ("float [-1e300, 1e300] not representable", FLOAT_BENCH,
         [-1e300, 1e300], capabilities.REASON_RANGE_NOT_REPRESENTABLE),
        ("double [-DBL_MAX, DBL_MAX] span not finite", DOUBLE_BENCH,
         [-DBL_MAX, DBL_MAX], capabilities.REASON_UNSAFE_SPAN),
        ("double [-1e308, 1e308] span not finite", DOUBLE_BENCH,
         [-1e308, 1e308], capabilities.REASON_UNSAFE_SPAN),
    ]
    for label, bench, bounds, reason in unsafe:
        bad, why = rejected(spec(bench, "ascending", params={"value_range": bounds}))
        check(label + " rejected", bad and reason in why, why)

    # the largest span that IS admissible must still be accepted, so the guard
    # is a real boundary and not a blanket ban on large ranges
    ok, why = validate_spec(
        spec(INT_BENCH, "ascending", params={"value_range": [0.0, INT_MAX - 1]}),
        {INT_BENCH})
    check("int span at exactly the safe maximum accepted", ok, why)
    bad, _ = rejected(
        spec(INT_BENCH, "ascending", params={"value_range": [0.0, INT_MAX]}))
    check("int span one above the safe maximum rejected", bad)

    # endpoints outside the container, even with a tiny span
    bad, why = rejected(
        spec(INT_BENCH, "ascending", params={"value_range": [1e10, 1e10 + 1]}))
    check("int endpoint above INT_MAX rejected (small span)",
          bad and capabilities.REASON_RANGE_NOT_REPRESENTABLE in why, why)

    # rejected, never clipped: validation must not rewrite the spec it refuses
    offending = spec(INT_BENCH, "ascending",
                     params={"value_range": [-1e300, 1e300]})
    before = json.dumps(offending, sort_keys=True)
    bad, why = rejected(offending)
    check("an unrepresentable range is rejected, not clipped",
          bad and json.dumps(offending, sort_keys=True) == before
          and "rejected, not clipped" in why, why)


# ---------------------------------------------------------------------------
# 2. non-finite rejection
# ---------------------------------------------------------------------------

def group_non_finite():
    print("non-finite value_range and explicit values")

    nan = float("nan")
    inf = float("inf")
    for label, bounds in (
        ("[NaN, 1]", [nan, 1.0]),
        ("[0, NaN]", [0.0, nan]),
        ("[-Inf, 1]", [-inf, 1.0]),
        ("[0, +Inf]", [0.0, inf]),
        ("[-Inf, +Inf]", [-inf, inf]),
    ):
        bad, why = rejected(
            spec(DOUBLE_BENCH, "ascending", params={"value_range": bounds}))
        check("value_range %s rejected" % label,
              bad and capabilities.REASON_NON_FINITE_RANGE in why, why)

    # explicit values: no exception for double
    for label, bench, count in (
        ("int benchmark", INT_BENCH, 3),
        ("float benchmark", FLOAT_BENCH, 3),
        ("double benchmark", "reduce/27_reduce_average", 3),
    ):
        for what, value in (("NaN", nan), ("+Inf", inf), ("-Inf", -inf)):
            values = [1.0] * (count - 1) + [value]
            bad, why = rejected(spec(bench, "explicit_values", size=count,
                                     values=values))
            check("explicit %s rejected on the %s" % (what, label),
                  bad and (capabilities.REASON_NON_FINITE_VALUE in why
                           or capabilities.REASON_VALUE_NOT_REPRESENTABLE in why),
                  why)

    # finite explicit values still pass where the benchmark supports them
    ok, why = validate_spec(
        spec("reduce/27_reduce_average", "explicit_values", size=3,
             values=[1.0, 2.0, 3.0]), {"reduce/27_reduce_average"})
    check("finite explicit values still accepted", ok, why)


# ---------------------------------------------------------------------------
# 3. pattern-parameter relevance
# ---------------------------------------------------------------------------

def group_parameter_relevance():
    print("pattern-parameter relevance (A-H)")

    bad, why = rejected(spec(DOUBLE_BENCH, "random", params={"k": 1}))
    check("A random + k rejected",
          bad and capabilities.REASON_IRRELEVANT_PARAM in why, why)

    bad, why = rejected(
        spec(DOUBLE_BENCH, "all_zeros", params={"value_range": [0.0, 1.0]}))
    check("B all_zeros + value_range rejected",
          bad and capabilities.REASON_IRRELEVANT_PARAM in why, why)

    bad, why = rejected(
        spec(DOUBLE_BENCH, "extreme_values", params={"value_range": [0.0, 1.0]}))
    check("C extreme_values + value_range rejected",
          bad and capabilities.REASON_IRRELEVANT_PARAM in why, why)

    bad, why = rejected(
        spec("reduce/27_reduce_average", "explicit_values", size=3,
             params={"k": 1}, values=[1.0, 2.0, 3.0]))
    check("D explicit_values + k rejected",
          bad and capabilities.REASON_IRRELEVANT_PARAM in why, why)

    bad, why = rejected(spec(DOUBLE_BENCH, "random", size=4,
                             values=[1.0] * 16))
    check("E random + top-level values rejected",
          bad and capabilities.REASON_IRRELEVANT_PARAM in why, why)

    bad, why = rejected(spec(DOUBLE_BENCH, "random", params={"foo": 1}))
    check("F unknown pattern_params key rejected",
          bad and capabilities.REASON_UNKNOWN_PARAM in why, why)

    bad, why = rejected(
        spec(NO_HOOK_BENCH, "random", params={"value_range": [0.0, 1.0]}))
    check("G no-fill-hook benchmark + value_range rejected",
          bad and capabilities.REASON_INERT_PARAM in why, why)

    ok, why = validate_spec(spec(NO_HOOK_BENCH, "random"), {NO_HOOK_BENCH})
    check("H no-fill-hook benchmark, canonical random without params accepted",
          ok, why)

    # the k-patterns keep their k
    ok, why = validate_spec(
        spec(DOUBLE_BENCH, "duplicate_at", size=4, params={"k": 2}), {DOUBLE_BENCH})
    check("k still accepted on a k-pattern", ok, why)

    # every pattern/parameter combination follows exactly ONE table
    mismatched = []
    for pattern in PATTERNS:
        for param in capabilities.FILL_PARAMS:
            used = capabilities.pattern_uses(pattern, param)
            expected = (
                (param == "k" and pattern in capabilities.K_PATTERNS)
                or (param == "values" and pattern == "explicit_values")
                or (param == "value_range"
                    and pattern not in ("all_zeros", "extreme_values",
                                        "explicit_values"))
            )
            if used != expected:
                mismatched.append((pattern, param, used))
    check("the canonical relevance table matches the contracted rule",
          not mismatched, str(mismatched))


# ---------------------------------------------------------------------------
# 4. parameter-level fake diversity is structurally closed
# ---------------------------------------------------------------------------

def group_fake_diversity():
    print("parameter-level fake diversity")

    # two specs that differ ONLY in an inert parameter must not both survive
    base = spec(NO_HOOK_BENCH, "random", size=4)
    inert = spec(NO_HOOK_BENCH, "random", size=4,
                 params={"value_range": [0.0, 1.0]})
    ok_base, _ = validate_spec(base, {NO_HOOK_BENCH})
    ok_inert, _ = validate_spec(inert, {NO_HOOK_BENCH})
    check("only the canonical one of two inert-range twins survives",
          ok_base and not ok_inert)
    check("their spec_keys really were different (the defect was real)",
          spec_key(base) != spec_key(inert))

    # mutation must not manufacture inert parameters either
    offenders = []
    for benchmark in capabilities.policy_benchmarks():
        for produced in build_benchmark_specs(
                benchmark, [], {"stages": {"enhanced_tests": {}}}):
            if capabilities.full_spec_rejection(produced) is not None:
                offenders.append((benchmark, produced["pattern"],
                                  produced.get("pattern_params")))
    check("no generated/mutated spec carries an irrelevant or unsafe parameter",
          not offenders, str(offenders[:3]))

    # a historical seed with an irrelevant parameter produces no offspring
    from thesis.enhanced_tests.specs import _mutants_of
    seeded = spec(DOUBLE_BENCH, "random", size=8, params={"k": 3})
    check("a seed with an irrelevant parameter yields no mutants",
          _mutants_of(seeded, 4096) == [])

    # a pattern swap must not inherit a parameter the target ignores
    swapped = _mutants_of(
        spec(DOUBLE_BENCH, "random", size=8,
             params={"value_range": [-1.0, 1.0]}), 4096)
    check("random -> extreme_values swap carrying a value_range is dropped",
          all(m["pattern"] != "extreme_values" for m in swapped),
          str([m["pattern"] for m in swapped]))


# ---------------------------------------------------------------------------
# 5. fail-closed policy integrity
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def policy_file(content, as_bytes=False):
    """Point every consumer at a temporary policy artifact."""
    original = (capabilities.POLICY_PATH, derivation.POLICY, checker.POLICY)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "enhanced_policy.json"
        if content is not None:
            if as_bytes:
                path.write_bytes(content)
            else:
                path.write_text(json.dumps(content, indent=1), encoding="utf-8")
        capabilities.POLICY_PATH = path
        derivation.POLICY = path
        checker.POLICY = path
        capabilities.reset_policy_cache()
        try:
            yield path
        finally:
            (capabilities.POLICY_PATH, derivation.POLICY,
             checker.POLICY) = original
            capabilities.reset_policy_cache()


def fatal(callable_):
    try:
        callable_()
    except capabilities.EnhancedPolicyError as error:
        return True, str(error)
    except Exception as error:  # noqa: BLE001 - anything else is not fail-closed
        return False, "raised %s instead: %s" % (type(error).__name__, error)
    return False, "did not raise"


def group_policy_integrity():
    print("fail-closed policy integrity (A-H)")

    good = derivation.derived_document()

    with policy_file(good):
        ok = True
        try:
            capabilities.policy_preflight()
        except capabilities.EnhancedPolicyError as error:
            ok, detail = False, str(error)
        check("A correct policy passes the preflight", ok,
              locals().get("detail", ""))

    with policy_file(None):
        raised, detail = fatal(capabilities.load_policy)
        check("B missing policy is fatal", raised, detail)

    with policy_file(b"{not json", as_bytes=True):
        raised, detail = fatal(capabilities.load_policy)
        check("C invalid JSON is fatal", raised, detail)

    incomplete = json.loads(json.dumps(good))
    dropped = sorted(incomplete["benchmarks"])[0]
    del incomplete["benchmarks"][dropped]
    with policy_file(incomplete):
        check("D policy with 59 entries loses no structural gate",
              len(capabilities.load_policy()["benchmarks"]) == 59)
        raised, detail = fatal(lambda: capabilities.benchmark_policy(dropped))
        check("E a real benchmark missing from the policy is fatal, not "
              "unrestricted", raised, detail)
        raised, detail = fatal(capabilities.policy_preflight)
        check("D/E the preflight rejects the incomplete policy", raised, detail)
        raised, detail = fatal(
            lambda: capabilities.policy_preflight(expected_benchmarks=[dropped]))
        check("E the expected-benchmark gate rejects it too", raised, detail)

    extra = json.loads(json.dumps(good))
    extra["benchmarks"]["fake/99_fake_benchmark"] = json.loads(
        json.dumps(extra["benchmarks"][sorted(good["benchmarks"])[0]]))
    with policy_file(extra):
        raised, detail = fatal(capabilities.policy_preflight)
        check("F an extra/fake benchmark is fatal", raised, detail)

    stale = json.loads(json.dumps(good))
    stale["benchmarks"]["graph/19_graph_shortest_path"]["size_constraint"]["min_size"] = 0
    with policy_file(stale):
        raised, detail = fatal(capabilities.policy_preflight)
        check("G a stale size constraint is caught by the derivation preflight",
              raised, detail)
        matches, _ = derivation.policy_matches_derivation()
        check("G derive --check also reports it", not matches)

    unenforced = json.loads(json.dumps(good))
    unenforced["status"] = "DRAFT"
    with policy_file(unenforced):
        raised, detail = fatal(capabilities.load_policy)
        check("H a policy whose status is not ENFORCED is fatal", raised, detail)

    broken_partition = json.loads(json.dumps(good))
    first = sorted(broken_partition["benchmarks"])[0]
    entry = broken_partition["benchmarks"][first]
    if entry["supported_patterns"]:
        entry["supported_patterns"] = entry["supported_patterns"][:-1]
        with policy_file(broken_partition):
            raised, detail = fatal(capabilities.load_policy)
            check("an incomplete pattern partition is fatal", raised, detail)


def group_checker_fails_closed():
    print("the consistency checker no longer goes false-green")

    good = derivation.derived_document()
    stale = json.loads(json.dumps(good))
    stale["benchmarks"]["graph/19_graph_shortest_path"]["size_constraint"]["min_size"] = 0
    incomplete = json.loads(json.dumps(good))
    del incomplete["benchmarks"][sorted(incomplete["benchmarks"])[0]]
    extra = json.loads(json.dumps(good))
    extra["benchmarks"]["fake/99_fake_benchmark"] = json.loads(
        json.dumps(extra["benchmarks"][sorted(good["benchmarks"])[0]]))
    unenforced = json.loads(json.dumps(good))
    unenforced["status"] = "DRAFT"

    cases = [
        ("policy missing", None, False),
        ("invalid JSON", b"{not json", True),
        ("59 benchmark entries", incomplete, False),
        ("extra/fake benchmark", extra, False),
        ("stale size constraint", stale, False),
        ("status not ENFORCED", unenforced, False),
    ]
    for label, content, as_bytes in cases:
        with policy_file(content, as_bytes=as_bytes):
            code = checker.main()
        check("checker exits non-zero: %s" % label, code != 0, "exit %s" % code)

    with policy_file(good):
        code = checker.main()
    check("checker still exits 0 on the correct policy", code == 0,
          "exit %s" % code)


# ---------------------------------------------------------------------------
# 6. side-effect ordering
# ---------------------------------------------------------------------------

def _main_source(module):
    import inspect
    source, start = inspect.getsourcelines(module.main)
    return [(start + i, line) for i, line in enumerate(source)]


def _first_line_containing(lines, needle):
    for number, text in lines:
        if needle in text and not text.strip().startswith("#"):
            return number
    return None


def group_side_effect_ordering():
    print("policy preflight runs before any persistent side effect")

    from thesis.evaluation import run_enhanced_tests as runner

    runner_lines = _main_source(runner)
    preflight = _first_line_containing(runner_lines, "capabilities.policy_preflight(")
    check("runner calls the preflight in main()", preflight is not None)
    for label, needle in (
        ("run manifest", "ensure_run_manifest("),
        ("--force output deletion", "path.unlink()"),
        ("record file open", "output_path.open("),
        ("spec loading", "load_llm_specs("),
        ("environment gate", "missing_toolchain("),
    ):
        line = _first_line_containing(runner_lines, needle)
        check("runner: preflight precedes %s" % label,
              line is not None and preflight is not None and preflight < line,
              "preflight=%s %s=%s" % (preflight, label, line))

    gen_lines = _main_source(gen)
    gen_preflight = _first_line_containing(gen_lines, "capabilities.policy_preflight(")
    check("generator calls the preflight in main()", gen_preflight is not None)
    for label, needle in (
        ("output directory creation", ".mkdir("),
        ("--force output deletion", "path.unlink()"),
        ("output file open", "output_path.open("),
        ("API client creation", "adapter.create_client("),
        ("adapter loading", "load_adapter("),
    ):
        line = _first_line_containing(gen_lines, needle)
        check("generator: preflight precedes %s" % label,
              line is not None and gen_preflight is not None and gen_preflight < line,
              "preflight=%s %s=%s" % (gen_preflight, label, line))

    # dynamic proof for the generator: a failing preflight must abort before a
    # single byte is written and before the adapter is even loaded
    import tempfile as _tempfile

    def exploding_preflight(*_args, **_kwargs):
        raise capabilities.EnhancedPolicyError("test: policy unusable")

    def exploding_adapter(*_args, **_kwargs):
        raise AssertionError("the adapter was loaded despite a failed preflight")

    original_preflight = capabilities.policy_preflight
    original_adapter = gen.load_adapter
    with _tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "nested" / "specs.jsonl"
        argv = sys.argv[:]
        try:
            capabilities.policy_preflight = exploding_preflight
            gen.load_adapter = exploding_adapter
            sys.argv = ["generate_test_specs.py", "--config",
                        str(REPO_ROOT / "thesis" / "config" / "config.yaml"),
                        "--output", str(out), "--force"]
            aborted = False
            try:
                gen.main()
            except SystemExit:
                aborted = True
            except capabilities.EnhancedPolicyError:
                aborted = True
        finally:
            sys.argv = argv
            capabilities.policy_preflight = original_preflight
            gen.load_adapter = original_adapter
        check("generator aborts on a failed preflight", aborted)
        check("generator wrote nothing before aborting",
              not out.exists() and not out.parent.exists())


def main():
    groups = (
        group_range_safety,
        group_non_finite,
        group_parameter_relevance,
        group_fake_diversity,
        group_policy_integrity,
        group_checker_fails_closed,
        group_side_effect_ordering,
    )
    for group in groups:
        group()
        print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All %d E2-A.1 safety test groups passed." % len(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
