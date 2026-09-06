# Pre-run enforcement addendum

Provider-chokepoint enforcement, T0 authorization, fresh T0 runtime
revalidation, per-stage runtime binding and effective invocation provenance.

- Start HEAD: `636c370394f465a2b8ece7ea5c8920762af10178` (branch
  `thesis-static-analysis`, parent `d56db25c`), working tree clean, 0
  untracked files at the start.
- Date: 2026-09-06
- Scope: ENFORCEMENT and PROVENANCE only. No prompt, semantic-decision,
  comparator, verdict, spec, static-finding, repair, assembly, timing or
  reporting semantics is changed. No LLM/API call was made (every provider
  path in the tests is a mock). No pilot_002. No population, reuse,
  publication or run-id decision.

Three levels stay strictly separated:

| level | question | artifact |
|---|---|---|
| PRE-FLIGHT | is the PLANNED state compatible with the gate? | `pilot_preflight.py` (`PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true`) |
| T0 START ENFORCEMENT | may this process spend money NOW? | `run_authorization.authorize_start` + the chokepoint guard |
| POST-RUN VERIFICATION | did the run actually happen under the pinned conditions? | `verify_pilot_run.py` |

---

## 1. Start provenance

Entry gates on the start HEAD, before any change:

| gate | result |
|---|---|
| `check_cross_pilot_gate.py` | `CROSS_PILOT_GATE_STALE = false` (CURRENT), exit 0 |
| `check_semantic_decisions.py` | `SEMANTIC_GATE = PASS_WITH_DISCLOSURE`, rendering READY |
| `check_static_repair_readiness.py` | first run UNRESOLVED (transient `docker image inspect` failure on a busy daemon), re-measured on an idle daemon: **READY** |
| `check_timing_semantics.py --run-id pilot_001` | `status=PASS`, 0 violations, 1 known anomaly |
| `test_post_run_verification.py`, `test_manifest_fragments.py`, `test_assembly_provenance.py`, `test_report_contracts.py`, `test_timing_semantics.py`, `test_static_repair_provenance.py` | 6/6 green |

The transient readiness failure is itself evidence for this wave's rule: an
unmeasurable runtime is UNRESOLVED, never a silent pass.

## 2. Why a runner-level guard is not enough

`generate.py`, `run_repair.py` and every future runner can simply forget to
call the T0 guard, and a forgotten call is invisible until the invoice
arrives. The guard therefore sits where every cost-causing request must pass
through, and an AST inventory proves that those places are the only ones.

## 3. Provider call graph (AST, `provider_call_sites.py`, schema
`provider_call_sites.v1`)

21 provider call sites in productive code, 8 of them cost-causing:

| file | line | enclosing | kind | chokepoint |
|---|---|---|---|---|
| generate-anthropic.py | 145 | `AnthropicAdapter.generate` | direct_completion | `call_with_retries` |
| generate-openai.py | 94 | `OpenAIAdapter.generate` | direct_completion | `call_with_retries` |
| generate-gemini.py | 111 | `GeminiAdapter.generate` | direct_completion | `call_with_retries` |
| generate-openai-compatible.py | 132 | `OpenAICompatibleAdapter.generate` | direct_completion | `call_with_retries` |
| batch_api.py | 171 | `_anthropic_submit` | batch_submit | `submit_batch` |
| batch_api.py | 333 | `_openai_submit` | batch_upload | `submit_batch` |
| batch_api.py | 336 | `_openai_submit` | batch_submit | `submit_batch` |
| batch_api.py | 498 | `_gemini_submit` | batch_submit | `submit_batch` |

Read-only provider interactions (poll/retrieve/results/files.content) and
the four SDK client constructions are inventoried too. Measured: SDK client
construction performs **no** network I/O (0 `connect`/`getaddrinfo`
attempts for Anthropic, OpenAI incl. a custom `base_url`, and
`genai.Client`), so the guard may sit at the request boundary.

`UNGUARDED_PROVIDER_CALL_SITES = []`.

## 4. Direct chokepoint

`thesis/generation/common.py::call_with_retries`. Every adapter hands its
SDK call in as `fn=lambda: client...create(...)`, so the lambda can only be
executed by this function. It calls
`run_authorization.require_provider_call("direct")` before the first
attempt.

## 5. Batch chokepoint

