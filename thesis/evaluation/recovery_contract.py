"""Read-only recovery contract builder; requires frozen, verified evidence.

No old contract is rebuilt. Missing proof/readiness/parent evidence refuses
the build; this module never freezes or authorizes a run.
"""
from __future__ import annotations

import copy
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import recovery_equivalence as eq
from thesis.evaluation.recovery_lineage import RECOVERY, PARENT, PILOT, OWNERSHIP, RecoveryRefused
from thesis.evaluation.verify_parent_base_evidence import verify, read_json, BASE

SOURCES = (
    "thesis/evaluation/check_static_repair_readiness.py",
    "thesis/evaluation/recovery_lineage.py",
    "thesis/evaluation/recovery_contract.py",
    "thesis/evaluation/recovery_equivalence.py",
    "thesis/evaluation/verify_parent_base_evidence.py",
    "thesis/repair/recovery_routing.py",
    "thesis/evaluation/recovery_stage_evidence.py",
    "thesis/evaluation/recovery_context.py",
    "thesis/evaluation/recovery_historical_source.py",
    "thesis/repair/run_repair.py",
    "thesis/repair/backfill_authority.py",
    "thesis/repair/run_backfill.py",
    "thesis/evaluation/run_enhanced_tests.py",
    "thesis/evaluation/pilot_run_contract.py",
    "thesis/evaluation/run_authorization.py",
    "thesis/evaluation/repair_scope.py",
    "thesis/evaluation/verify_pilot_run.py",
    "thesis/evaluation/verify_recovery_run.py",
    "thesis/evaluation/composite_study_v2.py",
    "thesis/evaluation/recovery_source_projection.py",
    "thesis/analysis_overview/recovery_reader.py",
    "thesis/repair/run_recovery.py",
    "thesis/evaluation/recovery_preflight.py",
    "thesis/evaluation/test_recovery_infrastructure.py",
    "thesis/evaluation/test_recovery_historical_source.py",
    "thesis/evaluation/test_recovery_parent_evidence.py",
    "thesis/evaluation/test_recovery_pipeline.py",
    "thesis/evaluation/test_recovery_contract.py",
    "thesis/evaluation/recovery_protected_history.py",
    "thesis/evaluation/test_recovery_acceptance.py",
    "thesis/evaluation/test_recovery_authorization.py",
    "thesis/evaluation/test_recovery_verifier_fixture.py",
)


def build(config_path=None, run_id=None, primary_compiler="g++"):
    """Rebuild the new contract only; never rebuild the historical parent."""
    from thesis.config.load_config import load_config
    from thesis.evaluation import pilot_run_contract as pc
    from thesis.evaluation.recovery_context import ROOT, DEFINITIONS, load_lineage
    if config_path is None:
        raise RecoveryRefused("an explicit recovery config is required")
    if run_id not in (None, RECOVERY) or primary_compiler != "g++":
        raise RecoveryRefused("recovery identity/compiler differs")
    config = load_config(config_path)
    profile = (config.get("profiles") or {}).get("recovery")
    if profile != {"run_id": RECOVERY, "num_samples_per_prompt": 1,
                   "parent_run_id": PARENT, "selection": "parent_reference"}:
        raise RecoveryRefused("invalid recovery profile")
    lineage = load_lineage()
    report = verify(ROOT, lineage.document, lineage.document["lineage_sha256"])
    from thesis.evaluation import recovery_protected_history
    protected = recovery_protected_history.verify(ROOT, read_json(DEFINITIONS / "protected_history.json"))
    if report != read_json(DEFINITIONS / "parent_report.json"):
        raise RecoveryRefused("parent verification differs from frozen report")
    parent = read_json(ROOT / BASE / "run_contract.json")
    frozen = read_json(ROOT / BASE / "run_manifest.json")["resolved_config"]
    for key in ("models", "generation_defaults", "stages", "prompts"):
        if config.get(key) != frozen.get(key):
            raise RecoveryRefused("recovery methodical config differs: " + key)
    proof = read_json(DEFINITIONS / "equivalence.json")
    eq.validate(proof, proof.get("proof_sha256"), ROOT, SOURCES)
    readiness = read_json(DEFINITIONS / "readiness.json")
    if (readiness.get("gate") != "READY" or not readiness.get("runtime_fully_pinned")
            or readiness.get("equivalence_sha256") != proof["proof_sha256"]):
        raise RecoveryRefused("recovery readiness not bound to proven implementation")
    if Path(config["outputs"].get("readiness_artifact", "")).resolve() != DEFINITIONS / "readiness.json":
        raise RecoveryRefused("foreign recovery readiness")
    conditions = pc.conditions_view(config, primary_compiler)
    if conditions.get("pins_not_reproducing") or conditions.get("readiness_stale"):
        raise RecoveryRefused("recovery conditions do not reproduce")
    result = copy.deepcopy(parent)
    result.update(run_id=RECOVERY, profile="recovery", status="READY", blockers=[],
                  conditions=conditions, built_at_utc=None,
                  builder="recovery_contract.v1")
    result.pop("extension_provenance", None)
    result["base_run"] = dict(run_id=RECOVERY, expected_base_run_id=RECOVERY,
                              status="CONFIGURED", forbid_iteration_variants=True,
                              historical_baseline_run_id=PARENT)
    result["reuse_policy"] = dict(policy="EXPLICIT_STAGE_SPLIT_PARENT_REFERENCE",
                                  decided=True, reuse_status="DECIDED",
                                  generation_reuse=True, repair_reuse=False)
    result["recovery_provenance"] = {
        "schema_version": "recovery_contract.v1", "parent_run_id": PARENT,
        "parent_base_cells": 1584, "recovery_base_cells": 0,
        "parent_contract_sha256": parent["contract_sha256"],
        "parent_inventory_sha256": lineage.document["lineage_sha256"],
        "parent_report_sha256": ch.canonical_sha256(report),
        "protected_history": protected,
        "parent_authorization_sha256": lineage.document["parent_authorization_sha256"],
        "parent_runtime_evidence_sha256": lineage.document["parent_runtime_evidence_sha256"],
        "historical_repair_policy": "EXCLUDE_ALL_PARENT_REPAIR",
        "stage_ownership": OWNERSHIP.copy(), "equivalence_sha256": proof["proof_sha256"],
        "source_pins": eq.source_pins(ROOT, SOURCES),
    }
    result["population_freeze"] = dict(status="PARENT_REFERENCE", run_id=PARENT,
        sha256=lineage.document["parent_population_sha256"],
        benchmark_ids=parent["population_freeze"]["benchmark_ids"])
    result["methodology_freeze"] = dict(schema_version="recovery_methodology.v1",
                                        equivalence_sha256=proof["proof_sha256"])
    result["policy_state"] = dict(parent["policy_state"], expected_base_run_id=RECOVERY)
    result["contract_sha256"] = pc.contract_sha256(result)
    return result
