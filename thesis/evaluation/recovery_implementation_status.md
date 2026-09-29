# Stage-split recovery infrastructure

The productive entrypoint is `python3 -B -m thesis.repair.run_recovery --config thesis/config/recovery.yaml`.
It is NOT executed during implementation. Review and commit the implementation
before using it; the entrypoint refuses an uncommitted checkout.

## Ownership

- `pilot_002`: unchanged historical 396-cell population.
- `full_ext_001`: unchanged historical 1584-cell base generation, assembly,
  static, correctness and dynamic evidence.
- `full_ext_recovery_001`: zero base cells; new repair, enhanced and backfill
  evidence only. Iteration-zero inputs are hash-bound parent references.
- Recovery iteration records retain their own native run identity.
- Historical 62 repair responses/assemblies are never adopted. Historical
  requests are a comparator for 62 freshly derived initial requests only.
- The old extension must not be resumed from the parser-fixed checkout.

## Definitions and fail-closed checks

Definitions live in `thesis/evaluation/recovery/full_ext_recovery_001/`.
The recovery contract reopens the parent report, historical Git source pins,
the entire protected byte inventory, current equivalence proof and readiness.
It never rebuilds the old parent contract against new source code.
The authorization/provider guards rebuild this new contract.

The JSON Docker metadata parser preserves the old logical identity definition.
The proof separately records parser transport and recovery routing changes,
exact diffs, source pins, unchanged-code/config projections and test evidence.
Only the new recovery definitions are updated; historical certificates and
contracts are not rewritten.

Recovery repair loops start with new state. Existing missing-only stage
execution and batch/direct behavior are retained. Parent gaps are not rerun.
Enhanced execution requires all three recovery variants for the model to be
terminal, and records explicit candidate-source/writer/authority provenance.

The final recovery verifier reopens terminal states, sample sets, iteration
analyses, enhanced/backfill coverage, native ownership and runtime/invocation
evidence. Composite V2 requires the unchanged pilot verifier, verified parent
base and completed recovery verifier; a PLANNED check is not completion.
The stage-aware overview reader preserves native source envelopes.

## Verification scope

Tests include parser shape/equivalence negatives, immutable parent evidence,
deterministic contracts, authorization revalidation, fresh/resumed repair
state machines, held-out gates, missing-only backfill, population/reader
ownership, runtime-stamp schema and an on-disk 33-loop complete verifier
fixture. The latter uses a miniature synthetic population and injects only
the separately tested parent-contract/authorization discovery boundary; it
does not claim a productive recovery has completed.

The historical V1 planned-composite regression uses its exact original Git
source snapshot in a temporary directory. Its live certificate is intentionally
invalid in the new checkout; no global legacy check is weakened.

Read-only diagnostic entrypoint:
`python3 -B -m thesis.evaluation.recovery_preflight`.
`--allow-uncommitted` is exclusively the implementation audit, never a
productive start override. It must not be passed to the start entrypoint.

No productive authorization, provider call, experiment measurement or recovery
run is created by this implementation task.
