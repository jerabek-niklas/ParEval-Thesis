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

---

# Wave 1.1 — Cross-process authorization, the complete expected runtime stage matrix, invocation cleanup

Start HEAD `690f4d414b0bd959a1fcc136b49cc081a3ae4bc0` (parent `636c370…`,
branch `thesis-static-analysis`, clean working tree, 0 untracked).

## 1.1.1 The cross-process defect

Wave 1 established the safety invariant *inside one process*. The productive
generation orchestrator, however, starts every provider runner as a NEW
process:

```
generate.py -> subprocess -> generate-<provider>.py
            -> common.run_generation(...) -> adapter.generate(...)
            -> common.call_with_retries(...) -> require_provider_call(...)
```

An AST scan of the repository at the start HEAD showed that
`run_authorization.authorize_start` — the only installer of the process
context — had **no productive caller at all**: it was reached from tests
only. A run could therefore be fully authorized (frozen contract bound, T0
runtime evidence bound, `START_ALLOWED` authorization persisted) and its
provider child process would still be refused at its first request.

Reproduced before the fix, with a temporary run, a frozen contract, a
persisted valid authorization, persisted T0 evidence and a mock provider,
starting the child exactly the way `generate.py` starts one:

```
CHILD_CONTEXT_AT_START=NONE
CHILD_REFUSED ProviderCallRefused: PRE_RUN_INFRASTRUCTURE_FAILURE: no run
  authorization is installed in this process ...
DEFECT_REPRODUCED = True         MOCK_PROVIDER_REACHED = False
STORED_AUTHORIZATION_DECISION = START_ALLOWED
```

The same held for a later independent batch poll/resume process and for the
repair loop, which also runs in its own process.

## 1.1.2 Why a Python process context cannot cross a subprocess boundary

`_CONTEXT` is a module-level dict in the parent interpreter. `subprocess`
starts a fresh interpreter: it inherits argv, the environment and file
descriptors — never another process' heap. Serialising the context would be
the wrong fix twice over: it would make a *claim* travel instead of the
*evidence*, and a forged environment variable would then be enough to
authorize a run.

## 1.1.3 Persistent provenance is authoritative

    PERSISTENT RUN PROVENANCE IS AUTHORITATIVE;
    THE PROCESS CONTEXT IS ONLY A VALIDATED CACHE.

`thesis/evaluation/run_authorization.py` gained three functions:

* `load_and_validate_run_authorization(config, run_id, *, config_path,
  profile, contract_path=None)` — loads the persisted authorization and
  validates every check in `REHYDRATION_CHECKS`:
  `authorization_fragment_present`, `run_provenance_integrity`,
  `decision_is_start_allowed`, `run_id_exact`,
  `authorization_fingerprint_exact`, `contract_bound_to_run_exact`,
  `t0_runtime_evidence_present`, `t0_evidence_belongs_to_same_contract`,
  `authorization_runtime_sha_equals_t0`, `frozen_contract_file_unchanged`,
  `live_contract_rebuild_without_drift`. Never "the file exists → install a
  context".
* `hydrate_authorized_run_context(...)` — installs the validated persisted
  provenance as the process context. It creates no authorization, rewrites
  no historical one, and the fragments stay the source of truth.
* `bootstrap_provider_run(...)` — the single entry every productive provider
  process runs before it can reach a chokepoint.

The chokepoints are unchanged and still fail-closed: `require_provider_call`
refuses whenever no valid context is installed and never reads a file with
implicit defaults on failure. A worker that skips the bootstrap is still
refused — that is the permanent regression fixture for this defect.

## 1.1.4 First start vs rehydration vs pure poll vs uncontracted

| situation | behaviour |
|---|---|
| no authorization, contract discoverable | full `authorize_start` (`FIRST_START`): rebuild, fresh runtime probe, readiness match, contract binding, runtime binding, atomic authorization, read-back |
| authorization exists | `REHYDRATED_FROM_RUN_PROVENANCE`: validate + install, **no** second authorization, **no** runtime probe |
| new cost-causing submission | rehydration plus the existing `REVALIDATION_POLICY` at the chokepoint (batch submit re-probes the runtime, direct rebuilds the contract) |
| pure poll | rehydration only — no probe, no authorization, no new provider job |
| contracted run, poll, but no authorization | `LEGACY_UNAUTHORIZED_BATCH_PROVENANCE` → refused; never migrated, never invented |
| no frozen contract anywhere | `UNCONTRACTED_RUN_NO_AUTHORIZATION_INSTALLED` (smoke run, unit fixture, historical pilot_001): classified, no context installed, so every provider request is still refused at the chokepoint |

## 1.1.5 Frozen contract discovery

Deterministic, in this order (`CONTRACT_DISCOVERY_ORDER`):

1. an explicitly passed contract path,
2. the canonical per-run location
   `<intermediate_dir>/<run_id>/run_contract.json`,
3. for an already authorized run, the contract bound in the run provenance.

No new CLI parameter was needed: the canonical location is derived from
config + run id, which the child already receives via `--config`/`--profile`.
`pilot_run_contract.py freeze` now defaults `--out` to exactly that location,
so the productive freeze step puts the contract where a child process looks.
No hidden global, no parent Python context, no hand-set test hook.

## 1.1.6 Direct child process

`common.run_generation` bootstraps after the api-mode is resolved and before
any provider interaction, and prints the mode, the authorization sha, the
discovery source and whether a fresh runtime probe happened. A first-start
child authorizes the run itself and reaches the mock provider; a later child
rehydrates the same authorization sha with 0 probes and 0 new fragments.

## 1.1.7 Batch submit, separate poll, real resubmission

Three genuinely separate processes over one run:

* PROCESS 1 submits (rehydrated, mock submit reached, bookkeeping written),
* PROCESS 2 `--poll` polls (rehydrated, mock poll reached, **0** fresh
  runtime probes, **0** new authorizations, no new provider job, bookkeeping
  renamed to `.done.json`),
* PROCESS 3 resubmits the request whose response was missing — the REAL
  `BatchResponseMissing` path (the sample whose response never arrived is
  not written as a terminal record, and `load_resume_state` keeps only
  terminal ones, so the next non-poll invocation finds exactly it in
  `pending` and resubmits it). With contract
  drift or runtime drift beforehand: REFUSED, no second provider job.

## 1.1.8 Concurrent model processes

Four concurrent provider child processes for the same run:

* case A (no authorization yet): all four succeed, exactly ONE canonical
  `authorization.start.json` exists, all four agree on one methodical
  authorization sha, all four reach the mock provider, none needs a parent
  context;
* case B (authorization exists): 0 new authorizations, 4 rehydrations, same
  sha.

## 1.1.9 Repair

`thesis/repair/run_repair.py` bootstraps in `main()` through
`bootstrap_run_authorization(...)`. `--status` and `--dry-run` never reach a
chokepoint and are deliberately not bootstrapped; `--poll` rehydrates
read-only. A fresh repair process rehydrates the base run's authorization and
may then make the direct and the batch provider call; on contract drift or a
tampered authorization it is refused with the pre-run infrastructure exit
code, and no repair state is advanced. The bootstrap lives in the CLI entry
point, not in `orchestrator.py`, so the repair condition hash is untouched.

## 1.1.10 Orchestrator semantics

A provider runner exits with `EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE = 3` when
it cannot be authorized. `generate.py` maps that exit code to
`PreRunInfrastructureStop` and stops the whole orchestration **even with
`--continue-on-error`**: an unauthorized model is not "one model less", it
would silently produce a partially authorized population. Ordinary
provider/model failures keep their existing skippable behaviour.

`--dry-run` writes no authorization, performs no runtime probe, freezes no
manifest, starts no provider process and leaves the frozen contract
untouched (measured). `--restart` deletes the model's `generations.jsonl`
only: authorization, T0 runtime evidence and the frozen contract survive, and
the re-run rehydrates the same authorization.

## 1.1.11 The complete expected runtime stage matrix

`expected_stages(contract)` previously derived `static.main` from
`static_analysis` and nothing else, so a contracted PARCOACH/LLOV/repair
evaluation run without a stamp was never reported. `expected_runtime_stages`
(`expected_runtime_stages.v2`) now derives every expected runtime stage —
with a reason per entry — from the FROZEN contract:

* `correctness`, `dynamic`, `enhanced` from the expected stages (the dynamic
  rule is unchanged: contract expects dynamic → stamp required, else N/A);
