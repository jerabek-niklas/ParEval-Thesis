"""Runtime readiness of the successor run (RUNTIME EXPECTATION ONLY).

Not an authorization: it records that the CURRENT tool images, interpreters,
tool identities and provider endpoints reproduce exactly what the predecessor
recovery_001 was authorized under, so the successor continues its
trajectories under the original pins:

* two independent fresh runtime probes (the T0 measurement definition,
  recovery_preflight.runtime_probe) agree and equal the predecessor's T0
  runtime condition;
* the static-analysis and repair conditions equal the predecessor's;
* the provider endpoint identities (sha256 of the resolved URL, never the
  URL) of the successor models equal the predecessor's T0 evidence;
* TSan preflight (vm.mmap_rnd_bits=28), host repository path, API key
  presence (names only) and a free-disk floor hold.

Must run in the main container with the docker socket, PAREVAL_HOST_REPO and
the provider .env:

    python3 -B -m thesis.evaluation.successor_readiness [--write]

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import successor_lineage as sl
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

SCHEMA = "successor_readiness.v1"
MINIMUM_FREE_DISK_GB = 20
HOST_REPO = "C:/Users/jerab/Desktop/ParEval-thesis"
ROOT = Path(__file__).resolve().parents[2]


def readiness_path(root=None):
    return Path(root if root is not None else ROOT) / sl.DEFINITIONS_REL / "readiness.json"


def in_scope_models(config):
    by_id = {m["id"]: m for m in config.get("models") or []}
    missing = [m for m in sl.MODELS if m not in by_id or not by_id[m].get("enabled")]
    if missing:
        raise RecoveryRefused("successor models missing/disabled in the config: %s" % missing)
    return [by_id[m] for m in sl.MODELS]


def predecessor_endpoints(lineage):
    evidence = lineage.view.read_json(sl.PREDECESSOR_FRAGMENTS_REL + "/runtime.evidence.json")
    identities = (evidence.get("content") or {}).get("provider_endpoint_identities") or {}
    return OrderedDict((model, identities.get(model)) for model in sl.MODELS)


def current_endpoints(config):
    from thesis.evaluation.run_authorization import provider_endpoint_identities

    identities = provider_endpoint_identities(config)
    return OrderedDict((model, identities.get(model)) for model in sl.MODELS)


def check_runtime(config, lineage, probes):
    """Problems (list of strings) of the measured runtime against the pins."""
    predecessor = lineage.document["predecessor"]
    problems = []
    if len(probes) < 2:
        problems.append("two independent runtime probes are required")
    for index, probe in enumerate(probes):
        for problem in probe.get("problems") or []:
            problems.append("probe %d: %s" % (index + 1, problem))
        if probe.get("sha256") != predecessor["runtime_condition_sha256"]:
            problems.append("probe %d runtime %s... != predecessor T0 runtime %s..."
                            % (index + 1, str(probe.get("sha256"))[:12],
                               predecessor["runtime_condition_sha256"][:12]))
        if probe.get("static_analysis_condition_sha256") != predecessor["static_analysis_condition_sha256"]:
            problems.append("probe %d static-analysis condition differs from the predecessor" % (index + 1))
        if probe.get("repair_condition_sha256") != predecessor["repair_condition_sha256"]:
            problems.append("probe %d repair condition differs from the predecessor" % (index + 1))
        if not probe.get("tsan_preflight_pass"):
            problems.append("probe %d: TSan preflight fails (vm.mmap_rnd_bits=%s, %s)"
                            % (index + 1, probe.get("vm_mmap_rnd_bits"), probe.get("tsan_error")))
        if probe.get("host_repo_path") != HOST_REPO:
            problems.append("probe %d: PAREVAL_HOST_REPO is not %s" % (index + 1, HOST_REPO))
        if (probe.get("free_disk_gb") or 0) < MINIMUM_FREE_DISK_GB:
            problems.append("probe %d: free disk %.1f GB < %d GB"
                            % (index + 1, probe.get("free_disk_gb") or 0, MINIMUM_FREE_DISK_GB))
    keys = OrderedDict()
    for model in in_scope_models(config):
        keys[model["api_key_env"]] = "SET" if os.environ.get(model["api_key_env"]) else "MISSING"
    for name, state in keys.items():
        if state != "SET":
            problems.append("API key environment variable %s is not set" % name)
    expected = predecessor_endpoints(lineage)
    current = current_endpoints(config)
    for model in sl.MODELS:
        if not expected.get(model):
            problems.append("predecessor T0 evidence lacks the endpoint identity of %s" % model)
        elif current.get(model) != expected[model]:
            problems.append("provider endpoint of %s differs from the predecessor authorization "
                            "(identity %s... vs %s...)" % (model, str(current.get(model))[:12],
                                                          str(expected[model])[:12]))
    return problems, keys, current


def build(config, lineage, proof, probes):
    problems, keys, endpoints = check_runtime(config, lineage, probes)
    if problems:
        raise RecoveryRefused("successor runtime is not ready: " + "; ".join(problems))
    first = probes[0]
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("gate", "READY"),
        ("scope", "RUNTIME_EXPECTATION_ONLY_NOT_AUTHORIZATION"),
        ("run_id", sl.SUCCESSOR),
        ("predecessor_run_id", sl.PREDECESSOR),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("lineage_sha256", lineage.sha256),
        ("runtime_condition_sha256", first["sha256"]),
        ("predecessor_runtime_condition_sha256", lineage.document["predecessor"]["runtime_condition_sha256"]),
        ("static_analysis_condition_sha256", first["static_analysis_condition_sha256"]),
        ("repair_condition_sha256", first["repair_condition_sha256"]),
        ("runtime_fully_pinned", bool(first["condition"].get("fully_pinned"))),
        ("runtime_condition", first["condition"]),
        ("independent_probe_hashes", [p["sha256"] for p in probes]),
        ("tsan_preflight_pass", all(p["tsan_preflight_pass"] for p in probes)),
        ("vm_mmap_rnd_bits", first["vm_mmap_rnd_bits"]),
        ("minimum_free_disk_gb", MINIMUM_FREE_DISK_GB),
        ("minimum_free_disk_policy", "Operational floor, not a prediction of the run size; rechecked "
                                     "by the T0 authorization"),
        ("api_key_names", sorted(keys)),
        ("provider_endpoint_identities", endpoints),
        ("provider_endpoints_equal_predecessor", True),
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
            or document.get("runtime_condition_sha256")
            != lineage.document["predecessor"]["runtime_condition_sha256"]
            or not document.get("runtime_fully_pinned")):
        raise RecoveryRefused("successor readiness is missing, tampered or not bound")
    return True


def probe(config):
    from thesis.evaluation.recovery_preflight import runtime_probe

    return runtime_probe(config)


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=sl.CONFIG_REL)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    lineage = sl.load(ROOT)
    lineage.verify_quick()
    proof = json.loads(checked_path(ROOT, sl.DEFINITIONS_REL + "/equivalence.json")
                       .read_text(encoding="utf-8"))
    probes = [probe(config), probe(config)]
    try:
        document = build(config, lineage, proof, probes)
    except RecoveryRefused as refused:
        summary = [OrderedDict((k, p.get(k)) for k in ("sha256", "problems", "tsan_preflight_pass",
                                                       "vm_mmap_rnd_bits", "host_repo_path",
                                                       "free_disk_gb", "api_keys"))
                   for p in probes]
        print(json.dumps(OrderedDict([("gate", "NOT_READY"), ("reason", str(refused)),
                                      ("probes", summary)]), indent=2))
        return 1
    if args.write:
        from thesis.evaluation import atomic_io

        atomic_io.atomic_write_json(readiness_path(ROOT), document)
    print(json.dumps(OrderedDict((k, document[k]) for k in (
        "gate", "runtime_condition_sha256", "independent_probe_hashes", "equivalence_sha256",
        "lineage_sha256", "provider_endpoints_equal_predecessor", "readiness_sha256")), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
