# study_analysis_001 - final scientific analysis outputs

Mode: formal. Status: PASS. Results sha256 `12fa57f4518d6ad0bade4fc911fe8b49b6ec6cdb4d08417039a1df96c07d759a`.

Every number below is computed by `thesis/study_analysis` from the formally verified study (closure `c880da4144dc980ea8b6fc9ce66c3dbc04c2fa4f37be71b9dfeae81216c825c5`, composite `953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0`) under the frozen methodology `cb34143728ceaa08befe91100c741a6d95df9b39ebb8b44c4274a9d12acb20dc` (status FROZEN_BEFORE_AGGREGATION) and its post-freeze addendum `348b1516b8c194012323b1fcc9b5fbd94604e9866a1b6fd5dcd8ea30af002486` (status DECLARED_AFTER_DRY_RUN).

Pilot results carry the label: *pilot_002 / Pilotexperiment (12 benchmarks x 3 execution models x 11 models, 1 sample per prompt)*.

## How to read the results

- The primary hypothesis family (12 hypotheses, Holm) and every frozen metric (Q, E, S, D, F, R, C, G) follow `methodology.json`, frozen before any aggregation.
- Metrics X01-X06 and the interpretive caveats IC1-IC7 come from `methodology_addendum.json`, declared AFTER a non-productive dry run and its independent review: they are post-hoc, descriptive sensitivity analyses (no tests) and must be presented as such.
- Terminal loop statuses (stopped_clean, stopped_tests_pass, ...) are trajectory facts, never repair successes; a successful repair is an improvement of the same base cell on an explicit endpoint (R02).
- 95% intervals are stratified benchmark-cluster bootstrap percentile intervals; pilot intervals rest on 12 clusters (approximate); intervals marked as degenerate have zero width because every supporting cluster has the same value (a share at 0% or 100%, or a difference of 0).

## Mandatory disclosures

- **BL01** (every table or figure with a pilot or composite Q06 / E02 aggregate): Includes dense_la/00 (BL-01 tolerance convention: possible false FAIL verdicts; disclosure-bearing aggregate); sensitivity SA1 in T10.
- **REASONING** (every per-model table and figure): Reasoning settings differ between models and are not equalised (see the closure disclosure register, item reasoning_policy_differences); some providers report no reasoning-token field.
- **EFFECTIVE_STATES** (T3_tool_coverage, F4_tool_states): Tool states are the effective states (framework.effective_tool_state): a front-end TOOL_ERROR or PARTIAL entry of an artifact whose build failed counts as NOT_ANALYZED (dataset_disclosures.effective_state_overrides); the closure register reports the raw states.
- **DEGENERATE_CI** (every table whose CI is degenerate): Degenerate percentile interval (zero width): every supporting cluster has the same value (a share at 0% or 100%, or a difference of 0); the bootstrap cannot express the sampling uncertainty.
- **IC1**: Q06 is in-sample for test_feedback and combined_feedback: their loops see the ParEval test verdict and stop when it passes (every stopped_tests_pass trajectory is a Q06 pass), so they optimise the endpoint; for static_feedback Q06 is out-of-sample (measured once in phase 2, never seen by the loop). The variants therefore differ in trigger and stop rules, not only in feedback content; test_feedback cannot regress on Q06 by construction.
- **IC2**: E02 is not an independent confirmation of Q06 gains: it counts build failures, and most E02 improvements are the same cells as the Q06 improvements; the held-out signal proper is the joint transition X06 (e.g. Q06 repaired but E02 still failing) and G01.
- **IC3**: G01 compares Q06-repaired cells (cells that failed at baseline and are harder) with cells that passed at baseline (E05 BASE); its differences mix cell difficulty with overfitting, and its cohorts differ per variant.
- **IC4**: DIRTY means at least one finding the frozen tool configuration marks blocking (dominated by clang-tidy bugprone heuristics, see X03), not a confirmed defect; under the frozen rule findings of entries in analysis-gap states count (sensitivity X02).
- **IC5**: The composite primary estimates pool the pilot (12 clusters) and full_ext (48 clusters) blocks; the per-block estimates (T9b) are descriptive, the pilot ones approximate; a composite difference need not hold in both blocks.
- **IC6**: static_feedback repair triggers are dominated by clang-tidy bugprone findings and, on MPI, by low-confidence hints (design document: no trustworthy static MPI tool exists); static_feedback results measure this frozen blocking-set configuration, not static analysis in general.
- **IC7**: The pipeline auto-closes unbalanced braces before measurement; many static_feedback regressions are base-pass cells whose final repair answer was auto-closed and then failed to build (X01). Q10 (frozen SA2) is unpaired and compares different cohorts.
- thesis/evaluation/closure/study_closure_001/disclosures.md (17-item register)
- thesis/evaluation/pilot_002_publication_policy.json (11 mandatory disclosure sources, pilot label)
- the 62 answers of the aborted parent repair full_ext_001__static_feedback__iter1 were discarded before any analysis (assembly only); their samples were regenerated by full_ext_recovery_001, so those openai_gpt55 static_feedback iteration-1 candidates are second draws

## LaTeX usage

- `tables/preamble.tex` lists the packages the tables and figures need (booktabs, longtable, pgfplots compat 1.18, T1 font encoding); wide tables need landscape pages (pdflscape or lscape) - see the comments in `tables/preamble.tex` and in each table file.
- Figures: `\begin{figure}\centering\input{figures/<id>.tex}\input{figures/<id>.caption.tex}\end{figure}`; SVG files are previews of the same data.

## Contents

