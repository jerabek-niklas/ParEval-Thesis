# full_ext_recovery_002: implemented, frozen, non-productive preflight PASS - STOPPED before the first productive start

Scope: `qwen3_coder_api` and `deepseek_v4_flash` only. `static_feedback` and
`combined_feedback` are CONTINUED from recovery_001 (both stopped at iteration 1,
`analyzed_waiting_external`, LLOV missing); `test_feedback` is ADOPTED (done in
recovery_001). No authorization, analysis or provider request of the successor has
happened. The productive start needs a commit (clean worktree) and the author's
explicit approval.

## Frozen definitions (this directory)

| file | identity |
|---|---|
| `lineage.json` | `890b8c9b...` - predecessor byte snapshot `d3548dc9...` (1,506 files), bindings, handoff facts, retirement record |
| `equivalence.json` | `ad8b1c79...` - 346 unchanged predecessor pins + 1 routing change, baseline re-derived from the 8d88ebc Git blobs, config projection = recovery_001, test evidence |
| `readiness.json` | `c6382309...` - runtime `0d5f4889...` (= recovery_001 T0) in two probes, TSan/mmap 28, provider endpoints = recovery_001 T0 |
| `contract.json` | `827f7eac...` READY, model_ids = the two models |
| `test_evidence_py38/py311/py312.json` | 48/48 synthetic tests PASS in pareval-llov (3.8.0), parcoach-demo (3.11.4), pareval-thesis (3.12.3) |
| `ast_python38/312.json` | `successor_ast.index_v1` projection evidence |

## What is reused (hash-bound reference, never copied or rewritten)

| loop | predecessor answers | active at handoff | LLOV missing (omp) |
|---|---|---|---|
| deepseek_v4_flash/static_feedback | 76 | 76 | 25 |
| deepseek_v4_flash/combined_feedback | 80 | 80 | 29 |
| qwen3_coder_api/static_feedback | 83 | 83 | 27 |
| qwen3_coder_api/combined_feedback | 90 | 90 | 31 |
| deepseek_v4_flash/test_feedback (adopted) | 24 + 8 | 0 (done) | - |
| qwen3_coder_api/test_feedback (adopted) | 43 + 21 | 0 (done) | - |

All 425 predecessor requests rebuild byte-identically through the successor read
routing (replay gate). Iteration 0 is read from full_ext_001 through the recovery_001
parent lineage; iteration 1 from the predecessor snapshot plus successor-owned LLOV
supplements (`thesis/results/intermediate/full_ext_recovery_002/<model>/supplements/...`);
iteration 2 is successor-native (`full_ext_recovery_002__<variant>__iter2`).

## Implementation (successor modules, all pinned by the proof)

- `thesis/repair/successor_routing.py`: `SuccessorRepairLoop` = the native
  `RepairLoop` with routed reads, refused writes for iterations 0/1, durable
  submission-intent ledger (`repair/<variant>/iter2/submissions.jsonl`; ambiguous
  intent -> STOP, `--resolve-ambiguous` is an explicit operator decision), per-step
  authority + predecessor immutability, successor-started tool containers.
- `thesis/repair/run_successor.py`: single-writer driver (O_EXCL lock, no stale
  takeover), first-start runtime/endpoint gate, T0 bootstrap/rehydration, parallel
  provider phase across loops (`--parallel-submissions`, default 1 = native),
  one automatic re-queue for recorded provider failures and failed tool rounds,
  per-model verification.
- `thesis/evaluation/successor_external.py` (tool containers): binding checks without
  contract rebuild (python 3.8 LLOV), writer token, SUPPLEMENT (missing-only) and
  NATIVE (iteration 2) modes.
- `successor_handoff/lineage/supplement/writer/contract/equivalence/readiness/freeze/
  preflight`, `verify_successor_run.py`, tests.

## Pinned edit and retirement

The only predecessor-pinned file changed is `thesis/evaluation/pilot_run_contract.py`
(`build_contract` gains the `recovery_successor` dispatch; non-routing AST unchanged,
exact diff in `equivalence.json`). Consequence: recovery_001's contract no longer
rebuilds, so every recovery_001 writer is retired for all models; recovery_001
evidence stays byte-frozen (retirement record in `lineage.json`). The 71 existing
recovery/extension regression tests still pass.

## Start / resume (after commit and explicit approval)

Inside pareval-thesis with the docker socket, `--env-file .env` and
`-e PAREVAL_HOST_REPO=C:/Users/jerab/Desktop/ParEval-thesis`:
`python3 -B -u -m thesis.repair.run_successor [--parallel-submissions N]`.
The same command resumes after any abort. `--status` / `--dry-run` are read-only.

## Open / limitations

- Phase-2 backfill and held-out (enhanced) tests of all trajectory targets remain
  open work; the per-model verification reports `model_complete: false`.
- Native `run_backfill` is not writer-lock-aware: it must not be run on the successor
  while `run_successor` runs (native `run_repair` is refused: no writer token, no
  provider context).
- Per-step predecessor immutability is stat-guarded (full re-hash on any size/mtime/
  membership change; every predecessor read re-hashes its bytes; deep verification at
  start and in the final verification) because a full re-hash takes minutes on the
  Docker Desktop bind mount.