`thesis/generation/batch_api.py::submit_batch` (all provider-specific
submit helpers are private and reachable only from it) with
`require_provider_call("batch_submit")`. `poll_batch` is a status read of an
already authorized job: it validates the existing authorization but creates
none and re-probes nothing.

Revalidation policy per kind:

| kind | authorization read-back | contract rebuild | fresh runtime |
|---|---|---|---|
| direct | yes | yes | no (T0 covered it) |
| batch_submit (a NEW provider job) | yes | yes | **yes** |
| batch_poll | yes | no | no |

## 6. Authorization schema (`run_start_authorization.v1`)

Fields: `schema_version`, `authorization_policy_version`, `run_id`,
`frozen_contract_sha256`, `rebuilt_contract_sha256`,
`readiness_runtime_condition_sha256`, `fresh_t0_runtime_condition_sha256`,
`decision = START_ALLOWED`, `required_runtime_domains`,
`authorization_sha256`, plus the volatile content `authorized_at_utc`,
`hostname`, `pid`, `thread_id`, `probe_duration_seconds`.

The METHODICAL fingerprint covers only the first nine fields:
`AUTHORIZATION_VOLATILE_FIELDS_EXCLUDED_FROM_FINGERPRINT = true` (tested:
changing timestamp/pid/hostname/thread/probe duration leaves the sha
unchanged; changing a contract sha changes it).

Order (never authorization first, evidence later): load frozen contract →
verify integrity → rebuild live → compare → fresh runtime probe → compare
against readiness and contract → bind contract → bind T0 evidence → validate
the merged fragment state → register the authorization atomically → read it
back and validate → only then a provider request. The fragment timestamps
prove the order (`contract.json` and `runtime.evidence.json` are registered
before `authorization.start.json`).

## 7. Parallel first starts

8 concurrent processes authorized the same fresh run: **8 authorized, 0
refused, exactly 1 canonical authorization fragment, 1 distinct methodical
fingerprint**, and all 8 reached the mock provider afterwards. A ninth
process whose runtime drifted between the probes is REFUSED, reaches no
provider mock, leaves the existing authorization unchanged and writes no
second authorization.

This works because the authorization AND the T0 evidence are fingerprinted
methodically (`t0_evidence_fingerprint` excludes `checked_at_utc` and
`probe_duration_seconds`) — otherwise two starters would disagree about the
same measured runtime.

## 8. T0 runtime probe

`measure_fresh_runtime` reuses the readiness definition
(`check_static_repair_readiness.measure_runtime` +
`static_provenance.runtime_condition`) — no second identity definition. It
requires main + parcoach + llov, each with an immutable image identity and
measured tool identities. Real measurement on this host (6.6 s):

| domain | image id | rootfs | identities |
|---|---|---|---|
| main | `sha256:eb1c2e93cfab…` | `f6bc13cbc026…` | g++ 13.3.0, gcc_analyzer, clang-tidy, cppcheck, infer, `mpirun (Open MPI) 4.1.6` |
| parcoach | `sha256:dbac7091e60b…` | `2975b0d46cf4…` | PARCOACH 2.4.0, executable `1bad67527d18…`, LLVM 15.0.7 |
| llov | `sha256:67d8c6c0b36e…` | `835fc4ef1433…` | clang 7.1.0, plugin `19bbc86baf21…` |

`FRESH_T0_RUNTIME_SHA == READINESS_RUNTIME_SHA == a2f46b1a5e35e601…`
(measured against the final re-measured readiness proof, 6.7 s, 0 problems).

Operational note: on a busy Docker Desktop daemon `docker image inspect
pareval-thesis` intermittently answered "No such image" during this wave
(three times out of six runs, always right after a burst of container
starts; the image was present each time). The gate correctly reported
UNRESOLVED and the measurement succeeded on a quiet daemon — which is
precisely the behaviour this wave requires: an unmeasurable runtime blocks
the start instead of passing silently.

Refusals (all tested): stale main image, stale compiler, stale MPI, stale
PARCOACH executable, stale LLOV image, stale LLOV plugin → `START_REFUSED`
with **no** authorization written; probe error / missing image / docker down
→ `PRE_RUN_RUNTIME_UNRESOLVED`, never a provider failure.

## 9. `T0_REQUIRES_DOCKER_AND_ALL_THREE_IMAGES = true`

