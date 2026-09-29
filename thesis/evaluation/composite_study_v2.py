"""Stage-split composite: two population sources and one derived lineage."""
from __future__ import annotations
import copy
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import PARENT, PILOT, RECOVERY, RecoveryRefused, fingerprint
from thesis.evaluation.verify_parent_base_evidence import read_json


def population(blocks, derived):
    if ([b.get("run_id") for b in blocks] != [PILOT, PARENT]
            or derived != {"run_id": RECOVERY, "parent_run_id": PARENT, "base_cells": 0}):
        raise RecoveryRefused("composite requires exactly two population sources and one derived lineage")
    keys = set()
    benchmarks = set()
    models = None
    for block, expected in zip(blocks, (12, 48)):
        prompts = block.get("prompt_hashes", {})
        bench = {"/".join(k.split("|")[:2]) for k in prompts}
        model_ids = block.get("model_ids", [])
        if (len(prompts) != expected * 3 or len(bench) != expected
                or len(model_ids) != 11 or len(set(model_ids)) != 11
                or block.get("samples_per_prompt") != 1
                or keys.intersection(prompts) or benchmarks.intersection(bench)):
            raise RecoveryRefused("population size, duplication, or overlap mismatch")
        for benchmark in bench:
            executions = sorted(k.split("|")[2] for k in prompts if "/".join(k.split("|")[:2]) == benchmark)
            if executions != ["mpi", "omp", "serial"]:
                raise RecoveryRefused("incomplete execution triple")
        if models is not None and models != set(model_ids):
            raise RecoveryRefused("composite model sets differ")
        models = set(model_ids)
        keys.update(prompts)
        benchmarks.update(bench)
    return dict(benchmarks=60, prompts=180, base_cells=1980,
                pilot_base_cells=396, extension_base_cells=1584,
                recovery_base_cells=0, overlap=0)


def build(root, recovery_contract):
    root = Path(root)
    historical = read_json(root / "thesis/evaluation/full_001_composite.json")
    blocks = copy.deepcopy(historical["source_runs"])
    derived = dict(run_id=RECOVERY, parent_run_id=PARENT, base_cells=0)
    counts = population(blocks, derived)
    document = dict(schema_version="composite_study.v2", study_id="full_001",
                    status="PLANNED_NOT_COMPLETE", source_runs=blocks, derived_lineage=derived,
                    recovery_contract_sha256=recovery_contract["contract_sha256"],
                    parent_inventory_sha256=recovery_contract["recovery_provenance"]["parent_inventory_sha256"],
                    historical_manifest_raw_sha256=ch.raw_sha256(root / "thesis/evaluation/full_001_composite.json"),
                    counts=counts)
    document["manifest_sha256"] = fingerprint(document, "manifest_sha256")
    return document


def verify(root, document, config, config_path, require_complete=False):
    from thesis.evaluation import recovery_contract, verify_recovery_run, verify_pilot_run
    from thesis.evaluation.composite_study import read_base_cells
    root = Path(root)
    if (document.get("schema_version") != "composite_study.v2"
            or document.get("manifest_sha256") != fingerprint(document, "manifest_sha256")):
        raise RecoveryRefused("invalid composite V2 fingerprint")
    contract = recovery_contract.build(config_path, RECOVERY)
    if document != build(root, contract):
        raise RecoveryRefused("composite V2 definitions drift")
    if len(read_base_cells(document, root)) != 1980:
        raise RecoveryRefused("composite base cells are incomplete")
    pilot = verify_pilot_run.verify(config, PILOT, root / "thesis/results/intermediate/pilot_002/run_contract.json")
    if pilot.get("status") != "PASS" or pilot.get("counts") != {"PASS":269,"FAIL":0,"UNRESOLVED":0}:
        raise RecoveryRefused("pilot no longer verifies 269/0/0")
    if require_complete:
        recovery = verify_recovery_run.verify(config, config_path)
        if recovery.get("status") != "PASS":
            raise RecoveryRefused("recovery acceptance missing")
    return dict(status="PASS", scope="COMPLETE" if require_complete else "PLANNED_ONLY",
                **document["counts"])
