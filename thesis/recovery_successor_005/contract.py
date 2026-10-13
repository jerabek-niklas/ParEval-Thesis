"""Deterministic contract builder of the phase-2 run (profile recovery_successor_005).

Reached through pilot_run_contract.build_contract (generic recovery_successor_NNN
dispatch). Every call re-verifies, read-only:

* the phase-2 configuration profile (exact dict) and config file pin,
* the persisted phase-2 lineage (self-hash) and every protected byte of the
  six historical runs (stat-guarded full re-hash),
* the frozen target table (self-hash == lineage binding),
* the frozen ORIGIN (recovery_001) contract (self-hash == lineage binding),
* the phase-2 equivalence proof (fast mode) and the readiness bound to it,
* the content-addressed condition view of the live configuration.

The contract IS the origin methodology: a copy of the frozen recovery_001
contract (stages, tool sets, conditions, prompts, models) with the phase-2
identity, all eleven models and the phase2_provenance block. It never
rebuilds, freezes, authorizes or rewrites any historical contract. A refusal
raises RecoveryRefused; a returned contract is READY.

Python 3.8 compatible (validated inside the tool containers).
"""
from __future__ import annotations

import copy
import json
import os
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_005 import equivalence as pe
from thesis.recovery_successor_005 import lineage as pl

ROOT = Path(__file__).resolve().parents[2]
BUILDER = "phase2_contract_005.v1"
READINESS_SCHEMA = "phase2_readiness.v1"
# the order in which run.py measures (one stage at a time, never concurrent)
MEASUREMENT_ORDER = ("static.main", "static.parcoach", "static.llov", "correctness", "dynamic", "enhanced")
STAGE_ASSIGNMENT = OrderedDict([
    ("base", ["enhanced"]),
    ("static_feedback", ["correctness", "dynamic", "enhanced"]),
    ("test_feedback", ["static.main", "static.parcoach", "static.llov", "enhanced"]),
    ("combined_feedback", ["enhanced"]),
])


def expected_profile():
    return OrderedDict([
        ("run_id", pl.SUCCESSOR),
        ("num_samples_per_prompt", 1),
        ("parent_run_id", pl.PARENT),
        ("predecessor_run_id", pl.ORIGIN),
        ("selection", "phase2_backfill_enhanced"),
    ])


def definitions(root):
    return Path(root).resolve() / pl.DEFINITIONS_REL


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def _canonical_config_path(root, config_path):
    expected = (Path(root).resolve() / pl.CONFIG_REL).resolve()
    if Path(config_path).resolve() != expected:
        raise RecoveryRefused("the phase-2 contract is bound to %s" % pl.CONFIG_REL)
    return expected


def enhanced_condition(config):
    """The enhanced execution condition the contract pins (config values only;
    CLI overrides are refused under the NONE override plan)."""
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    return OrderedDict([
        ("frozen_specs_path", "thesis/enhanced_tests/frozen/e3_final_specs.jsonl"),
        ("jobs", OrderedDict(sorted((stage.get("jobs") or {}).items()))),
        ("run_timeout_seconds", stage.get("run_timeout_seconds")),
        ("target_cases_per_benchmark", stage.get("target_cases_per_benchmark")),
        ("gate_cache", "SHARED_IN_PROCESS_NEVER_PERSISTED"),
    ])


