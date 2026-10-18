# Methodology addendum study_analysis_001.addendum_1 (`study_analysis_methodology_addendum.v1`, DECLARED_AFTER_DRY_RUN)

Generated from `thesis/study_analysis/methodology_addendum.json` by `thesis/study_analysis/methodology_doc.py` - do not edit by hand. Declared on 2026-10-17, AFTER a non-productive dry run and its independent review.

Amends `thesis/study_analysis/methodology.json` (canonical sha256 `cb34143728ceaa08befe91100c741a6d95df9b39ebb8b44c4274a9d12acb20dc`). The frozen methodology stays unchanged: its definitions, populations, primary hypothesis family and statistics protocol are NOT modified. This addendum was declared AFTER a non-productive dry run and an independent review of it; every item below is labelled post-freeze. Its metrics are descriptive sensitivity analyses (no hypothesis tests, no Holm), its caveats and table notes are disclosures. The thesis text must present addendum results as post-hoc.

Trigger: independent verification of the dry run (raw recomputation PASS; statistics, presentation and adversarial methodology review findings).

## Post-freeze descriptive metrics

### X01 `paired_auto_closed_sensitivity` (post-freeze, descriptive)

| field | definition |
| --- | --- |
| Meaning | R04 net gain and R05 variant difference for Q06 and E02 on the cohort of base cells none of whose artifacts (base and every iteration of all three trajectories) was brace-auto-closed by the pipeline (clean_auto_closed) |
| Population | FINAL[v] vs BASE and FINAL[v1] vs FINAL[v2], paired |
| Observation unit | base cell |
| Numerator | as R04 / R05 on the restricted cohort |
| Denominator | restricted cohort cells (E02: with >= 1 valid pair) |
| Applicability | base cells without any auto-closed artifact |
| Missingness / error states | fail closed |
| Aggregation | paired differences, ratio of sums; descriptive cluster-bootstrap CI (replicates_descriptive) |
| Limits of interpretation | post-freeze and descriptive; the exclusion depends on post-repair artifacts, i.e. it selects on a repair outcome - it shows sensitivity, not a corrected effect; reported next to the frozen R04/R05, never instead of them |

### X02 `three_state_tool_verdict_reading` (post-freeze, descriptive)

| field | definition |
| --- | --- |
| Meaning | the static three-state verdict F01 recomputed under the tool-verdict reading: reported blocking findings count only from applicable tools whose state is COMPLETED or PARTIAL (the states for which framework.tool_verdict can yield a defect verdict); findings recorded under TIMEOUT, TOOL_ERROR or NOT_ANALYZED entries do not make an artifact DIRTY |
| Population | BASE / FINAL[v] |
| Observation unit | artifact |
| Numerator | artifacts per state (DIRTY, CLEAN_COMPLETE, NO_FINDING_INCOMPLETE) |
| Denominator | artifacts |
| Applicability | all |
| Missingness / error states | fail closed |
| Aggregation | counts and shares; descriptive CI for the DIRTY share; plus the count of artifacts that are DIRTY under F01 but not under this reading |
| Limits of interpretation | post-freeze sensitivity of the F01 rule conflict documented in normalize.py (170 artifacts in the dry run, all build_failed, clang_tidy NOT_ANALYZED entries) |

### X03 `dirty_composition` (post-freeze, descriptive)

| field | definition |
| --- | --- |
| Meaning | composition of the F01 DIRTY verdicts: per static analysis tool the artifacts that are DIRTY ONLY through that tool; per (tool, check_id) for the 10 check ids with most reported blocking findings per tool: reported blocking findings and artifacts with >= 1 such finding |
| Population | BASE |
| Observation unit | artifact / finding |
| Numerator | artifacts / findings |
| Denominator | DIRTY artifacts (only-via share); BASE artifacts to which the tool applies (check-id artifact share) |
| Applicability | BASE |
| Missingness / error states | fail closed |
| Aggregation | counts and shares, no CI |
| Limits of interpretation | post-freeze descriptive; DIRTY means at least one finding the frozen tool configuration marks blocking, not a confirmed defect |

### X04 `statically_clean_but_incorrect` (post-freeze, descriptive)

| field | definition |
| --- | --- |
| Meaning | goal G4 quantity: among FINAL artifacts failing Q06, the share whose static verdict F01 is CLEAN_COMPLETE (and, separately, NO_FINDING_INCOMPLETE) - code the static tools pass but the tests reject |
| Population | FINAL[v] |
| Observation unit | artifact |
| Numerator | FINAL artifacts with Q06 not pass and F01 == CLEAN_COMPLETE (resp. NO_FINDING_INCOMPLETE) |
| Denominator | FINAL artifacts with Q06 not pass (verdict not baseline_incompatible) |
| Applicability | all variants; static_feedback is the reference case of the design document |
| Missingness / error states | fail closed |
| Aggregation | count ratio; descriptive CI |
| Limits of interpretation | post-freeze descriptive (the frozen methodology named the goal but defined no metric) |

### X05 `iterations_to_clean` (post-freeze, descriptive)

| field | definition |
| --- | --- |
| Meaning | goal G4 quantity: final_iteration of the trajectories that ended with the loop's own clean stop (stopped_clean or stopped_tests_pass): mean and distribution over iterations 0, 1, 2 |
| Population | trajectories |
| Observation unit | trajectory |
| Numerator | sum of final_iteration (mean) / trajectories per iteration (distribution) |
| Denominator | trajectories ending stopped_clean or stopped_tests_pass |
| Applicability | trajectories with a clean stop |
| Missingness / error states | fail closed |
| Aggregation | mean and counts, no CI |
| Limits of interpretation | post-freeze descriptive; a clean stop is the loop's own criterion, not a success metric |

