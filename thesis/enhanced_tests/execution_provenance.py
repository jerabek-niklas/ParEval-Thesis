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
    G  effective config  the execution-relevant enhanced settings PLUS the two
                         values the runner resolves separately and that can
                         change a record on their own: the effective
                         run_timeout_seconds and the effective jobs map after
                         the CLI override is merged in
    H  toolchain         compiler identity, and - only when an MPI execution
                         model actually runs - the MPI compiler and runtime
                         identity, via the existing run_manifest helpers. No
                         new environment subsystem.

The GLOBAL fingerprint above covers everything that is shared across models.
The tested CANDIDATE CODE is per model, so it is fingerprinted separately:

    candidate_source_fingerprint()   hashes the actual assembled source BYTES of
                                     every assembled sample of one model, via
                                     the productive framework discovery path
    model_execution_fingerprint()    global fingerprint + that model's candidate
                                     fingerprint

`sample_id` is a NAME, not a content address
(`<model><type><name>__<exec>_sample<i>`), so two different generated programs
can carry the same one. Resume therefore compares the MODEL execution
fingerprint, which contains the source hashes.

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

FINGERPRINT_VERSION = "e3.1.1"

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


# the MPI tools whose identity can change an MPI result
MPI_COMPILER = "mpicxx"
MPI_RUNTIME = "mpirun"


def _tool_version(tool):
    """`<tool> --version`, first line, via the existing run_manifest helper.

    Returns None when the tool is absent - never a made-up string. A productive
    MPI run cannot get past the runner's environment gate in that state anyway.
    """
    try:
        from thesis.evaluation import run_manifest
        return run_manifest._compiler_version(tool)
    except Exception:  # noqa: BLE001 - absence is reported, never invented
        return None


def _toolchain(primary_compiler="g++", execution_models=()):
    """H: reuse the existing run_manifest helpers; invent nothing.

    MPI identity is included ONLY when an MPI execution model actually runs, so
    a serial-only run does not become dependent on an unused MPI installation.
    """
    entry = OrderedDict()
    entry["primary_compiler"] = primary_compiler
    entry["primary_compiler_version"] = _tool_version(primary_compiler)

    models = set(execution_models or ())
    mpi_used = bool({"mpi"} & models)
    entry["mpi_in_execution_models"] = mpi_used
    if mpi_used:
        entry["mpi_compiler"] = MPI_COMPILER
        entry["mpi_compiler_version"] = _tool_version(MPI_COMPILER)
        entry["mpi_runtime"] = MPI_RUNTIME
        entry["mpi_runtime_version"] = _tool_version(MPI_RUNTIME)
    return entry


def enhanced_execution_fingerprint(
    specs_path,
    settings: Dict[str, Any],
    runtime: "Optional[Dict[str, Any]]" = None,
    primary_compiler: str = "g++",
    include_toolchain: bool = True,
) -> "Dict[str, Any]":
    """The full GLOBAL execution condition plus its content-addressed fingerprint.

    `runtime` carries the values the runner resolves OUTSIDE `stage_settings`
    and that can change a record on their own:

        run_timeout_seconds  stages.enhanced_tests.run_timeout_seconds, else
                             the runner's DEFAULT_RUN_TIMEOUT. A different
                             timeout can turn the same program into
                             timeout vs. pass/fail.
        effective_jobs       the jobs map AFTER built-in defaults, config and
                             the --jobs CLI override are merged. Not a claim
                             that parallelism changes mathematical semantics -
                             an operational execution condition capable of
                             affecting timeout outcomes, which the runner's own
                             overcommit note already records.

    They are passed explicitly rather than read from `settings`, because
    `stage_settings` does not contain either.
    """
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
    runtime = dict(runtime or {})
    effective_config = OrderedDict(
        (key, settings.get(key)) for key in EXECUTION_RELEVANT_SETTINGS)
    effective_config["run_timeout_seconds"] = runtime.get("run_timeout_seconds")
    effective_jobs = runtime.get("effective_jobs")
    effective_config["effective_jobs"] = (
        OrderedDict(sorted(effective_jobs.items()))
        if isinstance(effective_jobs, dict) else effective_jobs)
    components["G_effective_config"] = effective_config
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


