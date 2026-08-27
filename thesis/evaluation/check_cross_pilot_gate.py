#!/usr/bin/env python3
"""Staleness check for the cross-pilot comparability gate.

Recomputes the candidate-subset state fingerprints stored in
thesis/evaluation/cross_pilot_comparability.json under the SAME canonical
hash rules used at gate-creation time and compares them.

Hash rules (authoritative; any later audit must reproduce exactly these):
  cpu_cc_sha256        SHA-256 over the RAW BYTES of
                       drivers/cpp/benchmarks/<problem_type>/<name>/cpu.cc
  baseline_hpp_sha256  SHA-256 over the RAW BYTES of
                       drivers/cpp/benchmarks/<problem_type>/<name>/baseline.hpp
  prompt_sha256.<pm>   SHA-256 over the UTF-8 encoding of the full `prompt`
                       string of the entry in
                       thesis/prompts/generation-prompts-thesis.json matched by
                       the stable identity (problem_type, name,
                       parallelism_model). Array positions are never join keys.
  enhanced_spec_keys_sha256
                       Benchmark-local projection of
                       thesis/results/cache/enhanced/specs.jsonl: take every
                       raw line whose parsed JSON object has
                       obj["benchmark"] == "<problem_type>/<name>", strip one
                       trailing "\\n" / "\\r\\n" from the line, sort the lines
                       lexicographically as Unicode strings, join with "\\n",
                       SHA-256 over the UTF-8 encoding of the joined string.
                       (Benchmark-local by construction: edits to specs of
                       OTHER benchmarks do not change this hash.)

Semantics of the result (frozen in the gate artifact's validity block):
  all stored hashes reproducible and equal      -> CROSS_PILOT_GATE_STALE = false
  at least one reproducible hash differs        -> CROSS_PILOT_GATE_STALE = true
                                                   (comparability_re_evaluation_required;
                                                   a hash diff does NOT by itself
                                                   yield a new classification)
  a stored non-null state no longer addressable -> CROSS_PILOT_GATE_STALE = UNRESOLVED
A stored null hash (state documented as unavailable at creation time) is
skipped, never treated as a mismatch.

Exit codes: 0 = fresh (false), 1 = stale (true), 2 = UNRESOLVED / infra error.

Read-only: this script never writes anything.
"""

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "thesis" / "evaluation" / "cross_pilot_comparability.json"
PROMPTS_PATH = REPO_ROOT / "thesis" / "prompts" / "generation-prompts-thesis.json"
SPECS_PATH = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"
BENCH_ROOT = REPO_ROOT / "drivers" / "cpp" / "benchmarks"

PM_CANON = ("serial", "omp", "mpi")


def sha256_file_bytes(path: Path):
    """Raw-byte hash; None if the file does not exist."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_prompt_hashes():
    """(problem_type, name, parallelism_model) -> sha256(utf-8 prompt)."""
    entries = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    out = {}
    for e in entries:
        key = (e["problem_type"], e["name"], e["parallelism_model"])
        out[key] = hashlib.sha256(e["prompt"].encode("utf-8")).hexdigest()
    return out


def enhanced_spec_hash(benchmark: str):
    """Canonical benchmark-local spec projection hash; None if the specs file
    is absent. An empty projection (no lines for the benchmark) hashes the
    empty string - a stable, meaningful state of its own."""
    if not SPECS_PATH.is_file():
        return None
    lines = []
    with SPECS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip("\r\n")
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except ValueError:
                continue
            if obj.get("benchmark") == benchmark:
                lines.append(stripped)
    lines.sort()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def recompute_state(benchmark: str):
    """Recompute all fingerprints for one '<problem_type>/<name>' id."""
    pt, name = benchmark.split("/", 1)
    bench_dir = BENCH_ROOT / pt / name
    prompt_hashes = load_prompt_hashes()
    prompts = {}
    for pm in PM_CANON:
        prompts[pm] = prompt_hashes.get((pt, name, pm))
    return {
        "benchmark": benchmark,
        "cpu_cc_sha256": sha256_file_bytes(bench_dir / "cpu.cc"),
        "baseline_hpp_sha256": sha256_file_bytes(bench_dir / "baseline.hpp"),
        "prompt_sha256": prompts,
        "enhanced_spec_keys_sha256": enhanced_spec_hash(benchmark),
    }


def main() -> int:
    if not GATE_PATH.is_file():
        print("ERROR: gate artifact missing: %s" % GATE_PATH)
        return 2

    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    stored_states = gate.get("candidate_subset_state", [])
    if not stored_states:
        print("ERROR: gate artifact has no candidate_subset_state")
        return 2

    stale = False
    unresolved = False
    for stored in stored_states:
        bench = stored["benchmark"]
        current = recompute_state(bench)
        for field in ("cpu_cc_sha256", "baseline_hpp_sha256",
                      "enhanced_spec_keys_sha256"):
            old, new = stored.get(field), current[field]
            if old is None:
                print("%s %s: stored null (unavailable at creation) - skipped"
                      % (bench, field))
                continue
            if new is None:
                print("%s %s: UNRESOLVED (source no longer addressable)"
                      % (bench, field))
                unresolved = True
            elif old != new:
                print("%s %s: STALE (stored %s... != current %s...)"
                      % (bench, field, old[:12], new[:12]))
                stale = True
            else:
                print("%s %s: ok" % (bench, field))
        for pm in PM_CANON:
            old = (stored.get("prompt_sha256") or {}).get(pm)
            new = current["prompt_sha256"][pm]
            label = "%s prompt_sha256.%s" % (bench, pm)
            if old is None:
                print("%s: stored null - skipped" % label)
            elif new is None:
                print("%s: UNRESOLVED (identity no longer present)" % label)
                unresolved = True
            elif old != new:
                print("%s: STALE" % label)
                stale = True
            else:
                print("%s: ok" % label)

    if stale:
        print("\nCROSS_PILOT_GATE_STALE = true")
        print("-> comparability_re_evaluation_required (a hash diff does not"
              " by itself produce a new comparability classification)")
        return 1
    if unresolved:
        print("\nCROSS_PILOT_GATE_STALE = UNRESOLVED")
        return 2
    print("\nCROSS_PILOT_GATE_STALE = false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