### X06 `joint_parEval_heldout_transitions` (post-freeze, descriptive)

| field | definition |
| --- | --- |
| Meaning | joint transition of the same base cell on Q06 and E02 (e.g. Q06 not_pass->pass with E02 not_all_pass->not_all_pass: repaired on the known tests but not on the held-out specs) |
| Population | BASE paired with FINAL[v] |
| Observation unit | base cell |
| Numerator | cells per (Q06 transition, E02 transition) |
| Denominator | paired cohort cells with >= 1 valid enhanced pair |
| Applicability | all base cells |
| Missingness / error states | fail closed |
| Aggregation | counts and shares, no CI |
| Limits of interpretation | post-freeze descriptive; E02 counts build failures, so E02 and Q06 changes are largely the same cells |

## Estimate fields

- **ci_degenerate**: true for every estimate whose percentile interval has zero width (ci_low == ci_high): every supporting cluster has the same value (a share at 0% or 100%, or a difference of 0), so the bootstrap cannot express sampling uncertainty; tables mark such intervals and never present them as evidence of certainty
- **p_resolution**: primary family only: the smallest positive two-sided bootstrap p-value, 2 / replicates_primary; a p_value of 0 means p < p_resolution
- **p_holm_resolution**: primary family only: the Holm-adjusted resolution, the running maximum over the Holm order of (m - rank + 1) * p_resolution; a p_holm of 0 means p_holm < p_holm_resolution

## Interpretive caveats (must be stated in the thesis text)

- **IC1** (applies to `Q06`, `R02`, `R04`, `R05`, `T5_repair_by_model`, `T9_primary_tests`): Q06 is in-sample for test_feedback and combined_feedback: their loops see the ParEval test verdict and stop when it passes (every stopped_tests_pass trajectory is a Q06 pass), so they optimise the endpoint; for static_feedback Q06 is out-of-sample (measured once in phase 2, never seen by the loop). The variants therefore differ in trigger and stop rules, not only in feedback content; test_feedback cannot regress on Q06 by construction.
- **IC2** (applies to `E02`, `R04`, `R05`, `T5b_repair_by_model_heldout`, `T9_primary_tests`, `G01`): E02 is not an independent confirmation of Q06 gains: it counts build failures, and most E02 improvements are the same cells as the Q06 improvements; the held-out signal proper is the joint transition X06 (e.g. Q06 repaired but E02 still failing) and G01.
- **IC3** (applies to `G01`, `T7_heldout`): G01 compares Q06-repaired cells (cells that failed at baseline and are harder) with cells that passed at baseline (E05 BASE); its differences mix cell difficulty with overfitting, and its cohorts differ per variant.
- **IC4** (applies to `F01`, `R01`, `T2d_initial_heldout_composite`, `T2e_initial_heldout_pilot`, `T2f_initial_heldout_full_ext`, `T8_execution_models`): DIRTY means at least one finding the frozen tool configuration marks blocking (dominated by clang-tidy bugprone heuristics, see X03), not a confirmed defect; under the frozen rule findings of entries in analysis-gap states count (sensitivity X02).
- **IC5** (applies to `R05`, `T9_primary_tests`, `T9b_primary_by_block`): The composite primary estimates pool the pilot (12 clusters) and full_ext (48 clusters) blocks; the per-block estimates (T9b) are descriptive, the pilot ones approximate; a composite difference need not hold in both blocks.
- **IC6** (applies to `R05`, `static_feedback`): static_feedback repair triggers are dominated by clang-tidy bugprone findings and, on MPI, by low-confidence hints (design document: no trustworthy static MPI tool exists); static_feedback results measure this frozen blocking-set configuration, not static analysis in general.
- **IC7** (applies to `Q04`, `Q10`, `X01`, `T10_sensitivity`): The pipeline auto-closes unbalanced braces before measurement; many static_feedback regressions are base-pass cells whose final repair answer was auto-closed and then failed to build (X01). Q10 (frozen SA2) is unpaired and compares different cohorts.

## Mandatory table and figure notes

- **BL01** (every table or figure with a pilot or composite Q06 / E02 aggregate): Includes dense_la/00 (BL-01 tolerance convention: possible false FAIL verdicts; disclosure-bearing aggregate); sensitivity SA1 in T10.
- **REASONING** (every per-model table and figure): Reasoning settings differ between models and are not equalised (see the closure disclosure register, item reasoning_policy_differences); some providers report no reasoning-token field.
- **EFFECTIVE_STATES** (T3_tool_coverage, F4_tool_states): Tool states are the effective states (framework.effective_tool_state): a front-end TOOL_ERROR or PARTIAL entry of an artifact whose build failed counts as NOT_ANALYZED (dataset_disclosures.effective_state_overrides); the closure register reports the raw states.
- **DEGENERATE_CI** (every table whose CI is degenerate): Degenerate percentile interval (zero width): every supporting cluster has the same value (a share at 0% or 100%, or a difference of 0); the bootstrap cannot express the sampling uncertainty.

## Disclosures outside the analysis outputs

- thesis/evaluation/closure/study_closure_001/disclosures.md (17-item register)
- thesis/evaluation/pilot_002_publication_policy.json (11 mandatory disclosure sources, pilot label)
- the 62 answers of the aborted parent repair full_ext_001__static_feedback__iter1 were discarded before any analysis (assembly only); their samples were regenerated by full_ext_recovery_001, so those openai_gpt55 static_feedback iteration-1 candidates are second draws

## Goals without a frozen metric

- G4 'statically clean but incorrect' rate of static_feedback -> X04
- G4 iterations-to-clean -> X05