Generation itself needs no docker, but the T0 safety gate deliberately
couples the pilot start to docker and to all three images, because the same
run will later produce correctness, enhanced and static results in exactly
those runtimes. A docker outage is reported as `PRE_RUN_RUNTIME_UNRESOLVED`.

## 10. Per-stage runtime binding (`stage_runtime_evidence.v1`)

Fragments (per-writer architecture): `runtime.stage.correctness`,
`runtime.stage.dynamic`, `runtime.stage.enhanced`,
`runtime.stage.static.main`, `runtime.stage.static.parcoach`,
`runtime.stage.static.llov`, `runtime.stage.repair_evaluation`.

Order inside a stage: load contract/authorization → determine the effective
invocation → check it against the contract → measure the stage runtime
fresh → compare against contract/T0 → register the invocation fragment →
register the runtime fragment → **only then** write result records.

Observation modes: with docker the stage compares the full image identity
(`docker_inspect`); inside an analysis container, where no docker socket
exists, it compares the tool identities and evidence of its own domain with
the SAME in-container probe the readiness proof uses (`inside_container`),
and records which fields it could not observe. The image-level identity of
that container stays pinned by T0.

A run without a frozen contract (smoke runs, historical pilot_001, unit
fixtures) reports `PRE_RUN_ENFORCEMENT = NOT_APPLICABLE` and proceeds; the
post-run verifier then reports the missing stamps as UNRESOLVED — never PASS.

## 11. Runtime matrix

The post-run verifier emits a machine-readable matrix

    | stage | domain | contract | t0 | stage_observed | status |

with PASS (exact), UNRESOLVED (no stamp for an expected stage) and FAIL
(explicit mismatch, or a stamp taken against another contract/T0).
`retrospective_runtime_substitution_allowed = false`: a probe taken today is
never a substitute for the stamp the stage failed to take.

## 12. Stage drift behaviour

