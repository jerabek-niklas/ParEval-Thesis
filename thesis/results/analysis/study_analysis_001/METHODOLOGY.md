# Methodology study_analysis_001 (`study_analysis_methodology.v1`, FROZEN_BEFORE_AGGREGATION)

Generated from `thesis/study_analysis/methodology.json` by `thesis/study_analysis/methodology_doc.py` - do not edit by hand. Frozen on 2026-10-17, before any aggregation.

Applies to the runs `pilot_002`, `full_ext_001`, `full_ext_recovery_001`, `full_ext_recovery_002`, `full_ext_recovery_003`, `full_ext_recovery_004`, `full_ext_phase2_001` (closure `study_closure_001`, composite `phase2_composite.v1`); excluded: `full_ext_001__static_feedback__iter1`.

## Study goals

Source: thesis/docs/repair-loop-design.md (sections 1, 3, 9).

**Official research questions:** MISSING - the repository documents study goals but no numbered thesis research questions; the goals below are quoted from the design document and must be replaced or confirmed by the author's official research questions.

- **G1** (section 1): Measure whether and how analysis feedback improves LLM-generated parallel code (initial generation followed by bounded repair iterations).
- **G2** (section 1, 2): Which kind of feedback helps: static analysis (static_feedback) vs. ParEval tests + dynamic analysis (test_feedback) vs. all sources (combined_feedback), as an ablation over three loop variants with identical starting points.
- **G3** (section 3): Held-out generalisation / overfitting: whether rising ParEval pass rates over iterations are matched by enhanced (held-out) pass rates.
- **G4** (section 9): Per variant and iteration: blocking findings per tool/class, ParEval pass rate, enhanced pass rate, stop-reason distribution, iterations-to-clean, cost; per problem type; 'statically clean but incorrect' rate of static_feedback.

Documented deviations:

- repair-loop-design.md states an iteration budget of 3; the frozen methodology (pilot_002_methodology_freeze.json repair.max_iterations, every run contract) executed at most 2 repair iterations - the analysis uses the frozen value 2.

## Observation units

- **base_cell**: one (block, model, benchmark, execution_model) prompt cell with exactly one initial generation (num_samples_per_prompt = 1); identified by (block, model_id, sample_id)
- **artifact**: one assembled program (base cell at iteration 0 or a repair candidate at iteration >= 1); identified by (block, model_id, source_run, sample_id)
- **trajectory**: the repair trajectory of one base cell under one variant: iterations 0..final_iteration, terminal status from the loop's own state ledger
- **enhanced_pair**: one (artifact, held-out spec) execution; NOT an independent observation
- **benchmark**: the resampling cluster: every artifact of a benchmark (all models, execution models, variants, iterations) shares its prompt family and oracle

## Populations

- **BASE**: the 1,980 base cells (pilot_002 396 + full_ext_001 1,584), iteration-0 artifacts. *Use:* initial code quality.
- **STEP**: for variant v and step k in {0,1,2}: per base cell the artifact of iteration min(k, final_iteration) of its v trajectory (last artifact carried forward); STEP[v][0] == BASE. *Use:* quality after iteration k; identical cohort for every v and k.
- **FINAL**: for variant v: per base cell the artifact of the trajectory's terminal iteration (== STEP[v][2]); for trajectories terminal at iteration 0 the final artifact IS the base artifact. *Use:* repair outcome per strategy on the identical 1,980-cell cohort.
- **GENERATED**: all 5,460 artifacts (1,980 base + 3,480 repair candidates). *Use:* diagnostic only; never mixed with FINAL or STEP rates.
- **REPAIR_CANDIDATES**: the 3,480 repair candidates (iteration >= 1). *Use:* diagnostic only.
- **ENH_PAIRS**: the enhanced pairs of the artifacts of a population; VALID pairs = status not in GATED. *Use:* held-out evaluation.

Rules:

