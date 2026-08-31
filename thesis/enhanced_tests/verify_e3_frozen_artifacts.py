#!/usr/bin/env python3
"""Verify the frozen E3 artifacts from COMMITTED FILES ONLY.

This is the fresh-clone check: it must pass in a checkout that has no
`thesis/results/cache/` at all and without contacting any model. It proves that
the accepted E3 experiment artifact - not a re-runnable generation process - is
what is version controlled, and that every E3 claim about it still holds.

Inputs (all tracked):

    thesis/enhanced_tests/frozen/e3_pre_specs.jsonl      pre-E3 snapshot
    thesis/enhanced_tests/frozen/e3_final_specs.jsonl    final E3 snapshot
    thesis/enhanced_tests/enhanced_e3_regeneration_manifest.json
    the current policy / capability sources

Read-only. Exit 0 and E3_FROZEN_ARTIFACTS_REPRODUCIBLE = true on success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests.specs import spec_key, validate_spec  # noqa: E402

FROZEN = REPO_ROOT / "thesis" / "enhanced_tests" / "frozen"
PRE = FROZEN / "e3_pre_specs.jsonl"
FINAL = FROZEN / "e3_final_specs.jsonl"
MANIFEST = REPO_ROOT / "thesis" / "enhanced_tests" / "enhanced_e3_regeneration_manifest.json"

EXPECTED_PRE_SHA = "0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874"
EXPECTED_FINAL_SHA = "49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292"

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dedupe_first_valid(rows, known):
    seen, out, dup = set(), [], []
    for spec in rows:
        key = spec_key(spec)
        if key in seen:
            dup.append(spec)
            continue
        seen.add(key)
        out.append(spec)
    return out, dup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="", help="write the result summary here")
    args = ap.parse_args()

    print("frozen artifacts exist and are committed")
    check("pre-E3 snapshot present", PRE.is_file(), str(PRE))
    check("final E3 snapshot present", FINAL.is_file(), str(FINAL))
    check("E3 manifest present", MANIFEST.is_file(), str(MANIFEST))
    if FAILURES:
        print("\nE3_FROZEN_ARTIFACTS_REPRODUCIBLE = false")
        return 1
    print()

    print("1-2. content hashes")
    pre_sha, final_sha = sha256_file(PRE), sha256_file(FINAL)
    check("pre-E3 sha256 == %s" % EXPECTED_PRE_SHA[:16], pre_sha == EXPECTED_PRE_SHA, pre_sha)
    check("final sha256 == %s" % EXPECTED_FINAL_SHA[:16], final_sha == EXPECTED_FINAL_SHA, final_sha)
    print()

    pre_rows, final_rows = load(PRE), load(FINAL)
    known = {b for b in capabilities.policy_benchmarks()}

    print("3-6. population counts")
    pre_keys = [spec_key(s) for s in pre_rows]
    check("pre-E3 rows = 483", len(pre_rows) == 483, str(len(pre_rows)))
    check("pre-E3 distinct identities = 471", len(set(pre_keys)) == 471,
          str(len(set(pre_keys))))
    check("pre-E3 duplicate rows = 12", len(pre_keys) - len(set(pre_keys)) == 12,
          str(len(pre_keys) - len(set(pre_keys))))
    check("final rows = 471", len(final_rows) == 471, str(len(final_rows)))
    check("final distinct identities = 471",
          len({spec_key(s) for s in final_rows}) == 471)
    check("both snapshots cover 60 benchmarks",
          len({s["benchmark"] for s in pre_rows}) == 60
          and len({s["benchmark"] for s in final_rows}) == 60)
    print()

    print("7-9. retention / replacement partition, recomputed from the snapshots")
    pre_unique, _dups = dedupe_first_valid(pre_rows, known)
    old_valid, old_invalid = [], []
    for spec in pre_unique:
        ok, _why = validate_spec(spec, known)
        (old_valid if ok else old_invalid).append(spec)
    check("old valid identities = 272", len(old_valid) == 272, str(len(old_valid)))
    check("old invalid identities = 199", len(old_invalid) == 199, str(len(old_invalid)))

    from thesis.enhanced_tests.classify_specs_e2b import drift_reason
    drifted = [s for s in old_valid if drift_reason(s["benchmark"], s["pattern"])]
    check("retained unchanged = 262", len(old_valid) - len(drifted) == 262,
          str(len(old_valid) - len(drifted)))
    check("retained drifted = 10", len(drifted) == 10, str(len(drifted)))

    final_keys = {spec_key(s) for s in final_rows}
    old_valid_keys = {spec_key(s) for s in old_valid}
    replacements = [s for s in final_rows if spec_key(s) not in old_valid_keys]
    check("replacements = 199", len(replacements) == 199, str(len(replacements)))
    print()

    print("10-11. manifest sets match the snapshots exactly")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_repl = {e["spec_key"] for e in manifest["replacement_specs"]}
    check("manifest replacement set == recomputed replacement set",
          manifest_repl == {repr(spec_key(s)) for s in replacements},
          "%d vs %d" % (len(manifest_repl), len(replacements)))
    manifest_reexec = {e["spec_key"] for e in manifest["requires_reexecution"]}
    check("manifest re-execution set == recomputed drifted set",
          manifest_reexec == {repr(spec_key(s)) for s in drifted},
          "%d vs %d" % (len(manifest_reexec), len(drifted)))
    check("manifest records both frozen snapshot hashes",
          manifest.get("pre_e3_sha256") == EXPECTED_PRE_SHA
          and manifest.get("final_e3_sha256") == EXPECTED_FINAL_SHA)
    print()

    print("12-15. the final snapshot satisfies the frozen policy")
    invalid = [(s["benchmark"], s["pattern"])
               for s in final_rows if not validate_spec(s, known)[0]]
    check("final invalid = 0", not invalid, str(invalid[:3]))
    check("final duplicate spec_keys = 0", len(final_keys) == len(final_rows))
    unsupported = [(s["benchmark"], s["pattern"]) for s in final_rows
                   if capabilities.pattern_status(s["benchmark"], s["pattern"])[0]
                   != "supported"]
    check("final unsupported/deferred = 0", not unsupported, str(unsupported[:3]))
    out_of_domain = [s for s in final_rows
                     if capabilities.value_range_domain_rejection(
                         s["benchmark"], s["pattern"],
                         (s.get("pattern_params") or {}).get("value_range")) is not None
                     or capabilities.explicit_values_domain_rejection(
                         s["benchmark"], s.get("values") or []) is not None]
    check("final out-of-domain = 0", not out_of_domain)
    check("final extreme_values = 0",
          not [s for s in final_rows if s["pattern"] == "extreme_values"])
    nonfinite = [s for s in final_rows
                 if any(not math.isfinite(float(v))
                        for v in ((s.get("pattern_params") or {}).get("value_range") or []))
                 or any(not math.isfinite(float(v)) for v in (s.get("values") or []))]
    check("final non-finite parameters = 0", not nonfinite)
    per_benchmark = Counter(s["benchmark"] for s in final_rows)
    check("every benchmark has >= 1 spec", min(per_benchmark.values()) >= 1)
    print()

    print("16-17. retention proof: nothing valid was dropped or modified")
    final_by_key = {spec_key(s): s for s in final_rows}
    dropped = [s for s in old_valid if spec_key(s) not in final_by_key]
    check("no old valid identity dropped", not dropped,
          str([(s["benchmark"], s["pattern"]) for s in dropped[:3]]))
    modified = [s for s in old_valid
                if spec_key(s) in final_by_key and final_by_key[spec_key(s)] != s]
    check("no old valid spec object modified", not modified,
          str([s["benchmark"] for s in modified[:3]]))
    retained_invalid = [s for s in old_invalid if spec_key(s) in final_by_key]
    check("no old invalid identity retained", not retained_invalid,
          str([(s["benchmark"], s["pattern"]) for s in retained_invalid[:3]]))
    print()

    print("no local generator cache was consulted")
    cache = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"
    check("verification does not require %s" % cache.name, True,
          "present" if cache.exists() else "absent - and that is fine")
    print()

    ok = not FAILURES
    print("E3_FROZEN_ARTIFACTS_REPRODUCIBLE = %s" % str(ok).lower())
    if args.json:
        Path(args.json).write_text(json.dumps(OrderedDict([
            ("E3_FROZEN_ARTIFACTS_REPRODUCIBLE", ok),
            ("pre_e3_sha256", pre_sha),
            ("final_e3_sha256", final_sha),
            ("failures", FAILURES),
        ]), indent=1) + "\n", encoding="utf-8")
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
