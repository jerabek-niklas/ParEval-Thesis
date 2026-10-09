"""Deterministic contract builder of the successor run (profile recovery_successor).

Reached through pilot_run_contract.build_contract (the only profile dispatch
the authorization chokepoint uses). Every call re-verifies, read-only:

* the successor configuration profile (exact dict) and config file pin,
* the persisted successor lineage (self-hash) and the COMPLETE predecessor
  byte snapshot (membership + size + raw sha256),
* the frozen predecessor contract (self-hash == lineage binding) and the
  predecessor authorization / T0 / commit bindings,
* the successor equivalence proof (fast mode),
* the successor readiness artifact bound to that proof,
* the content-addressed condition view of the live configuration.

It never rebuilds, freezes, authorizes or rewrites the predecessor contract.
A refusal raises RecoveryRefused; a returned contract is READY.

Python 3.8 compatible (rebuilt inside the tool containers by the
authorization rehydration).
"""
from __future__ import annotations

import copy
import json
import os
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import successor_equivalence as se
from thesis.evaluation import successor_lineage as sl
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = "successor_contract.v1"
READINESS_SCHEMA = "successor_readiness.v1"


def expected_profile():
    return OrderedDict([
        ("run_id", sl.SUCCESSOR),
        ("num_samples_per_prompt", 1),
        ("parent_run_id", sl.PARENT),
        ("predecessor_run_id", sl.PREDECESSOR),
        ("selection", "predecessor_reference"),
    ])


def definitions(root):
    return Path(root).resolve() / sl.DEFINITIONS_REL


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def _canonical_config_path(root, config_path):
    expected = (Path(root).resolve() / sl.CONFIG_REL).resolve()
    if Path(config_path).resolve() != expected:
        raise RecoveryRefused("the successor contract is bound to %s" % sl.CONFIG_REL)
    return expected


