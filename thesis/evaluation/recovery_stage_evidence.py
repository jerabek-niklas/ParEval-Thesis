"""Pure candidate/provenance helpers for future enhanced/backfill integration.

There is no runner here. Returning a plan never starts a tool or writes data.
"""
from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import (RECOVERY, PARENT, RecoveryRefused,
                                               require_complete_loop, reject_historical_response)


def enhanced_base_candidate(lineage, model_id, sample_id, states_by_loop, expected_by_loop, terminal_statuses):
    expected_loops = {(m, v) for m in [model_id]
                      for v in ("static_feedback", "test_feedback", "combined_feedback")}
    if set(states_by_loop) != expected_loops or set(expected_by_loop) != expected_loops:
        raise RecoveryRefused("held-out requires every contracted recovery loop")
    for key in sorted(expected_loops):
        require_complete_loop(states_by_loop[key], expected_by_loop[key], terminal_statuses)
    if model_id not in lineage.document["model_ids"]:
        raise RecoveryRefused("candidate model outside bound population")
    relative = "thesis/results/intermediate/%s/%s/sources/%s/generated-code.hpp" % (PARENT, model_id, sample_id)
    path = lineage.read_path(relative)
    return {"writer_run_id": RECOVERY, "candidate_source_run": PARENT,
            "candidate_source_sha256": ch.raw_sha256(path), "candidate_source_path": relative,
            "model_id": model_id, "sample_id": sample_id,
            "authority_run_id": RECOVERY}


def validate_new_evidence(record, candidate, authorization_sha):
    if not authorization_sha or record.get("authorization_sha256") != authorization_sha:
        raise RecoveryRefused("wrong recovery authorization")
    if record.get("run_id") != candidate["writer_run_id"]:
        raise RecoveryRefused("wrong writer/native run identity")
    for key in ("writer_run_id", "candidate_source_run", "candidate_source_sha256", "model_id", "sample_id"):
        if not candidate.get(key) or record.get(key) != candidate[key]:
            raise RecoveryRefused("candidate provenance mismatch: " + key)
    return True


def missing_recovery_keys(existing_rows, expected_keys, key):
    """Missing only: a stored gap/timeout is present, never eligible for rerun."""
    seen = set()
    for row in existing_rows:
        if row.get("run_id") != RECOVERY:
            reject_historical_response(row)
        value = key(row)
        if value in seen or value not in expected_keys:
            raise RecoveryRefused("duplicate/unexpected recovery evidence")
        seen.add(value)
    return set(expected_keys) - seen