`STAGE_RUNTIME_DRIFT` carries stage, runtime domain, expected, observed,
drift fields and the recommendation ("fresh run_id after refreeze /
environment restoration"). It is raised BEFORE any record; the stage
produces zero model or tool results, and it is explicitly not a
`TOOL_ERROR`, not a tool-state gap and not a model failure. Tested for:
main image, compiler, MPI, enhanced main image, LLOV image, LLOV plugin,
PARCOACH executable, PARCOACH program version, clang-tidy identity.

## 13. argparse override inventory (`cli_override_inventory.v1`)

Code-based (AST over every runner's `add_argument`), 45 methodical and 11
non-methodical options:

| stage | methodical | non-methodical |
|---|---|---|
| generation | config, profile, model_id | restart, poll |
| generation driver | config, profile, model_id, provider, continue_on_error | restart, poll, dry_run |
| assembly | config, profile, model_id | export_pareval_json |
| correctness | config, profile, model_id, primary_compiler, **run_timeout**, run_id | – |
| static | config, profile, model_id, tools, primary_compiler, run_id, replace_tool_entries, replace_legacy_record, rerun_gaps | – |
| dynamic | config, profile, model_id, tools, primary_compiler, run_id, skip_unavailable_tools | – |
| enhanced | config, profile, model_id, specs, run_id, jobs | force, output_file_name |
| repair | config, profile, model_id, variant, max_wave, primary_compiler | poll, dry_run, status |

An unclassified option defaults to METHODICAL.

## 14. Effective invocation schema (`effective_stage_invocation.v1`)

Per stage: `run_id`, `stage`, `profile`, `model_scope`, `override_policy`,
`effective_values` (each `{value, source: CLI|CONFIG|DEFAULT}`), optional
`contract_expected_values`, `invocation_sha256` (methodical: schema, stage,
run, profile, scope, policy and the values with their sources — no
timestamp, pid or hostname).

Only OVERRIDABLE methodical values are stored. Config-only values (`niter`,
launch grid, build timeout, spec target counts) already have an
authoritative owner in the evaluation condition and are refused as a second
source of truth (`FORBIDDEN_DUPLICATE_FIELDS`, tested).

## 15. The correctness-timeout false PASS

Before this wave a run could be started with `--run-timeout 60` while both
the manifest and the contract said 120, and the verifier compared
manifest-config against contract (120 == 120) and reported PASS. Now the
correctness stage persists the EFFECTIVE value with its source and refuses
before any record when the contract pins another value:

| config | contract | actual CLI | result |
|---|---|---|---|
| 120 | 120 | – | effective 120 CONFIG → allowed |
| 120 | 120 | `--run-timeout 60` | **REFUSED before the stage**, no records, post-run FAIL if the fragment is forged |
| 120 | 60 | `--run-timeout 60` | allowed (declared and pinned) |

## 16. Real BatchResponseMissing resubmission

Driven through the productive path (`common.run_generation` → real
`submit_batch`/`poll_batch`, only the private provider helpers mocked):
submit → poll returns one of two responses → the missing request stays
unwritten and the job file is consumed (`generation_batch.done.json`) → the
next invocation enters the real resubmission path. Results:

- no drift → the mock submit is reached (a second job is created)
- contract drift → `NEW_SUBMISSION_REFUSED`, no new provider job
- runtime drift → `NEW_SUBMISSION_REFUSED`, no new provider job

## 17. Post-run verification changes

New checks: `run_provenance_integrity` (fragment content vs its registered
fingerprint), `start_authorization_present/allowed/fingerprint_consistent/
matches_contract`, `t0_runtime_evidence_present`,
`t0_fresh_runtime_matched_readiness`, `t0_authorization_runtime_consistent`,
`t0_required_identities_present`, `stage_runtime:<stage>.<domain>` and
`effective_invocation:<stage>`, plus the runtime matrix. False-PASS paths
closed and tested: hand-edited T0 evidence, hand-edited stage evidence,
stage evidence from another contract, deleted required identity, missing
stamp with results present, forged effective timeout.

## 18. Tests

New: `test_provider_chokepoint.py` (unguarded direct/batch refusal,
authorized direct/batch/poll, AST audit, authorization schema/fingerprint/
ordering/read-back, 8 concurrent first starts, concurrent runtime drift,
new-submission revalidation, real BatchResponseMissing resubmission, SDK
client-construction network measurement) and `test_stage_enforcement.py`
(9 runtime drift fixtures, unresolved/NOT_APPLICABLE paths, 7 invocation
fixtures, post-run runtime-chain verification). Extended:
`test_post_run_verification.py` (the fixture world now authorizes through
the productive T0 path and stamps its stages).

## 19. Cross-pilot impact

Two coarse entries went stale — `run_correctness.py` and
`run_enhanced_tests.py` — both pure additions of the enforcement block
(`git diff --numstat`: 32/26 added lines, no verdict logic). Classified
`ENFORCEMENT_ONLY`, refreshed with justification, and the wave recorded
under `cross_pilot_reevaluation.areas.E_invocation.pre_run_enforcement_wave`.
Fingerprint `4957b9c3…` → `c523648b…`; the gate is CURRENT again.
Correctness 99/99/198, the enhanced comparability and the static/repair
comparability are untouched.

The static/repair readiness artifact was re-measured because the repair
condition contains a raw hash of `orchestrator.py`, which now carries the
repair-evaluation stage stamp: recomputing the repair condition with the
HEAD version of that file reproduces the previous value exactly (the only
differing field is `orchestrator_sha256`). Static condition unchanged
(`327b235a…`), repair `935430bb…` → `e6f5c32b…`, runtime `70c0f489…` →
`a2f46b1a…`, gate READY, fully pinned, 0 unresolved.

## 20. Final readiness

| statement | value |
|---|---|
| `T0_START_GUARD_ENFORCED_BY_PROVIDER_CHOKEPOINT` | true |
| `UNGUARDED_PROVIDER_CALL_SITES` | [] |
| `PER_STAGE_RUNTIME_BINDING` | READY |
| `EFFECTIVE_INVOCATION_PROVENANCE` | READY |
| `POST_RUN_VERIFICATION_MECHANISM` | READY |
| `PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT` | true (unchanged) |
| `SAFE_TO_PROCEED_TO_POPULATION_FREEZE` | true |

Open (not blocking, unchanged by this wave): the pilot_002 population is
`NOT_YET_DECIDED`, the base run id is `NOT_YET_CONFIGURED`, reuse is
`UNDECIDED`, the publication policy is open, TSan/ASLR stays
`OPEN_FOR_FINAL_ENVIRONMENT_GATE`, and pilot_002 has not been run, so it is
not post-run verified.
