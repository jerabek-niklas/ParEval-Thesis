#!/usr/bin/env python3
"""E3.1 tests: frozen artifacts, canonical mutation frontier and the
fail-closed enhanced execution-resume boundary.

The resume matrix is the point of this file. Before E3.1 a resumed run could
keep a record produced under a different spec cache, harness, benchmark oracle
or driver, because `spec_key` encodes none of that and only the policy hash was
compared. Every one of those drift classes must now refuse.

Run:  python thesis/enhanced_tests/test_e31_execution_provenance.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import execution_provenance as execprov  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    DEFAULT_SETTINGS,
    build_benchmark_specs,
    canonical_seed_identities,
    spec_key,
    validate_spec,
)

FROZEN = REPO_ROOT / "thesis" / "enhanced_tests" / "frozen"
PRE = FROZEN / "e3_pre_specs.jsonl"
FINAL = FROZEN / "e3_final_specs.jsonl"
FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


def load(path):
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def by_benchmark(rows):
    out = {}
    for spec in rows:
        out.setdefault(spec["benchmark"], []).append(spec)
    return out


def current_fingerprint():
    # toolchain omitted: it is machine-dependent and would make this test
    # depend on whether a compiler is installed
    return execprov.enhanced_execution_fingerprint(
        FINAL, dict(DEFAULT_SETTINGS), include_toolchain=False)


# ---------------------------------------------------------------------------
# 1. frozen artifacts
# ---------------------------------------------------------------------------

def group_frozen_artifacts():
    print("frozen execution artifacts are version controlled")
    check("pre-E3 snapshot exists", PRE.is_file())
    check("final E3 snapshot exists", FINAL.is_file())

    import hashlib
    check("final snapshot sha256 is the accepted E3 hash",
          hashlib.sha256(FINAL.read_bytes()).hexdigest()
          == "49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292")
    check("pre-E3 snapshot sha256 is the accepted pre-E3 hash",
          hashlib.sha256(PRE.read_bytes()).hexdigest()
          == "0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874")

    final = load(FINAL)
    check("final snapshot holds 471 specs", len(final) == 471, str(len(final)))
    check("final snapshot keys are unique",
          len({spec_key(s) for s in final}) == 471)
    check("final snapshot covers 60 benchmarks",
          len({s["benchmark"] for s in final}) == 60)

    # the runner must default to the frozen artifact, not the ignored cache
    import inspect
    from thesis.evaluation import run_enhanced_tests as runner
    source = inspect.getsource(runner.parse_args)
    check("the runner defaults --specs to the frozen artifact",
          "frozen" in source and "e3_final_specs.jsonl" in source)
    check("the runner no longer defaults to the gitignored cache",
          "results\" / \"cache\"" not in source)


# ---------------------------------------------------------------------------
# 2. canonical mutation frontier
# ---------------------------------------------------------------------------

def group_canonical_frontier():
    print("the mutation frontier is built from unique valid seed identities")
    config = {"stages": {"enhanced_tests": {}}}
    pre_rows = load(PRE)
    known = {s["benchmark"] for s in pre_rows}
    pre_by = by_benchmark(pre_rows)

    # duplicate ROWS must not change anything any more
    duplicate_effect = []
    for benchmark, seeds in pre_by.items():
        deduped, seen = [], set()
        for spec in seeds:
            key = spec_key(spec)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(spec)
        if len(deduped) == len(seeds):
            continue
        raw = [spec_key(s) for s in build_benchmark_specs(benchmark, seeds, config)]
        ded = [spec_key(s) for s in build_benchmark_specs(benchmark, deduped, config)]
        if raw != ded:
            duplicate_effect.append(benchmark)
    check("duplicate rows can no longer change the derived suite",
          not duplicate_effect, str(duplicate_effect[:3]))

    # invalid seed rows must not breed
    invalid_effect = []
    for benchmark, seeds in pre_by.items():
        valid = [s for s in seeds if validate_spec(s, known)[0]]
        if len(valid) == len(seeds):
            continue
        raw = [spec_key(s) for s in build_benchmark_specs(benchmark, seeds, config)]
        val = [spec_key(s) for s in build_benchmark_specs(benchmark, valid, config)]
        if raw != val:
            invalid_effect.append(benchmark)
    check("invalid seed rows can no longer change the derived suite",
          not invalid_effect, str(invalid_effect[:3]))

    # the canonicalizer itself
    sample = pre_by["sparse_la/46_sparse_la_spmm"]
    canonical = canonical_seed_identities(sample, known)
    check("canonicalization keeps one object per spec_key",
          len({spec_key(s) for s in canonical}) == len(canonical))
    check("canonicalization drops invalid seeds",
          all(validate_spec(s, known)[0] for s in canonical))
    check("canonicalization preserves first-appearance order",
          [spec_key(s) for s in canonical]
          == sorted({spec_key(s) for s in canonical},
                    key=lambda k: [spec_key(x) for x in canonical].index(k)))

    # a duplicate whose FIRST serialization is invalid must not mask a later
    # valid one with the same identity
    valid_spec = {"benchmark": "dense_la/00_dense_la_lu_decomp", "size": 4,
                  "pattern": "random", "pattern_params": {}, "source": "llm",
                  "rationale": "valid"}
    invalid_twin = dict(valid_spec, pattern_params={"k": 1}, rationale="invalid twin")
    picked = canonical_seed_identities(
        [invalid_twin, valid_spec], {"dense_la/00_dense_la_lu_decomp"})
    check("an invalid first occurrence does not mask a later valid identity",
          len(picked) == 1 and picked[0]["rationale"] == "valid",
          str([p.get("rationale") for p in picked]))

    # and the frozen suite is untouched by all of this
    final_by = by_benchmark(load(FINAL))
    total = sum(len(build_benchmark_specs(b, final_by[b], config))
                for b in final_by)
    check("the frozen artifact still yields the same 1200-spec suite",
          total == 1200, str(total))


# ---------------------------------------------------------------------------
# 3. the resume matrix
# ---------------------------------------------------------------------------

def mutate(fingerprint, component, key, value):
    """A fingerprint with one component altered and the SHA recomputed."""
    other = copy.deepcopy(fingerprint)
    other["components"][component][key] = value
    other["enhanced_execution_fingerprint_sha256"] = execprov._canonical_hash({
        "fingerprint_version": other["fingerprint_version"],
        "components": other["components"],
    })
    return other


def group_resume_matrix():
    print("resume matrix: only an identical execution condition may skip rows")
    current = current_fingerprint()

    allowed, why = execprov.resume_allowed(current, current)
    check("1. identical provenance -> resume ACCEPTED", allowed, why)

    cases = [
        ("2. different policy", "B_policy", "enhanced_policy_sha256", "deadbeef"),
        ("4. different spec artifact SHA", "A_spec_set", "specs_sha256", "deadbeef"),
        ("5. changed enhanced-fill.hpp", "C_harness_sources",
         "drivers/cpp/enhanced-fill.hpp", "deadbeef"),
        ("6a. changed specs.py", "C_harness_sources",
         "thesis/enhanced_tests/specs.py", "deadbeef"),
        ("6b. changed capabilities.py", "C_harness_sources",
         "thesis/enhanced_tests/capabilities.py", "deadbeef"),
        ("7. changed benchmark cpu.cc/baseline.hpp", "E_benchmark_sources",
         "combined_sha256", "deadbeef"),
        ("8a. changed serial driver", "F_driver_sources",
         "drivers/cpp/models/serial-driver.cc", "deadbeef"),
        ("8b. changed build config", "F_driver_sources",
         "thesis/evaluation/build_config.py", "deadbeef"),
        ("8c. changed runner", "D_runner_sources",
         "thesis/evaluation/run_enhanced_tests.py", "deadbeef"),
        ("8d. changed effective config", "G_effective_config",
         "max_spec_size", 8192),
    ]
    for label, component, key, value in cases:
        recorded = mutate(current, component, key, value)
        allowed, why = execprov.resume_allowed(recorded, current)
        check("%s -> resume REFUSED" % label, not allowed, why)
        check("   %s names the differing component" % label.split(".")[0],
              component in why, why)

    allowed, why = execprov.resume_allowed(None, current)
    check("3a. missing provenance -> resume REFUSED", not allowed, why)
    allowed, why = execprov.resume_allowed({}, current)
    check("3b. empty provenance -> resume REFUSED", not allowed, why)
    allowed, why = execprov.resume_allowed(
        {"enhanced_policy_provenance": {"enhanced_policy_sha256": "x"}}, current)
    check("3c. policy-only provenance (pre-E3.1 record) -> resume REFUSED",
          not allowed, why)

    # the fingerprint must NOT depend on things that cannot change a result
    check("the fingerprint does not include the git HEAD",
          "head" not in json.dumps(current["components"]).lower())

    # and the runner must actually use this decision, before using `done`
    import inspect
    from thesis.evaluation import run_enhanced_tests as runner
    source = inspect.getsource(runner.main)
    # E3.1.1: the runner now calls the STRICTER per-model decision, which
    # embeds this global fingerprint plus the candidate source hashes. Assert
    # the property (a fingerprint-based resume decision that covers the global
    # condition), not the old function name.
    check("the runner uses a fingerprint-based resume decision",
          "execprov.model_resume_allowed(" in source
          or "execprov.resume_allowed(" in source)
    check("the per-model decision embeds the global execution fingerprint",
          "global_execution_fingerprint_sha256"
          in json.dumps(execprov.model_execution_fingerprint(
              current, {"model_id": "m", "combined_sha256": "x",
                        "sample_count": 0})))
    check("the refusal exits instead of skipping rows", "sys.exit(3)" in source)
    lines = source.splitlines()
    guard = next((i for i, l in enumerate(lines) if "RESUME REFUSED" in l), None)
    use = next((i for i, l in enumerate(lines) if "skipping those" in l), None)
    check("the guard runs before the resume set is used",
          guard is not None and use is not None and guard < use)


# ---------------------------------------------------------------------------
# 4. run manifest hard gate
# ---------------------------------------------------------------------------

def group_manifest_gate():
    print("run manifest fails closed on an execution-condition mismatch")
    from thesis.evaluation import run_manifest

    current = current_fingerprint()
    with tempfile.TemporaryDirectory() as tmp:
        config = {"outputs": {"intermediate_dir": tmp}, "stages": {}}
        run_manifest.ensure_run_manifest(
            config, "e31_test_run", stage="enhanced_tests",
            enhanced_execution=current)
        path = run_manifest.manifest_path(config, "e31_test_run")
        check("the manifest stores the execution provenance",
              path.is_file()
              and json.loads(path.read_text(encoding="utf-8"))
              .get("enhanced_execution", {})
              .get("enhanced_execution_fingerprint_sha256")
              == current["enhanced_execution_fingerprint_sha256"])

        # same fingerprint: fine
        ok = True
        try:
            run_manifest.ensure_run_manifest(
                config, "e31_test_run", stage="enhanced_tests",
                enhanced_execution=current)
        except run_manifest.EnhancedExecutionConditionMismatch:
            ok = False
        check("9a. same fingerprint -> manifest accepts the continuation", ok)

        # different fingerprint: hard fail
        drifted = mutate(current, "A_spec_set", "specs_sha256", "deadbeef")
        raised = False
        try:
            run_manifest.ensure_run_manifest(
                config, "e31_test_run", stage="enhanced_tests",
                enhanced_execution=drifted)
        except run_manifest.EnhancedExecutionConditionMismatch as error:
            raised = "fresh run_id" in str(error)
        check("9b. different fingerprint -> manifest HARD FAILS", raised)

        # a manifest that predates the fingerprint is not silently backfilled
        legacy_config = {"outputs": {"intermediate_dir": tmp}, "stages": {}}
        run_manifest.ensure_run_manifest(
            legacy_config, "e31_legacy_run", stage="enhanced_tests")
        raised = False
        try:
            run_manifest.ensure_run_manifest(
                legacy_config, "e31_legacy_run", stage="enhanced_tests",
                enhanced_execution=current)
        except run_manifest.EnhancedExecutionConditionMismatch:
            raised = True
        check("9c. a pre-E3.1 manifest is not backfilled-and-reused", raised)


def main():
    groups = (group_frozen_artifacts, group_canonical_frontier,
              group_resume_matrix, group_manifest_gate)
    for group in groups:
        group()
        print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All %d E3.1 execution-provenance test groups passed." % len(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
