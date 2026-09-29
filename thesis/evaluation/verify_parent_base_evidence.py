"""Read-only inventory and BASE-only verification; never a full-run PASS.

CLI prints to stdout. It never writes an inventory or a result directory.
Freezing the returned document is a separate, reviewed action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import (
    PARENT, PILOT, RECOVERY, SCHEMA, OWNERSHIP, RecoveryLineage,
    RecoveryRefused, checked_path, fingerprint,
)

FILES = {"generations.jsonl": "generation", "assembly.jsonl": "assembly",
         "static_analysis.jsonl": "static", "correctness.jsonl": "correctness",
         "dynamic_analysis.jsonl": "dynamic"}
BASE = "thesis/results/intermediate/" + PARENT
RAW = "thesis/results/raw/" + PARENT


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def records(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def files(root):
    result = []
    for prefix in (RAW, BASE):
        directory = checked_path(root, prefix)
        if not directory.is_dir():
            raise RecoveryRefused("missing parent directory: " + prefix)
        for path in directory.rglob("*"):
            relative = path.relative_to(root).as_posix()
            checked_path(root, relative)  # reject aliases, including directories
            if path.is_file():
                result.append(relative)
    return sorted(result)


def metadata(root, relative):
    path = checked_path(root, relative)
    data = path.read_bytes()
    stage = FILES.get(path.name, "provenance")
    if "/repair/" in relative:
        stage = "historical_only"
    if path.name == "generated-code.hpp":
        stage = "source"
    model = relative.split("/")[4] if len(relative.split("/")) > 5 else None
    count = identity = None
    if stage in FILES.values():
        rows = records(path)
        count = len(rows)
        identity = ch.canonical_sha256([
            [r.get("run_id"), r.get("model_id", (r.get("model") or {}).get("id")), r.get("sample_id")]
            for r in rows])
    return dict(path=relative, raw_sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                stage=stage, source_run=PARENT, model_id=model,
                record_count=count, record_identities_sha256=identity)


def inventory(root):
    root = Path(root).resolve()
    contract = read_json(root / BASE / "run_contract.json")
    manifest = read_json(root / BASE / "run_manifest.json")
    return dict(schema_version=SCHEMA, run_id=RECOVERY, parent_run_id=PARENT,
                pilot_run_id=PILOT, recovery_base_cells=0, stage_ownership=OWNERSHIP.copy(),
                historical_repair_policy="EXCLUDE_ALL_PARENT_REPAIR",
                parent_contract_sha256=contract["contract_sha256"],
                parent_authorization_sha256=manifest["authorization"]["authorization_sha256"],
                parent_runtime_evidence_sha256=ch.canonical_sha256(manifest["runtime_evidence"]),
                parent_population_sha256=ch.canonical_sha256(contract["selected_prompt_hashes"]),
                model_ids=contract["model_ids"],
                max_iterations=contract["repair_plan"]["max_iterations"],
                artifacts=[metadata(root, p) for p in files(root)])


def build_inventory(root):
    document = inventory(root)
    document["lineage_sha256"] = fingerprint(document)
    verify(root, document, document["lineage_sha256"])
    return document


def verify(root, document, expected_sha):
    """Validate bytes, exact native cell sets and existing stage provenance."""
    from thesis.evaluation import pilot_run_contract as pc, run_authorization as ra
    from thesis.evaluation import manifest_fragments as mf, stage_runtime as sr
    from thesis.evaluation import verify_pilot_run as vp
    from thesis.evaluation import recovery_historical_source
    root = Path(root).resolve()
    lineage = RecoveryLineage(root, document, expected_sha)
    lineage.verify_artifacts()
    if files(root) != list(lineage.refs):
        raise RecoveryRefused("parent inventory membership changed")
    for relative, ref in lineage.refs.items():
        if metadata(root, relative) != vars(ref):
            raise RecoveryRefused("inventory identity metadata mismatch: " + relative)
    contract = pc.load_frozen(root / BASE / "run_contract.json")
    manifest = read_json(root / BASE / "run_manifest.json")
    historical_source = recovery_historical_source.verify(root, manifest, contract)
    auth = manifest.get("authorization") or {}
    evidence = manifest.get("runtime_evidence") or {}
    if (contract["run_id"] != PARENT or contract["contract_sha256"] != document.get("parent_contract_sha256")
            or manifest.get("contract_sha256") != contract["contract_sha256"]
            or auth.get("run_id") != PARENT or auth.get("decision") != "START_ALLOWED"
            or ra.authorization_fingerprint(auth) != auth.get("authorization_sha256")
            or auth.get("authorization_sha256") != document.get("parent_authorization_sha256")
            or auth.get("frozen_contract_sha256") != contract["contract_sha256"]
            or evidence.get("contract_sha256") != contract["contract_sha256"]
            or evidence.get("fresh_runtime_condition_sha256") != auth.get("fresh_t0_runtime_condition_sha256")
            or ch.canonical_sha256(evidence) != document.get("parent_runtime_evidence_sha256")):
        raise RecoveryRefused("parent contract/authorization/T0 binding mismatch")
    if mf.verify_fragment_integrity(root / "thesis/results/intermediate", PARENT):
        raise RecoveryRefused("parent fragment integrity failure")
    for fragment, value in (("authorization.start.json", auth), ("runtime.evidence.json", evidence)):
        if read_json(root / BASE / "run_manifest.fragments" / fragment).get("content") != value:
            raise RecoveryRefused("parent fragment/manifest disagreement")
    prompts = contract["selected_prompt_hashes"]
    models = contract["model_ids"]
    if (len(prompts) != 144 or len(models) != 11 or len(set(models)) != 11
            or len({"/".join(k.split("|")[:2]) for k in prompts}) != 48
            or ch.canonical_sha256(prompts) != document.get("parent_population_sha256")
            or models != document.get("model_ids")):
        raise RecoveryRefused("parent population mismatch")
    expected_models = set(models)
    report = vp.Report(PARENT)
    config = manifest.get("resolved_config")
    if not isinstance(config, dict):
        raise RecoveryRefused("parent frozen configuration missing")
    intermediate = root / "thesis/results/intermediate"
    vp.check_identity(report, PARENT, contract, manifest)
    vp.check_conditions(report, contract, manifest)
    vp.check_split_static_invocations(report, contract, manifest, intermediate, PARENT)
    for prefix, filename in ((RAW, "generations.jsonl"), (BASE, "assembly.jsonl")):
        actual = {p.parent.name for p in (root / prefix).glob("*/" + filename)}
        if actual != expected_models:
            raise RecoveryRefused("unexpected/missing parent model")
    for model in models:
        expected = {"%s__%s__%s__%s__sample_0" % (model, *k.split("|")) for k in prompts}
        assembled = {}
        for filename, stage in FILES.items():
            prefix = RAW if stage == "generation" else BASE
            path = root / prefix / model / filename
            rows = records(path)
            ids = [r.get("sample_id") for r in rows]
            if len(ids) != len(set(ids)) or set(ids) != expected:
                raise RecoveryRefused("missing/extra/duplicate parent cells: " + stage)
            for row in rows:
                if row.get("run_id") != PARENT or row.get("model_id", (row.get("model") or {}).get("id")) != model:
                    raise RecoveryRefused("foreign parent record")
                if stage == "generation":
                    prompt = row.get("prompt") or {}
                    key = "|".join(str(prompt.get(k)) for k in ("problem_type", "name", "parallelism_model"))
                    if prompts.get(key) != ch.utf8_sha256(prompt.get("prompt_text", "")):
                        raise RecoveryRefused("generation prompt drift")
                    if row["sample_id"] != "%s__%s__sample_0" % (model, key.replace("|", "__")):
                        raise RecoveryRefused("prompt/sample identity mismatch")
                if stage == "assembly":
                    relative = BASE + "/" + model + "/sources/" + row["sample_id"] + "/generated-code.hpp"
                    if row.get("source_path", "").replace("\\", "/") != relative or not row.get("assembled"):
                        raise RecoveryRefused("assembly candidate identity mismatch")
                    source = lineage.read_path(relative)
                    if ch.raw_sha256(source) != row.get("source_sha256"):
                        raise RecoveryRefused("assembly source hash mismatch")
                    assembled[row["sample_id"]] = row["source_sha256"]
                if stage == "static" and row.get("sample_source_sha256") != assembled[row["sample_id"]]:
                    raise RecoveryRefused("static candidate hash mismatch")
            summary = {"generation": "generation_summary.json", "assembly": "assembly_summary.json",
                       "static": "static_analysis_summary.json", "correctness": "correctness_summary.json",
                       "dynamic": "dynamic_analysis_summary.json"}[stage]
            lineage.read_path(prefix + "/" + model + "/" + summary)
        entries = vp.check_assembly(report, intermediate, PARENT, model, manifest, contract,
                                    generation_sample_ids=sorted(expected))
        vp.check_static(report, config, intermediate, PARENT, model, entries)
        vp.check_correctness(report, intermediate, PARENT, model, entries)
        vp.check_dynamic(report, config, intermediate, PARENT, model, entries)
    t0 = sr.t0_domains(manifest)
    for stage in ("static.main", "static.parcoach", "static.llov", "correctness", "dynamic"):
        stamp = read_json(root / BASE / "run_manifest.fragments" / ("runtime.stage." + stage + ".json"))["content"]
        mode = stamp.get("observation_mode")
        fields = sr.COMPARED_FIELDS.get(mode)
        domains = sr.STAGE_DOMAINS[stage][1]
        if (not fields or stamp.get("stage") != stage or stamp.get("run_id") != PARENT
                or stamp.get("contract_sha256") != contract["contract_sha256"]
                or stamp.get("authorization_sha256") != auth["authorization_sha256"]
                or stamp.get("match") is not True or stamp.get("drift_fields")
                or sr._evidence_fingerprint(stamp) != stamp.get("stage_runtime_sha256")
                or set(stamp.get("domains", {})) != set(domains)):
            raise RecoveryRefused("invalid parent runtime stamp: " + stage)
        for domain in domains:
            observed = stamp["domains"][domain]
            if observed.get("compared_fields") != list(fields) or sr.domain_diff(t0[domain], observed, fields):
                raise RecoveryRefused("parent runtime domain mismatch")
    if report.status() != "PASS":
        raise RecoveryRefused("parent base checks failed: " + "; ".join(
            c["check"] + ": " + c["detail"] for c in report.checks if c["status"] in ("FAIL", "UNRESOLVED")))
    return {"schema_version": "parent_base_evidence_report.v1", "status": "PASS",
            "scope": "BASE_ONLY_NOT_FULL_RUN_ACCEPTANCE", "source_run": PARENT,
            "lineage_sha256": expected_sha, "base_cells": 1584,
            "contract_sha256": contract["contract_sha256"], "historical_repair_adopted": False,
            "historical_source": historical_source,
            "base_checks": report.checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    if args.manifest:
        result = verify(args.root, read_json(args.manifest), args.expected_sha)
    else:
        result = build_inventory(args.root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