* `static.main` when at least one main-container tool (compiler,
  gcc_analyzer, clang_tidy, cppcheck, infer, …) is contracted and applicable;
* `static.parcoach` when PARCOACH is enabled in the frozen static toolset AND
  its execution-model scope meets the contracted population (MPI);
* `static.llov` likewise for LLOV (OpenMP);
* `repair_evaluation` when the frozen repair plan is enabled and evaluates
  repair candidates.

To make the FROZEN contract — not the live config — the authority, the
contract carries the derivation inputs: `pilot_run_contract.v2` adds
`static_toolset` (per tool: enabled + effective execution models, read
through the productive `resolve_tool_settings`) and `repair_plan`. A config
edit after the freeze is therefore contract drift, not a silently changed
expectation. The live config is used only as a fallback for a pre-v2
contract, and that fallback is marked in the reason text.

`not_expected_runtime_stages` names why every other stage is
NOT_APPLICABLE, so a missing stamp is never indistinguishable from "never
contracted".

For the real repository config the preflight now prints:

```
EXPECTED_RUNTIME_STAGES = correctness[main], dynamic[main], enhanced[main],
    static.main[main], static.parcoach[parcoach], static.llov[llov],
    repair_evaluation[main]
```

## 1.1.12 One status ladder for matrix and verifier

`runtime_matrix` and `check_stage_runtime` previously computed the row status
twice, by two different rules that could disagree. The ladder now lives once
in `stage_runtime.runtime_matrix`:

```
no stamp                     -> UNRESOLVED
stamp of another contract    -> FAIL
no comparable identity       -> UNRESOLVED
T0 domain != stage domain    -> FAIL
stamp against another T0     -> FAIL
otherwise                    -> PASS
```

The verifier emits one check per row plus `stage_runtime_expected_set`, whose
evidence carries the expected rows with their reasons, the NOT_APPLICABLE
list and `result_files_substitute_for_runtime_stamp: false`.

Measured on a split-container fixture run (main + PARCOACH + LLOV + repair,
population serial/omp/mpi): three separate static invocations register three
separate runtime fragments (`runtime.stage.static.main`,
`runtime.stage.static.parcoach`, `runtime.stage.static.llov`) with no
same-owner conflict, and all rows PASS. Removing any one stamp yields
UNRESOLVED for exactly that row **although the result files are present**;
a stamp carrying a foreign `contract_sha256` yields FAIL. With repair
disabled no repair stamp is required. With a serial-only population,
PARCOACH and LLOV are not required even though both are enabled — the
non-applicability is reported with its reason instead of silently dropped.

## 1.1.13 Invocation cleanup

`run_correctness.py` registered `output_file_name` as an effective
invocation value although the CLI inventory classifies the stage's own output
file name as NON_METHODICAL ("the measured content is unchanged"). It is
removed. `run_enhanced_tests.py`'s `specs_path` was renamed to its canonical
CLI dest `specs` (value unchanged).

The rule is now machine-checkable rather than asserted:
`effective_invocation.field_classification(stage, field)` resolves each
registered field to a CLI dest via `INVOCATION_FIELD_TO_CLI_DEST` and
requires it to be in `METHODICAL_CLI_OVERRIDES_BY_STAGE[stage]` (stage
mapping `STAGE_TO_INVENTORY_STAGE`: static.main/parcoach/llov → `static`,
repair_evaluation → `repair`). `build_invocation` refuses anything else, so a
NON_METHODICAL or unknown field can no longer enter a fragment.
`FORBIDDEN_DUPLICATE_FIELDS` (config-only values with an authoritative owner
in the evaluation condition) stays as it was, and the override policy is
unchanged: `ALLOWED_ONLY_IF_DECLARED_AND_PINNED`.

Correctness effective invocation after the cleanup:
`effective_run_timeout_seconds`, `primary_compiler` (plus `model_scope` when
a model filter is used).

## 1.1.14 Tests

New: `thesis/evaluation/test_cross_process_authorization.py` — the defect
regression fixture, first start / rehydration in real child processes,
tampered authorization, tampered T0 evidence, contract drift, runtime drift
before a new submission, batch submit / separate poll / real cross-process
resubmission with both drift cases, four concurrent children in both cases,
repair in its own process (direct + batch, plus both drift refusals),
dry-run, `--continue-on-error`, `--restart`, contract discovery and the
UNGUARDED-call-site re-check. Extended: `test_stage_enforcement.py` (the
expected-runtime-stage derivation A–H including applicability, the
split-container matrix, every missing/foreign stamp case, the invocation
classification), `test_provider_chokepoint.py` (the batch world now carries
its own run id, readiness proof and canonical contract, because the bootstrap
revalidates the contract rebuild of the config the runner actually uses), and
`test_post_run_verification.py` (the fixture world stamps every expected
stage generically and supports extra models, stage overrides and a
population).

Every provider interaction is a mock below the chokepoints. **API calls: 0.**

## 1.1.15 Cross-pilot impact

Two coarse entries went stale, both from this wave's provenance-only edits:
`run_correctness.py` (3 added / 1 removed) and `run_enhanced_tests.py`
(3 added / 1 removed). Classified `PROVENANCE_ONLY` with the diff quantified
from `git diff --numstat`, refreshed with justification, and the wave
recorded under
`cross_pilot_reevaluation.areas.E_invocation.cross_process_authorization_wave`
with what it changed and what it did not. Fingerprint `c523648b…` →
`2251bd2b…`; the gate is CURRENT again. Correctness 99/99/198, the enhanced
comparability and the static/repair comparability are untouched, and no
pilot_001 artifact was modified.

The static/repair readiness artifact was re-measured (READY, fully pinned,
0 unresolved) and every methodical sha is byte-identical to the start HEAD —
static `327b235a…`, repair `e6f5c32b…`, runtime `a2f46b1a…` — so the file
was left at its HEAD state.

## 1.1.17 Findings from the adversarial review of this wave, and their fixes

The wave was reviewed adversarially (six independent reviewers over the
bootstrap, the matrix derivation, the invocation coupling, the runner
integration, the test rigour and the requirement coverage; every finding then
put to three independent refuters). Everything below is a defect the review
found in THIS wave's own work and that was fixed before the wave closed.

**Per-model invocations were a hard failure (found: HIGH, fixed).** The
PARCOACH and LLOV containers and the repair loop are started once per model
(the repair `external_tool_commands` pass `--model-id {model_id}`, the repair
loop runs per (model, variant)). The invocation fragment was keyed by the
stage alone, so the SECOND model raised `InvocationRefused` and stopped the
run — measured, not deduced. The owner now carries the model scope
(`invocation_owner`), so genuinely different invocations coexist while a
CHANGED invocation under the SAME scope is still a hard failure and an
identical one is still idempotent. The owner carries the full SCOPE of an
invocation - the model scope plus the effective values in
`INVOCATION_SCOPE_FIELDS` (`variant`, `tools`), i.e. exactly the axes that say
WHICH SUBSET OF THE WORK this invocation covers: `static.parcoach@m1`,
`repair_evaluation@m1@variant-test_feedback`. The review's second pass caught
that the model axis alone was not enough - the repair loop runs 11 models x 3
variants over ONE base run id, and the three variants share the run id and
(model-only) owner while computing different fingerprints, so the SECOND
variant of every model was refused. Conditions that are not scope (timeouts,
compiler, flags) stay fingerprint-only, so a contradicting condition under the
same scope is still a HARD FAIL - measured in both directions. The verifier
aggregates every invocation of a stage (`invocations_for_stage`) and requires
all of them to match the contract.

**The two container stages registered no invocation at all (found: HIGH,
fixed).** `run_static_analysis.py` built its effective values only for
`static.main` and passed `None` for the PARCOACH/LLOV domains. With the
complete expected matrix, `effective_invocation:static.parcoach` and
`:static.llov` would have been UNRESOLVED forever. One CLI invocation is now
projected onto every runtime domain it stamps, with the same effective values.

**The enhanced stage would have been refused at runtime (found by the wave's
own machine check, fixed).** The first version of the rule demanded that every
invocation field be a METHODICAL CLI option of that stage;
`effective_enhanced_run_timeout_seconds` is contract-pinned but has no
`--run-timeout` option on the enhanced runner, so the enhanced stage would
have raised `InvocationRefused`. The rule now reads: a field must be either a
methodical CLI override of the stage OR a value the frozen contract pins
(`CONTRACT_EXPECTATIONS`) — both are "declared and pinned" — and never a
NON_METHODICAL option. A new AST test reads the effective-values dicts out of
the productive runners and puts them through the real check, so this class of
regression cannot recur silently.