- `manifest.json` / `manifest_start.json`: input manifest (every input file with its sha256) at the end and the start of the run
- `preflight.json`, `validation_report.json` / `.md`: preconditions and the independent validation
- `methodology.json` / `METHODOLOGY.md`, `methodology_addendum.json` / `METHODOLOGY_ADDENDUM.md`
- `results.json`: identities, counts, the primary hypothesis family and the output index; `results/estimates.json.gz` / `.csv.gz`: every estimate
- `data/`: the normalized tables (CSV; findings and enhanced pairs gzip-compressed)
- `tables/<id>.{csv,json,tex}` and `figures/<id>.{csv,tex,caption.tex,svg}`

## Tables

- `T1_inventory`: Study inventory per block (population: BASE, REPAIR_CANDIDATES, GENERATED, TRAJECTORIES, ENH_PAIRS(GENERATED) (counts))
- `T1b_provenance`: Evidence owners and input identities (population: GENERATED (evidence records))
- `T2a_initial_quality_composite`: Initial code quality (BASE), block composite (population: BASE (iteration-0 artifacts of the base cells))
- `T2b_initial_quality_pilot`: Initial code quality (BASE), block pilot (population: BASE (iteration-0 artifacts of the base cells))
- `T2c_initial_quality_full_ext`: Initial code quality (BASE), block full_ext (population: BASE (iteration-0 artifacts of the base cells))
- `T2d_initial_heldout_composite`: Initial held-out pass and analysis verdicts (BASE), block composite (population: BASE (iteration-0 artifacts of the base cells); E01/E04: ENH_PAIRS(BASE))
- `T2e_initial_heldout_pilot`: Initial held-out pass and analysis verdicts (BASE), block pilot (population: BASE (iteration-0 artifacts of the base cells); E01/E04: ENH_PAIRS(BASE))
- `T2f_initial_heldout_full_ext`: Initial held-out pass and analysis verdicts (BASE), block full_ext (population: BASE (iteration-0 artifacts of the base cells); E01/E04: ENH_PAIRS(BASE))
- `T3_tool_coverage`: Analysis tool states and definitive coverage per tool and block (population: GENERATED (state shares; diagnostic only; never mixed with FINAL or STEP rates); BASE and GENERATED (coverage))
- `T4_findings`: Recorded findings per tool and finding family (population: BASE and GENERATED (GENERATED: diagnostic only; never mixed with FINAL or STEP rates))
- `T4b_tool_agreement`: Agreement of predefined tool pairs (population: GENERATED (diagnostic only; never mixed with FINAL or STEP rates))
- `T5_repair_by_model`: Repair outcome per model and variant (Q06 correctness pass) (population: BASE paired with FINAL[v] (identical base-cell cohort))
- `T5b_repair_by_model_heldout`: Repair outcome per model and variant (E02 enhanced all-pass) (population: BASE paired with FINAL[v] (identical base-cell cohort))
- `T6_stops_effort`: Loop stops per variant and block (population: TRAJECTORIES)
- `T6b_effort`: Repair effort per variant and block (population: REPAIR_CANDIDATES (diagnostic only; C02 also BASE, C05 FINAL[v] vs BASE))
- `T7a_heldout_rates`: Held-out (enhanced) and ParEval pass rates over the repair steps (population: BASE, STEP[v][k], FINAL[v]; E01: ENH_PAIRS(BASE) / ENH_PAIRS(FINAL))
- `T7b_heldout_transitions`: Held-out (enhanced) transitions of the repairs (population: BASE paired with FINAL[v]; G01: base cells improved on Q06)
- `T7c_joint_transitions`: POST-FREEZE (addendum_1, descriptive): Joint Q06 / E02 transitions of the same base cell (X06) (population: BASE paired with FINAL[v] (cells in both paired cohorts))
- `T8_execution_models`: Outcomes per execution model and variant (population: BASE paired with FINAL[v])
- `T9_primary_tests`: Primary hypotheses (Holm-adjusted) (population: BASE paired with FINAL[v]; FINAL[v1] vs FINAL[v2] (composite))
- `T9b_primary_by_block`: Primary hypotheses per block (descriptive) (population: BASE paired with FINAL[v]; FINAL[v1] vs FINAL[v2] (per block))
- `T10_sensitivity`: Sensitivity analyses SA1 (without BL-01 benchmark), X01 (post-freeze, without auto-closed cells) and SA2 (Q10) (population: BASE paired with FINAL[v]; FINAL[v1] vs FINAL[v2]; SA1 without the BL-01 benchmark cells; X01 without base cells with an auto-closed artifact)
- `T11_runtime`: Tool runtime per tool and execution model (SA4) (population: GENERATED (diagnostic only; never mixed with FINAL or STEP rates))
- `T12_addendum`: POST-FREEZE (addendum_1, descriptive): Static DIRTY under the tool-verdict reading (X02 vs F01) and statically clean but incorrect artifacts (X04) (population: BASE / FINAL[v])
- `T12b_dirty_checks`: POST-FREEZE (addendum_1, descriptive): Composition of the static DIRTY verdicts (X03) (population: BASE)
- `T12c_iterations_to_clean`: POST-FREEZE (addendum_1, descriptive): Iterations to a clean stop (X05) (population: TRAJECTORIES (ending stopped_clean / stopped_tests_pass))

## Figures

- `F1_correctness_before_after`: Correctness before and after repair (Q06, BASE vs FINAL)
- `F2_heldout_over_iterations`: ParEval vs held-out pass rate over repair steps
- `F3_heatmap_model_variant`: Net correctness gain per model and variant (R04, Q06)
- `F4_tool_states`: Analysis tool states (S01/D01, GENERATED - diagnostic)
- `F5_gain_vs_effort`: Net correctness gain vs repair output tokens

