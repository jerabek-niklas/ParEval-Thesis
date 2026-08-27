#!/usr/bin/env python3
"""Pilot preflight: runtime condition check REQUIRED before pilot_002.

The cross-pilot gate (cross_pilot_comparability.json) freezes the EXPECTED
evaluation/invocation/environment condition. This tool compares an ACTUAL
planned invocation and the ACTUAL runtime environment against it. The
repo-state checker (check_cross_pilot_gate.py) can never do this - a CLI
default is not the same thing as a future actual invocation.

Usage:
    python thesis/evaluation/pilot_preflight.py \
        --invocation <invocation.json> --environment <environment.json>

invocation.json describes the EFFECTIVE values the pilot run will use
(after applying any CLI overrides), at minimum:
    {"primary_compiler": "g++", "run_timeout_seconds": 120.0}

environment.json describes the ACTUAL runtime environment, captured inside
the execution container immediately before the run, at minimum:
    {"primary_compiler_version": "<first line of `g++ --version`>",
     "mpi_version_line": "<first line of `mpirun --version`>",
     "container_image_id_or_digest": "<docker image ID or repo digest>"}

Semantics (frozen in the gate's pilot_preflight block):
  PILOT_CONDITION_MATCH    true only if every verdict-relevant effective
                           invocation value equals the frozen expected value.
  PILOT_ENVIRONMENT_MATCH  true only if every expected environment value is
                           present and matches. A MISSING actual value is
                           UNRESOLVED, never a match. The container identity
                           must be RECORDED (non-empty) - the gate's pinning
                           classification is TAG_ONLY, so a concrete runtime
                           image ID/digest is mandatory evidence; it is
                           compared against the gate only if the gate stores
                           one, otherwise it is captured as new provenance.
  Result:
    exit 0  repo gate fresh AND both matches true      -> pilot authorized
            (by THIS gate; other open blockers still apply)
    exit 1  any mismatch                               -> pilot_002_not_authorized,
            CROSS_PILOT_GATE_STALE = true (re-evaluation required)
    exit 2  UNRESOLVED (missing provenance/inputs)     -> pilot_002_not_authorized

A mismatch does NOT produce a new comparability classification; it blocks
the pilot until the difference is re-evaluated. Read-only: writes nothing.
"""

import argparse
import json
import sys
from pathlib import Path

import check_cross_pilot_gate as repo_gate

GATE_PATH = repo_gate.GATE_PATH


def load_json(path):
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--invocation", required=True,
                    help="JSON file with the EFFECTIVE invocation values")
    ap.add_argument("--environment", required=True,
                    help="JSON file with the ACTUAL runtime environment values")
    ap.add_argument("--skip-repo-check", action="store_true",
                    help="skip the repo-state gate check (testing only)")
    args = ap.parse_args()

    gate = load_json(GATE_PATH)
    if gate is None:
        print("ERROR: gate artifact missing: %s" % GATE_PATH)
        return 2

    mismatch = False
    unresolved = False

    # ---- 0. repo-state gate ----
    if args.skip_repo_check:
        print("REPO_STATE_CHECK: skipped (--skip-repo-check; testing only)")
    else:
        print("REPO_STATE_CHECK")
        rc = repo_gate.main()
        if rc == 1:
            mismatch = True
        elif rc == 2:
            unresolved = True

    # ---- 1. effective invocation ----
    print("PILOT_INVOCATION_CHECK")
    inv = load_json(args.invocation)
    pol = (gate.get("effective_invocation_policy") or {})
    overrides = pol.get("verdict_relevant_cli_overrides") or {}
    cond_match = True
    if inv is None:
        print("  UNRESOLVED (invocation file missing/unreadable)")
        unresolved = True
        cond_match = None
    elif not overrides:
        print("  UNRESOLVED (gate stores no verdict_relevant_cli_overrides)")
        unresolved = True
        cond_match = None
    else:
        for key, spec in overrides.items():
            expected = spec.get("expected")
            actual = inv.get(key)
            if actual is None:
                print("  %s: UNRESOLVED (effective value not provided)" % key)
                unresolved = True
                cond_match = None if cond_match else cond_match
            elif actual != expected:
                print("  %s: MISMATCH (effective %r != expected %r)"
                      % (key, actual, expected))
                mismatch = True
                cond_match = False
            else:
                print("  %s: ok (effective %r)" % (key, actual))
    print("PILOT_CONDITION_MATCH = %s"
          % ("UNRESOLVED" if cond_match is None else str(cond_match).lower()))

    # ---- 2. runtime environment ----
    print("PILOT_ENVIRONMENT_CHECK")
    envfile = load_json(args.environment)
    expected_env = (gate.get("environment_condition") or {}).get("expected") or {}
    env_match = True
    if envfile is None:
        print("  UNRESOLVED (environment file missing/unreadable)")
        unresolved = True
        env_match = None
    elif not expected_env:
        print("  UNRESOLVED (gate stores no environment_condition.expected)")
        unresolved = True
        env_match = None
    else:
        for key in ("primary_compiler_version", "mpi_version_line"):
            expected = expected_env.get(key)
            actual = envfile.get(key)
            if expected is None:
                print("  %s: UNRESOLVED (no expected value in gate)" % key)
                unresolved = True
                env_match = None if env_match else env_match
            elif actual is None:
                print("  %s: UNRESOLVED (actual runtime value not provided - "
                      "missing provenance is never a match)" % key)
                unresolved = True
                env_match = None if env_match else env_match
            elif expected not in actual and actual != expected:
                print("  %s: MISMATCH (actual %r vs expected %r)"
                      % (key, actual, expected))
                mismatch = True
                env_match = False
            else:
                print("  %s: ok" % key)
        actual_img = envfile.get("container_image_id_or_digest")
        stored_img = (expected_env.get("container") or {}).get("image_digest_or_id")
        if not actual_img:
            print("  container_image_id_or_digest: UNRESOLVED (not provided - "
                  "the gate's pinning is %s, so a concrete runtime image "
                  "ID/digest is mandatory evidence)"
                  % ((expected_env.get("container") or {}).get("pinning")))
            unresolved = True
            env_match = None if env_match else env_match
        elif stored_img:
            if actual_img != stored_img:
                print("  container_image_id_or_digest: MISMATCH (%r != stored %r)"
                      % (actual_img, stored_img))
                mismatch = True
                env_match = False
            else:
                print("  container_image_id_or_digest: ok")
        else:
            print("  container_image_id_or_digest: recorded (%s) - no digest "
                  "frozen in the gate yet (pinning %s); persist this value as "
                  "run provenance" % (actual_img,
                                      (expected_env.get("container") or {}).get("pinning")))
    print("PILOT_ENVIRONMENT_MATCH = %s"
          % ("UNRESOLVED" if env_match is None else str(env_match).lower()))

    # ---- verdict ----
    if mismatch:
        print("\nRESULT: pilot_002_not_authorized (mismatch -> "
              "CROSS_PILOT_GATE_STALE = true; comparability_re_evaluation_"
              "required - no automatic reclassification)")
        return 1
    if unresolved:
        print("\nRESULT: pilot_002_not_authorized (UNRESOLVED runtime "
              "provenance - missing evidence is never a match)")
        return 2
    print("\nRESULT: pilot condition and environment match the frozen gate "
          "(this preflight authorizes ONLY the cross-pilot condition; other "
          "documented open blockers before pilot_002 remain)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