**A legacy batch job could be retro-authorized (found: HIGH, fixed).**
`pure_poll` came from the `--poll` flag alone, so a plain re-run of a
contracted run that already had batch bookkeeping but no authorization took
the FIRST_START path and authorized it after the fact. The bootstrap now also
receives `prior_submission` (batch bookkeeping present): any evidence of an
earlier submission without an authorization is
`LEGACY_UNAUTHORIZED_BATCH_PROVENANCE`, refused, never migrated.

**A no-op command authorized a run (found: MEDIUM, fixed).** Direct mode plus
`--poll` is a documented no-op, but the bootstrap ran before the early
return: a real docker probe and a persisted `START_ALLOWED` authorization for
a command that does nothing. It now returns before the bootstrap.

**A refusal destroyed data first (found: MEDIUM, fixed).** `--restart`
deleted the model's `generations.jsonl` before the bootstrap, so a
fail-closed refusal wiped the measurement data of an already authorized run.
The bootstrap now runs first.

**Infrastructure failures could escape unclassified (found: HIGH×2, fixed).**
`authorize_start` classified only the authorization fragment conflict, so a
failure while binding the contract or the T0 evidence escaped as a raw
exception — which the orchestrator would have read as an ordinary model
failure and skipped under `--continue-on-error`. And
`require_provider_call`'s own revalidation (a contract rebuild, a fragment
read, a probe) could raise outside the `PreRunInfrastructureFailure`
hierarchy, in which case the direct loop's generic handler would have written
it into the population as a MODEL failure record. Both paths are now wrapped
and re-raised classified. `run_repair.py` likewise maps a refusal raised
mid-wave — not only at the bootstrap — to the pre-run infrastructure exit
code.

**The tamper gate was not fail-closed (found: MEDIUM, fixed).** Rehydration
filtered `verify_fragment_integrity` by fragment-name prefix. It now refuses
on ANY fragment whose content no longer matches its registered fingerprint.

**Applicability could assert something false (found: MEDIUM/LOW, fixed).** A
contract without a usable `static_toolset` silently dropped the PARCOACH/LLOV
requirement and the report claimed "not enabled in the frozen static
toolset" — an assertion the contract does not support. Such a contract now
demands all three static stages fail-closed and says why; the builder also
refuses to call a contract READY when the static toolset or the repair plan
is not resolvable. An EMPTY effective execution-model scope (a config that
narrowed a tool outside its hard capabilities) now means "not applicable"
rather than "applicable", with the real reason in the report. An unmapped
stage in the invocation classifier is fail-closed, and a test couples
`STAGE_DOMAINS` to `STAGE_TO_INVENTORY_STAGE`.

**Vacuous assertions (found: MEDIUM/LOW, fixed).** Several checks would have
passed with the feature removed: "a provider/model failure is still skippable
by `--continue-on-error`" compared two constants (it now runs the
orchestrator with an ordinary exit code 1 and asserts it does NOT stop), "it
is NOT classified as a tool state or tool error" was a tautology
(`isinstance(instance, type)` is always false — it now checks the failure
class against `framework.ANALYSIS_STATES`), an AST-coverage assertion
compared a set with itself, and the drift assertions in
`test_provider_chokepoint.py` accepted a bare `SystemExit` (they now require
the pre-run infrastructure exit code). Newly covered: the productive
`allow_draft_contract=False` gate (a child without the fixture injection is
refused because the contract is a draft), the missing-authorization branch
(`start_authorization_present` → UNRESOLVED and rehydration refused), the
`stage_runtime_expected_set` evidence, the direct-mode `--poll` no-op, the
`--restart`-does-not-delete-on-refusal case and the retro-authorization case.

**A false provenance statement (found: LOW, fixed).** The enhanced invocation
recorded `source: CLI` for `--specs` even when the argparse default was used.
It now reports `DEFAULT` unless the value really differs from
`DEFAULT_SPECS_PATH`.

**The run provenance layer could still raise unclassified (found: MEDIUM,
fixed).** Two paths escaped the `PreRunInfrastructureFailure` hierarchy and
were reproduced against the working tree: a torn/truncated sibling fragment
makes `json.loads` raise INSIDE `verify_fragment_integrity` (before any
problem list exists), and a sibling fragment carrying a foreign run id makes
`merge_fragments` raise `FragmentConflict`, which `load_manifest` does not
catch. Either left the runner with a traceback and exit code 1 - which the
orchestrator skips under `--continue-on-error` as an ordinary model failure.
`bootstrap_provider_run` and `load_and_validate_run_authorization` now
classify EVERY exception, and four fixtures (torn sibling, foreign-run
sibling, contentless sibling, corrupt frozen contract) assert exit code 3, a
`PRE_RUN_INFRASTRUCTURE_FAILURE` message and no traceback.

**The registration lock was not Windows-safe under contention (found: HIGH,
fixed).** `_exclusive.__enter__` retried only on `FileExistsError`. On Windows
a concurrent `mkdir`/`rmdir` of the same lock directory fails with a sharing
violation (WinError 5/32) instead - measured at ~1.4% with six processes
registering one key, while the repository already retries exactly this
condition for renames in `atomic_io._replace`. Since this wave deliberately
has N provider children register the same keys concurrently, the gap mattered:
an unretried escape is an unclassified `PermissionError` in the middle of a
per-model pilot start. The lock now uses the same bounded retry, and a stress
fixture (6 processes x 120 registrations on ONE key) asserts zero unclassified
escapes and an intact fragment afterwards.

Not changed, with reasons: `canonical_contract_path` is relative to
`outputs.intermediate_dir` exactly like every other artifact path in the
pipeline, so it is as CWD-consistent as the rest of the run tree (children
are started with `cwd=REPO_ROOT`); and `run_repair --poll` bootstraps as a
read-only poll even though a poll can advance a wave into a new submission —
that submission still passes the batch chokepoint with its full
`fresh_runtime` revalidation, and treating the poll as read-only only makes
the unauthorized case MORE conservative.

## 1.1.16 Final readiness

| statement | value |
|---|---|
| `CROSS_PROCESS_AUTHORIZATION_READY` | true |
| `PROVIDER_CHILD_PROCESS_NEEDS_PARENT_RAM_CONTEXT` | false |
| `COMPLETE_STAGE_RUNTIME_MATRIX_READY` | true |
| `INVOCATION_CLEANUP_READY` | true |
| `UNGUARDED_PROVIDER_CALL_SITES` | [] |
| `RESULT_FILES_SUBSTITUTE_FOR_RUNTIME_STAMP` | false |
| `SAFE_TO_PROCEED_TO_POPULATION_FREEZE` | true |

Open and unchanged by this wave (not blocking): population
`NOT_YET_DECIDED`, base run id `NOT_YET_CONFIGURED`, reuse `UNDECIDED`,
publication open, TSan/ASLR `OPEN_FOR_FINAL_ENVIRONMENT_GATE`, pilot_002 not
run and therefore not post-run verified.

---

# Wave 1.2 — Repair scope completeness, sample-level terminality, fail-closed expected set, post-run repair verification

Start HEAD `dd23092522655c42b7c88af698cff073fa630243` (parent `690f4d4…`,
branch `thesis-static-analysis`, clean working tree, 0 untracked). Change
class: **VERIFIER_COMPLETENESS_ONLY**.

## 1.2.1 The gap

The frozen contract pins every model, every repair variant, `max_iterations`
and the repair plan, and the invocation infrastructure registers one
`repair_evaluation` invocation per `(model_id, variant)`. The post-run
verifier, however, only checked that *at least one* repair invocation
existed, that the *present* invocations did not contradict the contract, and
that iteration artifacts did not leak into the base population. It never
asked whether **all contracted (model_id × variant) loops were actually and
completely evidenced**. Concretely: 33 expected loops, 1 model × static_feedback
present with a correct invocation and a valid global `repair_evaluation`
runtime stamp — PASS. That is the false PASS this wave closes.

## 1.2.2 Repair loop state source of truth

    REPAIR_LOOP_STATE_SOURCE_OF_TRUTH =
        <intermediate_dir>/<base_run_id>/<model_id>/repair/<variant>/state.jsonl
        schema   orchestrator.STATE_SCHEMA_VERSION (repair_state.v2)
        writer   orchestrator.RepairLoop.append_sample_state
        reader   orchestrator.load_sample_states  (latest record per sample_id)

