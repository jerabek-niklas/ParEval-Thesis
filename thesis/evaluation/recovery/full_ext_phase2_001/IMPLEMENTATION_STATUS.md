# full_ext_phase2_001: implemented, frozen, non-productive preflight - awaiting start approval

Phase 2 of the full extension (profile `recovery_successor_005`, run id `full_ext_phase2_001`):
the phase-2 backfill and the held-out enhanced tests of all eleven models, WITHOUT any
provider request. All 66 repair loops are terminal (pilot 33 by pilot_002; full extension 6
by full_ext_recovery_001, 4 by 002, 8 by 003, 15 by 004). pilot_002 completed its phase 2
earlier (943 samples, 18,860 enhanced rows) and is only verified read-only. No
authorization, measurement or provider request of this run has happened before the
author's explicit start approval.

## Work (frozen target table, missing-only)

| stage | candidates | items | applicable measurements |
|---|---|---|---|
| static.main (test_feedback) | 320 | 1,280 rows | gcc_analyzer 320, clang_tidy 320, cppcheck 320, infer 166 |
| static.parcoach (test_feedback) | 320 | 320 rows | 134 (mpi) |
| static.llov (test_feedback) | 320 | 320 rows | 154 (omp) |
| correctness (static_feedback) | 1,249 | 1,249 records | 1,249 |
| dynamic (static_feedback) | 1,249 | 1,249 records | 1,249 |
| enhanced (all) | 4,517 = 1,584 base + 2,933 candidates | 90,340 (sample, spec) pairs | 90,340 |

Inapplicable static tools get the native NOT_APPLICABLE entry (as run_model writes it).
combined_feedback candidates and the 1,584 base cells are complete except for enhanced.
Existing TIMEOUT / TOOL_ERROR / PARTIAL / NOT_ANALYZED entries and every documented
verdict are measurements and are never re-measured. The aborted parent repair
(`full_ext_001__static_feedback__iter1`, 62 answers) is excluded.

Per model (static / test / combined candidates; enhanced samples incl. 144 base cells):

| model | static_feedback | test_feedback | combined_feedback | enhanced samples |
|---|---|---|---|---|
| claude_fable_5 | 105 | 21 | 109 | 379 |
| claude_opus_5 | 97 | 27 | 100 | 368 |
| deepseek_v4_flash | 117 | 32 | 130 | 423 |
| deepseek_v4_pro | 123 | 40 | 130 | 437 |
| gemini_31_pro | 143 | 12 | 150 | 449 |
| gemini_36_flash | 112 | 26 | 118 | 400 |
| openai_gpt55 | 81 | 14 | 96 | 335 |
| openai_gpt56_sol | 80 | 16 | 99 | 339 |
| qwen36_35b_a3b | 129 | 43 | 142 | 458 |
| qwen37_max | 129 | 25 | 136 | 434 |
| qwen3_coder_api | 133 | 64 | 154 | 495 |
| **sum** | **1,249** | **320** | **1,364** | **4,517** |

## Frozen definitions (this directory)

| document | self-hash | content |
|---|---|---|
| `targets.json` | `c836011f34ad8961aaf5ed46b325d9542bc6c22e5b01c6818e40fd216feacec7` | 77 targets, 4,517 candidates (1,584 base + 2,933 repair) |
| `lineage.json` | `81a5a18350cfd76c2b4b18a15cb97fabfa9594230729741c8a4b32b9c4317bb6` | raw-byte inventories + chain of custody + historical definitions |
| `test_evidence_py312.json` | `2b314ad56dab386d41d6ae12f96a37a73c4546c306c4b9dae263cc6a3480fa74` | suite in pareval-thesis (Python 3.12) (109 tests) |
| `test_evidence_py38.json` | `00060df304ce594afa0df2151544dfd770b9e3ba6b050c1853f25e561128949e` | authority + static subset in pareval-llov (Python 3.8) (47 tests) |
| `test_evidence_py311.json` | `08d535ce818969bbb961951c999a22a99b370e82224e1dd0f3427283fecc4431` | authority + static subset in parcoach-demo:2.4.1 (Python 3.11) (47 tests) |
| `ast_python38.json` | `ec8bd3ac3358ce1cc63342b51a48944b97fb46f2871a834a06a5d5de1f744399` | AST evidence, Python 3.8 |
| `ast_python312.json` | `0846de7dd93967a2b6b0a1bfe6dbf6c8971105193c9ba6d9715e482f8189d085` | AST evidence, Python 3.12 |
| `equivalence.json` | `1a14223e1b3fd9e85fffc5be335776b9cfe4924248942b796b66cd8465f9be57` | origin pins, phase-2 source pins, config projection, measurement equivalence |
| `readiness.json` | `dc2c8cbddace2b01db2b07b9a15bcfd2452b6284d99cf9d67711cbd7a3bfdf05` | runtime == origin T0 (two probes), no provider key |
| `contract.json` | `1fd28309588a328d2459cbdf56cc95110492e15a84bd9afd2c0074e2135cdbc0` | frozen recovery_001 contract + phase2_provenance |

## Architecture

