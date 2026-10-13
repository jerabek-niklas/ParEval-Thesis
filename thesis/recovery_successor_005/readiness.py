"""Runtime readiness of the phase-2 run (RUNTIME EXPECTATION ONLY).

Not an authorization: it records that the CURRENT tool images, interpreters
and tool identities reproduce exactly the runtime every historical
measurement of the study ran under (recovery_001 T0 = the runtime of
pilot_002, full_ext_001 and full_ext_recovery_001..004):

* two independent fresh runtime probes (the T0 measurement definition,
  recovery_preflight.runtime_probe) agree and equal the origin T0 runtime
  condition;
* the static-analysis and repair conditions equal the origin's;
* TSan preflight (vm.mmap_rnd_bits=28), host repository path and a
  free-disk floor hold.

Phase 2 makes no provider request: no API key and no provider endpoint is
required or recorded (no phase-2 path reaches a provider; see the import
scan of the preflight).

Must run in the main container with the docker socket and PAREVAL_HOST_REPO:

    python3 -B -m thesis.recovery_successor_005.readiness [--write]

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path

from thesis.recovery_successor_005 import lineage as pl
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

SCHEMA = "phase2_readiness.v1"
MINIMUM_FREE_DISK_GB = 20
HOST_REPO = "C:/Users/jerab/Desktop/ParEval-thesis"
ROOT = Path(__file__).resolve().parents[2]


def readiness_path(root=None):
    return Path(root if root is not None else ROOT) / pl.DEFINITIONS_REL / "readiness.json"


def check_runtime(lineage, probes):
    origin = lineage.origin
    problems = []
    if len(probes) < 2:
        problems.append("two independent runtime probes are required")
    for index, probe in enumerate(probes):
        for problem in probe.get("problems") or []:
            problems.append("probe %d: %s" % (index + 1, problem))
        if probe.get("sha256") != origin["runtime_condition_sha256"]:
            problems.append("probe %d runtime %s... != origin T0 runtime %s..."
                            % (index + 1, str(probe.get("sha256"))[:12], origin["runtime_condition_sha256"][:12]))
        if probe.get("static_analysis_condition_sha256") != origin["static_analysis_condition_sha256"]:
            problems.append("probe %d static-analysis condition differs from the origin" % (index + 1))
        if probe.get("repair_condition_sha256") != origin["repair_condition_sha256"]:
            problems.append("probe %d repair condition differs from the origin" % (index + 1))
        if not probe.get("tsan_preflight_pass"):
            problems.append("probe %d: TSan preflight fails (vm.mmap_rnd_bits=%s, %s)"
                            % (index + 1, probe.get("vm_mmap_rnd_bits"), probe.get("tsan_error")))
        if probe.get("host_repo_path") != HOST_REPO:
            problems.append("probe %d: PAREVAL_HOST_REPO is not %s" % (index + 1, HOST_REPO))
        if (probe.get("free_disk_gb") or 0) < MINIMUM_FREE_DISK_GB:
            problems.append("probe %d: free disk %.1f GB < %d GB"
                            % (index + 1, probe.get("free_disk_gb") or 0, MINIMUM_FREE_DISK_GB))
    return problems


def build(lineage, proof, probes):
    problems = check_runtime(lineage, probes)
    if problems:
        raise RecoveryRefused("phase-2 runtime is not ready: " + "; ".join(problems))
    first = probes[0]
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("gate", "READY"),
        ("scope", "RUNTIME_EXPECTATION_ONLY_NOT_AUTHORIZATION"),
        ("run_id", pl.SUCCESSOR),
        ("origin_run_id", pl.ORIGIN),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("lineage_sha256", lineage.sha256),
        ("runtime_condition_sha256", first["sha256"]),
        ("origin_runtime_condition_sha256", lineage.origin["runtime_condition_sha256"]),
        ("static_analysis_condition_sha256", first["static_analysis_condition_sha256"]),
        ("repair_condition_sha256", first["repair_condition_sha256"]),
        ("runtime_fully_pinned", bool(first["condition"].get("fully_pinned"))),
        ("runtime_condition", first["condition"]),
        ("independent_probe_hashes", [p["sha256"] for p in probes]),
        ("tsan_preflight_pass", all(p["tsan_preflight_pass"] for p in probes)),
        ("vm_mmap_rnd_bits", first["vm_mmap_rnd_bits"]),
        ("minimum_free_disk_gb", MINIMUM_FREE_DISK_GB),
        ("minimum_free_disk_policy", "Operational floor, not a prediction of the run size; rechecked "
                                     "by the T0 authorization and the preflight"),
        ("provider_calls", "NONE"),
        ("host_repo_path", HOST_REPO),
    ])
    if not document["runtime_fully_pinned"]:
        raise RecoveryRefused("the measured runtime is not fully pinned")
    document["readiness_sha256"] = canonical_sha256(OrderedDict(
        (k, v) for k, v in document.items() if k != "readiness_sha256"))
    return document


def validate(document, lineage, proof):
    body = OrderedDict((k, v) for k, v in document.items() if k != "readiness_sha256")
    if (document.get("schema_version") != SCHEMA or document.get("gate") != "READY"
            or canonical_sha256(body) != document.get("readiness_sha256")
            or document.get("equivalence_sha256") != proof["proof_sha256"]
            or document.get("lineage_sha256") != lineage.sha256
            or document.get("runtime_condition_sha256") != lineage.origin["runtime_condition_sha256"]
            or document.get("provider_calls") != "NONE"
            or not document.get("runtime_fully_pinned")):
        raise RecoveryRefused("phase-2 readiness is missing, tampered or not bound")
    return True


def probe(config):
    from thesis.evaluation.recovery_preflight import runtime_probe

    return runtime_probe(config)


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=pl.CONFIG_REL)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    pl.isolate_providers()
    config = load_config(args.config)
    pl.scrub_provider_environment(config)
    lineage = pl.load(ROOT)
    lineage.verify_quick()
    proof = json.loads(checked_path(ROOT, pl.DEFINITIONS_REL + "/equivalence.json").read_text(encoding="utf-8"))
    probes = [probe(config), probe(config)]
    try:
        document = build(lineage, proof, probes)
    except RecoveryRefused as refused:
        summary = [OrderedDict((k, p.get(k)) for k in ("sha256", "problems", "tsan_preflight_pass",
                                                       "vm_mmap_rnd_bits", "host_repo_path", "free_disk_gb"))
                   for p in probes]
        print(json.dumps(OrderedDict([("gate", "NOT_READY"), ("reason", str(refused)),
                                      ("probes", summary)]), indent=2))
        return 1
    if args.write:
        from thesis.evaluation import atomic_io

        atomic_io.atomic_write_json(readiness_path(ROOT), document)
    print(json.dumps(OrderedDict((k, document[k]) for k in (
        "gate", "runtime_condition_sha256", "independent_probe_hashes", "equivalence_sha256",
        "lineage_sha256", "readiness_sha256")), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