Audit of the productive state machine (`thesis/repair/orchestrator.py`):
`state.jsonl` is append-only, one record per status change with `run_id`,
`model_id`, `variant`, `sample_id`, `iteration`, `status`; `load_sample_states`
keeps the latest record per sample. `wave_state.json` caches the phase
pointer (`PHASES`; `submitted` is persisted only in batch mode with the
`batch` bookkeeping) and `pending_external.txt` exists while the loop waits
for container tools (phase `analyzed_waiting_external`). Iteration artifacts
live under `<base>__<variant>__iter<N>` (`LoopPaths.iter_run_id`; iteration 0
is the base run). Nothing is inferred from directory names alone, from
summaries, from Markdown or from invocation fragments.

## 1.2.3 Sample-level terminality — one definition

    terminal(loop) := state.jsonl exists AND no sample is STATUS_ACTIVE

This is exactly the productive definition `run_backfill.loops_terminated`
has always applied (held-out ordering: enhanced tests may run only once
every loop is terminal). The wave extracts it into
`run_backfill.loop_state_terminality(state_path)` and makes
`loops_terminated` call it, so the verifier and the backfill share ONE
function — no second, independently maintained terminality semantics. The
helper returns `state_present`, `terminal`, `samples_total`,
`samples_active`, `terminal_breakdown` (keyed by
`orchestrator.TERMINAL_STATUSES`), `unknown_statuses` and
`max_iteration_observed` (the maximum iteration any sample reached). No
single per-loop `terminal_reason` is invented and `current_iteration` is not
used as a loop field: a loop has many samples that stop for different reasons
at different iterations. `orchestrator.py` itself is untouched (its raw hash
is part of the repair condition).

## 1.2.4 Expected repair set — frozen contract only, fail-closed

`repair_scope.expected_repair_loops(contract)` (`repair_expected_set.v1`,
rule `FROZEN_CONTRACT_FAIL_CLOSED`):

| case | condition | result |
|---|---|---|
| A | `repair_plan` absent (pre-v2, incomplete, damaged) | **UNRESOLVED**, empty set, reason "frozen contract carries no repair_plan" — never a live-config fallback |
| B | `enabled = true` and variants missing/empty/non-distinct, `repair_plan.error`, `max_iterations` not a non-negative int, `model_ids` empty/duplicated, or `repair` missing from `expected_stages` | **FAIL** — never an empty PASS set |
| C | `enabled = false` | `[]` and **NOT_APPLICABLE** — the only legitimate empty set |
| — | enabled and usable | `model_ids × variants`, sorted, each with `max_iterations`, `expected = true` and a reason |

`api_mode` and `external_tools` are carried for the contradiction checks but
never change the set size. Measured on the productive config's contract
view: **33 = 11 enabled models × 3 configured variants** (static_feedback,
test_feedback, combined_feedback — read from the config/contract, not
hardcoded).

## 1.2.5 Actual loops, identity and categories

`loop_inventory` discovers loops where `LoopPaths` places them and resolves
each to its logical identity **from the state records' own consistent claim**
(`model_id`, `variant`, `run_id`). Categories: `expected_and_present`,
`expected_missing`, `unexpected_extra` (model or variant outside the
contract → FAIL), `duplicate_identity` (two locations resolving to one
logical loop → FAIL), `unkeyable` (records disagreeing among themselves,
missing `sample_id`, or a non-productive variant name → FAIL). A location
whose records claim another model/variant/run is a contradiction (FAIL) but
still resolves, which is what makes duplicates visible instead of silently
vanishing.

Per actual loop: `model_id`, `variant`, `state_path`, `state_present`,
`terminal`, `samples_total`, `samples_active`, `terminal_breakdown`,
`max_iteration_observed`, `wave_phase`, `pending_batch` (phase `submitted`),
`pending_external` (`pending_external.txt` or phase
`analyzed_waiting_external`), iteration artifacts and `contradictions`.

## 1.2.6 Missing loops: narrowing vs unexplained absence

A missing expected loop is **FAIL** only with evidence of a *deliberate*
narrowing (`REPAIR_SCOPE_NARROWED_BELOW_CONTRACT`): the repair CLI narrows
with a single `--model-id` and/or `--variant`, so a deliberate narrowing
always leaves a **rectangle** of invocations (models′ × variants′) that is a
strict subset of the contract product set, with no state at all for the loops
outside it. Anything else — no invocations, a non-rectangular subset, states
without invocations — is unexplained evidence (run aborted, artifact never
written, output lost) and stays **UNRESOLVED**; never PASS, never a
speculated FAIL. (The repair orchestrator always writes `variant` with source
`CLI` and `model_scope=[model]`, so the invocation's `source` field alone is
NOT narrowing evidence; the rectangle shape is.)

## 1.2.7 Invocation membership AND coverage

`expected_repair_invocation_scopes(contract)` = the product set;
`observed_repair_invocation_scopes(manifest)` resolves every
`repair_evaluation` invocation to exactly one model (`model_scope` must name
one) and one variant (`effective_values.variant`). **Membership**: every
observed scope is contracted (unexpected → FAIL; duplicate for one scope →
FAIL; contract contradiction or fingerprint mismatch → FAIL; unkeyable →
FAIL). **Coverage**: every expected scope has exactly one invocation (missing
→ UNRESOLVED, or FAIL under proven narrowing). Membership without coverage
was precisely the old false PASS.

A valid global `repair_evaluation` runtime stamp is runtime provenance; it
is not asked to exist 33 times, and
`RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP = false` is asserted by a
fixture (stamp PASS, 5/6 loops → `repair_scope_complete ≠ PASS`).

## 1.2.8 Iteration bound and pending contradictions

The orchestrator decides `stopped_budget` **at** `iteration >= max_iterations`
(`decide()`), so a recorded sample iteration may equal but never exceed the
bound: `max_iteration_observed <= repair_plan.max_iterations` (iteration 0
being the base analysis). Over the bound → FAIL; `stopped_budget` within the
bound is legitimate; "exactly max_iterations" is never demanded. Iteration
artifact directories are validated the same way (foreign variant, foreign
model, invalid or over-bound `N`, unparseable `<base>__…` names, duplicate
`(model, variant, N)` → `repair_iteration_identity` FAIL), and the existing
base/repair separation check stays in place.

Pending batch: terminal + `submitted` → FAIL; non-terminal + `submitted`
with `api_mode = batch` → UNRESOLVED (legitimately unfinished); any pending
batch when the frozen plan allows no batch path (`api_mode = direct`) → FAIL
even if non-terminal. Pending external: `external_tools = []` + pending →
FAIL; enabled + non-terminal + pending → UNRESOLVED; terminal + pending →
FAIL. Unknown sample status → FAIL.

## 1.2.9 Infrastructure terminal states

`stopped_analysis_incomplete` and `stopped_api_exhausted` (and
`stopped_baseline_incompatible`) are `orchestrator.NON_MODEL_TERMINAL_STATUSES`:
the loop is complete with a limitation, which the row and the aggregate
report as `limitations`; `repair_unusable` is terminal and reported in the
breakdown. None of them is reclassified as a model failure, a missing loop or
a scope FAIL. No publication decision is taken here.

## 1.2.10 The repair matrix and the aggregate

`build_repair_matrix` (`repair_scope_matrix.v1`) produces one row per
expected loop (`model_id, variant, expected, invocation_status,
state_status, terminal, samples_total, samples_active, terminal_breakdown,
max_iteration_observed, max_iterations_contract, pending_batch,
pending_external, status, detail`) and the aggregate
`repair_scope_complete` with `expected_loop_count`, `observed_loop_count`,
`pass/unresolved/fail_loop_count`, `missing`, `unexpected`, `duplicate`,
`unkeyable`, and — as SEPARATE fields — `total_repair_samples`,
`terminal_repair_samples`, `active_repair_samples`,
`sample_terminal_breakdown`. LOOP counts and SAMPLE counts are never
conflated ("6/6 loops terminal" vs "stopped_clean: 12 samples").

