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
