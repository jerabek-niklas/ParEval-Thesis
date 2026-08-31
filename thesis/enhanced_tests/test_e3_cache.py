#!/usr/bin/env python3
"""E3 tests: final spec-cache invariants, retention proof, replacement-path
safety and the fail-closed result-reuse boundary.

E3 changed no harness semantics and no policy - it replaced the specs the
frozen E2-B policy invalidated. These tests assert the properties that makes
sound:

  * every spec in the final cache is valid under the frozen policy;
  * the cache carries no fake diversity the earlier waves froze out;
  * every historically valid spec survived unchanged, with its spec_key;
  * every historically invalid spec is gone;
  * a replacement can never be produced outside the productive generator's
    validation, nor collide with a retained spec;
  * a resumed run cannot silently keep a result produced under a different
    enhanced policy.

Run:  python thesis/enhanced_tests/test_e3_cache.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests import generate_test_specs as gen  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    DEFAULT_SETTINGS,
    spec_key,
    validate_spec,
)

CACHE = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"
FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


def load_cache():
    return [json.loads(line) for line in
            CACHE.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. the final cache satisfies the frozen policy
# ---------------------------------------------------------------------------

def group_final_cache():
    print("final cache is valid under the frozen E2-B policy")
    specs = load_cache()
    known = {b for b, _d in gen.parameterizable_benchmarks()}

    invalid = []
    for spec in specs:
        ok, why = validate_spec(spec, known)
        if not ok:
            invalid.append((spec["benchmark"], spec["pattern"], why.split(":")[0]))
    check("FINAL_INVALID_SPEC_COUNT = 0", not invalid, str(invalid[:3]))

    keys = [spec_key(s) for s in specs]
    check("every spec_key is unique", len(keys) == len(set(keys)),
          "%d rows, %d keys" % (len(keys), len(set(keys))))

    per_benchmark = Counter(s["benchmark"] for s in specs)
    check("all 60 benchmarks are represented", len(per_benchmark) == 60,
          str(len(per_benchmark)))
    check("every benchmark has at least one spec",
          per_benchmark and min(per_benchmark.values()) >= 1,
          str(sorted(per_benchmark.items(), key=lambda kv: kv[1])[:3]))
    check("no benchmark exceeds max_spec_size",
          all(s["size"] <= int(DEFAULT_SETTINGS["max_spec_size"]) for s in specs))


# ---------------------------------------------------------------------------
# 2. no fake diversity came back
# ---------------------------------------------------------------------------

def group_no_fake_diversity():
    print("none of the frozen-out fake diversity returned")
    specs = load_cache()

    check("no extreme_values spec",
          not [s for s in specs if s["pattern"] == "extreme_values"])

    unsupported = [(s["benchmark"], s["pattern"]) for s in specs
                   if capabilities.pattern_status(s["benchmark"], s["pattern"])[0]
                   != "supported"]
    check("no unsupported or deferred pattern", not unsupported, str(unsupported[:3]))

    irrelevant = [s for s in specs if capabilities.parameter_rejection(
        s["benchmark"], s["pattern"], s.get("pattern_params") or {},
        bool(s.get("values"))) is not None]
    check("no irrelevant / inert / unknown parameter", not irrelevant,
          str([(s["benchmark"], s["pattern"]) for s in irrelevant[:3]]))

    out_of_domain = [s for s in specs
                     if capabilities.value_range_domain_rejection(
                         s["benchmark"], s["pattern"],
                         (s.get("pattern_params") or {}).get("value_range")) is not None
                     or capabilities.explicit_values_domain_rejection(
                         s["benchmark"], s.get("values") or []) is not None]
    check("no out-of-domain range or explicit value", not out_of_domain,
          str([(s["benchmark"], s["pattern"]) for s in out_of_domain[:3]]))

    nonfinite = []
    for spec in specs:
        rng = (spec.get("pattern_params") or {}).get("value_range") or []
        if any(not math.isfinite(float(v)) for v in rng):
            nonfinite.append(spec["benchmark"])
        if any(not math.isfinite(float(v)) for v in (spec.get("values") or [])):
            nonfinite.append(spec["benchmark"])
    check("no non-finite parameter", not nonfinite, str(nonfinite[:3]))

    degenerate = [s for s in specs
                  if (s.get("pattern_params") or {}).get("value_range")
                  and float(s["pattern_params"]["value_range"][0])
                  == float(s["pattern_params"]["value_range"][1])
                  and s["pattern"] != "all_same"]
    check("a degenerate range only ever carries all_same", not degenerate,
          str([(s["benchmark"], s["pattern"]) for s in degenerate[:3]]))

    no_hook = [s for s in specs
               if not capabilities.has_fill_hook(s["benchmark"])
               and ((s.get("pattern_params") or {}) or s.get("values"))]
    check("no-fill benchmarks carry no fill parameters", not no_hook,
          str([(s["benchmark"], s["pattern"]) for s in no_hook[:3]]))
    no_hook_patterns = {s["pattern"] for s in specs
                        if not capabilities.has_fill_hook(s["benchmark"])}
    check("no-fill benchmarks use only the canonical pattern",
          no_hook_patterns <= {"random"}, str(no_hook_patterns))

    split = [s for s in specs
             if s["benchmark"].startswith("sort/43")
             and (s.get("pattern_params") or {}).get("value_range")]
    check("sort/43 carries no global value_range", not split)

    k_specs = [s for s in specs if (s.get("pattern_params") or {}).get("k") is not None]
    check("k only ever appears on a k-pattern",
          all(s["pattern"] in capabilities.K_PATTERNS for s in k_specs),
          str({s["pattern"] for s in k_specs} - set(capabilities.K_PATTERNS)))

    spikes = [s for s in specs if s["pattern"] == "spike_at"]
    check("every spike_at spec is domain-bounded and size >= 2",
          all(s["size"] >= 2 for s in spikes)
          and all(capabilities.value_range_domain_rejection(
              s["benchmark"], "spike_at",
              (s.get("pattern_params") or {}).get("value_range")) is None
              for s in spikes))


# ---------------------------------------------------------------------------
# 3. retention proof against the parent commit's cache
# ---------------------------------------------------------------------------

def group_retention():
    print("retention proof against the pre-E3 cache")
    # The spec cache is NOT version controlled (.gitignore: thesis/results/cache/),
    # so the pre-E3 state is not recoverable from git. E3 therefore wrote an
    # explicit, hashed backup next to it, and that backup is what this proof
    # compares against.
    backups = sorted(CACHE.parent.glob("specs.pre_e3_*.jsonl"))
    if not backups:
        check("pre-E3 backup present", False,
              "no specs.pre_e3_*.jsonl next to the cache")
        return
    check("pre-E3 backup present (cache is gitignored)", True)
    old = [json.loads(line) for line in
           backups[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    known = {s["benchmark"] for s in old}
    final = load_cache()
    final_by_key = {spec_key(s): s for s in final}

    old_valid, old_invalid, seen = [], [], set()
    for spec in old:
        key = spec_key(spec)
        if key in seen:
            continue
        seen.add(key)
        ok, _why = validate_spec(spec, known)
        (old_valid if ok else old_invalid).append(spec)

    dropped = [s for s in old_valid if spec_key(s) not in final_by_key]
    check("VALID_OLD_SPECS_DROPPED = 0", not dropped,
          str([(s["benchmark"], s["pattern"]) for s in dropped[:3]]))

    modified = [s for s in old_valid
                if spec_key(s) in final_by_key and final_by_key[spec_key(s)] != s]
    check("VALID_OLD_SPECS_MODIFIED = 0", not modified,
          str([s["benchmark"] for s in modified[:3]]))

    retained_invalid = [s for s in old_invalid if spec_key(s) in final_by_key]
    check("INVALID_OLD_SPECS_RETAINED = 0", not retained_invalid,
          str([(s["benchmark"], s["pattern"]) for s in retained_invalid[:3]]))

    old_counts = Counter()
    seen2 = set()
    for spec in old:
        key = spec_key(spec)
        if key in seen2:
            continue
        seen2.add(key)
        old_counts[spec["benchmark"]] += 1
    final_counts = Counter(s["benchmark"] for s in final)
    inflated = [b for b in final_counts if final_counts[b] > old_counts.get(b, 0)]
    check("no benchmark grew beyond its historical distinct population",
          not inflated, str(inflated[:3]))


# ---------------------------------------------------------------------------
# 4. the replacement path itself
# ---------------------------------------------------------------------------

def group_replacement_path():
    print("replacement generation stays inside the productive path")
    settings = dict(DEFAULT_SETTINGS)
    benchmark = "fft/05_fft_inverse_fft"
    retained = [{"benchmark": benchmark, "size": 8, "pattern": "ascending",
                 "pattern_params": {"value_range": [-1.0, 1.0]},
                 "source": "llm", "rationale": "retained"}]

    calls = []

    def fake(prompt):
        calls.append(prompt)
        return json.dumps([
            # a repeat of the retained spec
            {"size": 8, "pattern": "ascending",
             "pattern_params": {"value_range": [-1.0, 1.0]}, "rationale": "dup"},
            # policy-invalid proposals the validator must reject
            {"size": 8, "pattern": "extreme_values", "pattern_params": {},
             "rationale": "banned label"},
            {"size": 8, "pattern": "ascending",
             "pattern_params": {"value_range": [-5.0, 5.0]}, "rationale": "out of domain"},
            {"size": 0, "pattern": "random", "pattern_params": {},
             "rationale": "size 0 disallowed here"},
            {"size": 8, "pattern": "random", "pattern_params": {"k": 2},
             "rationale": "irrelevant k"},
            # two acceptable ones, then one over budget
            {"size": 4, "pattern": "alternating",
             "pattern_params": {"value_range": [-1.0, 1.0]}, "rationale": "ok1"},
            {"size": 16, "pattern": "random", "pattern_params": {}, "rationale": "ok2"},
            {"size": 32, "pattern": "descending", "pattern_params": {},
             "rationale": "over budget"},
        ])

    accepted, discarded, under, outcome = gen.generate_for_benchmark(
        fake, benchmark, "prompt", "baseline", settings, {benchmark},
        "glm_5_2", retained_specs=retained, replacement_budget=2)

    check("the replacement budget is honoured", len(accepted) == 2,
          str(len(accepted)))
    check("no replacement collides with a retained spec_key",
          all(spec_key(s) != spec_key(retained[0]) for s in accepted))
    check("replacements are unique among themselves",
          len({spec_key(s) for s in accepted}) == len(accepted))
    for spec in accepted:
        spec.setdefault("source", "llm")
        ok, why = validate_spec(spec, {benchmark})
        check("replacement %s/%s passes validate_spec" % (spec["pattern"], spec["size"]),
              ok, why)
    reasons = " ".join(d["reason"] for d in discarded)
    check("the banned extreme_values label was rejected", "extreme_values" in reasons)
    check("the out-of-domain range was rejected",
          capabilities.REASON_RANGE_OUTSIDE_DOMAIN in reasons)
    check("the disallowed size 0 was rejected",
          capabilities.REASON_INVALID_SIZE in reasons)
    check("the irrelevant k was rejected",
          capabilities.REASON_IRRELEVANT_PARAM in reasons)
    check("the over-budget proposal was refused",
          "over replacement budget" in reasons)
    check("the prompt showed the retained spec as already accepted",
          "ALREADY ACCEPTED" in calls[0])
    check("under_target is false when the budget is met", not under)
    check("the generator reports TARGET_MET", outcome["reason"] == "TARGET_MET",
          str(outcome))

    # E3.1: a provider failure must never be reported as a capability limit
    def dead(_prompt):
        return None

    _a, _d, under2, outcome2 = gen.generate_for_benchmark(
        dead, benchmark, "prompt", "baseline", settings, {benchmark},
        "glm_5_2", retained_specs=retained, replacement_budget=2)
    check("an API failure is classified API_FAILURE, not CAPABILITY_LIMITED",
          under2 and outcome2["reason"] == "API_FAILURE", str(outcome2))

    def garbage(_prompt):
        return "not json at all"

    _a, _d, under3, outcome3 = gen.generate_for_benchmark(
        garbage, benchmark, "prompt", "baseline", settings, {benchmark},
        "glm_5_2", retained_specs=retained, replacement_budget=2)
    check("an unparseable response is classified PARSE_OR_REFILL_EXHAUSTED",
          under3 and outcome3["reason"] == "PARSE_OR_REFILL_EXHAUSTED",
          str(outcome3))

    def only_invalid(_prompt):
        return json.dumps([{"size": 8, "pattern": "extreme_values",
                            "pattern_params": {}, "rationale": "banned"}])

    _a, _d, under4, outcome4 = gen.generate_for_benchmark(
        only_invalid, benchmark, "prompt", "baseline", settings, {benchmark},
        "glm_5_2", retained_specs=retained, replacement_budget=2)
    check("an exhausted admissible space is classified CAPABILITY_LIMITED",
          under4 and outcome4["reason"] == "CAPABILITY_LIMITED", str(outcome4))


# ---------------------------------------------------------------------------
# 5. fail-closed result-reuse boundary
# ---------------------------------------------------------------------------

def group_result_reuse_boundary():
    print("a resumed run cannot keep results from another policy")
    import inspect
    from thesis.evaluation import run_enhanced_tests as runner

    source = inspect.getsource(runner.main)
    check("resume compares the recorded enhanced policy hash",
          "RESUME REFUSED" in source and "enhanced_policy_provenance" in source)
    check("the mismatch path exits instead of reusing",
          "sys.exit(3)" in source)

    lines = source.splitlines()
    guard = next((i for i, l in enumerate(lines) if "RESUME REFUSED" in l), None)
    skip = next((i for i, l in enumerate(lines) if "skipping those" in l), None)
    check("the guard runs before the resume set is announced/used",
          guard is not None and skip is not None and guard < skip,
          "guard=%s skip=%s" % (guard, skip))

    # the gate cache is per-process, so it cannot carry a stale verdict across
    # runs; only the records file can, and that is what the guard covers
    check("the baseline gate cache is per-process, not persisted",
          "gate_cache: \"dict[tuple, str]\" = {}" in source)


def group_reexecution_set():
    print("re-execution and regeneration stay separate")
    from thesis.enhanced_tests.classify_specs_e2b import drift_reason
    manifest_path = (REPO_ROOT / "thesis" / "enhanced_tests"
                     / "enhanced_e3_regeneration_manifest.json")
    if not manifest_path.exists():
        check("E3 manifest present", False, str(manifest_path))
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    new_keys = {e["spec_key"] for e in manifest["replacement_specs"]}
    reexec_keys = {e["spec_key"] for e in manifest["requires_reexecution"]}

    check("the re-execution set contains no newly generated spec",
          reexec_keys.isdisjoint(new_keys), str(sorted(reexec_keys & new_keys)[:3]))
    check("every re-execution entry is flagged requires_reexecution",
          all(e["requires_reexecution"] for e in manifest["requires_reexecution"]))
    check("every replacement is flagged replacement_for_invalid",
          all(e["generation_reason"] == "replacement_for_invalid"
              for e in manifest["replacement_specs"]))

    # The E2-B classifier's drift map is pattern-based, so re-running it over the
    # POST-E3 cache also flags newly generated spike_at/ramp specs. Those were
    # produced UNDER the current semantics and have never been executed, so they
    # cannot have drifted: re-execution applies only to retained history.
    specs = load_cache()
    drifted_now = [s for s in specs if drift_reason(s["benchmark"], s["pattern"])]
    historical = [s for s in drifted_now if repr(spec_key(s)) not in new_keys]
    check("the manifest re-execution set is exactly the historical drifted set",
          reexec_keys == {repr(spec_key(s)) for s in historical},
          "%d vs %d" % (len(reexec_keys), len(historical)))
    check("no regeneration is outstanding after E3",
          manifest["replacement_shortfall"] == 0
          and manifest["final_checks"]["FINAL_INVALID_SPEC_COUNT"] == 0)


def main():
    groups = (group_final_cache, group_no_fake_diversity, group_retention,
              group_replacement_path, group_result_reuse_boundary,
              group_reexecution_set)
    for group in groups:
        group()
        print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All %d E3 cache test groups passed." % len(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