`thesis/recovery_successor_005/` (new files only; no existing file edited - the generic
`recovery_successor_NNN` dispatch of `pilot_run_contract.build_contract` resolves the
contract builder):

- `targets.py` - frozen target table: 77 targets (11 base + 66 iteration targets), each
  candidate bound to its loop's request and its source sha256; owners from the census
  (native: `O__<variant>__iter<N>`; continued 002/003: iteration 1 in recovery_001,
  iteration 2 in the successor).
- `lineage.py` - raw-byte inventories of pilot_002, full_ext_001 and
  full_ext_recovery_001..004 (9,485 files), chain of custody against the earlier frozen
  inventories (recovery_001 `protected_history.json`, the 004 lineage's recovery_001
  snapshot and 002/003 sibling inventories, the 004 contract, the 001..003 definitions),
  the historical definitions, write confinement to `thesis/results/intermediate/full_ext_phase2_001`,
  provider isolation (the config loader's `.env` import is disabled, provider variables are
  removed from the process).
- `ledger.py` / `plan.py` - one presence semantics (history + 002/003 supplements +
  phase-2 ledgers; a phase-2 row may never shadow a historical one) and the missing-only plan.
- `measure_static.py` + `external.py` - static supplements (`successor_static_supplement.v1`,
  the 003 schema) through `successor_supplement.measure_entry`; main tools in-process,
  PARCOACH/LLOV in their pinned images (container entrypoint `external.py`).
- `measure_runtime.py` - correctness via `run_correctness.run_sample`; dynamic as a 1:1
  re-statement of `run_dynamic_analysis.run_model`'s per-sample body.
- `measure_enhanced.py` - `run_enhanced_tests.precompute_gates` / `process_sample`
  unchanged; one gate cache shared by all targets of an invocation (as the native runner
  shares it across models), jobs serial 2 / omp 1 / mpi 1 and timeout from the config
  (fingerprint component G unchanged), a registration sidecar per target written before
  the first record (crash-safe resume, refused under another execution condition).
- `verify.py` / `composite.py` - per-model completeness of all eleven models (pilot +
  full extension, exact enhanced pair sets, provenance and binding of every row,
  registration drift, immutability, 1,980-cell population) and the unified merged view.
- authority: `contract.py` (copy of the frozen recovery_001 contract + `phase2_provenance`),
  `equivalence.py` (346 unchanged origin pins + the registered routing change, phase-2
  source pins, config projection = origin, measurement-equivalence tests), `readiness.py`
  (runtime == origin T0 in two probes, TSan/mmap 28; no provider key), `freeze.py`,
  `preflight.py`, `run.py`.

Every new record carries `writer_run_id`/`authority_run_id` = full_ext_phase2_001,
`candidate_source_run`, `candidate_source_sha256`, `candidate_source_path`, `variant`,
`iteration` and the binding (contract, authorization, stage runtime, invocation sha256).
Results live under `thesis/results/intermediate/full_ext_phase2_001/<model>/supplements/<source_run>/`.

## Operational safety

- single writer lock; cross-run quiescence (no container / lock of any successor run);
  dirty worktree refused; protected bytes re-hashed at every start and stat-guarded per target;
- missing-only resume: the same command continues; torn ledger tails are archived;
- graceful stop: `docker stop -t 7200 pareval-phase2-001` (SIGTERM) finishes the sample in
  flight and releases the lock; Ctrl-C aborts like the native runners and never writes
  an interrupted measurement;
- global stop on any integrity / contract / provenance / runtime conflict; a failure
  confined to one target is recorded as open and the other targets continue;
- no measurement runs concurrently with another (timeouts and timings must not be
  distorted; this mirrors the pilot phase 2).

## Runtime estimate (from existing measurements)

| stage | basis | estimate |
|---|---|---|
| static.main | 1,126 tool runs, full_ext_001 means (infer 19-26 s, clang_tidy ~4.7 s, gcc_analyzer ~2 s, cppcheck ~0.7 s) | ~1.5-2 h |
| static.parcoach / llov | 134 x ~12-15 s + 154 x <1 s + 44 container starts | ~0.7 h |
| correctness | 1,249 x 4.7-7.1 s (pilot backfill / full_ext loops) | ~1.6-2.5 h |
| dynamic | 1,249 x 54-62 s | ~19-22 h |
| enhanced | pilot per-sample cost by execution model (serial 36 s at 2 jobs, omp 31 s, mpi 67 s) x full-ext mix; shared gates ~1 h | ~55 h |
| protected-byte verification | per invocation start | ~15 min |
| **total** | sequential, one stage at a time | **~78-82 h (~3.3 days)** |

## Start / resume (after commit and explicit approval)

`docker run -d --name pareval-phase2-001 -v /var/run/docker.sock:/var/run/docker.sock
-v "C:/Users/jerab/Desktop/ParEval-thesis:/workspace" -w /workspace
-e PAREVAL_HOST_REPO=C:/Users/jerab/Desktop/ParEval-thesis pareval-thesis
python3 -B -u -m thesis.recovery_successor_005.run`
(no `--env-file`: no provider key is needed). Resume: the same command after
`docker rm pareval-phase2-001`. `--status` / `--dry-run` are read-only.