- FINAL and STEP are selected exclusively from the loop's own terminal state ledger (state.jsonl, continued loops: recovery_001 rows overlaid by the successor rows); no held-out (enhanced) or post-hoc evidence takes part in the selection
- terminal statuses are trajectory facts, not success metrics: stopped_clean and stopped_tests_pass are never counted as successful repairs
- BASE, STEP and FINAL rates of different variants use the identical base-cell cohort; GENERATED/REPAIR_CANDIDATES rates are reported separately and labelled diagnostic

## Strata

- **block**: pilot, full_ext, composite
- **block_rule**: pilot (pilot_002, 12 benchmarks) and full_ext (full_ext_001 + recovery 001..004 + phase 2, 48 benchmarks) are disjoint benchmark sets; every table reports both blocks; 'composite' pools them under the frozen composite population (1,980 cells) and is always reported next to the blocks; pilot numbers carry the pilot label
- **model_id**: the 11 models (no ranking, no aggregate score)
- **execution_model**: serial, omp, mpi
- **variant**: static_feedback, test_feedback, combined_feedback
- **family**: problem type of the benchmark (12 families; pilot 1 + full_ext 4 benchmarks per family)
- **iteration**: 0, 1, 2

## State vocabularies and rules

- **tool_states**: `COMPLETED`, `PARTIAL`, `TIMEOUT`, `TOOL_ERROR`, `NOT_ANALYZED`, `NOT_APPLICABLE`, `ABSENT_INAPPLICABLE`
**tool state rules**

- COMPLETED: the tool finished its analysis; it does NOT imply defect-free code
- PARTIAL: an incomplete analysis; absence of findings under PARTIAL is NOT 'clean'
- TIMEOUT and TOOL_ERROR are analysis gaps, never confirmed program defects
- NOT_ANALYZED: the tool ran but did not analyze the model code (e.g. frontend abort); an analysis gap
- NOT_APPLICABLE: the tool does not apply to the execution model (recorded entry)
- ABSENT_INAPPLICABLE: no entry for a tool that does not apply to the artifact's execution model (14 historical pilot records); reported separately, treated like NOT_APPLICABLE for applicability, never as a gap
- an ABSENT entry for an APPLICABLE tool is a data error (the pipeline fails closed)

- **analysis_gap_states**: `PARTIAL`, `TIMEOUT`, `TOOL_ERROR`, `NOT_ANALYZED`
- **correctness_verdicts**: `pass`, `build_failed`, `validation_failed`, `runtime_error`, `timeout`, `baseline_incompatible`
**correctness rules**

- pass = verdict 'pass' (ParEval tests, all launch grid points)
- baseline_incompatible (oracle-side, execution contract A1b) is excluded from every correctness denominator and reported separately (0 observed in the frozen data; the rule is kept)

- **enhanced_statuses**: `pass`, `fail`, `build_failed`, `crash`, `timeout`, `runtime_error`, `baseline_incompatible`, `numerically_unstable`
- **enhanced_gated**: `baseline_incompatible`, `numerically_unstable`
**enhanced rules**

- gated pairs (oracle-side) are never counted against a model; they are documented in full (E4)
- build_failed, crash, timeout, runtime_error and fail are model outcomes of valid pairs (end-to-end evaluation)
- gates are spec-level: within one (block, benchmark, spec, execution_model) every artifact carries the same gate decision (verified: 48 gated groups, 0 mixed) - paired comparisons therefore use identical valid spec sets; a mixed group fails the pipeline

- **terminal_statuses**: `stopped_clean`, `stopped_tests_pass`, `stopped_budget`, `stopped_analysis_incomplete`, `repair_unusable`, `stopped_baseline_incompatible`, `stopped_api_exhausted`
- **non_model_terminal_statuses**: `stopped_baseline_incompatible`, `stopped_analysis_incomplete`, `stopped_api_exhausted`

## Finding rules

