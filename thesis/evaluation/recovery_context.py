"""Explicit stage-split readers shared by recovery entrypoints.

Reading a parent artifact never grants write authority. Parent reference paths
are enumerated and verified by the frozen lineage; there is no file fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

from thesis.evaluation.recovery_lineage import (
    PARENT, RECOVERY, VARIANTS, RecoveryLineage, RecoveryRefused,
    require_complete_loop,
)

ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = ROOT / "thesis/evaluation/recovery/full_ext_recovery_001"


def load_lineage():
    document = json.loads((DEFINITIONS / "lineage.json").read_text(encoding="utf-8"))
    return RecoveryLineage(ROOT, document, document["lineage_sha256"])


def is_recovery(run):
    return run == RECOVERY or (isinstance(run, str) and run.startswith(RECOVERY + "__"))


def candidate_run(run):
    if run == RECOVERY:
        return PARENT
    if is_recovery(run):
        lineage = load_lineage()
        allowed = {lineage.iteration_run(v, i) for v in VARIANTS for i in (1, 2)}
        if run not in allowed:
            raise RecoveryRefused("unregistered recovery iteration")
    return run


def assembly_path(intermediate, run, model):
    if run != RECOVERY:
        candidate_run(run)
        return Path(intermediate) / run / model / "assembly.jsonl"
    lineage = load_lineage()
    if Path(intermediate).resolve() != ROOT / "thesis/results/intermediate":
        raise RecoveryRefused("unbound recovery evidence root")
    return lineage.read_path("thesis/results/intermediate/%s/%s/assembly.jsonl" % (PARENT, model))


def require_terminal(config, model):
    from thesis.repair import orchestrator
    lineage = load_lineage()
    path = assembly_path(config["outputs"]["intermediate_dir"], RECOVERY, model)
    expected = [json.loads(line)["sample_id"] for line in path.read_text(encoding="utf-8").splitlines() if line]
    if model not in lineage.document["model_ids"]:
        raise RecoveryRefused("model outside recovery population")
    for variant in VARIANTS:
        paths = orchestrator.LoopPaths(config, RECOVERY, model, variant)
        rows = list(orchestrator.load_sample_states(paths.state_path).values())
        require_complete_loop(rows, expected, orchestrator.TERMINAL_STATUSES)
        wave = json.loads(paths.wave_state_path.read_text(encoding="utf-8"))
        if (wave.get("run_id") != RECOVERY or wave.get("model_id") != model
                or wave.get("variant") != variant or wave.get("phase") != "done"):
            raise RecoveryRefused("recovery wave is not terminal")
    return True


def candidate_provenance(config, run, model, sample):
    from thesis.evaluation.condition_hashing import raw_sha256
    source = candidate_run(run)
    path = Path(config["outputs"]["intermediate_dir"]) / source / model / "sources" / sample / "generated-code.hpp"
    if run == RECOVERY:
        load_lineage().read_path(path.resolve().relative_to(ROOT).as_posix())
    if not path.is_file():
        raise RecoveryRefused("missing explicit candidate source")
    return dict(writer_run_id=run, candidate_source_run=source,
                candidate_source_sha256=raw_sha256(path), authority_run_id=RECOVERY)


def validate_target(config, target, model, enhanced=False):
    from thesis.evaluation import recovery_contract, run_authorization
    from thesis.repair import orchestrator
    contract = recovery_contract.build(ROOT / "thesis/config/recovery.yaml", RECOVERY)
    run_authorization.load_and_validate_run_authorization(
        config, RECOVERY, config_path=ROOT / "thesis/config/recovery.yaml", profile="recovery")
    if model not in contract["model_ids"]:
        raise RecoveryRefused("foreign recovery model")
    source = candidate_run(target)
    if not is_recovery(target):
        raise RecoveryRefused("writer outside recovery lineage")
    path = assembly_path(config["outputs"]["intermediate_dir"], target, model)
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s]
    ids = [r.get("sample_id") for r in rows]
    if not rows or len(set(ids)) != len(ids) or any(
            r.get("run_id") != source or r.get("model_id") != model for r in rows):
        raise RecoveryRefused("candidate assembly identity mismatch")
    if target != RECOVERY:
        variant, number = target[len(RECOVERY) + 2:].split("__iter")
        iteration = int(number)
        paths = orchestrator.LoopPaths(config, RECOVERY, model, variant)
        states = orchestrator.load_sample_states(paths.state_path)
        wave = json.loads(paths.wave_state_path.read_text(encoding="utf-8"))
        requests = [json.loads(s) for s in paths.requests_path(iteration).read_text(encoding="utf-8").splitlines() if s]
        request_ids = [r.get("sample_id") for r in requests]
        if len(set(request_ids)) != len(request_ids) or not set(ids) <= set(request_ids):
            raise RecoveryRefused("iteration assembly outside its request set")
        if any(r.get("run_id") != RECOVERY or r.get("model_id") != model
               or r.get("variant") != variant or r.get("iteration") != iteration for r in requests):
            raise RecoveryRefused("foreign iteration request")
        in_flight = (wave.get("run_id") == RECOVERY and wave.get("model_id") == model
                     and wave.get("variant") == variant and wave.get("iteration") == iteration
                     and wave.get("phase") in ("assembled", "analyzed_waiting_external", "analyzed"))
        for sample in ids:
            row = states.get(sample, {})
            minimum = iteration - 1 if in_flight else iteration
            if row.get("run_id") != RECOVERY or row.get("iteration", -1) < minimum:
                raise RecoveryRefused("iteration lacks supporting recovery trajectory")
    if enhanced:
        require_terminal(config, model)
    return True
