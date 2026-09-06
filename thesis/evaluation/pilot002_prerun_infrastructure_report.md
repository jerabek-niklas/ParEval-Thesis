# Pilot-002 pre-run infrastructure

Assembly integrity & provenance, newline/hash discipline, cleaning
provenance, timing semantics, reporting contracts, concurrent manifest
safety, pre-run contract and post-run verification.

- Start HEAD: `d56db25c6ee1cb063a25aae2cb28c787f16a5df0` (branch `thesis-static-analysis`)
- Date: 2026-09-06
- Scope: MECHANISMS only. No LLM/API calls, no pilot_002, no decision about
  population, base run id, reuse or publication; no methodology, comparator,
  prompt, spec, static-finding or repair-semantics change.
- pilot_001 evidence: READ-ONLY. Re-assembly for the byte regression happens
  in a scratch intermediate directory; the historical tree is fingerprinted
  before and after (file count + newest mtime) and was unchanged in every run.

---

## 1. Two hash classes, kept strictly apart

`thesis/evaluation/condition_hashing.py`

| class | rule | applies to |
|---|---|---|
| CONDITION (method) | **LF-normalized** bytes (CRLF→LF, lone CR→LF), then SHA-256 | new condition fingerprints over implementation/policy/reporting files |
| ARTIFACT | **RAW bytes**, never normalized | `source_sha256` of `generated-code.hpp`, record files, spec files |

Reason: this repository is checked out with `core.autocrlf=true` on Windows
and with LF in a Linux clone, and there is no `.gitattributes`. A raw-byte
condition hash therefore fingerprints the checkout, not the method. An
artifact hash must stay raw: `source_sha256` is the identity of the bytes the
compiler reads.