Aggregate precedence: disabled → NOT_APPLICABLE (a loop on disk anyway →
FAIL); expected set UNRESOLVED → UNRESOLVED; expected set invalid → FAIL;
any unexpected/duplicate/unkeyable loop or invocation, iteration violation
or FAIL row → FAIL; any UNRESOLVED row → UNRESOLVED; only all-PASS → PASS.
The verifier emits `repair_expected_set`, `repair_invocation_membership`,
`repair_invocation_coverage`, `repair_loop:<model>/<variant>` per expected
loop, `repair_iteration_identity` and `repair_scope_complete`, embeds
`repair_matrix` and `repair_scope` in the report, and prints the matrix table
in its own output only.

`FUTURE_REPORTING_REQUIREMENT` (documented, **not rendered**): "33/33
expected repair loops reached a terminal state" (loop level) plus the
separately labelled sample-level terminal breakdown. `report_contracts.py`
and the overview renderer are untouched — `REPORTING_SEMANTICS_CHANGED = false`.

## 1.2.11 PARCOACH / LLOV membership vs coverage — measured, not fixed

The same membership-vs-coverage effect exists for `static.parcoach` and
`static.llov`, because those containers run once per model. Measured with a
reproducible fixture (`test_repair_scope.py::measure_static_split_gap`: two
contracted models with applicable mpi/omp samples, the second model's
container invocation removed):

| sub-case | static_coverage:m2 | effective_invocation | run |
|---|---|---|---|
| container never ran (no PARCOACH/LLOV entries for m2) | FAIL | PASS | FAIL |
| records present, invocation fragment missing | PASS | PASS | **PASS** |

    STATIC_SPLIT_INVOCATION_COVERAGE_GAP[parcoach] = OPEN_TECHNICAL_FINDING
    STATIC_SPLIT_INVOCATION_COVERAGE_GAP[llov]     = OPEN_TECHNICAL_FINDING

Static coverage catches a container that never ran; it cannot catch a
container whose findings exist but whose invocation provenance was never
registered. Affected stages: `static.parcoach`, `static.llov`
(`effective_invocation:<stage>` checks membership only). Per the wave's
scope this is documented with its reproducer and **not closed here**; no
static split-container code was changed for the measurement (only the
fixture registers per-model container invocations, mirroring the productive
`--model-id` container commands).

## 1.2.12 Tests

New `thesis/evaluation/test_repair_scope.py` (every fixture a real mini run
through the productive contract builder, manifest fragments and orchestrator
state writers): expected-set cases A/B/C with edge inputs; the
productive-config expected count; the terminality definition (all terminal,
one active, no state, unknown status, breakdown sums, shared function);
6/6 PASS; 5/6 without narrowing UNRESOLVED; `--variant` and `--model-id`
narrowing FAIL; missing invocation UNRESOLVED; missing state UNRESOLVED;
unexpected variant/model FAIL; duplicate FAIL; unkeyable FAIL (two ways);
iteration bound at/over max; `stopped_budget`; terminal + pending batch
FAIL; non-terminal + pending batch in batch mode UNRESOLVED; pending batch in
direct mode FAIL; terminal + pending external FAIL; non-terminal + pending
external UNRESOLVED; pending external with `external_tools = []` FAIL;
iteration identity violations; the three infrastructure terminal states;
runtime-stamp substitution; legacy/invalid/disabled plans; unexpected loop
despite disabled; the PARCOACH/LLOV measurement. The World fixture now
writes terminal repair loops for every contracted `(model, variant)` through
`RepairLoop.append_sample_state` / `save_wave_state`, registers one
`repair_evaluation` invocation per `(model, variant)` and one container
invocation per model (as production does), and can carry mpi/omp samples.

## 1.2.13 Unchanged

`orchestrator.py`, `feedback.py`, prompts, semantic decisions (E3.2 not
recorded, not decided), comparator, enhanced specs/policy, static finding
code, runtime identities, authorization, override policy and the reporting
renderer are untouched; the repair condition sha equals the readiness
artifact's value; cross-pilot stays CURRENT with no artifact update (no
tracked file changed); pilot_001 artifacts unchanged.

## 1.2.13a Review findings on this wave, and their fixes

An adversarial review of the wave's own work (six independent reviewers,
each finding put to three refuters) raised five points that were confirmed by
reading the code and fixed before the wave closed:

* **`api_mode_overrides` were not frozen (MEDIUM).** `batch_possible` was
  derived from the global `api_mode` only, so a frozen per-provider override
  to batch would have made a legitimately pending batch job a FAIL. The
  contract builder now freezes `repair_plan.api_mode_overrides`, and a batch
  path counts as possible when the global mode or any frozen override is
  batch (the contract does not map models to providers, so the check is per
  plan; documented limit).
* **A disabled plan tolerated some repair evidence (MEDIUM).** With
  `NOT_APPLICABLE` only keyable loops and unexpected invocations were
  checked; unkeyable invocations and iteration artifact directories were
  ignored. Now ANY repair evidence under a disabled plan is FAIL.
* **The builder could freeze a self-contradictory contract (MEDIUM).**
  `expected_stages()` treats a present `stages.repair` section without
  `enabled` as enabled, `repair_plan_view()` treated it as disabled. Both use
  the same default now, and the expected-set derivation also refuses an
  enabled plan whose contract does not list `repair` among its expected
  stages.
* **Variants the orchestrator refuses counted as usable (LOW).**
  `RepairLoop.__init__` refuses any variant outside `orchestrator.VARIANTS`;
  a frozen plan naming one is now an unusable plan (FAIL).
* **`max_iterations = 0` with `evaluates_repair_candidates = true` (LOW).**
  `decide()` stops every sample as `stopped_budget` at iteration 0, so no
  candidate can exist; the plan contradicts its own assertion and is FAIL.
  Without the evaluation claim an iteration-0-only plan stays usable.

The review's second round found a further set of real defects, each fixed
and covered by a fixture:

* **Every legitimate run with a repair iteration would have FAILed (HIGH,
  three independent reviewers).** The iteration-artifact scan read the
  iteration run's own `run_manifest.fragments/` directory as a "foreign
  model". The scan now recognises model directories only, and a fixture
  builds the productive iteration layout (model dir + per-writer manifest).
* **In-flight loops were FAIL instead of UNRESOLVED (HIGH).** An iteration
  directory is created (assembled) before its samples are analysed and
  decided, so on an in-flight loop it legitimately exceeds the recorded
  iterations; only a TERMINAL loop must have reached every iteration it
  produced.
* **Loops that stop at iteration 0 have no invocation — by design (MEDIUM).**
  `_run_analysis_stages` (which registers the `repair_evaluation` invocation
  and stamp) runs only when an iteration's internal stage records are
  missing, i.e. for iterations ≥ 1. A loop whose samples all stop at
  iteration 0 is complete without one; `invocation_status` is then
  `NOT_APPLICABLE` and `invocation_required = false`, while a loop that
  analysed iteration ≥ 1 still requires exactly one. (Related, out of this
  wave's scope and noted honestly: the per-stage runtime rule of wave 1.1
  expects a `repair_evaluation` stamp whenever repair is contracted, so a
  pilot in which every loop stops at iteration 0 would report that stamp
  UNRESOLVED.)
* **A malformed `state.jsonl` crashed the verifier (MEDIUM).** The productive
  reader raises on a torn line; the verifier now turns that into an
  unkeyable loop with a FAIL verdict instead of a traceback.
* **A record without a valid iteration bypassed the bound (MEDIUM).** The
  shared helper counts `invalid_iterations`; any such record is a
  contradiction (FAIL).
* **A base run id containing `__` broke iteration parsing (MEDIUM).** The
  iteration-run regex was backtracking into the base id; parsing is now
  anchored on the known base run id.
* **A loop with all samples terminal but not finalized was PASS (MEDIUM).**
  The orchestrator's own completion marker is `wave_state.phase == done`; a
  terminal loop without it (interrupted between `decided` and `done`, or no
  wave state) is UNRESOLVED. Loop states are also compared with the model's
  assembled base samples: missing samples → UNRESOLVED, a sample that is not
  an assembled base sample → FAIL.
* **Invocation keyability and run binding (LOW).** Keyability is no longer
  inferred from problem text; an invocation fragment naming another run is a
  membership FAIL; the narrowing inference treats any state *location*
  (keyable or not) on a missing scope as "not no state".
* **Membership fixtures (MEDIUM/LOW gaps).** Unexpected-model invocation,
  duplicate invocation for one scope, foreign-run invocation, verifier-level
  unknown-status and STATUS_ACTIVE cases are now executed fixtures; the
  unreachable "duplicate iteration identity" check was removed.

