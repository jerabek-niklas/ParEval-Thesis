# full_ext_recovery_003: implemented, frozen, non-productive preflight - awaiting start approval

Scope: `claude_fable_5`, `claude_opus_5`, `gemini_31_pro`, `openai_gpt55`.
`static_feedback` and `combined_feedback` are CONTINUED from recovery_001 (all 8 loops
frozen at iteration 1, `analyzed_waiting_external`: recovery_001 ran neither PARCOACH
nor LLOV for these models); `test_feedback` is ADOPTED (done in recovery_001). No
authorization, analysis or provider request of this run has happened before the
author's explicit start approval.

## Frozen definitions (this directory)

| file | identity |
|---|---|
| `lineage.json` | `ff0f0a97...` - recovery_001 byte snapshot `a2d96658...` (1,506 files), predecessor bindings, handoff facts of the 12 loops, retirement records of recovery_001 and full_ext_recovery_002 (334 protected files) |
| `equivalence.json` | `2bdd53aa...` - 346 unchanged recovery_001 source pins + 1 routing change (`pilot_run_contract.build_contract`, both successor dispatches), baseline from the 8d88ebc Git blobs, config projection = recovery_001, 003 sources + reused 002 helpers pinned |
| `readiness.json` | `1f9a5163...` - runtime `0d5f4889...` (= recovery_001 T0) in two probes, TSan/mmap 28, provider endpoint identities = recovery_001 T0 (`None` = SDK-fixed endpoint for all four models), keys ANTHROPIC/GEMINI/OPENAI set |
| `contract.json` | `e7becfe7...` READY, model_ids = the four models |
| `test_evidence_py38/py311/py312.json` | 57/57 synthetic tests PASS in pareval-llov (3.8.0), parcoach-demo (3.11.4), pareval-thesis (3.12.3) |
| `ast_python38/312.json` | `successor_ast.index_v1` projection evidence |

## Handoff (verified from the recovery_001 bytes)

| loop | predecessor answers (it1) | active | PARCOACH missing (mpi) | LLOV missing (omp) |
|---|---|---|---|---|
| claude_fable_5 static / combined | 69 / 77 | 69 / 77 | 31 / 34 | 25 / 29 |
| claude_opus_5 static / combined | 52 / 58 | 52 / 58 | 25 / 26 | 17 / 21 |
| gemini_31_pro static / combined | 95 / 96 | 95 / 96 | 39 / 39 | 36 / 37 |
| openai_gpt55 static / combined | 62 / 66 | 62 / 66 | 29 / 30 | 20 / 23 |
| **sum** | **575** | **575** | **253** | **208** |

test_feedback (adopted, done): claude_fable_5 16+5, claude_opus_5 18+9, gemini_31_pro
10+2, openai_gpt55 10+4 answers. Iteration-2 requests: at most 575 (only samples still
active after the iteration-1 decision); the exact number follows from the decisions.

## Architecture

`thesis/recovery_successor_003/` = the full_ext_recovery_002 successor modules with
their constants rebound (handoff, lineage, equivalence, contract, readiness, external,
routing, run, verify, freeze, preflight, tests); `successor_writer`,
`successor_supplement` and `successor_ast` are reused unchanged. Differences to 002:

- PARCOACH **and** LLOV are successor-owned iteration-1 supplements (both images, both
  pinned); a supplement tool must be entirely absent from a predecessor record; a
  supplement counts as complete only when it covers every assembled sample (stubs
  included, as the native single-pass `run_model`).
- Provider endpoint identities are compared including `None`.
- Schedule `api_first.v1` (all provider requests before any deferrable analysis),
  submissions interleaved by provider (anthropic, gemini, openai, anthropic).
- The per-model verification is persisted under
  `thesis/results/intermediate/full_ext_recovery_003/verification/`.

## Pinned edit and retirement of full_ext_recovery_002

`thesis/evaluation/pilot_run_contract.py` (`build_contract`) gains a GENERIC dispatch:
profile `recovery_successor_NNN` -> `thesis.recovery_successor_NNN.contract.build`, so
later successors add packages instead of editing the file again. The
full_ext_recovery_002 proof pins the previous bytes of that file, so 002 can no longer
rebuild its contract: all 002 writers are retired (002 is complete in its repair scope;
its results stay byte-frozen, inventoried in `lineage.json` and verified by this run).
The 123 existing successor/recovery/extension regression tests still pass.

## Start / resume (after commit and explicit approval)

Inside pareval-thesis with the docker socket, `--env-file .env` and
`-e PAREVAL_HOST_REPO=C:/Users/jerab/Desktop/ParEval-thesis`:
`python3 -B -u -m thesis.recovery_successor_003.run --parallel-submissions 2`.
The same command resumes after any abort; `--status` / `--dry-run` are read-only.

## Open after this run

Phase-2 backfill and held-out (enhanced) tests of all trajectory targets
(`model_complete: false`); the 5 models without any full_ext repair
(deepseek_v4_pro, gemini_36_flash, openai_gpt56_sol, qwen36_35b_a3b, qwen37_max).
