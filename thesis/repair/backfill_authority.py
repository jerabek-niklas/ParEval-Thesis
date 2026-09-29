"""Fail-closed authority/target separation; does not execute measurements."""
from __future__ import annotations
import json
import os
from contextlib import contextmanager
from pathlib import Path

def validate_target(config, base_run_id, target_run_id, model_id, enhanced=False):
    from thesis.evaluation import stage_runtime
    from thesis.repair import orchestrator
    from thesis.repair.run_backfill import loop_state_terminality
    if base_run_id == "full_ext_recovery_001":
        from thesis.evaluation.recovery_context import validate_target as validate_recovery
        validate_recovery(config, target_run_id, model_id, enhanced)
        return stage_runtime.enforcement_state(config, base_run_id)
    state = stage_runtime.enforcement_state(config, base_run_id)
    if not state.get("enforced"):
        raise ValueError("backfill requires an authorized contracted base run")
    contract = state["contract"]
    if contract.get("profile") == "full_extension":
        from thesis.evaluation import method_equivalence, extension_contract, condition_hashing
        certificate = json.loads(extension_contract.CERTIFICATE.read_text(encoding="utf-8"))
        method_equivalence.validate_certificate(
            certificate, (contract.get("extension_provenance") or {}).get("equivalence_sha256"))
        runner_pin = condition_hashing.canonical_sha256({
            extension_contract.RUNNER: condition_hashing.raw_sha256(extension_contract.ROOT / extension_contract.RUNNER)})
        if runner_pin != (contract.get("conditions") or {}).get("enhanced_runner_sources_sha256"):
            raise ValueError("backfill runner differs from the extension contract")
    if model_id not in contract.get("model_ids", []):
        raise ValueError("backfill model is outside the contract")
    variants = (contract.get("repair_plan") or {}).get("variants", [])
    if target_run_id != base_run_id:
        prefix = base_run_id + "__"
        matches = []
        for variant in variants:
            stem = prefix + variant + "__iter"
            if target_run_id.startswith(stem):
                suffix = target_run_id[len(stem):]
                if suffix.isdigit() and str(int(suffix)) == suffix and int(suffix) > 0:
                    matches.append((variant, int(suffix)))
        if len(matches) != 1:
            raise ValueError("invalid base -> iteration relationship")
        variant, iteration = matches[0]
        paths = orchestrator.LoopPaths(config, base_run_id, model_id, variant)
        states = orchestrator.load_sample_states(paths.state_path)
        if not states or iteration > max(int(s.get("iteration", -1)) for s in states.values()):
            raise ValueError("iteration has no supporting repair state")
        if iteration > int((contract.get("repair_plan") or {}).get("max_iterations", -1)):
            raise ValueError("iteration exceeds the contracted budget")
    root = Path(config["outputs"]["intermediate_dir"])
    assembly = root / target_run_id / model_id / "assembly.jsonl"
    if not assembly.is_file():
        raise ValueError("backfill target has no assembly")
    ids = set()
    for line in assembly.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("run_id") != target_run_id or row.get("model_id") != model_id:
            raise ValueError("assembly target identity mismatch")
        sample_id = row.get("sample_id")
        if not sample_id or sample_id in ids:
            raise ValueError("duplicate/missing assembly sample identity")
        ids.add(sample_id)
    if not ids:
        raise ValueError("empty backfill assembly")
    if target_run_id != base_run_id:
        for sample_id in ids:
            recorded = states.get(sample_id) or {}
            reached = recorded.get("iteration")
            if (not isinstance(reached, int) or isinstance(reached, bool) or reached < iteration):
                raise ValueError("target sample has no supporting repair iteration: " + sample_id)
    if enhanced:
        for variant in variants:
            terminal = loop_state_terminality(orchestrator.LoopPaths(config, base_run_id, model_id, variant).state_path)
            if (not terminal["state_present"] or not terminal["terminal"] or
                    terminal["unknown_statuses"] or terminal["invalid_iterations"]):
                raise ValueError("Enhanced backfill requires all valid terminal loops")
    return state

def refuse_partial(path, expected_ids, tool_settings=None):
    """Existing gaps count as measurements. Never retry them or partial files."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return "missing"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row.get("sample_id") for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise ValueError("partial/duplicate/unexpected stage records: " + str(path))
    if tool_settings is not None:
        for row in rows:
            if row.get("execution_model") not in ("serial", "omp", "mpi"):
                raise ValueError("missing execution identity in dynamic record")
            required = {name for name, setting in tool_settings.items()
                        if row["execution_model"] in setting.execution_models}
            if not required <= set(row.get("tools") or {}):
                raise ValueError("partial dynamic tool coverage: " + str(path))
    return "complete"

@contextmanager
def backfill_lock(config, base, model):
    """Fail closed after crash; never auto-remove another process's lock."""
    directory = Path(config["outputs"]["intermediate_dir"]) / base / model
    if not directory.is_dir():
        raise ValueError("backfill base/model directory missing")
    path = directory / "backfill.lock"
    descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, ("pid=%d\n" % os.getpid()).encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink()
