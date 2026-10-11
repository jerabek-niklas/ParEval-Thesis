# full_ext_recovery_004: implemented, frozen, non-productive preflight - awaiting start approval

Scope: the five models without any full-extension repair: `deepseek_v4_pro`,
`qwen36_35b_a3b`, `qwen37_max`, `gemini_36_flash`, `openai_gpt56_sol` (model priority in
this order). All 15 loops (`static_feedback`, `test_feedback`, `combined_feedback`) are
FRESH: iteration 0 is the full_ext_001 evidence, read-only by hash-bound reference and
never re-measured; iterations 1 and 2 are successor-native. No predecessor repair
exists for these models (verified absence), none is adopted. No authorization, analysis
or provider request of this run has happened before the author's explicit start
approval.

## Frozen definitions (this directory)

| file | identity |
|---|---|
| `lineage.json` | `faa086a1...` - recovery_001 byte snapshot `66f7d338...` (1,506 files, per-file hashes identical to the 003 snapshot `a2d96658...`), predecessor bindings (contract `884ad0fb...`, authorization `446a4370...`, repair condition `98b8be0f...`), 15 FRESH loop origins (144/144 parent cells each, every needed stage present, 0 external gaps), protected sibling inventories full_ext_recovery_002 (334 files, RETIRED) and full_ext_recovery_003 (571 files, COMPLETE_FROZEN_PROTECTED) |
| `equivalence.json` | `df423693...` - 346 unchanged recovery_001 source pins + 1 routing change (`pilot_run_contract.build_contract`, generic dispatch, unchanged since 003), config projection = recovery_001, 004 sources pinned, methodology replay digest `2051945d...` |
| `readiness.json` | `e92387dc...` - runtime `0d5f4889...` (= recovery_001 T0) in two probes, TSan/mmap 28, provider endpoint identities = recovery_001 T0, key names ALIBABA_MODEL_STUDIO_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY (presence checked by the preflight; values never recorded) |
| `contract.json` | `f2e77c2c...` READY, model_ids = the five models, schedule `api_first.v2` |
| `test_evidence_py38/py311/py312.json` | 71/71 synthetic tests PASS in pareval-llov (3.8.0), parcoach-demo (3.11.4), pareval-thesis (3.12.3) |
| `ast_python38/312.json` | `successor_ast.index_v1` projection evidence |

## Methodology replay (frozen in `equivalence.json`, re-derived before the first start)

The 004 routing re-derives, byte-identically, everything recovery_001 decided natively
for its six models (18 loops): 2,592 iteration-0 decisions, 1,025 iteration-1 requests
and the 170 iteration-1/2 decisions of its test_feedback loops - 0 mismatches. The
static/combined iteration>=1 path is the unchanged, pinned native orchestrator.

## Iteration 0 (non-productive dry run on the real parent evidence)

| loop | active -> iteration-1 requests | stopped_clean | stopped_analysis_incomplete | stopped_tests_pass |
|---|---|---|---|---|
| deepseek_v4_pro static / test / combined | 76 / 28 / 82 | 34 / - / 32 | 34 / - / 30 | - / 116 / - |
| qwen36_35b_a3b static / test / combined | 77 / 29 / 85 | 40 / - / 35 | 27 / - / 24 | - / 115 / - |
| qwen37_max static / test / combined | 81 / 17 / 84 | 31 / - / 30 | 32 / - / 30 | - / 127 / - |
| gemini_36_flash static / test / combined | 69 / 16 / 72 | 38 / - / 38 | 37 / - / 34 | - / 128 / - |
| openai_gpt56_sol static / test / combined | 60 / 13 / 65 | 34 / - / 34 | 50 / - / 45 | - / 131 / - |
| **sum** | **854** (363 / 103 / 388) | | | |

Iteration-2 requests: at most the samples still active after the iteration-1 decision.

## Architecture

`thesis/recovery_successor_004/` is derived from the full_ext_recovery_003 package
(handoff, lineage, routing, run, verify, contract, readiness, equivalence, external,
freeze, preflight, tests; routing and run substantially extended for the FRESH origin,
the intent ledgers, the lane breaker and `api_first.v2`; `census` is new);
`successor_writer`, `successor_supplement` and `successor_ast` are reused unchanged. No edit of any existing file: the generic
`recovery_successor_NNN` dispatch of `pilot_run_contract.build_contract` (added by 003)
resolves the 004 contract builder. Differences to 003:

- FRESH origin: iteration 0 = full_ext_001 evidence via the recovery_001 parent lineage
  (size and raw sha256 checked on every read); the iteration-0 decisions and the wave
  state are written natively by 004 (as recovery_001 did for its models). Parent
  measurements are never repeated or backfilled.
- Native request budget (unchanged): at most 2 counted submission rounds per sample and
  iteration (`request_retry_rounds`), each round one provider call with
  `retry_attempts = 2` internal retries; at most 2 iterations, so at most 854 + 854 =
  1,708 counted iteration requests.