- **reported_blocking**: a recorded finding with blocking == true and low_confidence == false
- **low_confidence**: a recorded finding with low_confidence == true (validation-derived low precision, rendered as a hint in the loop; counted separately, never as a confirmed defect)
- **non_blocking**: a recorded finding with blocking == false
- **compile_error**: a blocking finding of the compiler tool (build precondition, reported separately from analysis findings)
- **families**: thesis.evaluation.finding_classes.classify_finding(tool, check_id, message) -> memory, uninitialized, null_deref, arithmetic, race, deadlock, mpi_usage, api_misuse, build, other
- **no_cross_tool_sum**: findings of different tools are never added into one defect count; tables report per tool; candidate-level 'any blocking finding' indicators are unions over tools and are labelled as such
- **analysis_verdict_three_state**: per stage (static excluding the compiler, dynamic): DIRTY = >= 1 reported blocking finding from any applicable tool; CLEAN_COMPLETE = no reported blocking finding and every applicable tool COMPLETED; NO_FINDING_INCOMPLETE = no reported blocking finding and >= 1 applicable tool in an analysis gap state

## Metrics

### Q01 `generation_success`

| field | definition |
| --- | --- |
| Meaning | the provider returned a successful generation |
| Population | BASE (and every artifact's generation record) |
| Observation unit | artifact |
| Numerator | artifacts with generation status.success == true |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | a missing generation record fails the pipeline |
| Aggregation | count ratio |
| Limits of interpretation | says nothing about code quality |

### Q02 `assembly_success`

| field | definition |
| --- | --- |
| Meaning | the answer was assembled into a compilable translation-unit file |
| Population | BASE / GENERATED |
| Observation unit | artifact |
| Numerator | assembled == true |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | assembly applies deterministic cleaning (Q04) |

### Q03 `generation_truncated`

| field | definition |
| --- | --- |
| Meaning | the generation hit the output limit |
| Population | BASE / GENERATED |
| Observation unit | artifact |
| Numerator | generation_truncated == true |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | - |

### Q04 `cleaning_intervention`

| field | definition |
| --- | --- |
| Meaning | the pipeline changed the raw answer before measurement; one sub-metric per flag: used_fence, dropped_leading_lines > 0, dropped_trailing_lines > 0, dropped_duplicated_prompt_lines > 0, relocated_includes non-empty, auto_closed, signature_suspect, braces_balanced == false; 'any' = union of the flags except used_fence (markdown fences are formatting, not code changes) and 'any_including_fence' |
| Population | BASE / GENERATED |
| Observation unit | artifact |
| Numerator | artifacts with the flag |
| Denominator | assembled artifacts |
| Applicability | assembled artifacts |
| Missingness / error states | a missing cleaning block fails closed |
| Aggregation | count ratio |
| Limits of interpretation | auto_closed means the PIPELINE closed braces - an intervention on the measured object; read next to every pass rate (sensitivity SA2) |

### Q05 `build_success`

| field | definition |
| --- | --- |
| Meaning | the correctness-stage build compiled |
| Population | BASE / STEP / FINAL / GENERATED |
| Observation unit | artifact |
| Numerator | correctness compile.ok == true |
| Denominator | artifacts with a correctness record |
| Applicability | all |
| Missingness / error states | every study artifact has a correctness record (verified); a missing one fails closed |
| Aggregation | count ratio; CI by benchmark-cluster bootstrap |
| Limits of interpretation | pipeline build with the frozen compiler; not a statement about other toolchains |

### Q06 `correctness_pass`

| field | definition |
| --- | --- |
| Meaning | the artifact passes the ParEval correctness tests (PRIMARY ENDPOINT) |
| Population | BASE / STEP / FINAL / GENERATED |
| Observation unit | artifact |
| Numerator | verdict == pass |
| Denominator | artifacts with a correctness verdict other than baseline_incompatible |
| Applicability | all |
| Missingness / error states | fail closed; baseline_incompatible excluded and reported |
| Aggregation | count ratio; CI by benchmark-cluster bootstrap |
| Limits of interpretation | one deterministic input draw per benchmark (unseeded rand); dense_la/00 carries the BL-01 tolerance disclosure (sensitivity SA1) |

### Q07 `correctness_pass_given_build`

| field | definition |
| --- | --- |
| Meaning | pass rate among built artifacts |
| Population | as Q06 |
| Observation unit | artifact |
| Numerator | verdict == pass |
| Denominator | compile.ok == true |
| Applicability | built artifacts |
| Missingness / error states | as Q06 |
| Aggregation | count ratio |
| Limits of interpretation | conditional - its denominator differs between populations |

### Q08 `correctness_verdict_distribution`

| field | definition |
| --- | --- |
| Meaning | distribution of the verdict vocabulary |
| Population | as Q06 |
| Observation unit | artifact |
| Numerator | artifacts per verdict |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | counts and shares |
| Limits of interpretation | - |

### Q09 `correctness_pass_raw_clean`

| field | definition |
| --- | --- |
| Meaning | proxy for unchanged raw-answer quality: pass rate among artifacts without any cleaning intervention (Q04 any_including_fence == false) |
| Population | BASE |
| Observation unit | artifact |
| Numerator | verdict == pass among raw-clean artifacts |
| Denominator | raw-clean artifacts |
| Applicability | raw-clean artifacts |
| Missingness / error states | as Q06 |
| Aggregation | count ratio |
| Limits of interpretation | selected subset (models that format cleanly are over-represented); descriptive |

### Q10 `correctness_pass_excluding_auto_closed`

| field | definition |
| --- | --- |
| Meaning | pass rate after removing artifacts whose braces the pipeline auto-closed (sensitivity SA2) |
| Population | BASE / FINAL |
| Observation unit | artifact |
| Numerator | verdict == pass and auto_closed == false |
| Denominator | artifacts with auto_closed == false |
| Applicability | all |
| Missingness / error states | as Q06 |
| Aggregation | count ratio |
| Limits of interpretation | sensitivity analysis |

### E01 `enhanced_pair_pass`

| field | definition |
| --- | --- |
| Meaning | end-to-end held-out pass rate over valid pairs |
| Population | ENH_PAIRS of BASE / STEP / FINAL / GENERATED |
| Observation unit | enhanced pair (inference: benchmark cluster) |
| Numerator | valid pairs with status pass |
| Denominator | valid pairs |
| Applicability | valid pairs |
| Missingness / error states | every artifact carries exactly its expected pair set (verified 109,200/109,200); a missing pair fails closed |
| Aggregation | ratio of sums (pairs are not independent); CI by benchmark-cluster bootstrap |
| Limits of interpretation | 20 specs per artifact; specs are benchmark-specific |

### E02 `enhanced_all_pass`

| field | definition |
| --- | --- |
| Meaning | the artifact passes every valid held-out spec (KEY SECONDARY ENDPOINT) |
| Population | BASE / STEP / FINAL / GENERATED |
| Observation unit | artifact |
| Numerator | artifacts with >= 1 valid pair and every valid pair pass |
| Denominator | artifacts with >= 1 valid pair |
| Applicability | artifacts with >= 1 valid pair (artifacts without any valid pair are counted separately) |
| Missingness / error states | fail closed |
| Aggregation | count ratio; CI by benchmark-cluster bootstrap |
| Limits of interpretation | strict endpoint |

### E03 `enhanced_status_distribution`

| field | definition |
| --- | --- |
| Meaning | distribution of pass, fail, build_failed, crash, timeout, runtime_error and the gated statuses |
| Population | ENH_PAIRS |
| Observation unit | enhanced pair |
| Numerator | pairs per status |
| Denominator | all pairs |
| Applicability | all pairs |
| Missingness / error states | fail closed |
| Aggregation | counts and shares |
| Limits of interpretation | pairs are clustered |

### E04 `enhanced_gated_share`

| field | definition |
| --- | --- |
| Meaning | share of oracle-side gated pairs (baseline_incompatible, numerically_unstable) |
| Population | ENH_PAIRS |
| Observation unit | enhanced pair |
| Numerator | gated pairs |
| Denominator | all pairs |
| Applicability | all pairs |
| Missingness / error states | fail closed |
| Aggregation | count ratio; also gated (benchmark, spec, execution_model) groups |
| Limits of interpretation | an oracle property, never a model failure |

### E05 `enhanced_all_pass_given_correctness_pass`

| field | definition |
| --- | --- |
| Meaning | held-out robustness of artifacts that pass the known tests |
| Population | BASE / FINAL |
| Observation unit | artifact |
| Numerator | E02 all-pass among correctness-pass artifacts |
| Denominator | correctness-pass artifacts with >= 1 valid pair |
| Applicability | correctness pass |
| Missingness / error states | as E02 |
| Aggregation | count ratio |
| Limits of interpretation | conditional on Q06 |

### S01 `static_tool_state_distribution`

| field | definition |
| --- | --- |
| Meaning | analysis states of each static tool (compiler, gcc_analyzer, clang_tidy, cppcheck, infer, parcoach, llov) |
| Population | BASE / FINAL / GENERATED |
| Observation unit | artifact x static tool |
| Numerator | artifacts per state |
| Denominator | artifacts |
| Applicability | all; NOT_APPLICABLE and ABSENT_INAPPLICABLE shown separately |
| Missingness / error states | an absent entry for an applicable tool fails closed |
| Aggregation | counts and shares |
| Limits of interpretation | COMPLETED does not imply defect-free code |

### S02 `static_definitive_coverage`

| field | definition |
| --- | --- |
| Meaning | share of applicable artifacts whose analysis is COMPLETED |
| Population | as S01 |
| Observation unit | artifact x static tool |
| Numerator | COMPLETED |
| Denominator | artifacts to which the tool applies |
| Applicability | applicable |
| Missingness / error states | as S01 |
| Aggregation | count ratio |
| Limits of interpretation | - |

### S03 `static_analysis_complete`

| field | definition |
| --- | --- |
| Meaning | every applicable static analysis tool (excluding the compiler) COMPLETED |
| Population | as S01 |
| Observation unit | artifact |
| Numerator | artifacts with all applicable tools COMPLETED |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | as S01 |
| Aggregation | count ratio |
| Limits of interpretation | - |

### D01 `dynamic_tool_state_distribution`

| field | definition |
| --- | --- |
| Meaning | analysis states of asan_ubsan, tsan, memcheck, must |
| Population | as S01 |
| Observation unit | artifact x dynamic tool |
| Numerator | artifacts per state |
| Denominator | artifacts |
| Applicability | all; NOT_APPLICABLE separately |
| Missingness / error states | fail closed |
| Aggregation | counts and shares |
| Limits of interpretation | dynamic tools observe only the ParEval inputs |

### D02 `dynamic_definitive_coverage`

| field | definition |
| --- | --- |
| Meaning | COMPLETED among applicable |
| Population | as S01 |
| Observation unit | artifact x dynamic tool |
| Numerator | COMPLETED |
| Denominator | applicable artifacts |
| Applicability | applicable |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | - |

### D03 `dynamic_analysis_complete`

| field | definition |
| --- | --- |
| Meaning | every applicable dynamic tool COMPLETED |
| Population | as S01 |
| Observation unit | artifact |
| Numerator | artifacts |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | - |

### F01 `static_verdict_three_state`

| field | definition |
| --- | --- |
| Meaning | DIRTY / CLEAN_COMPLETE / NO_FINDING_INCOMPLETE over the static analysis tools (finding_rules.analysis_verdict_three_state) |
| Population | BASE / STEP / FINAL |
| Observation unit | artifact |
| Numerator | artifacts per state |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | counts and shares; DIRTY share with CI |
| Limits of interpretation | a union over tools of different precision; low-confidence findings excluded |

### F02 `dynamic_verdict_three_state`

| field | definition |
| --- | --- |
| Meaning | as F01 over the dynamic tools |
| Population | BASE / STEP / FINAL |
| Observation unit | artifact |
| Numerator | artifacts per state |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | counts and shares |
| Limits of interpretation | ParEval inputs only |

### F03 `compile_error_any`

| field | definition |
| --- | --- |
| Meaning | the compiler tool reported a blocking compile error |
| Population | BASE / STEP / FINAL |
| Observation unit | artifact |
| Numerator | artifacts |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | - |

### F04 `low_confidence_any`

| field | definition |
| --- | --- |
| Meaning | >= 1 low-confidence finding (any tool) |
| Population | BASE / FINAL |
| Observation unit | artifact |
| Numerator | artifacts |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | low precision by validation (parcoach, MPI-Checker) |

### F05 `findings_by_tool_family`

| field | definition |
| --- | --- |
| Meaning | recorded findings per tool x family x kind (reported_blocking, low_confidence, non_blocking) |
| Population | BASE / FINAL / GENERATED |
| Observation unit | finding |
| Numerator | findings |
| Denominator | - (counts); additionally artifacts with >= 1 finding of the family per tool |
| Applicability | tool entries with findings |
| Missingness / error states | fail closed |
| Aggregation | counts per tool (never summed across tools) |
| Limits of interpretation | counts depend on tool coverage (S02) |

### F06 `tool_agreement`

| field | definition |
| --- | --- |
| Meaning | agreement of two tools on the presence of a reported blocking finding of one family class on artifacts where BOTH tools COMPLETED; predefined pairs: (tsan, llov) race on omp; (must, parcoach) mpi_usage/deadlock on mpi; (asan_ubsan, memcheck) memory on all; (gcc_analyzer, cppcheck) memory+null_deref+uninitialized on all |
| Population | GENERATED |
| Observation unit | artifact |
| Numerator | 2x2 table counts |
| Denominator | artifacts with both tools COMPLETED |
| Applicability | both tools applicable and COMPLETED |
| Missingness / error states | pairs without overlap are reported as not estimable |
| Aggregation | 2x2 counts, positive agreement, Cohen's kappa (descriptive, no test) |
| Limits of interpretation | low-confidence findings excluded; tools differ in precision and scope |

### R01 `repair_transition`

| field | definition |
| --- | --- |
| Meaning | per endpoint X in {Q06 correctness_pass, E02 enhanced_all_pass, F01 static three-state, F02 dynamic three-state}: transition of the SAME base cell from BASE to STEP/FINAL |
| Population | BASE paired with STEP[v][k] and FINAL[v] |
| Observation unit | base cell |
| Numerator | cells per (base state, final state) |
| Denominator | base cells (E02: cells with >= 1 valid pair; identical for base and final because gates are spec-level) |
| Applicability | all base cells |
| Missingness / error states | fail closed |
| Aggregation | transition matrices |
| Limits of interpretation | - |

### R02 `repair_success_rate`

| field | definition |
| --- | --- |
| Meaning | a SUCCESSFUL REPAIR is an improvement on an explicit endpoint for the same base cell: base not pass -> final pass (Q06), resp. base not all-pass -> final all-pass (E02) |
| Population | as R01 |
| Observation unit | base cell |
| Numerator | improved cells |
| Denominator | cells failing the endpoint at baseline |
| Applicability | base-failing cells |
| Missingness / error states | fail closed |
| Aggregation | count ratio; CI by benchmark-cluster bootstrap |
| Limits of interpretation | conditional on the baseline failure set, which differs between models; terminal statuses play no role |

### R03 `regression_rate`

| field | definition |
| --- | --- |
| Meaning | base pass -> final not pass on the endpoint |
| Population | as R01 |
| Observation unit | base cell |
| Numerator | regressed cells |
| Denominator | cells passing the endpoint at baseline |
| Applicability | base-passing cells |
| Missingness / error states | fail closed |
| Aggregation | count ratio; CI |
| Limits of interpretation | trajectories that never left iteration 0 cannot regress |

### R04 `net_gain`

| field | definition |
| --- | --- |
| Meaning | rate(FINAL[v]) - rate(BASE) on the identical cohort (= (improved - regressed) / cells) |
| Population | as R01 |
| Observation unit | base cell |
| Numerator | improved - regressed |
| Denominator | cells |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | paired difference; CI by benchmark-cluster bootstrap; PRIMARY FAMILY |
| Limits of interpretation | - |

### R05 `variant_difference`

| field | definition |
| --- | --- |
| Meaning | rate(FINAL[v1]) - rate(FINAL[v2]) on the identical cohort |
| Population | FINAL[v1] vs FINAL[v2] paired by base cell |
| Observation unit | base cell |
| Numerator | sum over cells of (y_v1 - y_v2) |
| Denominator | cells |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | paired difference; CI by benchmark-cluster bootstrap; PRIMARY FAMILY |
| Limits of interpretation | variants differ in loop length as well as in feedback content |

### R06 `stop_status_distribution`

| field | definition |
| --- | --- |
| Meaning | terminal status x final iteration per variant |
| Population | trajectories |
| Observation unit | trajectory |
| Numerator | trajectories |
| Denominator | trajectories |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | counts and shares |
| Limits of interpretation | descriptive - stop statuses are NOT success metrics |

### R07 `budget_exhaustion_rate`

| field | definition |
| --- | --- |
| Meaning | the loop used the whole iteration budget (stopped_budget) |
| Population | trajectories |
| Observation unit | trajectory |
| Numerator | stopped_budget |
| Denominator | trajectories |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | - |

### R08 `analysis_incomplete_stop_rate`

| field | definition |
| --- | --- |
| Meaning | the loop stopped because analyses were incomplete (non-model terminal status) |
| Population | trajectories |
| Observation unit | trajectory |
| Numerator | stopped_analysis_incomplete |
| Denominator | trajectories |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | not a model outcome |

### R09 `repaired_share`

| field | definition |
| --- | --- |
| Meaning | trajectories that requested at least one repair (final_iteration >= 1) |
| Population | trajectories |
| Observation unit | trajectory |
| Numerator | trajectories |
| Denominator | trajectories |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | count ratio |
| Limits of interpretation | - |

### R10 `iterations_used`

| field | definition |
| --- | --- |
| Meaning | mean final_iteration |
| Population | trajectories |
| Observation unit | trajectory |
| Numerator | sum of final_iteration |
| Denominator | trajectories |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | mean |
| Limits of interpretation | bounded by 2 |

### C01 `repair_requests`

| field | definition |
| --- | --- |
| Meaning | repair generation records (one per candidate) and request rounds (request_rounds.json) |
| Population | REPAIR_CANDIDATES |
| Observation unit | repair generation |
| Numerator | records / rounds |
| Denominator | - (counts); per trajectory and per improved cell |
| Applicability | repair candidates |
| Missingness / error states | a missing generation record fails closed |
| Aggregation | counts |
| Limits of interpretation | rounds include provider retries |

### C02 `tokens`

| field | definition |
| --- | --- |
| Meaning | provider-normalized input, output and reasoning tokens (usage_normalized) |
| Population | BASE / REPAIR_CANDIDATES |
| Observation unit | generation |
| Numerator | token sums |
| Denominator | generations (per-request means); reasoning tokens only over generations where the provider reports the field |
| Applicability | all generations |
| Missingness / error states | reasoning_tokens null = provider reports no field (distinct from 0); coverage reported |
| Aggregation | sums, means, medians |
| Limits of interpretation | providers count tokens differently; reasoning settings differ per model (disclosure) |

### C03 `repair_latency`

| field | definition |
| --- | --- |
| Meaning | direct-mode request wall time (status.duration_seconds, timing_mode direct) |
| Population | REPAIR_CANDIDATES |
| Observation unit | generation |
| Numerator | - |
| Denominator | direct-mode generations |
| Applicability | timing_mode == direct only; batch spans are queue time and are never used |
| Missingness / error states | null durations excluded and counted |
| Aggregation | median and p95 |
| Limits of interpretation | network and provider load; spread over days |

### C04 `tool_runtime`

| field | definition |
| --- | --- |
| Meaning | per tool duration_seconds |
| Population | GENERATED |
| Observation unit | artifact x tool |
| Numerator | - |
| Denominator | tool entries with a numeric duration, excluding TIMEOUT entries |
| Applicability | ran tools |
| Missingness / error states | TIMEOUT entries reported as their own share (their duration is the limit) |
| Aggregation | median and p95 per tool x execution model; reported WITH and WITHOUT entries above the 3,600 s reporting threshold (the documented Infer outlier); raw data unchanged, no standby estimate subtracted |
| Limits of interpretation | wall-clock, host-dependent |

### C05 `gain_per_effort`

| field | definition |
| --- | --- |
| Meaning | improved cells (R02 numerator, Q06) per 1,000,000 repair output tokens and per 100 repair requests |
| Population | FINAL[v] vs BASE |
| Observation unit | variant x model |
| Numerator | improved cells |
| Denominator | repair output tokens / requests of the variant |
| Applicability | variants with >= 1 repair request |
| Missingness / error states | - |
| Aggregation | ratio (descriptive) |
| Limits of interpretation | descriptive only; no ranking |

### G01 `heldout_robustness_of_repairs`

| field | definition |
| --- | --- |
| Meaning | share of correctness-repaired cells whose final artifact is enhanced all-pass, compared with the enhanced all-pass share of cells that passed at baseline (E05 BASE) |
| Population | base cells improved on Q06 under variant v |
| Observation unit | base cell |
| Numerator | improved cells with final E02 all-pass |
| Denominator | improved cells with >= 1 valid pair |
| Applicability | Q06-improved cells |
| Missingness / error states | fail closed |
| Aggregation | count ratio; difference to the baseline-pass reference with CI |
| Limits of interpretation | small denominators per model; descriptive per model |

### G02 `trajectory_parEval_vs_heldout`

| field | definition |
| --- | --- |
| Meaning | Q06 and E02/E01 over steps per variant (overfitting check, goal G3) |
| Population | STEP[v][k], k = 0, 1, 2 |
| Observation unit | base cell |
| Numerator | per step |
| Denominator | identical cohort |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | rates with CI per step |
| Limits of interpretation | - |

## Sensitivity analyses

- **SA1** `exclude_dense_la_00`: repeat Q06/R02/R04/R05 without benchmark dense_la/00_dense_la_lu_decomp (BL-01 tolerance disclosure)
- **SA2** `exclude_auto_closed`: Q10: repeat Q06 without artifacts whose braces the pipeline auto-closed
- **SA3** `per_block`: every headline estimate per block (pilot, full_ext) next to the composite
- **SA4** `runtime_outlier`: C04 with and without tool entries above 3,600 s

## Statistics

- **Inference unit**: benchmark (cluster): all artifacts, pairs, models, execution models, variants and iterations of one benchmark are resampled together
- **bootstrap.method**: nonparametric cluster bootstrap, percentile intervals
- **bootstrap.stratified_by**: block (pilot benchmarks resampled among the 12 pilot benchmarks, full_ext among its 48)
- **bootstrap.confidence_level**: 0.95
- **bootstrap.replicates_primary**: 10000
- **bootstrap.replicates_descriptive**: 2000
- **bootstrap.seed**: 20261017
- **bootstrap.rng**: Python random.Random(seed); one shared set of replicate weights per (seed, replicates) so paired estimates share resamples
- **Point estimates**: ratio of sums over the observation units of the population (not means of per-benchmark rates)
- **Paired differences**: computed per base cell and aggregated as ratio of sums; bootstrap over benchmarks keeps the pairing
- **tests.primary_family**: R04 net_gain (3 variants) and R05 variant_difference (3 pairs) for the endpoints Q06 and E02 on the composite cohort: 12 hypotheses H0: difference = 0
- **tests.p_values**: two-sided bootstrap p = min(1, 2 * min(share of replicate differences <= 0, share >= 0)) with replicates_primary
- **tests.multiplicity**: Holm step-down at alpha 0.05 over the 12 primary hypotheses
- **tests.everything_else**: descriptive estimates with unadjusted 95% CIs, labelled as such; no further tests
- **Small-cluster warning**: pilot block has 12 clusters: percentile intervals are approximate; flagged in every pilot table
- **Not done**: no aggregate model score; no model ranking; no tests treating the 109,200 enhanced pairs or the 5,460 artifacts as independent

## Reporting

- **every_table_states**: population, observation unit, numerator and denominator per cell, CI method where shown, block
- **pilot_label**: pilot_002 / Pilotexperiment (12 benchmarks x 3 execution models x 11 models, 1 sample per prompt)
- **disclosures**: thesis/evaluation/closure/study_closure_001/disclosures.md (register) and the 11 policy sources of thesis/evaluation/pilot_002_publication_policy.json