def build(config_path=None, run_id=None, primary_compiler="g++", root=None, writer_check=True):
    """Rebuild the phase-2 contract from the live, verified state.

    The productive path (T0, rehydration, the per-target authority) runs with
    writer_check=True: only a process holding the phase-2 writer lock token
    (run.py and its tool containers) can obtain the contract. Read-only gates
    (freeze, preflight) pass writer_check=False."""
    from thesis.config.load_config import load_config
    from thesis.evaluation import pilot_run_contract as pc
    from thesis.recovery_successor_005 import readiness as phase2_readiness
    from thesis.recovery_successor_005 import targets as pt

    root = Path(root).resolve() if root is not None else ROOT
    if config_path is None:
        raise RecoveryRefused("an explicit phase-2 config is required")
    if writer_check:
        sw.require_token(root, pl.SUCCESSOR, os.environ.get(sw.TOKEN_ENV))
    if run_id not in (None, pl.SUCCESSOR) or primary_compiler != "g++":
        raise RecoveryRefused("phase-2 identity/compiler differs")
    config_path = _canonical_config_path(root, config_path)
    pl.isolate_providers()
    config = load_config(config_path)
    pl.scrub_provider_environment(config)
    if dict((config.get("profiles") or {}).get(pl.PROFILE) or {}) != dict(expected_profile()):
        raise RecoveryRefused("invalid phase-2 profile")
    outputs = config.get("outputs") or {}
    for key, folder in (("raw_dir", "raw"), ("intermediate_dir", "intermediate")):
        if (root / str(outputs.get(key, ""))).resolve() != (root / "thesis/results" / folder).resolve():
            raise RecoveryRefused("phase-2 outputs must use the bound repository layout")
    enabled = [m["id"] for m in config.get("models") or [] if m.get("enabled")]
    if sorted(enabled) != sorted(pl.MODELS):
        raise RecoveryRefused("the configured models differ from the eleven study models")
    defs = definitions(root)
    lineage = pl.load(root)
    lineage.verify_quick()
    table = pt.load_table(root, lineage.targets_sha256)
    origin = lineage.origin
    frozen = pc.load_frozen(checked_path(root, origin["contract_path"]))
    if frozen["contract_sha256"] != origin["contract_sha256"]:
        raise RecoveryRefused("origin contract differs from the lineage binding")
    proof = read_json(defs / "equivalence.json")
    pe.validate(proof, root, lineage, config)
    readiness_rel = pl.DEFINITIONS_REL + "/readiness.json"
    if (root / str(outputs.get("readiness_artifact", ""))).resolve() != (root / readiness_rel).resolve():
        raise RecoveryRefused("foreign phase-2 readiness")
    readiness = read_json(root / readiness_rel)
    if readiness.get("schema_version") != READINESS_SCHEMA:
        raise RecoveryRefused("phase-2 readiness is not bound to the proven implementation")
    phase2_readiness.validate(readiness, lineage, proof)
    conditions = pc.conditions_view(config, primary_compiler)
    if conditions.get("pins_not_reproducing") or conditions.get("readiness_stale"):
        raise RecoveryRefused("phase-2 conditions do not reproduce")
    totals = OrderedDict(table.document["sample_totals"])
    result = copy.deepcopy(frozen)
    inherited = result.pop("recovery_provenance", None)
    result.update(run_id=pl.SUCCESSOR, profile=pl.PROFILE, status="READY", blockers=[],
                  conditions=conditions, built_at_utc=None, builder=BUILDER,
                  model_ids=list(pl.MODELS))
    result["base_run"] = OrderedDict([
        ("run_id", pl.SUCCESSOR), ("expected_base_run_id", pl.SUCCESSOR),
        ("status", "CONFIGURED"), ("forbid_iteration_variants", True),
        ("historical_baseline_run_id", pl.PARENT), ("predecessor_run_id", pl.ORIGIN)])
    result["reuse_policy"] = OrderedDict([
        ("policy", "PHASE2_MEASUREMENT_ONLY"), ("decided", True),
        ("reuse_status", "DECIDED"), ("generation_reuse", True),
        ("repair_reuse", "ALL_66_REPAIR_LOOPS_TERMINAL_READ_ONLY")])
    result["phase2_provenance"] = OrderedDict([
        ("schema_version", BUILDER),
        ("origin_run_id", pl.ORIGIN),
        ("parent_run_id", pl.PARENT),
        ("pilot_run_id", pl.PILOT),
        ("owner_runs", list(pl.OWNERS)),
        ("phase2_base_cells", 0),
        ("provider_calls", "NONE"),
        ("origin_contract_sha256", origin["contract_sha256"]),
        ("origin_authorization_sha256", origin["authorization_sha256"]),
        ("origin_t0_runtime_evidence_fingerprint_sha256", origin["t0_runtime_evidence_fingerprint_sha256"]),
        ("origin_runtime_condition_sha256", origin["runtime_condition_sha256"]),
        ("origin_static_analysis_condition_sha256", origin["static_analysis_condition_sha256"]),
        ("origin_repair_condition_sha256", origin["repair_condition_sha256"]),
        ("origin_git_commit", origin["git_commit"]),
        ("origin_recovery_provenance_sha256", ch.canonical_sha256(inherited)),
        ("lineage_sha256", lineage.sha256),
        ("protected_file_counts", lineage.protected_file_counts()),
        ("targets_sha256", table.sha256),
        ("target_count", table.document["target_count"]),
        ("candidate_sample_totals", totals),
        ("census_digest", table.document["census_digest"]),
        ("excluded_historical_runs", list(pl.EXCLUDED_HISTORICAL_RUNS)),
        ("policy", lineage.document["policy"]),
        ("stage_assignment", STAGE_ASSIGNMENT),
        ("measurement_order", list(MEASUREMENT_ORDER)),
        ("enhanced_condition", enhanced_condition(config)),
        ("result_layout", "%s/<model>/supplements/<source_run>/" % pl.RESULTS_REL),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("readiness_lf_sha256", ch.lf_normalized_sha256(root / readiness_rel)),
        ("config_lf_sha256", ch.lf_normalized_sha256(config_path)),
        ("external_runner", "thesis/recovery_successor_005/external.py"),
    ])
    result["methodology_freeze"] = OrderedDict([
        ("schema_version", "phase2_methodology.v1"),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("origin_equivalence_sha256", proof["origin_proof_sha256"])])
    result["policy_state"] = OrderedDict(frozen["policy_state"], expected_base_run_id=pl.SUCCESSOR)
    result["contract_sha256"] = pc.contract_sha256(result)
    return result


def frozen_path(root=None):
    return definitions(root if root is not None else ROOT) / "contract.json"