def candidate_source_fingerprint(intermediate_dir, run_id, model_id,
                                 repo_root=None) -> "Dict[str, Any]":
    """Content-address the CANDIDATE CODE that one model's samples actually run.

    Discovery goes through the productive path
    (`framework.iter_assembled_samples`, which consumes assembly.jsonl), so
    there is no second candidate-discovery logic. The hash is taken over the
    assembled SOURCE BYTES, not over `sample_id` and not over metadata:
    assembly.jsonl records no content hash, and local mutable metadata is not
    trusted for this.
    """
    from thesis.evaluation import framework

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    samples = []
    for sample in framework.iter_assembled_samples(
            root, Path(intermediate_dir), run_id, model_id):
        try:
            relative = sample.source_path.resolve().relative_to(root.resolve())
            logical = relative.as_posix()
        except ValueError:
            logical = sample.source_path.name
        samples.append(OrderedDict([
            ("sample_id", sample.sample_id),
            ("model_id", sample.model_id),
            ("execution_model", sample.execution_model),
            ("benchmark", "%s/%s" % (sample.problem_type, sample.name)),
            ("source_logical_path", logical),
            ("source_sha256", _sha256_path(sample.source_path)),
        ]))
    samples.sort(key=lambda row: row["sample_id"])

    entry = OrderedDict()
    entry["model_id"] = model_id
    entry["run_id"] = run_id
    entry["sample_count"] = len(samples)
    entry["missing_source_count"] = sum(
        1 for row in samples if row["source_sha256"] is None)
    entry["combined_sha256"] = _canonical_hash(samples)
    entry["samples"] = samples
    return entry


def model_execution_fingerprint(global_fingerprint, candidate_fingerprint):
    """The per-model condition a resume must match: global + candidate code."""
    payload = OrderedDict([
        ("fingerprint_version", FINGERPRINT_VERSION),
        ("global_execution_fingerprint_sha256",
         (global_fingerprint or {}).get("enhanced_execution_fingerprint_sha256")),
        ("model_id", (candidate_fingerprint or {}).get("model_id")),
        ("candidate_sources_sha256",
         (candidate_fingerprint or {}).get("combined_sha256")),
        ("candidate_sample_count",
         (candidate_fingerprint or {}).get("sample_count")),
    ])
    entry = OrderedDict(payload)
    entry["model_execution_fingerprint_sha256"] = _canonical_hash(payload)
    # kept beside the hash for auditability, not part of it
    entry["candidate_sources"] = candidate_fingerprint
    return entry


def model_fingerprint_sha(provenance) -> Optional[str]:
    if not isinstance(provenance, dict):
        return None
    return provenance.get("model_execution_fingerprint_sha256")


def model_resume_allowed(recorded, current):
    """(allowed, reason) for the PER-MODEL condition, including candidate code.

    Fail-closed in exactly the same way as the global check: a record without a
    model execution fingerprint carries no evidence of the candidate code it was
    produced against, so it is refused rather than exempted.
    """
    recorded_sha = model_fingerprint_sha(recorded)
    current_sha = model_fingerprint_sha(current)
    if recorded_sha is None:
        return False, "no model execution provenance recorded"
    if recorded_sha != current_sha:
        differing = []
        if (recorded or {}).get("global_execution_fingerprint_sha256") != \
                (current or {}).get("global_execution_fingerprint_sha256"):
            differing.append("global execution condition")
        if (recorded or {}).get("candidate_sources_sha256") != \
                (current or {}).get("candidate_sources_sha256"):
            differing.append("candidate source contents")
        return False, "model execution condition changed: " + (
            ", ".join(differing) or "fingerprint differs")
    return True, "model execution condition unchanged"


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

    config = load_config(Path(args.config).resolve())
    settings = stage_settings(config)
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    runtime = {
        "run_timeout_seconds": float(stage.get("run_timeout_seconds", 30.0)),
        "effective_jobs": dict(settings.get("jobs") or {}),
    }
    fingerprint = enhanced_execution_fingerprint(
        args.specs, settings, runtime=runtime,
        include_toolchain=not args.no_toolchain)
    printable = OrderedDict(
        (k, v) for k, v in fingerprint.items() if k != "benchmark_source_hashes")
    print(json.dumps(printable, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
