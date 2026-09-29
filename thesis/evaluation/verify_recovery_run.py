"""Read-only recovery acceptance. Definitions alone never imply completion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import recovery_context as rc
from thesis.evaluation.recovery_lineage import RECOVERY, PARENT, VARIANTS, RecoveryRefused
from thesis.evaluation.verify_parent_base_evidence import records, read_json


def native_rows(path, run, model):
    rows = records(path)
    for row in rows:
        if (row.get("run_id") != run
                or row.get("model_id", (row.get("model") or {}).get("id")) != model):
            raise RecoveryRefused("foreign/historical result: " + str(path))
    return rows


def validate_owned_invocations(manifest, contract, required):
    from thesis.evaluation import effective_invocation as ei
    covered = {stage: set() for stage in required}
    for invocation in (manifest.get("stage_invocations") or {}).values():
        if (invocation.get("run_id") != RECOVERY
                or ei.invocation_fingerprint(invocation) != invocation.get("invocation_sha256")
                or ei.check_against_contract(invocation, contract)):
            raise RecoveryRefused("invalid recovery effective invocation")
        stage = invocation.get("stage")
        if stage in covered:
            covered[stage].update(invocation.get("model_scope") or contract["model_ids"])
    for stage, models in required.items():
        if not set(models) <= covered[stage]:
            raise RecoveryRefused("missing recovery invocation scope: " + stage)


def validate_completion_summary(summary):
    """Single final acceptance predicate; unknown/missing evidence fails closed."""
    expected = dict(parent_base_cells=1584, recovery_base_cells=0,
                    expected_loops=33, terminal_loops=33, active_samples=0,
                    parent_unchanged=True, authorization_valid=True,
                    coverage_complete=True, runtime_complete=True,
                    invocation_complete=True, historical_repair_adopted=False)
    if any(key not in summary or type(summary[key]) is not type(value)
           or summary[key] != value for key, value in expected.items()):
        raise RecoveryRefused("recovery acceptance evidence incomplete or contradictory")
    return True


def validate_runtime_domain(expected, observed, fields):
    """Check the productive stamp schema, which binds digests via domain SHA.

    stage_runtime records repo_digests in the domain fingerprint but does
    not repeat that list in its domain report. Do not invent a missing list.
    All other compared identity fields are persisted and checked directly.
    """
    from thesis.evaluation import stage_runtime as sr
    bound = sr.domain_sha256(expected, fields=fields)
    if (observed.get("compared_fields") != list(fields)
            or observed.get("expected_t0_domain_sha256") != bound
            or observed.get("observed_domain_sha256") != bound
            or observed.get("match") is not True
            or sr.domain_diff(expected, observed, tuple(f for f in fields if f != "repo_digests"))):
        raise RecoveryRefused("recovery runtime domain drift")


def verify(config, config_path):
    from thesis.evaluation import recovery_contract, run_authorization as ra
    from thesis.evaluation import run_manifest, verify_pilot_run as vp, stage_runtime as sr
    from thesis.evaluation import manifest_fragments as mf
    from thesis.repair import orchestrator, run_backfill as bf
    contract = recovery_contract.build(config_path, RECOVERY)
    validated = ra.load_and_validate_run_authorization(
        config, RECOVERY, config_path=config_path, profile="recovery")
    auth = validated["authorization"]["authorization_sha256"]
    manifest = run_manifest.load_manifest(config, RECOVERY)
    lineage = rc.load_lineage()
    lineage.verify_artifacts()
    root = Path(config["outputs"]["intermediate_dir"])
    raw = Path(config["outputs"]["raw_dir"])
    # There is no recovery base generation/assembly population, even if an
    # illicit file happens to contain zero JSONL records.
    forbidden_base = ("assembly.jsonl", "static_analysis.jsonl", "correctness.jsonl", "dynamic_analysis.jsonl")
    if list((raw / RECOVERY).glob("*/generations.jsonl")) or any(
            list((root / RECOVERY).glob("*/" + name)) for name in forbidden_base):
        raise RecoveryRefused("recovery introduced a base population")
    report = vp.Report(RECOVERY)
    vp.check_authorization(report, config, RECOVERY, contract, manifest)
    vp.check_runtime(report, manifest, contract)
    vp.check_config_drift(report, manifest)
    assembled_ids = {}
    owned_targets = set()
    required_invocations = {"enhanced": set(contract["model_ids"])}
    for model in contract["model_ids"]:
        rc.require_terminal(config, model)
        base = records(rc.assembly_path(root, RECOVERY, model))
        assembled_ids[model] = [r["sample_id"] for r in base if r.get("assembled")]
        runs = bf.discover_runs(config, RECOVERY, model)
        if not runs or runs[0]["run_id"] != RECOVERY:
            raise RecoveryRefused("missing explicit base reference")
        for run in runs:
            target = run["run_id"]
            owned_targets.add(target)
            rc.validate_target(config, target, model, enhanced=True)
            entries = list(bf.load_assembly(root, target, model).values())
            assembled = [r for r in entries if r.get("assembled")]
            target_manifest = run_manifest.load_manifest(config, target)
            if mf.verify_fragment_integrity(root, target):
                raise RecoveryRefused("recovery fragment integrity failure")
            if target != RECOVERY:
                executions = {r.get("execution_model") for r in assembled}
                for execution, stage in (("mpi", "static.parcoach"), ("omp", "static.llov")):
                    if execution in executions:
                        required_invocations.setdefault(stage, set()).add(model)
                generation_rows = native_rows(raw / target / model / "generations.jsonl", target, model)
                for row in generation_rows:
                    if row["sample_id"] not in assembled_ids[model]:
                        raise RecoveryRefused("repair response outside parent population")
                vp.check_assembly(report, root, target, model, target_manifest, contract,
                                  generation_sample_ids=sorted({r["sample_id"] for r in generation_rows}))
                vp.check_evaluated_population(report, model, generation_rows, assembled, contract)
                for name in ("static_analysis.jsonl", "correctness.jsonl", "dynamic_analysis.jsonl"):
                    stage_rows = native_rows(root / target / model / name, target, model)
                    ids = [r.get("sample_id") for r in stage_rows]
                    if len(ids) != len(set(ids)) or set(ids) != {r["sample_id"] for r in assembled}:
                        raise RecoveryRefused("missing/duplicate iteration analysis")
                vp.check_static(report, config, root, target, model, assembled)
                vp.check_correctness(report, root, target, model, assembled)
                vp.check_dynamic(report, config, root, target, model, assembled)
            plan = bf.plan_run(config, run, model, rc.ROOT, {})
            if target != RECOVERY and (any(plan[k] != "ok" for k in ("static", "correctness", "dynamic")) or plan["external"]):
                raise RecoveryRefused("iteration backfill coverage incomplete")
            if plan["enhanced"] not in ("ok", "not_applicable"):
                raise RecoveryRefused("enhanced coverage incomplete")
            if plan["enhanced"] == "ok":
                vp.check_enhanced(report, config, root, target, model, assembled, contract, target_manifest)
                seen = set()
                from thesis.enhanced_tests.specs import spec_key
                for row in native_rows(root / target / model / "enhanced_tests.jsonl", target, model):
                    key = (row.get("sample_id"), spec_key(row.get("spec") or {}))
                    if key in seen:
                        raise RecoveryRefused("duplicate enhanced ownership")
                    seen.add(key)
                    expected = rc.candidate_provenance(config, target, model, row["sample_id"])
                    if any(row.get(k) != v for k, v in expected.items()):
                        raise RecoveryRefused("enhanced candidate provenance mismatch")
    observed = {p.name for p in root.glob(RECOVERY + "__*") if p.is_dir()}
    if observed != owned_targets - {RECOVERY}:
        raise RecoveryRefused("unexplained recovery iteration directory")
    for area, pattern in ((raw, "*/generations.jsonl"), (root, "*/*.jsonl")):
        for directory in area.glob(RECOVERY + "*"):
            for path in directory.glob(pattern):
                if directory.name not in owned_targets or path.parent.name not in contract["model_ids"]:
                    raise RecoveryRefused("result outside explained recovery ownership")
    matrix = vp.check_repair_scope(report, contract, config, RECOVERY, manifest,
                                    assembled_ids, assembled_ids)
    if matrix.get("terminal_loop_count") != 33 or matrix.get("sample_totals", {}).get("active_repair_samples") != 0:
        raise RecoveryRefused("recovery is not 33/33 terminal")
    # Validate every written stamp, and require stamps for the productive
    # recovery stages, not for the referenced parent base stages.
    fragments = root / RECOVERY / "run_manifest.fragments"
    t0 = sr.t0_domains(manifest)
    stages = set()
    for path in sorted(fragments.glob("runtime.stage.*.json")):
        stamp = read_json(path)["content"]
        stage = stamp.get("stage")
        fields = sr.COMPARED_FIELDS.get(stamp.get("observation_mode"))
        if (not fields or stage not in sr.STAGE_DOMAINS or stamp.get("match") is not True
                or stamp.get("drift_fields") or stamp.get("run_id") != RECOVERY
                or stamp.get("authorization_sha256") != auth
                or stamp.get("contract_sha256") != contract["contract_sha256"]
                or sr._evidence_fingerprint(stamp) != stamp.get("stage_runtime_sha256")):
            raise RecoveryRefused("invalid recovery runtime stamp")
        if set(stamp.get("domains", {})) != set(sr.STAGE_DOMAINS[stage][1]):
            raise RecoveryRefused("missing runtime domain")
        for domain, observed_domain in stamp["domains"].items():
            validate_runtime_domain(t0[domain], observed_domain, fields)
        stages.add(stage)
    if "enhanced" not in stages or (len(owned_targets) > 1 and "repair_evaluation" not in stages):
        raise RecoveryRefused("missing recovery stage runtime evidence")
    if not set(required_invocations) <= stages:
        raise RecoveryRefused("missing split-container recovery runtime stamp")
    validate_owned_invocations(manifest, contract, required_invocations)
    if report.status() == "PASS":
        validate_completion_summary(dict(parent_base_cells=1584, recovery_base_cells=0,
            expected_loops=matrix["expected_loop_count"], terminal_loops=matrix["terminal_loop_count"],
            active_samples=matrix["sample_totals"]["active_repair_samples"],
            parent_unchanged=True, authorization_valid=True, coverage_complete=True,
            runtime_complete=True, invocation_complete=True, historical_repair_adopted=False))
    report.add("recovery_source_ownership", "PASS", "1584 parent references; zero new base cells; no historical response adoption")
    return dict(schema_version="recovery_post_run_verification.v1", run_id=RECOVERY,
                status=report.status(), counts=report.counts(), checks=report.checks,
                contract_sha256=contract["contract_sha256"],
                parent_inventory_sha256=lineage.document["lineage_sha256"],
                parent_base_cells=1584, recovery_base_cells=0, repair_scope=matrix,
                historical_repair_adopted=False)


def main():
    from thesis.config.load_config import load_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="thesis/config/recovery.yaml")
    args = parser.parse_args()
    try:
        result = verify(load_config(args.config), args.config)
    except Exception as error:
        result = dict(run_id=RECOVERY, status="FAIL", error=str(error))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