* **An expected loop whose only state location is unusable read as "no
  state" (fixture-driven fix).** A malformed or misclaimed `state.jsonl`
  under an expected loop's location made the aggregate FAIL (unkeyable
  location) while that loop's own row said "no repair state" (UNRESOLVED).
  The row now carries the contradiction itself: `state_status = FAIL` with
  the location's problems, never "absent".

The review's final confirmed finding (MEDIUM, in scope): the top-level
`repair_invocation_coverage` check still counted every expected scope without
an invocation as missing, ignoring the per-row `invocation_required` rule —
so a legitimately complete run in which one loop stopped every sample at
iteration 0 had all rows PASS and `repair_scope_complete` PASS, yet the
whole report stayed UNRESOLVED on that one check. My fixture had asserted
only the aggregate, not the overall verdict. Coverage is now derived from
the rows (only a required-and-absent invocation is missing; a loop with NO
state at all cannot claim it stopped at iteration 0, so its invocation stays
required — fixture C's narrowing FAIL depends on exactly that), and a mixed
fixture — five loops at iteration 1 with invocations, one loop stopped at
iteration 0 without — asserts `report["status"] == PASS`. The pre-existing
wave-1.1 checks (`effective_invocation:repair_evaluation` and the
`repair_evaluation` runtime stamp) still report UNRESOLVED when NO loop of
a run ever analysed an iteration ≥ 1; that coupling is outside this wave and
is recorded as an open observation, not changed.

A targeted re-review of the final coverage logic (two reviewers, three
refuters per finding, every claim executed against the productive wave
machine) confirmed one more HIGH false-UNRESOLVED and it is fixed: the
`invocation_required` rule keyed on "reached iteration ≥ 1"
(`max_iteration_observed`, or an iteration directory), but the orchestrator
writes `repair_unusable`@N after a refusal / exhausted reasoning budget /
unusable response (`mark_unusable` in `_finish_responses`) and
`stopped_api_exhausted`@N after a transport failure (`exhaust_request_rounds`)
BEFORE any analysis of N, `_assemble(N)` still creates the iteration
directory, and with nothing assemblable the loop finishes `done` without
`_run_analysis_stages` ever running — so no invocation can exist for a
legitimately complete loop. `invocation_required` now follows EVIDENCE OF
ANALYSIS: a state record at iteration ≥ 1 whose status the orchestrator
produces only by deciding an analysed iteration (`active` or a terminal
status other than `repair_unusable` / `stopped_api_exhausted`), scanned over
all records so an analysed iteration followed by a later refusal still
counts. Fixtures: `repair_unusable`@1 and `stopped_api_exhausted`@1 without
analysis (with the iteration directory present) → overall PASS with
`invocation_status = NOT_APPLICABLE`; an `active`@1 record followed by
`repair_unusable`@2 → invocation still required.

A third refutation-focused review round (every claim executed against the
productive machine) confirmed the mirror-image false PASS of the same rule
and it is fixed: the premise "`_run_analysis_stages` runs only for iterations
≥ 1" is false. `step()` enters a fresh loop in phase `start` and calls
`_to_analyzed(0)`, which runs the analysis stages — and with them
`enforce_stage(..., "repair_evaluation", ...)` — whenever
`missing_internal_stages(0)` is non-empty. Iteration 0 IS the base run, so
those records normally come from the BASE evaluation, but only for stages the
base run actually ran; `missing_internal_stages` compares against what the
variant's FEEDBACK needs (`needs_tests` / `needs_dynamic` via
`feedback.strategy_sources`, plus static unconditionally). In any run whose
contract does not expect a stage a variant needs, the loop analyses iteration
0 itself, registers its invocation there, and leaves ONLY iteration-0
records — so the old rule called the invocation not required and a deleted
or lost fragment came out as `NOT_APPLICABLE`, row PASS, `repair_scope_complete`
PASS.

The first version of the rule read this off the frozen contract's stage LIST
alone. That was refuted in the same wave (see below) and the rule now asks the
productive `missing_internal_stages(0)` as well, so the description that
follows is the CORRECTED one: `repair_scope.iteration_zero_analysis(contract,
config, variant, base_run_id, model_id)` decides per (model, variant) and
fail-closed (`ITERATION_ZERO_INVOCATION_POLICY =
CONTRACT_STAGE_COVERAGE_FAIL_CLOSED`):

* a stage the variant needs is NOT contracted → the base run cannot have
  written its records → the invocation is REQUIRED even with no analysed
  iteration ≥ 1;
* the base run's iteration-0 records do not cover that model's assembled
  samples NOW — asked through the productive `missing_internal_stages(0)`
  itself — → likewise REQUIRED;
* an unknown `expected_stages` list, feedback sources that cannot be resolved,
  or a probe that cannot run → likewise REQUIRED;
* every needed stage contracted AND the records complete → the base run
  covered iteration 0, and a loop that stops there legitimately has no
  invocation (`NOT_APPLICABLE`).

The feedback sources are resolved exactly as the orchestrator resolves them
(`feedback.strategy_sources`, which REPLACES the defaults when the config
narrows `stages.repair.strategies`); `DEFAULT_STRATEGY_SOURCES` is only a
fallback for a variant that cannot be resolved at all. The expected loop SET
still comes from the frozen contract alone, and no repair semantics are
touched. `invocation_required` is the disjunction of four fail-closed reasons
(no state at all / an analysed iteration ≥ 1 / a wave phase proving an
analysed iteration ≥ 1 / iteration 0 analysed by the loop); each row carries
`analysed_iterations`, `wave_proves_analysis`,
`iteration_zero_analysis_certain` and the full determination, the matrix
carries it per (model, variant), and the pre-run preflight prints
`REPAIR_ITERATION_ZERO_INVOCATION_POLICY` plus one
`REPAIR_ITERATION_ZERO_ANALYSIS` line per contracted variant — labelled
`BASE_RUN_COVERS_ITERATION_0_BY_CONTRACT`, because before the run there are no
records to probe. For the productive pilot config all three variants report
that contract leg clean (`static_analysis`, `correctness_tests` and
`dynamic_analysis` are all contracted), so the real run keeps the legitimate
`NOT_APPLICABLE` path whenever its base records are complete.

A fourth review round (five reviewers, one adversarial refuter per claim,
every claim executed) attacked exactly this rule and confirmed twelve
findings, three of them the same HIGH defect: **the contract's stage LIST is
not evidence of the base run's record COVERAGE**. `missing_internal_stages(0)`
does not ask which stages were contracted; it asks whether a record exists for
every assembled sample of that MODEL (and, for static, whether it carries every
internally required tool). A contracted `dynamic_analysis` stage that produced
no records — the normal residue of an interrupted dynamic run, and invisible to
the verifier, which has no `check_dynamic` — makes the productive loop analyse
iteration 0 and register its invocation, while the stage-name proxy called it
covered and excused the missing fragment as `NOT_APPLICABLE`, whole run PASS.

The determination now asks the productive function itself. `repair_scope.
productive_missing_internal_stages(config, base_run_id, model_id, variant)`
constructs an `orchestrator.RepairLoop` for that loop and returns
`missing_internal_stages(0)` — read-only, no re-implementation, and per
(model, variant) rather than per variant, because the base run can be complete
for one model and partial for another. `iteration_zero_analysis` now carries
two independent legs, either of which makes iteration-0 analysis certain:
`contract_missing_stages` (a needed stage the frozen contract never expected)
and `records_missing_stages` (the productive probe). A probe that cannot run
at all counts as missing, so nothing is excused on an unanswered question.

The records leg is sound in exactly the direction the contract leg cannot
reach: a loop that advanced past phase `start` passed `_to_analyzed(0)`, which
RAISES if a stage is still missing afterwards, so incomplete iteration-0
records mean the loop either analysed them itself or the artifacts contradict
the productive writer — both keep the invocation required. What that leg alone cannot see is
the opposite direction: records that are complete TODAY do not say WHO
completed them, because `_run_analysis_stages(0)` writes into the base run's
own stage files and the records carry no writer provenance. The fifth review
round below closes most of that gap with the static invocation LABEL, which
the loop appends and never rewrites away; the remainder is recorded there.

Five further confirmed findings are fixed in the same pass, all verifier-only:

