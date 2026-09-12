# E3.2 — Evidence Reconstruction, Current-vs-Historical Measurement, Re-Freeze Analysis & Author Decision Package

Source HEAD `c7a6dbc41d9c54786ec3c23db451d35f756054c1`. Evidence artifact `thesis/evaluation/e3_2_evidence.json` (schema `e3_2_evidence.v1`, sha256 `5de7565669a31e69d908b5048065805cab8f601b6cac90434f19fc81e88a3c16`); decision artifact `thesis/evaluation/e3_2_decisions.json` (schema `e3_2_decisions.v1`, sha256 `a1bc609e52eeffe707667b1a553c61eb8586796ca0c07d3810411a2cf7b3aa65`). Nothing under `thesis/results` was modified; no generation, no LLM/API call, no repair loop was run.

## 1. Inventory (no target number)

Inclusion criterion: an item is E3.2-relevant when a git-tracked report or artifact explicitly defers a DECISION whose outcome would change a pilot_002 methodology condition (prompt, enhanced policy/specs, static/repair condition, tool scope, hash rule) or require a pilot_001 disclosure, AND the item is not on the task's explicit separate-findings list; backlog feature waves without a provisional frozen value are listed under considered_not_e3_2

| | |
|---|---|
| `E3_2_ITEM_COUNT_FOUND` | 12 |
| `E3_2_ITEM_COUNT_EXPECTED_FROM_PRIOR_SUMMARY` | 7 |
| `E3_2_ITEM_COUNT_MATCHES_PRIOR_SUMMARY` | false |
| prior-summary candidates not repo-verified | none |
| additional repo-derived items | E32-08, E32-09, E32-10, E32-11, E32-12 |

12 found vs 7 in the prior summary: every prior candidate is repo-verified (7/7); the geometry precondition candidate covers geometry/12 as well (same decision fork, n >= 3) and the catalog-text candidate covers 12/13/14 and scan/34 (same string family); five further deferred decisions with repo sources were found: the assembly writer newline pin, which the adversarial review turned into a clang_tidy location-identity defect (E32-08), the Phase-0 gcc_analyzer FP-class demotion (E32-09), search/37 n = 0 (E32-10), the separately flagged malloc-leak demotion (E32-11, found by the review of E32-09) and search/35's un-normalized validation attempts (E32-12, found by the review of the inventory boundary)