Existing condition versions (`static_condition.v1`, `repair_condition.v1`,
the cross-pilot gate's shared/assembly state, the E3 frozen-spec verifier)
keep their documented raw-byte rule — a hash rule is part of a condition's
version and is not changed silently. Their known consequence is measured in
§8.

## 2. pilot_001 newline inventory (read-only)

`thesis/assembly/newline_inventory.py` → `thesis/evaluation/pilot001_newline_inventory.json`

| run | files | LF | CRLF | MIXED | OTHER | without trailing newline |
|---|---|---|---|---|---|---|
| pilot_001 (base) | 396 | 0 | 396 | 0 | 0 | 0 |
| 6 repair-iteration runs | 715 | 715 | 0 | 0 | 0 | 0 |
| **total** | **1111** | **715** | **396** | **0** | **0** | **0** |

The base run was assembled on the Windows host, the repair iterations in the
Linux container. Nothing was modified.

## 3. Assembly writer newline policy

`ASSEMBLY_WRITER_NEWLINE_POLICY = HOST_DEPENDENT`,
`ASSEMBLY_WRITER_NEWLINE_HOST_DEPENDENT = true`.

The only production writer of candidate sources is
`thesis/assembly/assemble_sources.py` (the repair orchestrator delegates to
the same `assemble_model()`). It writes in text mode with `newline=None`, so
`\n` becomes `os.linesep` — CRLF on Windows, LF in the container. This wave
**deliberately does not pin the writer to LF**: that would change the raw
bytes (and therefore every raw artifact hash) of re-assembled base samples
and needs its own re-freeze step. The behaviour is measured, documented, and
carried in the assembly condition as a statement about the CODE (never about
the host); the per-sample record stores the observed `newline_convention`,
and the per-model summary additionally records the assembling host
(`platform`, `os.linesep`, python version) as evidence.

## 4. Candidate-code transformation chain and its coverage

| # | stage | function / file | input → output | condition |
|---|---|---|---|---|
| 1 | provider text extraction | `_extract_text` in the 4 adapters, `_anthropic_extract_text` / `_openai_body_response` / `_gemini_extract_text` in `batch_api.py` | provider response → `output.raw_text` | `generation_cleaning_condition.v1` (AST-located, LF-normalized function sources) |
| 2 | generation-side cleaning | `common.clean_generated_code` → `cleaning.extract_code` | `raw_text` → `output.cleaned_code` (informational; **not** the assembly input) | `generation_cleaning_condition.v1` |
| 3 | assembly cleaning | `cleaning.clean_for_assembly(prompt_text, raw_text)` | record → body / pre-signature code / relocated includes | `assembly_condition.v1` (LF-normalized `cleaning.py`) |
| 4 | source layout | `assemble_content` + `patch_signature_line` + single-brace auto-close | cleaned parts → source text | `assembly_condition.v1` (LF-normalized `assemble_sources.py` + policy `auto_close_single_brace`) |
| 5 | write | `atomic_io.atomic_write_text(newline=None)` | source text → `generated-code.hpp` bytes | `assembly_condition.v1` (writer policy statement) |

`CONDITION_COVERAGE_GAPS = 0`,
`GENERATION_CLEANING_COVERED_BY_CONDITION = true`.
Neither the request semantics nor the cleaning output changed
(`GENERATION_REQUEST_SEMANTICS_CHANGED = false`,
`GENERATION_CLEANING_OUTPUT_CHANGED = false`,
`ASSEMBLY_CLEANING_OUTPUT_CHANGED = false`; proven by §6).

## 5. Assembly schema `assembly.v2` (additive)

Per assembled sample, additionally to the v1 fields:

| field | meaning |
|---|---|
| `assembly_input_sha256` | canonical JSON `{prompt_text, raw_text, generation_truncated}` (UTF-8, sort_keys, compact) — EXACTLY the record-borne input of the assembly stage; `generation_truncated` is included because it gates the auto-close and therefore the output bytes |
| `source_sha256` | RAW SHA-256 of `generated-code.hpp`, re-read from disk after the write |
| `newline_convention` | LF / CRLF / MIXED / OTHER of those bytes |
| `byte_size`, `trailing_newline` | from the same bytes |
| `logical_source_path` | `<model_id>/sources/<sample_id>/generated-code.hpp` — run-relative, never absolute/host/container |
| `assembly_condition_version`, `assembly_condition_sha256` | the method this file was produced under |
| `execution_model`, `benchmark` | projection keys of the per-model set |

Per model: `assembly_summary.json` with `assembly_set_sha256` (canonical
sorted projection of `sample_id`, `execution_model`, `benchmark`,
`logical_source_path`, `source_sha256`), the counts (records considered,
assembled, skipped, warnings, duplicates, stale sources removed), the
condition, the writer policy, the observed newline histogram and the
assembling host. The same values are registered in the run manifest as
`assembly_model_sets[<model_id>]`; a second, DIFFERENT set for the same model
under the same run is a hard failure (`AssemblySetMismatch`), an identical
re-registration is idempotent.

Legacy `assembly.v1` records (pilot_001) are **never rewritten**; they are
classified `LEGACY_UNPINNED_ASSEMBLY`, and an in-place re-assembly of such a
run is refused (`allow_legacy_rewrite` must be passed explicitly for a
deliberate, documented migration).

Fail-closed behaviour (tested):

| situation | result |
|---|---|
| duplicate `sample_id` in the generation records | REFUSED before anything is written |
| record hash ≠ file bytes | REFUSED (`tampered_sources`) |
| record without source file | REFUSED (`missing_sources`) |
| source file without record | ORPHAN DETECTED |
| sample no longer assembles / disappears | its stale source is removed, the removal recorded |
| crash during a source write | no `assembly.jsonl` at all (a reader sees zero samples, never stale ones); leftovers are reported as orphans |
| crash during the record write | no partial `assembly.jsonl` (single atomic write) |

## 6. GATE 1 — real pilot_001 assembly byte regression

`thesis/assembly/assembly_byte_regression.py` →
`thesis/evaluation/pilot001_assembly_byte_regression.json`

All 1111 historical samples (base + 6 repair-iteration runs, 11 models) were
re-assembled with the NEW code into a scratch directory and compared byte by
byte.

| metric | Windows host | Linux container |
|---|---|---|
| TOTAL | 1111 | 1111 |
| IDENTICAL | 396 (the CRLF base run) | 715 (the LF iteration runs) |
| DIFFERENT | 715 | 396 |
| DIFFERENT **same host** | **0** | **0** |
| DIFFERENT cross-host (newline-only) | 715 | 396 |
| DIFFERENT **content** | **0** | **0** |
| NOT_REPRODUCIBLE | 0 | 0 |
| LF-normalized equal | 1111 | 1111 |
| cleaning-flag mismatches | 0 | 0 |
| historical tree untouched | true | true |

Each historical file is byte-identical when re-assembled on the host that
originally produced it. `ASSEMBLY_SEMANTICS_CHANGED = false`,
`PILOT001_ASSEMBLED_BYTES_CHANGED = false`,
`GATE_1_PILOT001_ASSEMBLY_BYTE_REGRESSION = PASS`.

The gate itself is fail-closed: an empty comparison (wrong run prefix or model
filter), any NOT_REPRODUCIBLE sample, a cleaning-flag mismatch, a new source
without a historical counterpart or a modified historical tree all make it FAIL
and report `ASSEMBLY_SEMANTICS_CHANGED = UNDECIDED` instead of `false` — a gate
that compared nothing proves nothing.

## 7. Base vs. repair cleaning parity

The repair loop calls the same `assemble_sources.assemble_model()` with an
iteration run id; a test assembles one record under a base run and under an
iteration run and compares bytes and condition — identical. Iteration
artifacts carry the same provenance but are never counted as base population
(the post-run verifier fails a run whose iteration artifacts claim the base
run, and a base run id that looks like an iteration run).

## 8. Checkout portability (fresh Linux clone)

`thesis/evaluation/check_condition_portability.py`, run on the Windows CRLF
checkout and in a fresh `git clone` inside the container (LF, `core.autocrlf`
unset), with the wave's working-tree files copied in LF-normalized:

| condition | host (CRLF) | clone (LF) |
|---|---|---|
| `assembly_condition.v1` | `a2a76e89…` | `a2a76e89…` |
| `generation_cleaning_condition.v1` | `1e29649f…` | `1e29649f…` |
| `timing_semantics.v1` | `6638398d…` | `6638398d…` |
| `report_contract.v1` | `fdea3a1a…` | `fdea3a1a…` |

`CONDITION_FINGERPRINTS_CHECKOUT_INDEPENDENT = true` (0 of 13 implementation
files differ in their LF-normalized hash; 3 differ raw, as expected).
`test_assembly_provenance.py`, `test_manifest_fragments.py`,
`test_post_run_verification.py` and `test_cleaning.py` all pass in the clone.

Known PRE-EXISTING limitation (not introduced here, measured with a control
run on a pure HEAD clone with no working-tree files): the EXISTING gate and
E3 verifier hash raw bytes, so on an LF checkout they already report 15 STALE
entries and `E3_FROZEN_ARTIFACTS_REPRODUCIBLE = false` at the unmodified
start HEAD. On the productive Windows checkout both are green. Changing those
condition versions is out of scope for this wave.

## 9. Timing semantics

`thesis/evaluation/timing_semantics.py` (`timing_semantics.v1`, exported to
`timing_semantics.json`, sha `6638398d…`), validator
`thesis/evaluation/check_timing_semantics.py`.

Per field the contract states: producer, unit, meaning, clock source, start
and end boundary, availability in direct/batch mode, what it includes
(client/SDK retries, provider queue wait, local queue wait, build, process
startup, launcher overhead, runtime initialization, adapter overhead, CPU
contention), what it is suitable for (model-speed ranking, cross-model within
one execution model, cross-execution-model, cross-pilot absolute, cost) and
the allowed aggregation.

Global statements:

- `RUN_SECONDS_CROSS_EXECUTION_MODEL_COMPARABLE = false` — mpi run seconds
  include the `mpirun -np N` launcher and MPI init, omp the OpenMP runtime
  init (and the driver's fixed timing iterations), serial the process startup.
- `BATCH_QUEUE_TIME_IS_MODEL_LATENCY = false` — batch `duration_seconds`
  stays `null`; the job-level span is exposed as `batch_wall_clock_seconds`.
- `CROSS_MODEL_LATENCY_RANKING` — available only when every model ran in
  direct mode.
- `STATIC_DURATION_IS_MODEL_SPEED = false`.
- Timeouts store the OBSERVED elapsed plus a flag, never the configured
  limit; the limit comes from the run manifest.
- Provider cost = usage tokens × configured price only; generation and repair
  responses are counted once each; missing usage stays null.

Producer changes (metadata only): direct generation and direct repair
requests now measure `time.perf_counter()` (monotonic) and record
`status.timing_clock`; `apply_batch_timing` additionally derives
`batch_wall_clock_seconds`. No stage, prompt, retry or stop behaviour
changed.

The validator is fail-closed as well: a run id with no model evidence is a
VIOLATION (a validation that inspected nothing proves nothing), an explicitly
named model is never silently replaced by directory discovery, a model with
compile timings but zero run timings is NOT `TEST_RUNTIME_AVAILABLE`, the build
limit is read from `stages.correctness_tests.build_timeout_seconds` when
configured, and a run that used the unpersisted `--run-timeout` override can
declare it via `--run-timeout-seconds` instead of producing false violations.

pilot_001 inventory (read-only, `thesis/evaluation/pilot001_timing_inventory.json`):
status PASS, limits from the MANIFEST, 0 violations, 1 anomaly.

| class | models |
|---|---|
| `BATCH_QUEUE_ONLY` | 6 (claude_fable_5, claude_opus_5, gemini_31_pro, gemini_36_flash, openai_gpt55, openai_gpt56_sol) |
| `DIRECT_LATENCY_AVAILABLE` | 5 (deepseek_v4_flash, deepseek_v4_pro, qwen36_35b_a3b, qwen37_max, qwen3_coder_api) |
| `TEST_RUNTIME_AVAILABLE` (correctness) | 11 of 11 |

`CROSS_MODEL_LATENCY_RANKING = NOT_AVAILABLE` for pilot_001 (mixed modes).
The single anomaly is the known `enhanced_build_groups` row with
`compile_seconds = 70714.574` (a wall-clock suspension mid-compile) — flagged
as an anomaly, never silently aggregated as a build time. All six
repair-iteration runs are `DIRECT_LATENCY_AVAILABLE` with 0 violations.

## 10. Reporting contracts

`thesis/analysis_overview/report_contracts.py` + the overview renderer.

- **Manifest over live config**: stages and models come from the run
  manifest's frozen `resolved_config`; only paths come from the live config.
  Without a manifest the report says `LEGACY_FALLBACK_LIVE_CONFIG` explicitly.
- **Accepted semantic disclosure** (GATE 4): rendered automatically from
  `semantic_decisions_pilot002.json` — benchmark, decision id, accepted
  status, the cautious methodological limitation ("results for this benchmark
  may be sensitive to the accepted LU tolerance/rounding convention …"), the
  affected and not-affected results, the enhanced reporting note and the
  sample count. Every aggregate section that contains the benchmark is marked
  "_Includes accepted-disclosure benchmark(s) … the benchmark is NOT
  excluded_". No causal claim is made and nothing is auto-excluded (tested).
  Measured on a real pilot_001 overview built into a scratch analysis root
  (the committed report was NOT touched): 19 sections, of which the 14 that
  aggregate over benchmarks — including the static-coverage and repair-status
  tables — carry the marker, and the 5 contract/provenance sections
  (disclosures, cross-pilot, timing, config snapshot, report provenance)
  correctly do not.
- **An unreadable decision artifact is never silence**: if
  `semantic_decisions_pilot002.json` is missing, unreadable or malformed, the
  report says `SEMANTIC_DISCLOSURE_RENDERING = UNKNOWN`, marks every aggregate
  as unverified with respect to disclosure-bearing benchmarks and the builder
  prints a warning — it never states "no disclosure is registered".
- **Static coverage**: per tool CLEAN / DEFECT_FOUND / PARTIAL /
  NOT_ANALYZED / TOOL_ERROR / TIMEOUT / NOT_APPLICABLE, the number of samples
  with at least one coverage limitation, the low-confidence finding total
  (explicitly NOT attributed to a single tool — the underlying column is a
  per-row sum over all analysis tools) and the LLOV classes.
- **Repair statuses**: final status per (model, variant, sample) with the
  class MODEL_OUTCOME vs. INFRASTRUCTURE_STATE — `stopped_analysis_incomplete`
  and `stopped_api_exhausted` are never model failures.
- **Cross-pilot**: consumed from `cross_pilot_comparability.json` (per-cell
  classes, directly comparable benchmarks, mandatory disclosures, enhanced
  overlap totals, per-tool and repair classes, statistical caveats). No global
  "pilot_001 improved by X %" statement is derivable.
- **Timing semantics** block from the contract, including the per-model
  timing class and the ranking availability.
- **Report provenance** block + content-addressed `report_condition_sha256`
  (LF-normalized implementation, timing contract, semantic decisions; no
  timestamps or hostnames), also written as `overview_provenance.json`.
  Missing pins render as `UNKNOWN`, never guessed, and any value that is
  recomputed from the CURRENT repository rather than read from the run is
  named `…_recomputed_now` so it cannot be mistaken for run provenance.

## 11. Concurrent manifest safety (GATE 2)

Measured with real processes on the real host mount
(`thesis/results/intermediate`), inside the container on the same bind mount
(9p/DrvFS), and in a temp dir — 8 writers × 25 registrations each:

| architecture | stored | lost |
|---|---|---|
| legacy shared read-modify-write | 25–32 of 200 | **168–175** |
| per-writer fragments | 200 of 200 | **0** |

`MANIFEST_SHARED_WRITE_CAPABILITY = UNSAFE_OR_UNPROVEN` (legacy RMW on this
mount), `SELECTED_MANIFEST_ARCHITECTURE = PER_WRITER_FRAGMENTS`
(`thesis/evaluation/manifest_fragments.py`).

Cross-container write safety (found by the adversarial review, fixed and
regression-tested): a temp file named after the PID alone is NOT unique here —
every `docker run … python3 …` is PID 1, so two containers writing the same
target would pick the same temp path and one would rename away the other's
file mid-registration. Temp names now carry PID + thread id + 6 random bytes,
and `os.replace` retries briefly on the Windows sharing violation that a
concurrent writer/reader of the same target produces. Measured afterwards:
three separate containers (all PID 1) registering 40 models each into one run
on the real mount → 120/120 registrations, 0 errors, 0 temp leftovers, a
parsable snapshot; and 8 threads × 40 writes with the PID pinned to 1 → 320
distinct temp names, 0 errors. The derived `run_manifest.json` snapshot is
best-effort: if it cannot be refreshed, the registration still succeeds and
the fragments remain authoritative.

Properties (tested): one owner per fragment; atomic write (temp + fsync +
`os.replace`) inside an exclusive `mkdir` section with stale-lock takeover;
identical re-registration idempotent; same key + different fingerprint HARD
FAIL (also under real concurrency: exactly one registered, one refused, never
a mixed file); deterministic read-only merge; missing expected fragment →
incomplete; unexpected fragment reported; killed writers leave only complete
JSON (0 temp leftovers); an append-only registration history that is part of
no condition. `run_manifest.json` is regenerated as the merged snapshot.
Legacy runs with a shared manifest and no fragments directory keep it and are
never migrated in place (pilot_001 stays untouched).

## 12. Pre-run contract and T0 guard

`thesis/evaluation/pilot_run_contract.py` (`pilot_run_contract.v1`):
run id, profile, model ids, population (selection, limits, execution models,
prompt set sha + per-prompt map, selected prompt keys, expected sample
count), primary compiler, run and generation timeouts, the conditions
(generation, assembly, generation-cleaning, evaluation, enhanced frozen specs
+ policy, static, repair, static/repair runtime, semantic decisions,
cross-pilot artifact, timing contract), expected stages, the post-run
verifier version and the policy state. No secrets.

- `CONTRACT_BUILDER = READY`
- `CONTRACT_BUILDER_STATE = NOT_READY` — blockers: population
  `NOT_YET_DECIDED`, base run id `NOT_YET_CONFIGURED`, and the configured run
  id is still the historical `pilot_001`. Freezing a NOT_READY contract is
  refused.
- `FINAL_PILOT002_CONTRACT = NOT_YET_CREATED`
- `T0_START_GUARD = READY`: immediately before the first cost-causing request
  the contract is rebuilt from the live state and compared with the frozen
  sha; any drift → `START_REFUSED` and nothing is registered. On a match the
  contract sha and the T0 runtime evidence are bound to the run manifest
  BEFORE any request. A corrupt frozen contract (stored sha ≠ content sha) is
  refused.

## 13. GATE 3 — post-run verification

`thesis/evaluation/verify_pilot_run.py` (`verify_pilot_run.v1`) →
`post_run_verification.json`, statuses PASS / FAIL / UNRESOLVED.

Fixtures (`thesis/evaluation/test_post_run_verification.py`), each built with
the real production code and mutated in exactly one property:

Beyond the contracted coverage the verifier also compares the conditions the
run REGISTERED (static analysis, repair, assembly, enhanced specs, static/repair
runtime) with the ones the contract pinned, the run's profile, and whether every
SUCCESSFUL generation actually reached the assembled set — so a run cannot pass
vacuously by assembling nothing, and a run executed under a different analysis
condition cannot pass at all.

| fixture | expectation | result |
|---|---|---|
| A exact run | PASS | PASS |
| B wrong run_id | FAIL | FAIL |
| C missing model | FAIL | FAIL |
| D unexpected extra model | FAIL | FAIL |
| E sample count | FAIL | FAIL |
| F prompt drift | FAIL | FAIL |
| G source bytes ≠ record hash | FAIL | FAIL |
| G2 assembly set fingerprint drift | FAIL | FAIL |
| H orphan source | FAIL | FAIL |
| I missing correctness record | FAIL | FAIL |
| J terminal static gap state | PASS + coverage limitation | PASS |
| K missing static tool entry | FAIL | FAIL |
| L missing (sample, spec_key) pair | FAIL | FAIL |
| M candidate-source drift after the enhanced run | FAIL | FAIL |
| N runtime evidence ≠ contract | FAIL | FAIL |
| O no runtime evidence bound at T0 | UNRESOLVED | UNRESOLVED |
| P iteration artifact claiming the base run | FAIL | FAIL |
| P2 iteration run id as base run | FAIL | FAIL |
| Q bound contract sha drift | FAIL | FAIL |
| R no contract at all | UNRESOLVED | UNRESOLVED |
| S run registered another static condition | FAIL | FAIL |
| S2 run registered no analysis condition | UNRESOLVED | UNRESOLVED |
| T contract frozen for another profile | FAIL | FAIL |
| U successful generation never assembled | FAIL | FAIL |
| V enhanced record whose spec cannot be keyed | FAIL | FAIL |
| H2 assembly record without a generation record | FAIL | FAIL |

A retrospective live runtime measurement is explicitly NOT accepted as a
substitute for evidence bound at T0.

## 14. Controlled cross-pilot artifact update

One entry was stale: `assembly_state.files['thesis/assembly/assemble_sources.py']`
(coarse). Classified `PROVENANCE_ONLY` on the evidence of §6 and refreshed
with a justification; the semantic assembly dependency `cleaning.py` is
unchanged. The wave is recorded under
`cross_pilot_reevaluation.areas.C_generation_assembly.pilot_002_prerun_infrastructure_wave`
with a per-area change classification (assembly/generation-cleaning/manifest:
PROVENANCE_ONLY, timing: TIMING_METADATA_ONLY, reporting: REPORTING_ONLY,
execution semantics: UNCHANGED) and the byte-regression numbers. The
artifact's self-fingerprint was recomputed (`bfb09649…` → `4957b9c3…`).
Correctness cell counts (99/99/198), the comparability classification, the
candidate subset, the reuse status, the population and the base-run-id
targets are untouched. `check_cross_pilot_gate.py` is CURRENT again.

The static/repair readiness artifact was re-measured because the repair
condition contains a raw hash of `orchestrator.py`, and the monotonic-clock
change touches that file. Proof that this is provenance-only: recomputing the
repair condition with the HEAD version of `orchestrator.py` reproduces the
pinned `09a8e8a2…` exactly, i.e. the ONLY differing field is
`orchestrator_sha256` — variants, max_iterations, strategies, history mode,
low-confidence policy, feedback template, api mode, external tools, retry
policy and terminal statuses are identical. The orchestrator diff is exactly
two lines (`started_perf = time.perf_counter()` and passing it to
`apply_direct_timing`).

Re-measured artifact (`check_static_repair_readiness.py`, all 14 tool
fixtures PASS in all three images):

| condition | before | after |
|---|---|---|
| static analysis | `327b235a…` | `327b235a…` (unchanged) |
| repair | `09a8e8a2…` | `935430bb…` (only `orchestrator_sha256`) |
| static/repair runtime | `8c382160…` | `70c0f489…` (carries the repair sha) |
| gate | READY | READY, `runtime_fully_pinned = true`, 0 problems, 0 unresolved |

## 15. Open, unchanged by this wave

- pilot_002 population: `NOT_YET_DECIDED`
- pilot_002 base run id: `NOT_YET_CONFIGURED` (the config still carries
  `pilot_001`)
- reuse of pilot_001 generations: `UNDECIDED`
- publication policy: unchanged
- TSan/ASLR (`vm.mmap_rnd_bits`): `OPEN_FOR_FINAL_ENVIRONMENT_GATE`
- the raw-byte hash rule of the EXISTING gate/E3 conditions (checkout
  dependence, §8)
- pilot_001 has no per-sample source hashes and no runtime provenance
  (`LEGACY_UNPINNED_ASSEMBLY`)