* **Feedback sources are REPLACED, not unioned.** `feedback.strategy_sources`
  returns the config's `stages.repair.strategies.<variant>.sources` INSTEAD of
  the defaults, so the earlier union demanded records a narrowed plan never
  asks for — a complete run could never reach PASS. The verifier now resolves
  the sources exactly as the orchestrator does and falls back to
  `DEFAULT_STRATEGY_SOURCES` only when the variant cannot be resolved at all.
* **The persisted wave phase is evidence.** A loop interrupted between
  `_to_analyzed(N)` and `_decide(N)` has no decided record for N, yet its
  invocation exists. `wave_proves_analysis(phase, iteration)` reads the two
  phases the orchestrator writes inside `_to_analyzed` (`analyzed`,
  `analyzed_waiting_external`) as proof for that iteration, and the phases it
  writes for an iteration it has only STARTED (`decided`, `requests_built`,
  `submitted`, `responses_merged`, `assembled`, `done` — including the "no
  assemblable responses" branch, which persists `decided` for an unanalysed
  iteration) as proof only from iteration 2 on.
* **`finalized` no longer downgrades a terminal loop.** Under
  `REPAIR_TERMINALITY_POLICY = SAMPLE_STATE_BASED` the sample states decide;
  a wave left in phase `decided` by the documented `--max-wave N` run is
  complete in substance (`step()` would only rewrite it to `done` on its next
  call). Only a phase with OUTSTANDING work — or no wave bookkeeping at all —
  still contradicts terminal samples.
* **`max_iterations = 0` no longer destroys the expected set.** The plan is
  runnable (every sample stops as `stopped_budget` AT iteration 0); its
  contradiction with the builder's constant `evaluates_repair_candidates` is
  reported as a note on a PASS set instead of a FAIL that throws away all
  evidence.
* **Two crash paths.** A state line that is not a JSON object, or a record
  whose `status` is not a string, no longer escapes as a traceback but makes
  the loop unkeyable (fail-closed); a damaged frozen contract whose
  `variants` hold unhashable entries, or whose `api_mode_overrides` is not a
  mapping, now returns the documented CASE B FAIL instead of crashing before
  any check is recorded.
* **The verifier's own evidence stopped lying.** A `NOT_APPLICABLE` row said
  "invocation present" and the coverage line counted required-and-absent
  scopes as present; both now report what is actually there
  (`present_scope_count`, `not_required_scope_count`), and fixtures pin the
  strings.

Every one of these is pinned by a fixture that fails when the mechanism is
neutralised (verified by monkeypatching each in turn); three reviewer claims
were refuted and are recorded as such rather than acted on.

A FIFTH review round attacked the corrected rule itself (five reviewers, one
adversarial refuter per claim, every claim executed) and confirmed eight more
findings; three were refuted and are recorded as refuted. All eight are fixed,
all verifier-only:

* **The records leg was self-erasing (HIGH, false PASS).** A reviewer drove
  the PRODUCTIVE loop over a base run with one missing static record: the loop
  analysed iteration 0, registered its `repair_evaluation` invocation, and
  filled the gap — so afterwards `missing_internal_stages(0)` is empty again
  and deleting the fragment verified PASS. The fix is POSITIVE PROVENANCE:
  `_run_analysis_stages` passes
  `invocation_label = "repair <model>/<variant> iteration <n> (internal
  static)"` into `run_static_analysis.run_model`, which APPENDS it to the
  model's `static_analysis_summary.json` — an artifact the loop never rewrites
  away. `repair_scope.repair_labelled_static_invocations` reads those labels
  and reports the iterations of THIS loop; any hit makes the invocation
  required, whatever the records say. A fixture pins that the constant the
  verifier matches is the literal the orchestrator writes.
* **A base sample the assembler SKIPPED made every loop of that model FAIL
  (HIGH, false FAIL).** `_decide(0)`'s bootstrap marks every non-assembled
  base sample `repair_unusable` by design, so the loop state legitimately
  covers the model's WHOLE assembly set. The row compared it against the
  ASSEMBLED subset, so a single provider timeout would have failed that
  model's three loops on an otherwise complete run. The verifier now passes
  the full assembly-entry id set (`known_by_model`) and fails only for an id
  with no assembly entry at all; the "covers only n of m assembled samples"
  leg is unchanged.
* **`finalized` still downgraded two documented stops (MEDIUM, false
  UNRESOLVED).** `samples_active == 0` already proves nothing is left to
  decide, so only an UNDECIDED iteration contradicts terminal samples:
  `PHASES_WITH_OUTSTANDING_WORK` is now `("start", "analyzed")`, and the
  `--poll` / `--max-wave` stops at `decided`, `responses_merged` or
  `assembled` verify PASS.
* **The wave iteration was evidence but was never validated (MEDIUM, both
  directions).** It now has to be a non-negative integer (else a
  contradiction) and it is bound by the contracted `max_iterations` exactly
  like the sample states, so a loop whose own bookkeeping proves it drove past
  the budget FAILs instead of PASSing next to "max iteration 0 <= 0".
* **A `wave_state.json` that is valid JSON but not an object crashed the whole
  verifier (MEDIUM).** `_read_json` got the same shape guard `_read_records`
  received, so the shape is a contradiction on that row instead of an
  `AttributeError` before any check is recorded.
* **The global expectation contradicted the per-loop rule (HIGH, false
  UNRESOLVED).** `stage_runtime.expected_runtime_stages` demands a
  `repair_evaluation` stamp for every contracted repair plan, so a run whose
  every loop legitimately stops at iteration 0 — blessed by the matrix — was
  still dragged to UNRESOLVED by `stage_runtime:repair_evaluation.main` and
  `effective_invocation:repair_evaluation`. `verify_pilot_run.
  reconcile_repair_evaluation_expectation` now downgrades exactly those two
  checks to NOT_APPLICABLE, and only when the matrix is PASS, has at least one
  expected loop, and NO row requires or carries an invocation. As soon as one
  loop analysed anything, the missing stamp is unresolved again (both pinned
  by fixtures).

The residual is now narrower than the fourth round's: what remains
unattributable is an iteration-0 analysis whose ONLY missing stage was
correctness or dynamic, because `run_correctness` / `run_dynamic_analysis` are
called from `_run_analysis_stages` WITHOUT an invocation label (static is the
only labelled one). The static leg is checked unconditionally for every
variant, so the unlabelled case needs a base run that was complete for static
but incomplete for correctness/dynamic for that model, a loop that stopped at
iteration 0, and a lost fragment. It is recorded as
`ITERATION_ZERO_COVERAGE_RESIDUAL = CORRECTNESS_DYNAMIC_WRITER_NOT_ATTRIBUTABLE`,
non-blocking; closing it means giving those two runner calls the same label,
which is a PRODUCTIVE writer change and therefore out of scope here
(`FUTURE_PROVENANCE_REQUIREMENT`).

The readiness gate: three re-measurement attempts in this session failed
with "No such image: pareval-thesis" on the FIRST local-tag inspect after a
Docker Desktop idle period, while the identical call succeeds immediately
afterwards; warming the daemon with one manual inspect and running the gate
right away measured READY with the runtime condition `a2f46b1a…` and zero
non-volatile differences to the committed artifact. The committed artifact
was therefore kept byte-identical; the first-call-after-idle behaviour is
recorded as a measurement-infrastructure observation for the final
environment gate, not changed here.

## 1.2.14 Readiness

| statement | value |
|---|---|
| `REPAIR_SCOPE_VERIFICATION_READY` | true |
| `REPAIR_EXPECTED_SET_POLICY` | FROZEN_CONTRACT_FAIL_CLOSED |
| `REPAIR_TERMINALITY_POLICY` | SAMPLE_STATE_BASED |
| `POST_RUN_REPAIR_COMPLETENESS_REQUIRED` | true |
| `RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP` | false |
| `ITERATION_ZERO_INVOCATION_POLICY` | CONTRACT_STAGE_COVERAGE_FAIL_CLOSED |
| `ITERATION_ZERO_COVERAGE_RESIDUAL` | CORRECTNESS_DYNAMIC_WRITER_NOT_ATTRIBUTABLE (non-blocking) -> CLOSED_BY_WRITER_ATTRIBUTION in section 1.3 (2026-09-13) |
| `STATIC_SPLIT_INVOCATION_COVERAGE_GAP` | OPEN_TECHNICAL_FINDING (parcoach, llov) -> CLOSED in section 1.3 (2026-09-13) |
| `SAFE_TO_PROCEED_TO_E3_2_DECISION` | true |

