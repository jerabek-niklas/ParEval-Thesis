#!/usr/bin/env python3
"""The enhanced EXECUTION CONDITION, content-addressed.

A recorded enhanced result is the output of a specific spec set, a specific
policy, a specific harness, specific benchmark oracles, specific drivers and a
specific effective configuration. `spec_key` encodes none of that, so resume
keyed on `(sample_id, spec_key)` alone can silently keep a result that the
current tree would no longer produce. E3 closed the policy half of that gap;
this module closes the rest.

`enhanced_execution_fingerprint()` returns a canonical JSON structure plus its
SHA-256 over these components:

    A  spec set          actual specs-file SHA-256, distinct spec count,
                         benchmark count
    B  policy            enforced policy SHA-256, capability catalog SHA-256,
                         derivation version
    C  enhanced input /  drivers/cpp/enhanced-fill.hpp, drivers/cpp/utilities.hpp,
       harness source    thesis/enhanced_tests/specs.py,
                         thesis/enhanced_tests/capabilities.py
    D  runner            thesis/evaluation/run_enhanced_tests.py
    E  benchmark sources per-benchmark cpu.cc + baseline.hpp hashes, plus one
                         combined canonical hash
    F  driver sources    the serial/omp/mpi drivers and the shared harness
                         headers the build actually uses
    G  effective config  the execution-relevant enhanced settings
    H  toolchain         compiler (and MPI, when an MPI model runs) identity,
                         taken from the existing run_manifest helpers - no new
                         environment subsystem

Everything is CONTENT-addressed. No mtime, no bare path, no git HEAD: a README
commit must not invalidate a resume. The git HEAD is recorded alongside as
provenance, but is deliberately NOT part of the fingerprint.

Read-only. Python 3.8 compatible.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402

FINGERPRINT_VERSION = "e3.1"

# C: the enhanced input construction and its policy layer
HARNESS_SOURCES = (
    "drivers/cpp/enhanced-fill.hpp",
    "drivers/cpp/utilities.hpp",
    "thesis/enhanced_tests/specs.py",
    "thesis/enhanced_tests/capabilities.py",
)

# D: the productive enhanced runner
RUNNER_SOURCES = (
    "thesis/evaluation/run_enhanced_tests.py",
)

# F: what the enhanced build actually compiles besides the benchmark
DRIVER_SOURCES = (
    "drivers/cpp/models/serial-driver.cc",
    "drivers/cpp/models/omp-driver.cc",
    "drivers/cpp/models/mpi-driver.cc",
    "drivers/cpp/harness-markers.hpp",
    "thesis/evaluation/build_config.py",
)

# G: the enhanced settings that can change what a result MEANS
EXECUTION_RELEVANT_SETTINGS = (
    "execution_models",
    "enhanced_launch",
    "max_spec_size",
    "target_cases_per_benchmark",
    "static_base_sizes",
    "offered_patterns",
    "explicit_values_max_size",
    "llm_specs_min",
    "llm_specs_max",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> Optional[str]:
    return _sha256_bytes(path.read_bytes()) if path.is_file() else None


def _canonical_hash(obj: Any) -> str:
    """SHA-256 over a canonical JSON encoding (sorted keys, no whitespace)."""
    return _sha256_bytes(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8"))


def _source_hashes(relative_paths):
    out = OrderedDict()
    for relative in relative_paths:
        out[relative] = _sha256_path(REPO_ROOT / relative)
    return out


def benchmark_source_hashes():
    """E: cpu.cc + baseline.hpp of every benchmark the policy governs."""
    per_benchmark = OrderedDict()
    for benchmark in capabilities.policy_benchmarks():
        directory = REPO_ROOT / "drivers" / "cpp" / "benchmarks" / benchmark
        per_benchmark[benchmark] = OrderedDict([
            ("cpu_cc_sha256", _sha256_path(directory / "cpu.cc")),
            ("baseline_hpp_sha256", _sha256_path(directory / "baseline.hpp")),
        ])
    return per_benchmark


def _toolchain(primary_compiler="g++", execution_models=()):
    """H: reuse the existing run_manifest helpers; invent nothing."""
    entry = OrderedDict()
    try:
        from thesis.evaluation import run_manifest
        entry["primary_compiler"] = primary_compiler
        entry["primary_compiler_version"] = run_manifest._compiler_version(
            primary_compiler)
    except Exception as error:  # noqa: BLE001 - reported, never invented
        entry["primary_compiler"] = primary_compiler
        entry["primary_compiler_version"] = None
        entry["unavailable_reason"] = "%s: %s" % (type(error).__name__, error)
    entry["mpi_in_execution_models"] = bool(
        {"mpi"} & set(execution_models or ()))
    return entry


def enhanced_execution_fingerprint(
    specs_path,
    settings: Dict[str, Any],
    primary_compiler: str = "g++",
    include_toolchain: bool = True,
) -> "Dict[str, Any]":
    """The full execution condition plus its content-addressed fingerprint."""
    specs_path = Path(specs_path)
    spec_rows = []
    if specs_path.is_file():
        spec_rows = [json.loads(line) for line
                     in specs_path.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
    from thesis.enhanced_tests.specs import spec_key
    distinct = len({spec_key(s) for s in spec_rows})

    policy = capabilities.policy_provenance()

    components = OrderedDict()
    components["A_spec_set"] = OrderedDict([
        ("specs_sha256", _sha256_path(specs_path)),
        ("spec_rows", len(spec_rows)),
        ("distinct_spec_keys", distinct),
        ("benchmark_count", len({s["benchmark"] for s in spec_rows})),
    ])
    components["B_policy"] = OrderedDict([
        ("enhanced_policy_sha256", policy["enhanced_policy_sha256"]),
        ("capability_catalog_sha256", policy["derived_from_sha256"]),
        ("derivation_version", policy["derivation_version"]),
    ])
    components["C_harness_sources"] = _source_hashes(HARNESS_SOURCES)
    components["D_runner_sources"] = _source_hashes(RUNNER_SOURCES)

    per_benchmark = benchmark_source_hashes()
    components["E_benchmark_sources"] = OrderedDict([
        ("benchmark_count", len(per_benchmark)),
        ("combined_sha256", _canonical_hash(per_benchmark)),
    ])
    components["F_driver_sources"] = _source_hashes(DRIVER_SOURCES)
    components["G_effective_config"] = OrderedDict(
        (key, settings.get(key)) for key in EXECUTION_RELEVANT_SETTINGS)
    if include_toolchain:
        components["H_toolchain"] = _toolchain(
            primary_compiler, settings.get("execution_models") or ())

    fingerprint = OrderedDict()
    fingerprint["fingerprint_version"] = FINGERPRINT_VERSION
    fingerprint["components"] = components
    fingerprint["enhanced_execution_fingerprint_sha256"] = _canonical_hash(
        OrderedDict([("fingerprint_version", FINGERPRINT_VERSION),
                     ("components", components)]))
    # provenance only - deliberately NOT part of the hash, so an unrelated
    # commit cannot invalidate a resume
    fingerprint["benchmark_source_hashes"] = per_benchmark
    return fingerprint


def fingerprint_sha(provenance) -> Optional[str]:
    """The fingerprint SHA out of a stored provenance block, or None."""
    if not isinstance(provenance, dict):
        return None
    return provenance.get("enhanced_execution_fingerprint_sha256")


def resume_allowed(recorded, current):
    """(allowed, reason). THE resume decision, in one place so it is testable.

    Fail-closed: a resume is allowed only when the recorded provenance carries
    exactly the current execution fingerprint. Missing provenance is a refusal,
    not a legacy exemption - a record without it carries no evidence of the
    condition it was produced under.
    """
    current_sha = (current or {}).get("enhanced_execution_fingerprint_sha256")
    recorded_sha = fingerprint_sha(recorded)
    if recorded_sha is None:
        return False, "no execution provenance recorded"
    if recorded_sha != current_sha:
        return False, "execution condition changed: " + describe_mismatch(
            recorded, current)
    return True, "execution condition unchanged"


def describe_mismatch(recorded, current) -> str:
    """Which component groups differ - for an actionable refusal message."""
    if not isinstance(recorded, dict) or "components" not in recorded:
        return "no execution provenance recorded"
    old = recorded.get("components") or {}
    new = (current or {}).get("components") or {}
    differing = [name for name in sorted(set(old) | set(new))
                 if old.get(name) != new.get(name)]
    return ", ".join(differing) if differing else "fingerprint differs"


def main():
    import argparse
    from thesis.config.load_config import load_config
    from thesis.enhanced_tests.specs import stage_settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(REPO_ROOT / "thesis" / "config" / "config.yaml"))
    ap.add_argument("--specs", default=str(
        REPO_ROOT / "thesis" / "enhanced_tests" / "frozen" / "e3_final_specs.jsonl"))
    ap.add_argument("--no-toolchain", action="store_true",
                    help="omit component H (for reproducible cross-machine checks)")
    args = ap.parse_args()

    settings = stage_settings(load_config(Path(args.config).resolve()))
    fingerprint = enhanced_execution_fingerprint(
        args.specs, settings, include_toolchain=not args.no_toolchain)
    printable = OrderedDict(
        (k, v) for k, v in fingerprint.items() if k != "benchmark_source_hashes")
    print(json.dumps(printable, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