- Per-iteration durable intent ledgers `repair/<variant>/iter{N}/submissions.jsonl`
  (`successor_submission_intent.v2`; `request_rounds.json` is only a mirror): the intent
  is fsynced BEFORE the provider call. An intent without a persisted outcome (e.g. after
  a crash) is detected on the next ledger verification as AMBIGUOUS: below the native
  bound it blocks its loop until `--resolve-ambiguous MODEL/VARIANT/SAMPLE@ITERATION
  --resolution-note TEXT` (the lost response counts as a consumed round and is marked
  `possible_duplicate_billing`; the sample is re-requested only if a round remains); at
  the bound the sample ends `stopped_api_exhausted` with an UNKNOWN outcome, reported by
  the verifier. Nothing is ever resubmitted silently.
- Schedule `api_first.v2`: all iteration-1 requests first (prioritized by provider
  lane, then variant, then model), then ANALYZE@1 pipelined with SUBMIT@2 (a loop's
  iteration-2 requests enter the submission pool as soon as they are built), then
  ANALYZE@2. Iteration-1 requests per lane: Alibaba 559 (deepseek_v4_pro 186,
  qwen36_35b_a3b 191, qwen37_max 182), Gemini 157, OpenAI 138.
- Provider lanes `openai_compatible|ALIBABA_MODEL_STUDIO_BASE_URL` (deepseek_v4_pro,
  qwen36_35b_a3b, qwen37_max), `gemini|sdk_fixed`, `openai|sdk_fixed` with an
  operational circuit breaker: 3 consecutive failed provider calls of a lane (after
  their internal retries; refusals and deterministic errors do not count) pause that
  lane for `--api-retry-delay-seconds` (default 600 s; one call already in flight may
  still fail); then exactly one half-open probe with a sample that has not yet spent a
  round at this iteration. A successful probe closes the lane; a failed probe - or no
  eligible probe sample at all - marks the lane DOWN for the rest of the invocation (its
  loops stay resumable). Other lanes continue unaffected; non-down lanes start wave 2
  closed. Native budgets, prompts, retries and stop rules are unchanged.
- Global stop (all loops; checked before every new intent and every step, in-flight
  calls finish): authority, contract or binding refusal, lineage / parent / protected /
  sibling byte drift, repair evidence of a 004 model outside 004, driver-side
  infrastructure failure, and a contract / provenance / runtime conflict reported by a
  PARCOACH/LLOV container (exit 3 merge conflict, 4 refusal, 5 runtime or
  effective-invocation drift). Per-loop stop (the other loops continue): an AMBIGUOUS
  intent below the bound, a lane DOWN, a second `blocked_api` in a wave, a tool
  failure after one missing-only retry (`--external-retry-delay-seconds`, default 60 s),
  and any other loop-local refusal (torn ledger, foreign wave state).
- Cross-run quiescence: the productive start refuses tool containers (also exited ones)
  and writer locks of ANY successor run. 002 and 003 are fully re-hashed at the start
  and by the verifier; during the run every step re-checks them stat-guarded (membership,
  size, mtime) and re-hashes on any change.

## Accepted deviations (operational, documented)

1. Iteration-0 decisions are written by 004 from the parent evidence (identical rule,
   proven by the replay).
2. ANALYZE@1 is pipelined with SUBMIT@2 (ordering only; every decision is made on the
   same inputs).
3. The lane circuit breaker defers requests during an outage; it never changes a
   budget, a prompt or a decision.
4. A request refused before it was sent (`refused_before_send`) is not counted as a
   round (as in 002/003).
5. 003 is not retired (no dispatch edit was necessary); it is protected by the
   quiescence and inventory checks instead.

## Start / resume (after commit and explicit approval)

Inside pareval-thesis with the docker socket, `--env-file .env` and
`-e PAREVAL_HOST_REPO=C:/Users/jerab/Desktop/ParEval-thesis`:
`python3 -B -u -m thesis.recovery_successor_004.run --parallel-submissions 2`.
`--status` / `--dry-run` are read-only. An invocation that ends with unfinished loops
(lane DOWN, blocked, ambiguous) exits non-zero; the same command resumes the same state
machines. The writer lock has no stale takeover: after an unclean abort (killed
container) it is removed by the operator only after confirming that no writer is alive,
as are leftover labelled tool containers.

## Experiment census before this run

`python3 -B -m thesis.recovery_successor_004.census`: 66 repair loops, 51/66 terminal
(pilot 33/33, full extension 18/33: 6 recovery_001, 4 recovery_002, 8 recovery_003),
exactly the 15 loops of this run not started, 1,980 base cells (396 pilot + 1,584 full
extension; 720 parent cells for the five models), one repair condition. This run closes
the remaining 15 full-extension loops (target 66/66).