def build(config_path=None, run_id=None, primary_compiler="g++", root=None, writer_check=True):
    """Rebuild the successor contract from the live, verified state.

    Every rebuild on the productive path (T0, rehydration, the provider
    chokepoint, the per-step authority) runs through the pilot_run_contract
    dispatch with writer_check=True: only a process holding the successor
    writer lock token (run_successor and its tool containers) can obtain a
    successor provider context - a native run_repair/generation process
    started with the successor profile is refused. Read-only gates (freeze,
    preflight) pass writer_check=False."""
    from thesis.config.load_config import load_config
    from thesis.evaluation import pilot_run_contract as pc

    root = Path(root).resolve() if root is not None else ROOT
    if config_path is None:
        raise RecoveryRefused("an explicit successor config is required")
    if writer_check:
        sw.require_token(root, sl.SUCCESSOR, os.environ.get(sw.TOKEN_ENV))
    if run_id not in (None, sl.SUCCESSOR) or primary_compiler != "g++":
        raise RecoveryRefused("successor identity/compiler differs")
    config_path = _canonical_config_path(root, config_path)
    config = load_config(config_path)
    if dict((config.get("profiles") or {}).get(sl.PROFILE) or {}) != dict(expected_profile()):
        raise RecoveryRefused("invalid successor profile")
    outputs = config.get("outputs") or {}
    for key, folder in (("raw_dir", "raw"), ("intermediate_dir", "intermediate")):
        if (root / str(outputs.get(key, ""))).resolve() != (root / "thesis/results" / folder).resolve():
            raise RecoveryRefused("successor outputs must use the bound repository layout")
    defs = definitions(root)
    lineage = sl.load(root)
    lineage.verify_quick()
    predecessor = lineage.document["predecessor"]
    frozen = pc.load_frozen(checked_path(root, predecessor["contract_path"]))
    if frozen["contract_sha256"] != predecessor["contract_sha256"]:
        raise RecoveryRefused("predecessor contract differs from the lineage binding")
    proof = read_json(defs / "equivalence.json")
    se.validate(proof, root, lineage, config)
    readiness_rel = sl.DEFINITIONS_REL + "/readiness.json"
    if (root / str(outputs.get("readiness_artifact", ""))).resolve() != (root / readiness_rel).resolve():
        raise RecoveryRefused("foreign successor readiness")
    readiness = read_json(root / readiness_rel)
    if readiness.get("schema_version") != READINESS_SCHEMA:
        raise RecoveryRefused("successor readiness is not bound to the proven implementation")
    from thesis.evaluation import successor_readiness

    successor_readiness.validate(readiness, lineage, proof)
    conditions = pc.conditions_view(config, primary_compiler)
    if conditions.get("pins_not_reproducing") or conditions.get("readiness_stale"):
        raise RecoveryRefused("successor conditions do not reproduce")
    result = copy.deepcopy(frozen)
    inherited = result.pop("recovery_provenance", None)
    result.update(run_id=sl.SUCCESSOR, profile=sl.PROFILE, status="READY", blockers=[],
                  conditions=conditions, built_at_utc=None, builder=BUILDER,
                  model_ids=list(sl.MODELS))
    result["base_run"] = OrderedDict([
        ("run_id", sl.SUCCESSOR), ("expected_base_run_id", sl.SUCCESSOR),
        ("status", "CONFIGURED"), ("forbid_iteration_variants", True),
        ("historical_baseline_run_id", sl.PARENT), ("predecessor_run_id", sl.PREDECESSOR)])
    result["reuse_policy"] = OrderedDict([
        ("policy", "SUCCESSOR_PREDECESSOR_REFERENCE"), ("decided", True),
        ("reuse_status", "DECIDED"), ("generation_reuse", True),
        ("repair_reuse", "PREDECESSOR_TRAJECTORIES_BY_HASH_BOUND_REFERENCE")])
    handoff = OrderedDict((key, value["mode"]) for key, value in lineage.document["handoff"].items())
    cells = OrderedDict()
    for model in sl.MODELS:
        counts = set(lineage.handoff(model, variant)["state_samples"] for variant in sl.VARIANTS)
        if len(counts) != 1:
            raise RecoveryRefused("the variants of %s disagree on the parent cells" % model)
        cells[model] = counts.pop()
    result["successor_provenance"] = OrderedDict([
        ("schema_version", BUILDER),
        ("predecessor_run_id", sl.PREDECESSOR),
        ("parent_run_id", sl.PARENT),
        ("successor_base_cells", 0),
        ("parent_base_cells_in_scope", sum(cells.values())),
        ("parent_base_cells_per_model", cells),
        ("predecessor_repair_adopted", True),
        ("predecessor_retirement_sha256", ch.canonical_sha256(lineage.document["predecessor_retirement"])),
        ("predecessor_contract_sha256", predecessor["contract_sha256"]),
        ("predecessor_authorization_sha256", predecessor["authorization_sha256"]),
        ("predecessor_t0_runtime_evidence_fingerprint_sha256",
         predecessor["t0_runtime_evidence_fingerprint_sha256"]),
        ("predecessor_runtime_condition_sha256", predecessor["runtime_condition_sha256"]),
        ("predecessor_git_commit", predecessor["git_commit"]),
        ("parent_lineage_sha256", predecessor["parent_lineage_sha256"]),
        ("predecessor_recovery_provenance_sha256", ch.canonical_sha256(inherited)),
        ("lineage_sha256", lineage.sha256),
        ("predecessor_snapshot_sha256", lineage.document["predecessor_snapshot"]["snapshot_sha256"]),
        ("policy", lineage.document["policy"]),
        ("handoff", handoff),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("readiness_lf_sha256", ch.lf_normalized_sha256(root / readiness_rel)),
        ("config_lf_sha256", ch.lf_normalized_sha256(config_path)),
        ("external_runner", "thesis/evaluation/successor_external.py"),
    ])
    result["methodology_freeze"] = OrderedDict([
        ("schema_version", "successor_methodology.v1"),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("predecessor_equivalence_sha256", proof["predecessor_proof_sha256"])])
    result["policy_state"] = OrderedDict(frozen["policy_state"], expected_base_run_id=sl.SUCCESSOR)
    result["contract_sha256"] = pc.contract_sha256(result)
    return result


def frozen_path(root=None):
    return definitions(root if root is not None else ROOT) / "contract.json"