| id | item | result impact | pilot_002 configuration | pilot_001 comparability | rollup | author decision |
|---|---|---|---|---|---|---|
| E32-01 | OMPI_SKIP_MPICXX for gcc_analyzer (MPI) | MULTIPLE | DECISION_PENDING_AUTHOR | A: UNAFFECTED (cells keep the recorded clas / B: INCOMPARABLE for the gcc_analyzer MPI ce | DECISION_PENDING_AUTHOR | yes |
| E32-02 | infer configured scope on OpenMP | COVERAGE | DECISION_PENDING_AUTHOR | A: UNAFFECTED incrementally (infer/omp cell / B: UNAFFECTED incrementally for the infer/o | DECISION_PENDING_AUTHOR | yes |
| E32-03 | geometry/12,13,14 degenerate-input contract: prompt convention (return 0) vs precondition + min_size | NONE | DECISION_PENDING_AUTHOR | UNAFFECTED | DECISION_PENDING_AUTHOR | yes |
| E32-04 | catalog e2b_size_zero reason strings superseded by the prompt sentences (geometry/12,13,14; scan/34) | METADATA_ONLY | FREEZE_AS_IS | UNAFFECTED | NO_METHODICAL_IMPACT | no |
| E32-05 | raw-byte (checkout-dependent) hash rule of the OLD condition versions | NONE | FREEZE_AS_IS | UNAFFECTED | NO_METHODICAL_IMPACT | no |
| E32-06 | not_applicable_entry written without fingerprint / outside the per-tool merge check (528 pilot_001 entries) | METADATA_ONLY | FREEZE_AS_IS | UNAFFECTED | NO_METHODICAL_IMPACT | no |
| E32-07 | static-base / LLM spec_key collision in the enhanced mutation frontier | NONE | DECISION_PENDING_AUTHOR | A: UNAFFECTED incrementally (enhanced cells / B: UNAFFECTED incrementally for the same re | DECISION_PENDING_AUTHOR | yes |
| E32-08 | assembly writer newline policy HOST_DEPENDENT x clang_tidy byte-offset conversion: CRLF sources shift clang_tidy line/column identities | MULTIPLE | DECISION_PENDING_AUTHOR | LIMITED_WITH_DISCLOSURE | DECISION_PENDING_AUTHOR | yes |
| E32-09 | gcc_analyzer FP-class demotion (Phase-0 predicate T1-T5) designed, not applied | MULTIPLE | DECISION_PENDING_AUTHOR | A: UNAFFECTED (gcc_analyzer cells keep COMP / B: LIMITED_WITH_DISCLOSURE for every gcc_an | DECISION_PENDING_AUTHOR | yes |
| E32-10 | search/37 n = 0 deliberately not decided (technically excluded) | NONE | FREEZE_AS_IS | UNAFFECTED | NO_METHODICAL_IMPACT | no |
| E32-11 | gcc_analyzer -Wanalyzer-malloc-leak: same allocation-failure modelling, outside the decided demotion scope, 'flagged for a separate demotion decision' | MULTIPLE | DECISION_PENDING_AUTHOR | A: UNAFFECTED / B: LIMITED_WITH_DISCLOSURE for the gcc_anal | DECISION_PENDING_AUTHOR | yes |
| E32-12 | search/35 benchmark-local validation attempts numTries = 5 vs suite-wide MAX_VALIDATION_ATTEMPTS = 2 (explicitly left un-normalized in wave 2B) | NONE | DECISION_PENDING_AUTHOR | A: UNAFFECTED (both pilots run 5 attempts); / B: LIMITED_WITH_DISCLOSURE for the 33 searc | DECISION_PENDING_AUTHOR | yes |

Considered and NOT counted as E3.2 items (each with its source and reason): dense_la/00 BL-01 tolerance regime (already DECIDED and persisted; its deferred alternatives were rejected by the semantic int); disclosure rendering / post-run manifest 'NOT_IMPLEMENTED' text in older artifacts (stale provenance text superseded by implemented gates (check_semantic_decisions READY, ver); run_backfill.stage_coverage gap reporting; batch provider asymmetry; gcc_analyzer raw_stderr 8000-char cap; runtime identity in the run manifest (operational/reporting/provenance observations without a provisional frozen value; no pilot); Helgrind / DRD enabling (documented configuration option, not a deferred decision; dynamic-analysis tool set is fro); pilot_002 population / base run_id / reuse / publication policy / histogram/20 widening (explicitly excluded from this wave by the task (no population, run_id, reuse or publicatio); wave-2B future-wave backlog (B enhanced patterns, C dedicated timing wave for sparse45/49/graph19, E assembly cleaning wave, F reporting/provenance refresh; histogram/24 BL-08, search/36/39 size-0 asymmetry) (queued feature work without a provisional frozen value; the timing contract (timing_semant); LLOV re-pilot decision (wave-1 open gate) (superseded by the static/repair wave: LLOV classified METHOD_CHANGED_NOT_DIRECTLY_COMPARAB); STATIC_SPLIT_INVOCATION_COVERAGE_GAP (parcoach/llov), ITERATION_ZERO_COVERAGE_RESIDUAL, Docker readiness first-call observation, TSan/ASLR (explicitly separate infrastructure/environment findings (task: stay separate; final enviro).

## 2. Scratch measurement (history read-only)

The pilot_001 sources were re-analysed with the CURRENT static configuration in the three containers of the readiness proof (image ids main=sha256:eb1c2e93cfab, parcoach=sha256:dbac7091e60b, llov=sha256:67d8c6c0b36e). Historical tree fingerprint before/after: 2038 files, inventory sha `c861b33f575e0d96` / `c861b33f575e0d96` — `PILOT001_TREE_CHANGED_BY_E3_2_MEASUREMENT = false`.

Current configuration vs historical records, per tool (`compared` = entries present on both sides; `semantic_equal` = identical (tool, check_id, file, line, severity, blocking, low_confidence) sets; column/message-only and order/duplicate-only differences are reported separately and never counted as semantic):

| tool | compared | semantic equal | semantic different | column/message only | state changed | blocking old → new |
|---|---|---|---|---|---|---|
| compiler | 396 | 396 | 0 | 0 | 0 | 25 → 25 |
| gcc_analyzer | 396 | 396 | 0 | 11 | 0 | 181 → 181 |
| clang_tidy | 396 | 386 | 10 | 0 | 0 | 231 → 208 |
| cppcheck | 396 | 395 | 1 | 0 | 1 | 3 → 2 |
| infer | 12 | 12 | 0 | 0 | 0 | 0 → 0 |
| parcoach | 396 | 396 | 0 | 2 | 22 | 5 → 5 |
| llov | 396 | 392 | 4 | 0 | 22 | 32 → 36 |

infer was re-run for the 12 OpenMP samples of one model only (12/12 NOT_ANALYZED, frontend abort) - the full infer re-run was stopped for environment throughput; no E3.2 item depends on a serial/mpi infer comparison. The clang_tidy (10), cppcheck (1), parcoach (22 states) and llov (4, 22 states) differences are exactly the tool-state-wave class changes already recorded in cross_pilot_comparability.json areas.F_static_repair; gcc_analyzer and compiler reproduce pilot_001 exactly, which makes the ompi_skip comparison against the scratch current records definitive.

## 3. OMPI_SKIP_MPICXX

Location: parcoach: SET (tools.py:1797, clang-15 in registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1) - in effect for pilot_001 already; gcc_analyzer: NOT SET (mpicxx -fanalyzer in pareval-thesis) - considered and rejected in the static/repair readiness wave; compiler: NOT SET; clang_tidy: NOT SET; cppcheck: NOT SET; infer: NOT SET. PARCOACH robustness: PARCOACH cannot model OpenMPI's (deprecated) C++ bindings; the define makes mpi.h skip mpicxx.h. For gcc_analyzer it was proposed as noise reduction and rejected because it changes finding sets.

| | |
|---|---|
| `MPI_FINDING_SETS_COMPARED` | 132 |
| `MPI_FINDING_SETS_CHANGED` | 51 |
| `MPI_FINDING_SETS_UNCHANGED` | 81 |
| semantically equivalent after normalization (column/message only) | 16 |
| semantically different | 51 |
| blocking without → with flag | 147 → 75 |
| samples blocking → clean / clean → blocking | 21 / 0 |
| vanished findings by family | {"-Wanalyzer-malloc-leak": 4, "-Wanalyzer-null-dereference": 45, "-Wanalyzer-out-of-bounds": 1, "-Wanalyzer-possible-null-dereference": 19, "-Wanalyzer-too-complex": 464, "-Wanalyzer-use-of-uninitialized-value": 3} |
| vanished blocking by Phase-0 FP signature | {"NO_SIGNATURE": 6, "T1": 19, "T3": 2, "T5": 45} |
| analysis-state transitions | {"COMPLETED->COMPLETED": 46, "PARTIAL->COMPLETED": 2, "PARTIAL->PARTIAL": 76, "TOOL_ERROR->TOOL_ERROR": 8} |
| `PRIOR_SUMMARY_CLAIM` | 15/20 |
| `PRIOR_SUMMARY_CLAIM_REPRODUCED` | false |

the readiness wave's population of 20 MPI finding sets is not identified in the repo; measured over ALL 132 pilot_001 MPI samples: 51 changed, blocking 147 -> 75; over the 49 samples that carry blocking findings without the flag: 45 changed, blocking 147 -> 75. The direction and the roughly halved blocking count agree with the claim; the exact 15/20 and 68/40 figures are not reproducible as stated and the measured figures govern.

## 4. Decisions

`E3_2_DECISION = ACCEPTED_PENDING_AUTHOR_CONFIRMATION`. semantic_decisions_pilot002.json is the frozen per-benchmark prompt/oracle decision registry (validated by check_semantic_decisions.py, LF-hashed into the frozen contract and the report condition); E3.2 items are static/enhanced/condition/hash-rule items with a different schema, and writing them into that registry would move the report condition and the contract input without any benchmark semantic changing. This file is the E3.2 decision artifact; the registry is referenced, not modified.

Mechanical decisions (decided by this wave, no methodology content):

* **E32-04** — catalog e2b_size_zero reason strings superseded by the prompt sentences (geometry/12,13,14; scan/34): `FREEZE_AS_IS`; MECHANICAL: a text correction without semantic content; rewording now would move the policy SHA, the E3 manifest hashes and the execution fingerprint (component B) for zero result effect
* **E32-05** — raw-byte (checkout-dependent) hash rule of the OLD condition versions: `FREEZE_AS_IS`; MECHANICAL: representation only - the bytes the pipeline hashes are the same on the host and in every container of the pilot_002 execution environment (measured equal), so the values are stable for the run; re-versioning would cascade into readiness/cross-pilot/E3 re-freezes with zero semantic content. Third-party reproduction on an LF clone must compare the LF-normalized values (documented).
* **E32-06** — not_applicable_entry written without fingerprint / outside the per-tool merge check (528 pilot_001 entries): `FREEZE_AS_IS`; MECHANICAL: a provenance nicety with no finding, coverage or verdict content; fixing it is a static-merge code change that belongs to a static-condition re-freeze and would have to be verified against the legacy-merge tests, none of which pilot_002 needs
* **E32-10** — search/37 n = 0 deliberately not decided (technically excluded): `FREEZE_AS_IS`; MECHANICAL: an input that no stage can produce needs no contract sentence; adding one would be untestable and would require a third prompt regeneration

Pending author decisions (options and recommendations only; NOTHING persisted as an author decision):

### E32-01 — OMPI_SKIP_MPICXX for gcc_analyzer (MPI)

*Question.* Shall pilot_002's gcc_analyzer compile the reduced MPI translation unit with -DOMPI_SKIP_MPICXX (as PARCOACH does), or keep pilot_001's compile (OpenMPI C++ binding headers included)?

* **Option A** — keep pilot_001 behaviour: no -DOMPI_SKIP_MPICXX for gcc_analyzer (FREEZE_AS_IS)
  * measured consequence: finding sets identical to pilot_001 (measured: 396/396 gcc_analyzer entries semantically equal between the current tool and the historical records); 49 of 132 MPI samples carry blocking gcc_analyzer findings (147 blocking in total), 45 of them only through Phase-0 FP-class signatures (see E32-09)
  * pilot_001 comparability: UNAFFECTED: gcc_analyzer MPI cells keep COMPARABLE_WITH_LIMITATIONS
  * pilot_002 methodology: the analyzer explores the TU with the exploration budget the OpenMPI C++ binding headers leave it; the recorded PARTIAL/COMPLETED coverage states keep their pilot_001 meaning
  * repair: unchanged repair input for MPI samples
* **Option B** — append -DOMPI_SKIP_MPICXX to the gcc_analyzer compile at the default analyzer budget (CHANGE_THEN_FREEZE; static condition re-frozen)
  * measured consequence: 51 of 132 MPI finding sets change; blocking 147 -> 75; 21 samples go from blocking to clean, 0 from clean to blocking; vanished blocking findings by family: {"-Wanalyzer-malloc-leak": 4, "-Wanalyzer-null-dereference": 45, "-Wanalyzer-out-of-bounds": 1, "-Wanalyzer-possible-null-dereference": 19, "-Wanalyzer-too-complex": 464, "-Wanalyzer-use-of-uninitialized-value": 3}; by Phase-0 signature: {"NO_SIGNATURE": 6, "T1": 19, "T3": 2, "T5": 45}. Mechanism (review measurement adversarial review wf_13b0152d-caf, verifier agents (executed in pareval-thesis over all 132 pilot_001 MPI samples)): the define removes the C++ binding supernodes from the TU and with them shrinks GCC's whole-exploration budget (supernodes x analyzer-bb-explosion-factor), so the analyzer stops exploring the IDENTICAL model function earlier - too-complex give-ups vanish (464) because exploration ends before reaching those program points, whole-exploration bail-outs rise (whole-exploration bail-outs 18 -> 72 (54 new, none removed; 40 recorded as PARTIAL, 32 silent because GCC suppresses the system-header-located bail-out line) in one reproduction, 10/132 -> 40/132 with -Wsystem-headers in the other), and the 2 PARTIAL->COMPLETED transitions are silent bail-outs recorded as COMPLETED/CLEAN (their historical blocking finding returns at --param=analyzer-bb-explosion-factor=20, which restores every historical blocking set: -DOMPI_SKIP_MPICXX + --param=analyzer-bb-explosion-factor=20 reproduces the historical blocking sets 40/40 on the samples that changed)
  * pilot_001 comparability: INCOMPARABLE for the 12 x mpi x static_analysis x gcc_analyzer cells (finding counts AND analysis-state/coverage counts); LIMITED_WITH_DISCLOSURE for the MPI static_feedback/combined_feedback repair cells
  * pilot_002 methodology: a coverage LOSS presented by the records as a gain: fewer findings and 2 false COMPLETED states; the PARTIAL/COMPLETED state model would need an MPI caveat; a 'flag + explicit analyzer budget' variant is a NEW configuration that would need its own readiness measurement (not measured here)
  * repair: 21 MPI samples would start static_feedback/combined_feedback as clean instead of active because the analyzer no longer reaches their findings, not because the findings are wrong

`RECOMMENDATION = A` — the adversarial review refuted the noise-removal reading of the flag: the vanished findings are model-line program points the analyzer no longer REACHES (budget truncation), not header noise (file attribution already removes header findings) - 66 of 72 vanished blocking findings do carry the Phase-0 FP-class signature, but that class is handled by E32-09 without cutting coverage. B as measured trades 51 finding sets and the MPI coverage states for nothing the methodology wants; PARCOACH's use of the define is unrelated (robustness of a tool that cannot model the C++ bindings).

Residual risk: under A the analyzer keeps spending budget on unused binding headers (documented, pilot_001-identical); a future 'flag + explicit budget' configuration could recover the same coverage on a smaller TU but is unmeasured and would be a separate CHANGE_THEN_FREEZE with its own readiness proof

### E32-02 — infer configured scope on OpenMP

*Question.* Shall infer stay configured for OpenMP samples in pilot_002 (recording NOT_ANALYZED on every omp kernel and vetoing clean stops), or be narrowed to serial/mpi?

* **Option A** — keep infer execution_models [serial, omp, mpi] (FREEZE_AS_IS)
  * measured consequence: pilot_001: 130 omp infer entries NOT_ANALYZED (132 of 132 omp records abort in the frontend); current image, 12 omp samples re-run: {"NOT_ANALYZED": 12}
  * pilot_001 comparability: UNAFFECTED incrementally (infer/omp already METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE; the stored disclosure table stays valid)
  * pilot_002 methodology: every omp record documents the coverage gap explicitly (NOT_ANALYZED with the frontend reason); infer produces no OpenMP verdict; static condition unchanged
  * repair: issue-free omp samples end stopped_analysis_incomplete instead of stopped_clean (orchestrator.evaluate_stop; measured on the 132 pilot_001 omp base records: 52 active, 80 issue-free, all 80 incomplete under A); no feedback text changes
* **Option B** — narrow infer to execution_models [serial, mpi] (CHANGE_THEN_FREEZE WITH static-condition re-freeze: the configured scope is hashed into static_analysis_condition_sha256)
  * measured consequence: config-only in code (tool_config narrows by intersection, tools.py untouched), but static_analysis_condition_sha256 327b235a8014cb68 -> cf54ff519c477c23 (measured in memory), the readiness artifact goes stale and the runtime condition moves: readiness must be re-measured before T0. On the pilot_001 omp base records: 25 of the 80 issue-free samples would stop clean, 55 stay incomplete because of llov (55) and gcc_analyzer (11) gaps; the 52 active samples, their feedback and blocking sets are identical under A and B
  * pilot_001 comparability: UNAFFECTED incrementally for the infer/omp static cells (already METHOD_CHANGED, no verdict to compare); LIMITED_WITH_DISCLOSURE for the 12 x omp x repair x {static_feedback, combined_feedback} cells: the class stays METHOD_CHANGED, but the stored disclosure table (clean_stops_reassessed_under_tool_state: gap:infer rows) must be re-derived with infer not required on omp; test_feedback cells UNAFFECTED
  * pilot_002 methodology: the OpenMP static toolset becomes compiler + gcc_analyzer + clang_tidy + cppcheck + llov; the gap is stated by configuration instead of per record; the llov region-not-analyzed gap persists
  * repair: 25 of 80 issue-free omp samples can stop clean; the terminal-status population of the omp arm becomes comparable in kind with serial/mpi (a repair OUTCOME effect, not a feedback effect)

`RECOMMENDATION = B` — 132/132 pilot_001 OpenMP infer records abort in infer's clang-11 frontend and the current image reproduces it on every re-run sample; a tool that cannot analyse any OpenMP kernel contributes no verdict but, if required, vetoes every clean stop of the omp arm. Narrowing states the limitation once in the frozen configuration and recovers 25 of 80 issue-free clean stops; the remaining 55 are vetoed by llov's region-not-analyzed semantics, which is a deliberate tool-state decision, not an infer question. The cost is a static-condition re-freeze (same class as E32-09 B).

Residual risk: narrowing hides the gap from the per-record view (NOT_APPLICABLE instead of NOT_ANALYZED); a future infer with OpenMP support would need a re-freeze; the reporting must state that infer covers serial/mpi only; the E32-06 placeholder remains unfingerprinted

### E32-03 — geometry/12,13,14 degenerate-input contract: prompt convention (return 0) vs precondition + min_size

*Question.* Under which degenerate-input contract shall geometry/12, /13 and /14 be frozen: the explicit convention now in the prompts ('return 0' / 'area 0') with size 0 still DISALLOWED, the same convention with size 0 re-allowed (the reason for DISALLOWED no longer holds), or the precondition contract (n >= 3 / n >= 2 plus enforced min_size) that the decision artifact calls the preferred long-term contract?

* **Option A** — freeze the regenerated prompts as they are; e2b_size_zero stays DISALLOWED / min_size 1 on freeze-stability grounds; E3 artifact unchanged (FREEZE_AS_IS)
  * measured consequence: no change; the frozen E3 seeds at sizes 1/2 keep exercising the degenerate branch; correctness stage unaffected (n<2 / n<3 unreachable at TEST_SIZE 1024). NOTE: the catalog reason for DISALLOWED ('the frozen prompt does not state') is factually superseded - A keeps the VALUE for freeze stability only
  * pilot_001 comparability: UNAFFECTED (benchmarks not in pilot_001)
  * pilot_002 methodology: the contract is the oracle's own behaviour made explicit; every stage tests it consistently; size 0 - now a stated answer - is not exercised
  * repair: none
* **Option B** — precondition contract + min_size 3 (/12) and 2 (/13, /14); enhanced regeneration (E3 re-freeze) and a further prompt regeneration (CHANGE_THEN_FREEZE)
  * measured consequence: frozen seeds invalidated: /12 2, /13 1, /14 1; productive keys replaced: /12 12, /13 6, /14 5 (measured on the frozen artifact)
  * pilot_001 comparability: UNAFFECTED (benchmarks not in pilot_001)
  * pilot_002 methodology: the degenerate inputs leave the tested domain instead of being graded against a sentinel; /12 additionally needs a catalog field able to express a semantic min_size 3 (none exists today)
  * repair: none
* **Option C** — frozen convention + e2b_size_zero ALLOWED / min_size 0 for geometry/12, /13, /14 (the prompts now state the n = 0 answer) + E3 re-freeze (CHANGE_THEN_FREEZE)
  * measured consequence: review measurement (adversarial review wf_13b0152d-caf (in-memory simulation, enhanced_policy.json untouched)): size 0 re-allowed for geometry/12,13,14: 3 pre-E3 size-0 seed rows re-validated; verifier partition 272/199 -> 275/196; productive keys replaced 7/6/3 with the frozen seeds (7/6/4 with the re-validated seeds); 1-2 size-0 specs per productive suite
  * pilot_001 comparability: UNAFFECTED (benchmarks not in pilot_001)
  * pilot_002 methodology: the size-0 case the prompt now defines is exercised by the enhanced stage; E3 artifact, manifest and execution fingerprint re-frozen
  * repair: none

`RECOMMENDATION = A` — all three contracts are consistent with the oracle and the correctness stage cannot reach the degenerate branch; A keeps the E3 freeze, the prompt regeneration set and the readiness proofs intact, while B re-opens the enhanced freeze (4 seeds, 23 productive keys) plus a catalog schema change, and C re-opens it for a size-0 case of no measured discriminative value; both the precondition and the size-0 re-allowance can be adopted at the next enhanced regeneration without touching pilot_002

Residual risk: under A the prompt grades a sentinel convention (return 0) that some readers may consider inventive, and the catalog keeps a DISALLOWED value whose stated reason no longer holds (E32-04 records the superseded text; the VALUE is decided here)

### E32-07 — static-base / LLM spec_key collision in the enhanced mutation frontier

*Question.* Shall the enhanced mutation frontier keep the frozen E3 suite (static-base and LLM seed identities not collapsed against each other), or be canonicalized jointly and re-frozen?

* **Option A** — keep the frozen E3 suite (FREEZE_AS_IS)
  * measured consequence: no change; 12 benchmarks carry 38 colliding identities that only lengthen the pre-shuffle mutation list
  * pilot_001 comparability: UNAFFECTED incrementally (enhanced cells already not directly comparable across the E3 freeze)
  * pilot_002 methodology: emission already dedupes on spec_key, so the collision creates no fake diversity; the frontier's seed order is a documented, deterministic quirk
  * repair: none
* **Option B** — collapse static/LLM identities before mutation and re-freeze E3 (CHANGE_THEN_FREEZE)
  * measured consequence: productive key sets change for 10 benchmarks (dense_la/01_dense_la_solve, graph/16_graph_largest_component, graph/17_graph_highest_degree, graph/18_graph_count_components, graph/19_graph_shortest_path, histogram/23_histogram_first_letter_counts, reduce/25_reduce_xor, sort/43_sort_sort_an_array_of_structs_by_key, sort/44_sort_sort_non-zero_elements, sparse_la/49_sparse_la_sparse_lu_decomp); frozen artifact, E3 manifest and execution fingerprint re-frozen
  * pilot_001 comparability: UNAFFECTED incrementally; reduce/25's enhanced suite (a pilot_001 benchmark) changes composition once more
  * pilot_002 methodology: identity purity of the frontier; suite composition churn for 10 benchmarks without a measured diversity gain
  * repair: none

`RECOMMENDATION = A` — the collision is not a defect of the frozen suite (no duplicate emission, no invalid seed) but a property of two deterministic generators; collapsing it re-composes 10 benchmarks' suites for no measurable benefit and would force an E3 re-freeze right before pilot_002

Residual risk: a reader may find the frontier definition inelegant; the provenance report documents it

### E32-08 — assembly writer newline policy HOST_DEPENDENT x clang_tidy byte-offset conversion: CRLF sources shift clang_tidy line/column identities

*Question.* clang_tidy's byte FileOffset is converted against universal-newline text (tools.py:1242 read_text, :1246 offset_to_line_col), so CRLF-assembled sources (the Windows host writer) yield shifted line/column identities for clang_tidy findings while LF sources (container-assembled iterations) yield correct ones. Shall pilot_002 keep the host-dependent writer and the current conversion, pin the writer to LF, or fix the conversion (raw bytes) - the latter two re-freeze the assembly or static condition?

* **Option A** — keep ASSEMBLY_WRITER_NEWLINE_POLICY = HOST_DEPENDENT and tools.py unchanged (FREEZE_AS_IS)
  * measured consequence: pilot_002 base samples assembled on the Windows host reproduce the shifted clang_tidy locations at iteration 0 while container-assembled repair iterations get correct ones - exactly pilot_001's state (base: review measurement from the stored raw_stdout FileOffsets: 510 of 1286 located clang_tidy findings on the wrong line in 150 of 306 records with findings, 161 of them blocking; column wrong for all 1286; 6 end-of-file findings recorded with line null; iterations: LF, correct)
  * pilot_001 comparability: UNAFFECTED incrementally (both pilots carry the same defect); the defect itself limits every clang_tidy cell of BOTH pilots (see the item's disclosure)
  * pilot_002 methodology: a known location defect is frozen into the main pilot; clang_tidy identities (tool, check_id, file, line) of iteration 0 are wrong for every finding after the first CR
  * repair: iteration-0 feedback renders shifted 'line N:' text for clang_tidy findings (pilot_001: review measurement: 158 iteration-1 static_feedback/combined_feedback prompts rendered shifted clang_tidy line numbers; test_feedback unaffected)
* **Option B** — pin the assembly writer to LF (CHANGE_THEN_FREEZE; assembly condition and every raw artifact hash of re-assembled samples move)
  * measured consequence: correct clang_tidy locations for LF sources (measured: LF copy vs CRLF copy of the same source differ in gemini_36_flash geometry/10 serial: CRLF (bugprone-implicit-widening-of-multiplication-result 41:30, bugprone-narrowing-conversions 15:27, 29:16, 49:19) vs LF (39:15, 15:13, 28:9, 48:29), all blocking; identity (check_id, line) sets differ); pilot_002 base bytes differ from pilot_001's base bytes (LF vs CRLF), content identical
  * pilot_001 comparability: LIMITED_WITH_DISCLOSURE for the 12 x {serial, omp, mpi} x static_analysis x clang_tidy cells (pilot_001 base locations shifted, pilot_002 correct) and the static/combined repair cells
  * pilot_002 methodology: the conversion defect stays latent in tools.py (any future CRLF input re-triggers it)
  * repair: correct line numbers in the repair feedback
* **Option C** — convert clang-tidy's byte FileOffset against the raw bytes in tools.py (CHANGE_THEN_FREEZE; tools.py hash -> static condition re-freeze), optionally together with B
  * measured consequence: correct clang_tidy locations regardless of the writer's newline convention; static condition re-frozen, readiness re-measured; pilot_001 records can be re-derived from their stored raw_stdout FileOffsets (review: yes - every clang_tidy record stores the raw clang-tidy output with FileOffsets; recomputing (line, column) against the raw CRLF bytes is deterministic)
  * pilot_001 comparability: LIMITED_WITH_DISCLOSURE for the same clang_tidy and repair cells; counts/check_ids/blocking unaffected, line/column identities comparable only after re-derivation
  * pilot_002 methodology: the defect is removed at its root; the newline policy becomes irrelevant for clang_tidy
  * repair: correct line numbers in the repair feedback

`RECOMMENDATION = C` — the location defect was found by the adversarial review of this wave and reproduced first-hand (gemini_36_flash geometry/10 serial: CRLF lines 41/15/29/49 vs LF 39/15/28/48, all blocking); freezing a known identity defect into the main pilot (A) is not defensible when the fix is a byte-offset conversion; C removes the root cause and, unlike B, does not depend on the host; B alone leaves the latent defect. The cost is the static-condition re-freeze that E32-02 B and E32-09 B require anyway.

Residual risk: C changes tools.py and therefore the static condition (readiness re-proof, tool-state fixtures re-run); pilot_001 clang_tidy identities must be re-derived for any cross-pilot comparison; the residual non-ASCII column drift observed on LF sources by the review needs the same raw-byte conversion

### E32-09 — gcc_analyzer FP-class demotion (Phase-0 predicate T1-T5) designed, not applied

*Question.* Shall pilot_002 run gcc_analyzer as in pilot_001 (every -Wanalyzer-* finding blocking) or with the Phase-0 FP-class demotion (T1-T5 -> low_confidence) applied before the run?

* **Option A** — no demotion (FREEZE_AS_IS): every -Wanalyzer-* finding stays blocking
  * measured consequence: current records (base run, 396 samples): blocking by execution model {"mpi": 147, "omp": 29, "serial": 5}; of these, {"mpi": 139, "omp": 28, "serial": 5} match the FP signature (by rule {"T1": 68, "T2": 5, "T3": 19, "T5": 80}); residue kept blocking in-family {"-Wanalyzer-use-of-uninitialized-value": 3}, other families {"-Wanalyzer-malloc-leak": 4, "-Wanalyzer-out-of-bounds": 2}
  * pilot_001 comparability: UNAFFECTED (gcc_analyzer cells keep COMPARABLE_WITH_LIMITATIONS)
  * pilot_002 methodology: gcc_analyzer blocking counts stay 'not quotable as defect counts' (Phase-0); the repair loop iterates on findings the Phase-0 analysis classifies as >= 99 % analyzer artefacts
  * repair: unchanged: samples with only FP-class blocking findings enter the loop as repair targets
* **Option B** — apply the T1-T5 demotion as low_confidence marking in tools.py (finding kept, not deleted) and re-freeze the static condition (CHANGE_THEN_FREEZE)
  * measured consequence: samples whose blocking set empties under the demotion: {"mpi": 45, "omp": 7, "serial": 4} (of {"mpi": 49, "omp": 8, "serial": 4} with blocking); blocking findings demoted {"mpi": 139, "omp": 28, "serial": 5}; 9 findings stay blocking (3 uninitialized-value residue, 4 malloc-leak - see E32-11 - and 2 out-of-bounds)
  * pilot_001 comparability: LIMITED_WITH_DISCLOSURE for every gcc_analyzer cell: pilot_001 counts can be re-derived with the same message predicate (defined on the stored message), so counts stay comparable after re-derivation; repair trajectories are not (pilot_001 iterated on undemoted sets)
  * pilot_002 methodology: the finding semantics change from 'every analyzer warning is a defect' to 'analyzer warnings on vector-allocation counterfactual paths are low-confidence'; the demotion is message-based and auditable per finding
  * repair: the samples listed above start the loop as clean (or with only low-confidence findings, graced once); the repair experiment stops chasing vector-allocation phantoms

`RECOMMENDATION = B` — Phase-0 measured 787/794 (99.1 %) of the three families as analyzer FP-class on pilot_001 and declared the counts not quotable; the same predicate on the CURRENT base records demotes 172 of 181 blocking findings; running the main pilot with a known >= 99 % false-positive blocking signal as repair input would make the repair loop's static arm chase artefacts, and the counts could not be reported as defects anyway. Demotion as marking (not deletion) keeps every finding recorded and the pilot_001 comparison re-derivable. It also covers 66 of the 72 blocking findings that E32-01 B would have removed by truncation.

Residual risk: T5 (NULL '0' dereference) is the aggressive rule: a genuine dereference of a constant-propagated nullptr would be demoted too (0 such cases in pilot_001; the event path is now stored, so the anchored variant can be implemented); malloc-leak/out-of-bounds stay blocking unless E32-11 B is chosen; B is a static-condition change and requires the readiness re-freeze and a re-run of the tool-state fixtures

### E32-11 — gcc_analyzer -Wanalyzer-malloc-leak: same allocation-failure modelling, outside the decided demotion scope, 'flagged for a separate demotion decision'

*Question.* Shall -Wanalyzer-malloc-leak (flagged by the Phase-0 analysis as the same allocation-failure modelling as the demoted families, but left outside the decided demotion scope 'for a separate decision') stay blocking in pilot_002 or join the demotion predicate?

* **Option A** — keep -Wanalyzer-malloc-leak blocking (FREEZE_AS_IS; = current config)
  * measured consequence: current base records: 4 blocking malloc-leak findings in 2 records, all with T1 signature (vector-internal storage 'leaking' on counterfactual exception paths); after the E32-09 T1-T5 demotion 2 samples would stay blocking ONLY via malloc-leak: ["deepseek_v4_pro__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0", "qwen37_max__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0"]. Phase-0 over all 7 pilot_001 run dirs: 47 blocking (26 deduplicated), 20 token-bearing, 24 operator-new, 3 unknown
  * pilot_001 comparability: UNAFFECTED (same as pilot_001)
  * pilot_002 methodology: the demotion scope stays exactly the Phase-0 'decided' three families; a family the same analysis classifies as artefact keeps blocking and feeding the repair loop
  * repair: the samples above remain repair targets on malloc-leak findings alone
* **Option B** — add -Wanalyzer-malloc-leak to the demotion predicate's check_id set (same T1-T5 message signatures; CHANGE_THEN_FREEZE with the same static re-freeze as E32-09 B)
  * measured consequence: the 4 findings become low_confidence; the 2 samples start clean (or graced)
  * pilot_001 comparability: LIMITED_WITH_DISCLOSURE for the gcc_analyzer cells (same re-derivation as E32-09 B)
  * pilot_002 methodology: consistent treatment of the analyzer's allocation-failure modelling; out-of-bounds (2) stays blocking
  * repair: no phantom-leak repair targets

`RECOMMENDATION = B (only together with E32-09 B; A if E32-09 A)` — the Phase-0 document classifies malloc-leak as 'the same allocation-failure modeling' and every current malloc-leak message carries the T1 signature; demoting the three families but not this one would leave the same artefact class blocking for 2 samples. The decision is conditional on E32-09: without the demotion there is nothing to join.

Residual risk: a genuine leak of model-allocated memory on a real path would be demoted too (Phase-0: 24 of 47 are later-new-throws paths where the sample delete[]s both buffers; none genuine in pilot_001)

### E32-12 — search/35 benchmark-local validation attempts numTries = 5 vs suite-wide MAX_VALIDATION_ATTEMPTS = 2 (explicitly left un-normalized in wave 2B)

*Question.* search/35 validates with a benchmark-local numTries = 5 (drivers/cpp/benchmarks/search/35_.../cpu.cc:78) while the suite-wide contract is MAX_VALIDATION_ATTEMPTS = 2 (utilities.hpp:34-35) and search/38's identical hardcode was normalized in wave 2B (cpu.cc:66-73) with 35 explicitly left as is. Shall pilot_002 keep 5 attempts for search/35 or normalize it to the suite-wide contract?

* **Option A** — keep numTries = 5 (FREEZE_AS_IS; = pilot_001)
  * measured consequence: pilot_001 search/35 correctness: {"pass": 30, "validation_failed": 2, "build_failed": 1}; the two validation failures are deterministic (the candidate returns TEST_SIZE instead of the index: 'MISMATCH expected=1016 got=1024'), so they fail on the first attempt; validation power for search/35 stays 5 random inputs vs 2 suite-wide
  * pilot_001 comparability: UNAFFECTED (both pilots run 5); disclosure note only: cross_pilot_comparability.json's canonical condition text 'max_validation_attempts (2, utilities.hpp default; no -D override)' is inaccurate for search/35
  * pilot_002 methodology: one pilot_001 benchmark keeps a stricter validation contract than the rest of the suite; the wave-2B cost model note ('35's x5 newly documented') stays
  * repair: none
* **Option B** — normalize to numTries = MAX_VALIDATION_ATTEMPTS like search/38 (CHANGE_THEN_FREEZE: drivers tree changes -> static condition (drivers_tree_sha256) and the cross-pilot candidate_subset_state cpu_cc sha re-pinned)
  * measured consequence: pilot_001 verdicts of search/35 are invariant under 2 attempts (passes pass on every attempt; the 2 failures are deterministic); static_analysis_condition_sha256 changes (drivers_tree_sha256), readiness re-measured
  * pilot_001 comparability: LIMITED_WITH_DISCLOSURE for the 33 search/35 x {serial, omp, mpi} x correctness cells currently DIRECTLY_COMPARABLE (validation power 5 -> 2 attempts; observed verdicts invariant)
  * pilot_002 methodology: suite-wide uniform validation contract
  * repair: none

`RECOMMENDATION = A` — the observed pilot_001 verdicts are invariant under either attempt count, so the choice does not change any recorded result; A keeps the drivers tree, the static condition and the cross-pilot state pins untouched right before pilot_002, and the stricter local contract is documented. B is the cleaner contract and can be adopted together with any other drivers-tree re-freeze.

Residual risk: under A the cross-pilot artifact's canonical-condition text remains inaccurate for search/35 (a note, not a value change); under B a future search/35 candidate that fails only on attempts 3-5 would pass

## 5. Cross-pilot counts (from the artifact, unchanged)

`thesis/evaluation/cross_pilot_comparability.json`: classification `PILOT_SUBSET_ONLY_QUANTITATIVE_COMPARISON_DEFENSIBLE_WITH_EXCLUSIONS`; pilot_001 iteration-0 cells 396; candidate subset 99 cells; excluded 99 cells; transport effect verdict-preserving 99 / changed 0 / unresolved 99; fingerprint `57436c61d1cbf46f`; state commit `6fc8a1a9a33d`; artifact changed by this wave: false.

Comparability cells touched by E3.2 (only under the CHANGE options of the pending items): E32-01 option B — 12 pilot_001 benchmarks × mpi × static_analysis × gcc_analyzer (INCOMPARABLE quantitatively) plus the MPI static_feedback/combined_feedback repair cells (LIMITED_WITH_DISCLOSURE); E32-09 option B — every gcc_analyzer cell (LIMITED_WITH_DISCLOSURE, counts re-derivable) plus the static/combined repair cells; E32-02 and E32-07 change no comparability class incrementally; the mechanical items change none.

Disclosure texts (to be rendered only if the corresponding option is confirmed): under E32-01 B — 'pilot_002's gcc_analyzer analysed the MPI translation unit without OpenMPI's C++ binding headers; pilot_001's did not. MPI gcc_analyzer finding and blocking counts are therefore not quantitatively comparable between the pilots (51 of 132 pilot_001 MPI finding sets change under the pilot_002 compile); serial and OpenMP gcc_analyzer results, every other tool and the correctness/enhanced/timing stages are unaffected.' Under E32-09 B — 'pilot_002 marks gcc_analyzer findings matching the Phase-0 FP-class signature as low-confidence; pilot_001 treated them as blocking. Blocking counts are comparable only after re-deriving pilot_001's counts with the same message predicate; repair trajectories in static_feedback/combined_feedback are not comparable.'

## 6. Adversarial classification review

{
 "workflow": "wf_13b0152d-caf (5 attack dimensions, one adversarial verifier per claim, every claim executed)",
 "attacks_attempted": 18,
 "confirmed": 12,
 "refuted": 6,
 "accepted_disclosure_attacks": "none proposed as ACCEPTED_DISCLOSURE before the review; the LIMITED_WITH_DISCLOSURE cells of E32-01 B, E32-02 B, E32-08, E32-09 B, E32-11 B, E32-12 B were attacked via the disclosure-and-cells dimension",
 "no_methodical_impact_attacks": "E32-04, E32-05, E32-06, E32-08, E32-10 attacked; E32-08 CONFIRMED and reclassified; E32-04 partially confirmed (value question moved to E32-03 C); E32-05, E32-06, E32-10 refuted (evidence text corrections only)",
 "freeze_as_is_alternatives_discovered": "E32-08 (fix the conversion / pin LF), E32-03 option C; the other mechanical items have no methodology-bearing alternative (refuted)",
 "distinct_corrections_applied": [
  "E32-08: METADATA_ONLY/FREEZE_AS_IS/UNAFFECTED/NO_METHODICAL_IMPACT -> MULTIPLE (FINDING_SET + REPAIR_INPUT) / DECISION_PENDING_AUTHOR (A/B/C, recommendation C) / LIMITED_WITH_DISCLOSURE for all clang_tidy static cells and the static/combined repair cells: clang_tidy byte FileOffset converted against universal-newline text (tools.py:1242/1246) shifts line/column of every CRLF base record (first-hand reproduction + two review reproductions)",
  "E32-01: result_impact FINDING_SET -> MULTIPLE (COVERAGE negative + FINDING_SET); RECOMMENDATION B -> A: the flag truncates GCC's whole-exploration budget (2 silent false-COMPLETED records; -Wanalyzer-too-complex give-ups vanish because exploration ends earlier; bb-explosion-factor 20 restores the historical blocking sets); under B the gcc_analyzer x mpi cells are INCOMPARABLE for coverage states too",
  "E32-02: option B is NOT config-neutral (the tool scope is hashed into the static condition: 327b235a -> cf54ff51 measured) -> CHANGE_THEN_FREEZE with static re-freeze; result_impact MULTIPLE(COVERAGE+REPAIR_INPUT) -> COVERAGE (terminal-status relabelling of 25 of 80 issue-free omp samples; feedback unchanged; llov gaps keep 55 incomplete); under B the omp static/combined repair cells become LIMITED_WITH_DISCLOSURE (stored disclosure table must be re-derived)",
  "E32-03: OPTION C added (frozen convention + size 0 re-allowed + E3 re-freeze: the DISALLOWED reason no longer holds); option A explicitly decides DISALLOWED on freeze-stability grounds",
  "E32-04: premise 'enforced values unchanged and correct' dropped; item scoped to the text, the value question moved to E32-03 C",
  "E32-11 (new): malloc-leak demotion 'flagged for a separate decision' (pilot-001-corrected-numbers.md:421) was missing from the inventory",
  "E32-12 (new): search/35 numTries = 5 was wrongly excluded as backlog; it is a provisional frozen value pilot_002 runs under (drivers tree hashed into the static condition) on a DIRECTLY_COMPARABLE pilot_001 benchmark"
 ],
 "refuted_claims": [
  {
   "item_id": "E32-05",
   "title": "Old raw-byte condition hashes are working-tree-state dependent, not merely checkout-OS dependent: a fresh clone of the same HEAD on the same Windows host yields different static/repair condition ids a",
   "why": "The EVIDENCE reproduces exactly, but the attacked classification VALUES are not wrong under the two-axis semantics; what is wrong is the item's evidence/disclosure TEXT, which can be corrected inside the existing values.\n\nReproduced (all on HEAD c7a6dbc): core.autocrlf=true, no .gitattributes; productive tree 978 w/crlf + 115 w/lf (tool_config.py, feedback.py, assemble_sources.py, e3_final_specs.j"
  },
  {
   "item_id": "E32-04",
   "title": "The stale e2b_size_zero reason string is a generator-prompt input, so FREEZE_AS_IS is only valid conditional on E32-03 = A and E32-07 = A; under an E3 re-freeze the rewording must precede regeneration",
   "why": "The mechanical part of the claim reproduces (the e2b_size_zero reason string is embedded, truncated to 180 chars, in the LLM user prompt via _parameter_rules_block -> build_user_prompt -> generate_for_benchmark, and e3_regenerate.py uses the same builder; policy SHA is fingerprint component B). But the core premise - that under an E3 re-freeze the generator would receive a serial prompt that state"
  },
  {
   "item_id": "E32-09",
   "title": "'LIMITED_WITH_DISCLOSURE for every gcc_analyzer cell (counts re-derivable with the message predicate)' fails for the 12 MPI cells under the co-recommended E32-01 B, and re-derivability holds only for ",
   "why": "The claimant's numbers reproduce, but neither attacked value is wrong under the two-axis (per-item, per-cell) semantics.\n\n(1) \"Restrict E32-09 B to serial/omp; the 12 MPI gcc_analyzer cells remain INCOMPARABLE under E32-01 B\": those 12 cells are ALREADY listed as INCOMPARABLE under E32-01 B (review_input.md row E32-01; e32_build_artifacts.py:166 \"INCOMPARABLE for the gcc_analyzer MPI cells\"; e32_w"
  },
  {
   "item_id": "E32-01",
   "title": "Option B affected-cell list is incomplete: backfilled gcc_analyzer MPI records in the test_feedback iteration populations (62 records, 94 blocking findings of exactly the vanishing classes) and the sa",
   "why": "The claim's numbers reproduce (21 gcc_analyzer blocking->clean MPI samples, 10 sample-level has_blocking_findings flips, 39+23 = 62 backfilled gcc_analyzer MPI records with 67+27 = 94 blocking findings in the test_feedback iteration trees), but the attacked classification value is not wrong under the two-axis semantics:\n\n(1) The attacked phrase 'UNAFFECTED for everything else' does not exist in th"
  },
  {
   "item_id": "E32-10",
   "title": "search/37 n=0 was already closed by E2-B as NOT_APPLICABLE; identical-status search/36 and /39 are excluded, so E32-10 does not meet the criterion (or the inventory is inconsistent)",
   "why": "REFUTED. The cited evidence reproduces in substance, but it does not make any E32-10 classification value wrong, and the 'inventory inconsistency' premise fails on the one axis that actually separates search/37 from search/36/39.\n\n1) 'Proposed value already covers the point'. E32-10 is classified result_impact NONE / FREEZE_AS_IS (mechanical: unreachable input) / UNAFFECTED / NO_METHODICAL_IMPACT."
  },
  {
   "item_id": "E32-02",
   "title": "evidence_quality 'MEASURED_CURRENT_CONTAINER' / measurement_status COMPLETE / 'current container reproduces the abort on every OpenMP kernel' is not yet backed by any current infer record",
   "why": "REFUTED as a classification finding (the reproduced facts are real, but they do not make any classification value of E32-02 wrong).\n\n1) The attacked value is not a classification value under the review's semantics. The input file defines the axes as result_impact, pilot_002_configuration {FREEZE_AS_IS, CHANGE_THEN_FREEZE, DECISION_PENDING_AUTHOR}, pilot_001_comparability {UNAFFECTED, LIMITED_WITH_"
  }
 ]
}

## 7. Constraints proven

* `GENERATION_PERFORMED = false`
* `LLM_API_CALLS = 0`
* `PILOT001_HISTORICAL_TREE_CHANGED = false`
* `PROMPTS_CHANGED = false`
* `CORRECTNESS_VERDICT_SEMANTICS_CHANGED = false`
* `ASSEMBLY_SEMANTICS_CHANGED = false`
* `TIMING_SEMANTICS_CHANGED = false`
* `REPORTING_RENDERER_CHANGED = false`
* `REPAIR_SEMANTICS_CHANGED = false`
* `ENHANCED_FROZEN_SPECS_CHANGED = false`
* `POPULATION_CHANGED = false`
* `RUN_ID_CHANGED = false`

Next step: **AUTHOR CONFIRMATION OF E3.2 DECISIONS** (no new measurement wave); `SAFE_TO_PROCEED_TO_AUTHOR_DECISION = true`, `SAFE_TO_PROCEED_TO_POPULATION_FREEZE = false`.