Next step after this wave: **E3.2 re-freeze / accepted-disclosure decision**
(deliberately still OPEN — nothing is entered as ACCEPTED_DISCLOSURE for
OMPI_SKIP_MPICXX or the MPI finding-set effects here); only after that the
pilot_002 population freeze. Population `NOT_YET_DECIDED`, base run id
`NOT_YET_CONFIGURED`, reuse `UNDECIDED`, publication open, TSan/ASLR
`OPEN_FOR_FINAL_ENVIRONMENT_GATE`, pilot_002 not run.

## 1.3 Technical provenance cleanup (2026-09-13, start HEAD `78307026eeec`)

Both technical provenance gaps left open by wave 1.2 are closed; result semantics are untouched (`RESULT_SEMANTICS_CHANGED = false`, `PROVENANCE_SEMANTICS_CHANGED = true`). Machine-readable record: `thesis/evaluation/technical_provenance_cleanup.json` (sha `a71ee6580b837b38`).

### 1.3.1 PARCOACH / LLOV per-model invocation coverage - CLOSED

`stage_runtime.expected_split_static_invocations(contract)` derives the expected logical scopes `(stage, tool, model_id)` from the FROZEN contract only (`model_ids` x split tools enabled in `static_toolset` x tool scope INTERSECT contracted population; nothing hard-coded - the productive contract view currently yields 11 PARCOACH + 11 LLOV scopes). `split_static_invocation_matrix` reports MEMBERSHIP (observed scopes allowed and consistent) separately from COVERAGE (every expected scope evidenced) and the verifier emits `split_static_invocation_expected_set`, `split_static_invocation_membership`, `split_static_invocation_coverage` and one `split_static_invocation:<stage>/<model>` check per scope; `post_run_verification.json` carries `split_static_invocation_coverage` (`expected_scope_count`, `observed_scope_count`, `covered_scope_count`, `missing_scopes`, `unexpected_scopes`, `contradicting_scopes`, `per_tool`).

| expected scope | verdict |
|---|---|
| valid contract-bound invocation present | PASS |
| records present, invocation missing | UNRESOLVED (results exist, execution not provenance-bound) |
| records missing, invocation missing | UNRESOLVED here; `static_coverage` FAILs the run - never excused |
| deliberate narrowing evidence (frozen resolved_config subset / drift on the model list) | FAIL |
| invocation for a non-applicable scope, model outside the contract | FAIL |
| contract / fingerprint contradiction, unkeyable fragment | FAIL |
| consistent duplicates (per-model + whole-run fragment, same condition) | PASS, reported |
| contradictory duplicates | FAIL |

A whole-run fragment (`model_scope` null) covers a model only together with that model's own `static_analysis_summary.json` invocation that ran the tool. `RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION = false`, `RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION = false`. The wave-1.2 measurement fixture now reports `STATIC_SPLIT_INVOCATION_COVERAGE_GAP = CLOSED` for both tools (records present + invocation missing -> UNRESOLVED).

### 1.3.2 Iteration-0 correctness / dynamic writer attribution - CLOSED

`thesis/evaluation/writer_attribution.py` (`repair_writer_attribution.v1`) defines ONE attribution for the three internal stages: the label `repair %s/%s iteration %d (internal %s)` (byte-identical to the static label of wave 1.2) plus a structured block binding `base_run_id`, `model_id`, `variant`, `iteration`, `internal_stage` and the repair_evaluation enforcement context (contract, authorization, invocation and stage-runtime shas). `RepairLoop._run_analysis_stages` hands it to all three runners; the runners persist it in their per-model invocation histories: `static_analysis_summary.json` `invocations[]` (existing), `correctness_summary.json` (new sidecar, `correctness_summary.v1`), `dynamic_analysis_summary.json` `invocations[]` (new append-only history). Base runners write `writer = base` and no block. No result record gained a field; verdicts, findings, timeouts, launch grid and stop semantics are unchanged.

`repair_scope.iteration_zero_analysis` reads the three histories (`repair_labelled_static_iterations`, `repair_labelled_correctness_iterations`, `repair_labelled_dynamic_iterations`, `writer_attribution_problems`, `writer_attribution_unreadable`) and keeps the `repair_evaluation` invocation REQUIRED for any labelled iteration - positive WHO-WROTE provenance that survives complete records. Fail-closed: an unreadable history -> UNRESOLVED row; a malformed entry, a wrong model / base run, an uncontracted variant, an iteration beyond `max_iterations` or two attributions binding different provenance -> FAIL row; identical resume entries are one consistent observation. A loop whose base stages were complete and that ran no internal stage keeps `invocation NOT_APPLICABLE` (no blanket requirement). `ITERATION_ZERO_COVERAGE_RESIDUAL = CLOSED_BY_WRITER_ATTRIBUTION`.

### 1.3.3 Conditions

| condition | before | after | why |
|---|---|---|---|
| static_analysis_condition | `1f7733276dd17d0e` | `1f7733276dd17d0e` | unchanged: no input touched |
| repair_condition | `e6f5c32bbf329484` | `98b8be0f753dcbc1` | `orchestrator_sha256` only (raw hash of orchestrator.py: the attribution hand-off) |
| runtime_condition (readiness) | `516288da9998fd1c` | `0d5f4889334dea26` | the bound repair sha only; image identities unchanged; gate READY |
| assembly_condition | `a1488514eb2482a2` | `a1488514eb2482a2` | unchanged |
| enhanced E3 frozen specs | `49b0229c508f0630` | `49b0229c508f0630` | unchanged |
| cross-pilot fingerprint | `7356e25356af4fa9` | `acaf4584983c3de1` | run_correctness.py coarse shared-state refresh after a recorded function-level assessment; result classes unchanged |

### 1.3.4 Tests, review, flags

`test_provenance_cleanup.py`: 149 checks (split coverage A-M incl. narrowing, foreign run id, whole-run fragments; writer attribution A-P incl. the core regression 'correctness-only iteration-0 repair + deleted repair_evaluation invocation -> NON-PASS' and the counter-direction 'no internal analysis -> PASS / NOT_APPLICABLE'; the productive orchestrator and runners are exercised end-to-end with the compiler probe and the correctness sample runner stubbed). Full suite: all PASS. Adversarial review: round 1: 22 confirmed (all fixed), 5 refuted; round 2: 14 confirmed (all fixed), 2 refuted; open BLOCKING/MUST_FIX after round 2: 0.

* `E3_2_DECISION = ACCEPTED`
* `AUTHOR_CHOICES_CHANGED = false`
* `GENERATION_PERFORMED = false`
* `LLM_API_CALLS = 0`
* `PILOT001_HISTORICAL_TREE_CHANGED = false`
* `CORRECTNESS_VERDICT_SEMANTICS_CHANGED = false`
* `DYNAMIC_FINDING_SEMANTICS_CHANGED = false`
* `STATIC_FINDING_SEMANTICS_CHANGED = false`
* `REPAIR_STOP_SEMANTICS_CHANGED = false`
* `ASSEMBLY_SEMANTICS_CHANGED = false`
* `ENHANCED_SEMANTICS_CHANGED = false`
* `TIMING_SEMANTICS_CHANGED = false`
* `RESULT_SEMANTICS_CHANGED = false`
* `PROVENANCE_SEMANTICS_CHANGED = true`
* `POPULATION_CHANGED = false`
* `RUN_ID_CHANGED = false`
* `REUSE_DECIDED = false`
* `PUBLICATION_DECIDED = false`
* `STATIC_SPLIT_INVOCATION_COVERAGE_GAP = CLOSED`
* `ITERATION_ZERO_COVERAGE_RESIDUAL = CLOSED`
* `TECHNICAL_PROVENANCE_CLEANUP = COMPLETE`
* `SAFE_TO_PROCEED_TO_POPULATION_AND_METHODOLOGY_FREEZE = true`

Open for the FINAL ENVIRONMENT GATE (not here): Docker first-inspect observation (reproduced three times in this wave, once as a NOT_READY readiness artifact written by a review-workflow agent and re-measured READY; no policy introduced), TSan/ASLR. Population NOT_YET_DECIDED, base run id NOT_YET_CONFIGURED, reuse UNDECIDED, publication OPEN. Next step: **PILOT_002 POPULATION + FINAL METHODOLOGY/RUN FREEZE**.
