"""Read-only compatibility audit. Does not validate or replace a whole proof.

Invoke in BOTH pinned containers. Reports hashes, never request text or secrets.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

from thesis.evaluation import condition_hashing as ch, successor_ast as sa
from thesis.evaluation.recovery_equivalence import ROUTING_FUNCTIONS
from thesis.evaluation.recovery_historical_source import git_blob
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.evaluation.recovery_source_projection import pre_recovery_enhanced_source


def verify(root):
    root = Path(root).resolve()
    proof = json.loads((root / "thesis/evaluation/recovery/full_ext_recovery_001/equivalence.json").read_text(encoding="utf-8"))
    from thesis.evaluation.pilot_run_contract import load_frozen
    contract = load_frozen(root / "thesis/evaluation/recovery/full_ext_recovery_001/contract.json")
    if (ch.canonical_sha256({k: v for k, v in proof.items() if k != "proof_sha256"})
            != proof.get("proof_sha256") or proof.get("proof_sha256")
            != contract["recovery_provenance"]["equivalence_sha256"]):
        raise RecoveryRefused("AST reference proof is not bound to the frozen predecessor contract")
    expected = {k: v for k, v in proof["unchanged_projection"].items() if k.endswith("#non_routing_ast")}
    if len(expected) != 9:
        raise RecoveryRefused("unexpected frozen AST projection scope")
    rows = []
    for key, value in sorted(expected.items()):
        relative = key.split("#")[0]
        current = checked_path(root, relative).read_text(encoding="utf-8")
        historical = git_blob(root, proof["parent_commit"], relative).decode("utf-8")
        if relative.endswith("run_enhanced_tests.py"):
            current = pre_recovery_enhanced_source(current)
        before = sa.projection_sha256(historical, ROUTING_FUNCTIONS[relative])
        after = sa.projection_sha256(current, ROUTING_FUNCTIONS[relative])
        if before != value or after != value:
            raise RecoveryRefused("successor AST projection differs: " + relative)
        rows.append(dict(path=relative, historical_sha256=before, current_sha256=after,
                         frozen_sha256=value))
    result = dict(schema_version="successor_ast_evidence.v1", status="PASS",
                  scope="AST_ONLY_NOT_CONTRACT_OR_RUNTIME_ACCEPTANCE",
                  algorithm=sa.VERSION, python=platform.python_version(),
                  old_proof_sha256=proof["proof_sha256"], projections=rows,
                  source_pins={p: ch.raw_sha256(root / p) for p in (
                      "thesis/evaluation/successor_ast.py",
                      "thesis/evaluation/successor_ast_evidence.py")})
    result["evidence_sha256"] = ch.canonical_sha256(result)
    return result


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[2]), indent=2))
