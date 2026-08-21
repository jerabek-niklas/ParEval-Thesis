# Consolidated overview — run pilot_001

Generated 2026-08-21T11:34:14.311690Z. Source: stage JSONLs joined on (sample_id, variant, iteration); see overview.csv for the flat table. Trajectories are CARRY-FORWARD: a stopped sample keeps contributing its final artifact to later iterations (the population stays constant). Enhanced rates count pass over all non-gated specs (gated = baseline_incompatible + numerically_unstable).

## Pass-rate trajectories (ParEval vs. enhanced — overfitting view)

### static_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 396 | 79.5% (315/396) | 88.7% (6676/7524) |
| 1 | 396 | 82.6% (327/396) | 91.9% (6914/7524) |
| 2 | 396 | 82.8% (328/396) | 91.8% (6910/7524) |

### test_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 396 | 79.5% (315/396) | 88.7% (6676/7524) |
| 1 | 396 | 84.6% (335/396) | 92.0% (6919/7524) |
| 2 | 396 | 86.1% (341/396) | 92.0% (6925/7524) |

### combined_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 396 | 79.5% (315/396) | 88.7% (6676/7524) |
| 1 | 396 | 81.8% (324/396) | 90.0% (6771/7524) |
| 2 | 396 | 84.1% (333/396) | 91.3% (6872/7524) |

## Stop-reason distribution

### static_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 56 |
| stopped_clean | 340 |

### test_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 59 |
| stopped_tests_pass | 337 |

### combined_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 104 |
| stopped_clean | 292 |

## Blocking findings per tool over iterations (convergence)

Counts are per produced artifact at that iteration (no carry-forward — this shows what the loop's artifacts still contain). ALL enabled tools are listed, not just those with findings.

### static_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 396 | 25 | 181 | 231 | 3 | 45 | 5 | 32 | 2 | 15 | 2 | 14 |
| 1 | 159 | 3 | 139 | 29 | 0 | 15 | 0 | 8 | 0 | 9 | 0 | 12 |
| 2 | 76 | 18 | 114 | 21 | 3 | 12 | 12 | 7 | 0 | 6 | 0 | 7 |

### test_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 396 | 25 | 181 | 231 | 3 | 45 | 5 | 32 | 2 | 15 | 2 | 14 |
| 1 | 98 | 25 | 101 | 74 | 2 | 15 | 1 | 11 | 2 | 9 | 1 | 7 |
| 2 | 70 | 394 | 49 | 62 | 2 | 17 | 0 | 9 | 0 | 7 | 0 | 1 |

### combined_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 396 | 25 | 181 | 231 | 3 | 45 | 5 | 32 | 2 | 15 | 2 | 14 |
| 1 | 189 | 14 | 122 | 48 | 0 | 24 | 1 | 16 | 0 | 9 | 0 | 8 |
| 2 | 123 | 20 | 138 | 36 | 3 | 14 | 8 | 8 | 0 | 8 | 0 | 2 |

## Blocking findings by error class

Cells are `findings (samples)`: finding sums double-count when several tools report the same defect (redundancy by design); the sample count deduplicates across tools and is the citable number. Classes: thesis/evaluation/finding_classes.py.

**static_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 396 | 12 (7) | 28 (20) | 149 (57) | 232 (99) | 47 (36) | 5 (2) | 14 (10) | 47 (10) | 21 (12) |
| 1 | 159 | 2 (1) | 24 (12) | 113 (51) | 41 (23) | 17 (14) | 0 (0) | 12 (8) | 6 (2) | 0 (0) |
| 2 | 76 | 19 (7) | 13 (7) | 88 (37) | 6 (3) | 13 (9) | 12 (7) | 7 (4) | 39 (2) | 3 (2) |

**test_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 396 | 12 (7) | 28 (20) | 149 (57) | 232 (99) | 47 (36) | 5 (2) | 14 (10) | 47 (10) | 21 (12) |
| 1 | 98 | 5 (4) | 15 (12) | 84 (31) | 71 (35) | 20 (17) | 1 (1) | 7 (6) | 31 (2) | 14 (6) |
| 2 | 70 | 4 (3) | 10 (5) | 37 (21) | 48 (19) | 16 (13) | 0 (0) | 1 (1) | 409 (2) | 16 (6) |

**combined_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 396 | 12 (7) | 28 (20) | 149 (57) | 232 (99) | 47 (36) | 5 (2) | 14 (10) | 47 (10) | 21 (12) |
| 1 | 189 | 2 (2) | 12 (10) | 109 (47) | 46 (22) | 25 (21) | 1 (1) | 8 (7) | 24 (5) | 15 (7) |
| 2 | 123 | 32 (8) | 18 (10) | 96 (45) | 30 (14) | 16 (13) | 8 (5) | 2 (2) | 25 (5) | 10 (6) |

**static_feedback — class x model (final state, carry-forward):**

| model | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 36 | 0 (0) | 0 (0) | 4 (2) | 0 (0) | 3 (3) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 36 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 3 (2) | 0 (0) | 5 (1) | 1 (1) |
| deepseek_v4_flash | 36 | 1 (1) | 1 (1) | 7 (5) | 3 (1) | 6 (3) | 0 (0) | 5 (2) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 36 | 5 (1) | 0 (0) | 13 (6) | 0 (0) | 3 (2) | 0 (0) | 0 (0) | 0 (0) | 2 (1) |
| gemini_31_pro | 36 | 1 (1) | 4 (1) | 15 (5) | 0 (0) | 2 (1) | 0 (0) | 2 (1) | 0 (0) | 0 (0) |
| gemini_36_flash | 36 | 5 (2) | 3 (2) | 7 (4) | 0 (0) | 3 (2) | 3 (2) | 1 (1) | 0 (0) | 0 (0) |
| openai_gpt55 | 36 | 7 (2) | 1 (1) | 10 (3) | 1 (1) | 0 (0) | 6 (3) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt56_sol | 36 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 34 (1) | 0 (0) |
| qwen36_35b_a3b | 36 | 0 (0) | 0 (0) | 9 (3) | 0 (0) | 3 (2) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 36 | 0 (0) | 2 (1) | 7 (3) | 0 (0) | 1 (1) | 0 (0) | 1 (1) | 0 (0) | 0 (0) |
| qwen3_coder_api | 36 | 0 (0) | 2 (1) | 16 (6) | 2 (1) | 0 (0) | 0 (0) | 2 (2) | 0 (0) | 0 (0) |

**test_feedback — class x model (final state, carry-forward):**

| model | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 36 | 0 (0) | 0 (0) | 7 (3) | 21 (8) | 2 (2) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 36 | 0 (0) | 2 (2) | 15 (5) | 24 (4) | 3 (2) | 1 (1) | 0 (0) | 0 (0) | 4 (2) |
| deepseek_v4_flash | 36 | 1 (1) | 6 (4) | 19 (7) | 19 (10) | 3 (3) | 0 (0) | 0 (0) | 165 (1) | 1 (1) |
| deepseek_v4_pro | 36 | 2 (1) | 2 (2) | 15 (6) | 19 (10) | 5 (4) | 0 (0) | 0 (0) | 244 (1) | 3 (3) |
| gemini_31_pro | 36 | 0 (0) | 2 (1) | 12 (4) | 23 (14) | 3 (2) | 0 (0) | 0 (0) | 0 (0) | 2 (1) |
| gemini_36_flash | 36 | 0 (0) | 5 (2) | 11 (6) | 28 (6) | 7 (5) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 36 | 2 (1) | 1 (1) | 12 (6) | 15 (4) | 4 (3) | 0 (0) | 0 (0) | 0 (0) | 3 (1) |
| openai_gpt56_sol | 36 | 2 (1) | 7 (4) | 14 (7) | 10 (4) | 6 (4) | 0 (0) | 0 (0) | 0 (0) | 8 (1) |
| qwen36_35b_a3b | 36 | 1 (1) | 2 (2) | 23 (4) | 15 (9) | 3 (3) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 36 | 3 (2) | 2 (2) | 9 (3) | 33 (12) | 2 (2) | 4 (1) | 0 (0) | 0 (0) | 3 (2) |
| qwen3_coder_api | 36 | 1 (1) | 2 (1) | 19 (7) | 31 (14) | 1 (1) | 0 (0) | 1 (1) | 0 (0) | 1 (1) |

**combined_feedback — class x model (final state, carry-forward):**

| model | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 36 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 36 | 0 (0) | 0 (0) | 5 (3) | 0 (0) | 0 (0) | 2 (1) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 36 | 0 (0) | 4 (3) | 23 (8) | 3 (1) | 6 (4) | 0 (0) | 1 (1) | 2 (1) | 2 (2) |
| deepseek_v4_pro | 36 | 2 (1) | 0 (0) | 12 (5) | 5 (3) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 6 (2) |
| gemini_31_pro | 36 | 1 (1) | 2 (1) | 6 (4) | 5 (1) | 0 (0) | 0 (0) | 0 (0) | 6 (2) | 0 (0) |
| gemini_36_flash | 36 | 4 (1) | 0 (0) | 4 (3) | 5 (1) | 2 (2) | 2 (1) | 0 (0) | 14 (1) | 1 (1) |
| openai_gpt55 | 36 | 24 (4) | 2 (2) | 11 (7) | 0 (0) | 0 (0) | 2 (1) | 0 (0) | 0 (0) | 1 (1) |
| openai_gpt56_sol | 36 | 0 (0) | 4 (2) | 5 (4) | 1 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 36 | 0 (0) | 0 (0) | 9 (4) | 4 (3) | 3 (3) | 0 (0) | 0 (0) | 3 (1) | 0 (0) |
| qwen37_max | 36 | 0 (0) | 4 (1) | 8 (3) | 0 (0) | 0 (0) | 2 (2) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 36 | 1 (1) | 2 (1) | 13 (4) | 7 (4) | 2 (1) | 0 (0) | 1 (1) | 0 (0) | 0 (0) |

**class x execution model at iteration 0 (initial generations):**

| exec | n | memory | uninitialized | null_deref | arithmetic | race | deadlock | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 132 | 2 (1) | 0 (0) | 5 (4) | 37 (19) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 8 (2) |
| omp | 132 | 4 (2) | 12 (7) | 17 (6) | 56 (24) | 47 (36) | 0 (0) | 0 (0) | 6 (2) | 4 (4) |
| mpi | 132 | 6 (4) | 16 (13) | 127 (47) | 139 (56) | 0 (0) | 5 (2) | 14 (10) | 41 (8) | 9 (6) |

## Breakdown by problem type and execution model (final state)

### static_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 90.9% (30/33) | 99.4% (656/660) |
| fft | 33 | 97.0% (32/33) | 96.5% (573/594) |
| geometry | 33 | 93.9% (31/33) | 74.2% (392/528) |
| graph | 33 | 100.0% (33/33) | 100.0% (660/660) |
| histogram | 33 | 100.0% (33/33) | 100.0% (594/594) |
| reduce | 33 | 97.0% (32/33) | 89.1% (588/660) |
| scan | 33 | 100.0% (33/33) | 100.0% (660/660) |
| search | 33 | 97.0% (32/33) | 91.4% (543/594) |
| sort | 33 | 97.0% (32/33) | 97.1% (641/660) |
| sparse_la | 33 | 21.2% (7/33) | 88.5% (584/660) |
| stencil | 33 | 3.0% (1/33) | 62.3% (370/594) |
| transform | 33 | 97.0% (32/33) | 98.3% (649/660) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 132 | 81.8% (108/132) | 87.2% (2186/2508) |
| omp | 132 | 83.3% (110/132) | 93.9% (2356/2508) |
| serial | 132 | 83.3% (110/132) | 94.4% (2368/2508) |

### test_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 93.9% (31/33) | 100.0% (660/660) |
| fft | 33 | 100.0% (33/33) | 99.5% (591/594) |
| geometry | 33 | 97.0% (32/33) | 74.4% (393/528) |
| graph | 33 | 100.0% (33/33) | 100.0% (660/660) |
| histogram | 33 | 100.0% (33/33) | 100.0% (594/594) |
| reduce | 33 | 100.0% (33/33) | 90.2% (595/660) |
| scan | 33 | 100.0% (33/33) | 100.0% (660/660) |
| search | 33 | 100.0% (33/33) | 94.4% (561/594) |
| sort | 33 | 97.0% (32/33) | 96.8% (639/660) |
| sparse_la | 33 | 42.4% (14/33) | 82.1% (542/660) |
| stencil | 33 | 3.0% (1/33) | 62.3% (370/594) |
| transform | 33 | 100.0% (33/33) | 100.0% (660/660) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 132 | 87.1% (115/132) | 89.4% (2243/2508) |
| omp | 132 | 86.4% (114/132) | 94.7% (2376/2508) |
| serial | 132 | 84.8% (112/132) | 91.9% (2306/2508) |

### combined_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 93.9% (31/33) | 100.0% (660/660) |
| fft | 33 | 100.0% (33/33) | 99.0% (588/594) |
| geometry | 33 | 90.9% (30/33) | 71.2% (376/528) |
| graph | 33 | 100.0% (33/33) | 100.0% (660/660) |
| histogram | 33 | 100.0% (33/33) | 100.0% (594/594) |
| reduce | 33 | 100.0% (33/33) | 90.2% (595/660) |
| scan | 33 | 93.9% (31/33) | 94.2% (622/660) |
| search | 33 | 97.0% (32/33) | 94.3% (560/594) |
| sort | 33 | 97.0% (32/33) | 96.5% (637/660) |
| sparse_la | 33 | 36.4% (12/33) | 88.2% (582/660) |
| stencil | 33 | 3.0% (1/33) | 58.9% (350/594) |
| transform | 33 | 97.0% (32/33) | 98.2% (648/660) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 132 | 82.6% (109/132) | 85.5% (2144/2508) |
| omp | 132 | 85.6% (113/132) | 93.4% (2342/2508) |
| serial | 132 | 84.1% (111/132) | 95.1% (2386/2508) |

## "Statically clean but incorrect" (static_feedback, design §9)

Samples stopping clean (no blocking static findings): 340

- ParEval-incorrect among them: 13.8% (47/340)
- enhanced-failing among them: 16.8% (57/340)

## Enhanced tests by execution model

Spec-run verdicts per execution model (gates are SERIAL: sight omp/mpi crash/timeout manually for driver divergence, and expect rounding signatures in fail — see docs/enhanced-tests-parallel.md).

| exec | samples | pass | fail | crash | timeout | build_failed | runtime_error | gated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 275 | 4271 | 591 | 196 | 0 | 56 | 0 | 386 |
| omp | 367 | 5995 | 601 | 170 | 40 | 136 | 0 | 398 |
| mpi | 469 | 7257 | 880 | 297 | 124 | 326 | 0 | 496 |

## Race corroboration (omp)

Per deduplicated omp artifact: does the static race report (LLOV) have a dynamic witness (TSan)? `None` cells mean the tool did not run on that artifact — that is missing data, never a clean result.

| corroboration | artifacts |
| --- | --- |
| both report (corroborated) | 1 |
| LLOV only (static, dynamically unconfirmed) | 79 |
| TSan only (LLOV blind/not analyzable) | 43 |
| neither | 244 |

Artifacts with at least one race report (123 of 367 omp artifacts listed; the 244 without any report are only counted above):

| model | variant | iter | llov | tsan | ParEval | enhanced |
| --- | --- | --- | --- | --- | --- | --- |
| openai_gpt55 | static_feedback | 0 | 2 | 0 | pass 4/4 | 20p/0f |
| openai_gpt55 | static_feedback | 0 | 1 | 0 | pass 4/4 | 18p/0f |
| openai_gpt55 | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 0p/0f/+20 |
| openai_gpt55 | test_feedback | 1 | 1 | 0 | validation_failed 0/4 | 0p/0f/+20 |
| openai_gpt55 | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 0p/0f/+20 |
| gemini_31_pro | static_feedback | 0 | 1 | 0 | pass 4/4 | 18p/0f |
| gemini_31_pro | static_feedback | 0 | 0 | 2 | pass 4/4 | 20p/0f |
| gemini_31_pro | static_feedback | 1 | 0 | 2 | pass 4/4 | 20p/0f |
| gemini_31_pro | static_feedback | 2 | 0 | 2 | pass 4/4 | 20p/0f |
| gemini_31_pro | test_feedback | 1 | 0 | 1 | runtime_error 0/4 | 20p/0f |
| gemini_31_pro | test_feedback | 2 | 0 | 2 | pass 4/4 | 20p/0f |
| gemini_31_pro | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| claude_opus_5 | static_feedback | 0 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_opus_5 | static_feedback | 0 | 2 | 0 | pass 4/4 | 20p/0f |
| claude_opus_5 | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| claude_opus_5 | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_opus_5 | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 0 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 0 | 0 | 1 | pass 4/4 | 11p/5f |
| claude_fable_5 | static_feedback | 1 | 0 | 1 | pass 4/4 | 10p/6f |
| claude_fable_5 | static_feedback | 0 | 0 | 1 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| claude_fable_5 | test_feedback | 1 | 0 | 1 | pass 4/4 | 20p/0f |
| claude_fable_5 | test_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| claude_fable_5 | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| claude_fable_5 | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | combined_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| qwen3_coder_api | static_feedback | 0 | 1 | 1 | timeout 1/4 | 0p/0f/+20 |
| qwen3_coder_api | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| qwen3_coder_api | test_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| qwen3_coder_api | test_feedback | 1 | 0 | 1 | validation_failed 0/4 | 20p/0f |
| qwen3_coder_api | combined_feedback | 1 | 0 | 2 | validation_failed 0/4 | 20p/0f |
| qwen3_coder_api | combined_feedback | 1 | 1 | 0 | timeout 1/4 | 0p/0f/+20 |
| qwen3_coder_api | combined_feedback | 2 | 0 | 2 | pass 4/4 | 18p/0f/+2 |
| qwen3_coder_api | combined_feedback | 1 | 0 | 1 | validation_failed 0/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 0 | 1 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 0 | 2 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 0 | 1 | 0 | pass 4/4 | 18p/0f |
| deepseek_v4_pro | static_feedback | 0 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 1 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 2 | 0 | 2 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| deepseek_v4_pro | static_feedback | 1 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| deepseek_v4_pro | test_feedback | 1 | 0 | 2 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | test_feedback | 2 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | combined_feedback | 1 | 2 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_pro | combined_feedback | 2 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| openai_gpt56_sol | static_feedback | 0 | 2 | 0 | pass 4/4 | 20p/0f |
| openai_gpt56_sol | static_feedback | 0 | 1 | 0 | pass 4/4 | 18p/0f |
| openai_gpt56_sol | static_feedback | 0 | 2 | 0 | validation_failed 0/4 | 20p/0f |
| openai_gpt56_sol | static_feedback | 2 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| openai_gpt56_sol | test_feedback | 1 | 2 | 0 | validation_failed 0/4 | 20p/0f |
| openai_gpt56_sol | test_feedback | 2 | 2 | 0 | validation_failed 0/4 | 20p/0f |
| openai_gpt56_sol | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| openai_gpt56_sol | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| openai_gpt56_sol | combined_feedback | 2 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| gemini_36_flash | static_feedback | 0 | 1 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | static_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | static_feedback | 0 | 0 | 2 | pass 4/4 | 11p/5f |
| gemini_36_flash | static_feedback | 0 | 2 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | static_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | static_feedback | 0 | 1 | 0 | pass 4/4 | 18p/0f |
| gemini_36_flash | static_feedback | 0 | 0 | 1 | pass 4/4 | 20p/0f |
| gemini_36_flash | static_feedback | 1 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| gemini_36_flash | test_feedback | 1 | 0 | 2 | pass 4/4 | 20p/0f |
| gemini_36_flash | test_feedback | 2 | 0 | 2 | pass 4/4 | 20p/0f |
| gemini_36_flash | test_feedback | 1 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| gemini_36_flash | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| gemini_36_flash | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | combined_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| gemini_36_flash | combined_feedback | 1 | 0 | 1 | validation_failed 0/4 | 20p/0f |
| gemini_36_flash | combined_feedback | 2 | 0 | 1 | pass 4/4 | 20p/0f |
| gemini_36_flash | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| qwen37_max | static_feedback | 0 | 1 | 0 | pass 4/4 | 20p/0f |
| qwen37_max | static_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| qwen37_max | static_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |
| qwen37_max | test_feedback | 1 | 0 | 1 | validation_failed 0/4 | 20p/0f |
| qwen37_max | test_feedback | 2 | 0 | 1 | validation_failed 0/4 | 20p/0f |
| qwen36_35b_a3b | static_feedback | 0 | 0 | 1 | pass 4/4 | 20p/0f |
| qwen36_35b_a3b | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 0p/18f |
| qwen36_35b_a3b | static_feedback | 1 | 1 | 0 | pass 4/4 | 18p/0f |
| qwen36_35b_a3b | static_feedback | 2 | 1 | 0 | pass 4/4 | 18p/0f |
| qwen36_35b_a3b | static_feedback | 0 | 0 | 2 | pass 4/4 | 20p/0f |
| qwen36_35b_a3b | static_feedback | 1 | 0 | 2 | pass 4/4 | 20p/0f |
| qwen36_35b_a3b | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| qwen36_35b_a3b | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| qwen36_35b_a3b | test_feedback | 1 | 1 | 0 | pass 4/4 | 18p/0f |
| qwen36_35b_a3b | test_feedback | 1 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| qwen36_35b_a3b | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 20p/0f |
| qwen36_35b_a3b | test_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| qwen36_35b_a3b | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| qwen36_35b_a3b | combined_feedback | 2 | 0 | 1 | pass 4/4 | 20p/0f |
| qwen36_35b_a3b | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 0p/18f |
| qwen36_35b_a3b | combined_feedback | 2 | 1 | 0 | validation_failed 0/4 | 0p/18f |
| qwen36_35b_a3b | combined_feedback | 1 | 0 | 2 | pass 4/4 | 20p/0f |
| qwen36_35b_a3b | combined_feedback | 2 | 0 | 1 | pass 4/4 | 18p/2f |
| qwen36_35b_a3b | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| deepseek_v4_flash | static_feedback | 0 | 0 | 2 | validation_failed 0/4 | 16p/0f |
| deepseek_v4_flash | static_feedback | 1 | 0 | 1 | validation_failed 0/4 | 16p/0f |
| deepseek_v4_flash | static_feedback | 2 | 0 | 2 | validation_failed 0/4 | 16p/0f |
| deepseek_v4_flash | static_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | static_feedback | 2 | 2 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | static_feedback | 0 | 0 | 1 | build_failed 0/0 | 0p/0f/+20 |
| deepseek_v4_flash | static_feedback | 1 | 0 | 2 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | static_feedback | 0 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| deepseek_v4_flash | test_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | test_feedback | 1 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | test_feedback | 2 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | test_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| deepseek_v4_flash | test_feedback | 2 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| deepseek_v4_flash | combined_feedback | 1 | 0 | 2 | validation_failed 0/4 | 16p/0f |
| deepseek_v4_flash | combined_feedback | 2 | 0 | 2 | validation_failed 0/4 | 16p/0f |
| deepseek_v4_flash | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | combined_feedback | 2 | 2 | 0 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | combined_feedback | 1 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | combined_feedback | 2 | 0 | 1 | pass 4/4 | 20p/0f |
| deepseek_v4_flash | combined_feedback | 1 | 1 | 0 | validation_failed 0/4 | 11p/7f |
| deepseek_v4_flash | combined_feedback | 2 | 1 | 0 | validation_failed 0/4 | 11p/7f |

**stopped_budget attribution (omp):** 18 of 64 stopped_budget outcomes end on an iteration whose ONLY blocker is an LLOV race finding (TSan 0/not run) — budget burned without a dynamic witness.

## Runtime cost per tool

Median and p95 of the per-sample tool runtime, split by execution model (medians because the distributions are skewed). n = runs with a recorded duration; timeouts are excluded from median/p95 and reported as their own share.

| tool | exec | n | median s | p95 s | timeouts |
| --- | --- | --- | --- | --- | --- |
| compiler | serial | 275 | 2.02 | 3.06 | 0.0% (0/275) |
| compiler | omp | 367 | 1.91 | 3.35 | 0.0% (0/367) |
| compiler | mpi | 469 | 3.01 | 5.15 | 0.0% (0/469) |
| gcc_analyzer | serial | 275 | 1.19 | 2.40 | 0.0% (0/275) |
| gcc_analyzer | omp | 367 | 1.25 | 2.80 | 0.0% (0/367) |
| gcc_analyzer | mpi | 469 | 2.12 | 3.64 | 0.0% (0/469) |
| clang_tidy | serial | 275 | 4.01 | 9.64 | 0.0% (0/275) |
| clang_tidy | omp | 367 | 3.85 | 7.83 | 0.0% (0/367) |
| clang_tidy | mpi | 469 | 4.55 | 7.02 | 0.0% (0/469) |
| cppcheck | serial | 275 | 0.24 | 0.44 | 0.0% (0/275) |
| cppcheck | omp | 367 | 0.25 | 0.42 | 0.0% (0/367) |
| cppcheck | mpi | 469 | 0.61 | 0.99 | 0.0% (0/469) |
| infer | serial | 275 | 17.05 | 28.24 | 0.0% (0/275) |
| infer | omp | 367 | 17.35 | 28.23 | 0.0% (0/367) |
| infer | mpi | 469 | 24.58 | 37.85 | 0.0% (0/469) |
| parcoach | mpi | 469 | 0.03 | 0.77 | 16.0% (75/469) |
| llov | omp | 367 | 0.50 | 1.15 | 0.0% (0/367) |
| asan_ubsan | serial | 275 | 2.70 | 5.67 | 0.0% (0/275) |
| asan_ubsan | omp | 367 | 2.91 | 6.27 | 0.5% (2/367) |
| asan_ubsan | mpi | 469 | 20.26 | 38.97 | 0.0% (0/469) |
| tsan | omp | 367 | 1.86 | 8.55 | 0.5% (2/367) |
| memcheck | serial | 275 | 2.41 | 6.58 | 0.0% (0/275) |
| memcheck | omp | 367 | 2.77 | 36.48 | 2.2% (8/367) |
| must | mpi | 469 | 64.27 | 69.58 | 0.0% (0/469) |

## Generation effort and direct latency

Measurement semantics: thesis/docs/timing-and-effort.md (why batch wall time is not latency, why reasoning tokens are the primary effort metric).

Effort = tokens spent per generation (median over samples, plus the run total). reasoning median NA means the provider reports no reasoning-token field for this model.

| model | iteration | n | input med | output med | reasoning med | reasoning sum |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 0 | 36 | 295 | 330 | 24 | 2513 |
| claude_fable_5 | 1 | 32 | 1403 | 958 | 105 | 21747 |
| claude_fable_5 | 2 | 14 | 2274 | 2086 | 1415 | 40530 |
| claude_opus_5 | 0 | 36 | 295 | 382 | 31 | 5513 |
| claude_opus_5 | 1 | 34 | 1597 | 990 | 113 | 12972 |
| claude_opus_5 | 2 | 17 | 2792 | 1158 | 446 | 8201 |
| deepseek_v4_flash | 0 | 36 | 209 | 1162 | 804 | 53416 |
| deepseek_v4_flash | 1 | 45 | 1124 | 2927 | 2536 | 136579 |
| deepseek_v4_flash | 2 | 29 | 1908 | 2517 | 2041 | 80963 |
| deepseek_v4_pro | 0 | 36 | 209 | 1263 | 1050 | 76601 |
| deepseek_v4_pro | 1 | 41 | 960 | 5246 | 4815 | 210760 |
| deepseek_v4_pro | 2 | 31 | 1890 | 6011 | 5369 | 156552 |
| gemini_31_pro | 0 | 36 | 220 | 220 | 1275 | 57105 |
| gemini_31_pro | 1 | 39 | 1117 | 493 | 1937 | 111530 |
| gemini_31_pro | 2 | 26 | 2046 | 555 | 2603 | 84727 |
| gemini_36_flash | 0 | 36 | 220 | 248 | 1803 | 82635 |
| gemini_36_flash | 1 | 40 | 1113 | 630 | 3766 | 166683 |
| gemini_36_flash | 2 | 31 | 1851 | 656 | 4204 | 164303 |
| openai_gpt55 | 0 | 36 | 212 | 722 | 516 | 39421 |
| openai_gpt55 | 1 | 40 | 1083 | 1719 | 1034 | 65234 |
| openai_gpt55 | 2 | 25 | 2165 | 3919 | 3106 | 79387 |
| openai_gpt56_sol | 0 | 36 | 212 | 522 | 303 | 16785 |
| openai_gpt56_sol | 1 | 34 | 1151 | 1817 | 1071 | 40022 |
| openai_gpt56_sol | 2 | 17 | 2235 | 2583 | 1552 | 29410 |
| qwen36_35b_a3b | 0 | 36 | 228 | 3964 | 3840 | 149015 |
| qwen36_35b_a3b | 1 | 45 | 864 | 6419 | 6121 | 257273 |
| qwen36_35b_a3b | 2 | 25 | 1622 | 7543 | 7090 | 171713 |
| qwen37_max | 0 | 36 | 228 | 2695 | 2493 | 124637 |
| qwen37_max | 1 | 42 | 1163 | 4581 | 4130 | 196458 |
| qwen37_max | 2 | 21 | 1981 | 6486 | 5839 | 123771 |
| qwen3_coder_api | 0 | 36 | 215 | 244 | NA | NA |
| qwen3_coder_api | 1 | 54 | 962 | 511 | NA | NA |
| qwen3_coder_api | 2 | 33 | 2168 | 718 | NA | NA |

Direct request latency (timing_mode == "direct" records ONLY — batch records carry no latency by design, their wall time is provider queue time). Latency additionally includes network and provider load; comparable numbers require one contiguous direct run.

| model | n (direct) | median s | p95 s |
| --- | --- | --- | --- |
| claude_fable_5 | 46 | 13.04 | 83.85 |
| claude_opus_5 | 51 | 12.82 | 20.40 |
| deepseek_v4_flash | 110 | 18.67 | 68.21 |
| deepseek_v4_pro | 108 | 74.69 | 274.77 |
| gemini_31_pro | 65 | 19.86 | 65.65 |
| gemini_36_flash | 71 | 20.06 | 46.36 |
| openai_gpt55 | 65 | 30.08 | 114.92 |
| openai_gpt56_sol | 51 | 42.05 | 100.66 |
| qwen36_35b_a3b | 106 | 38.83 | 60.88 |
| qwen37_max | 99 | 80.03 | 183.67 |
| qwen3_coder_api | 123 | 6.25 | 13.55 |

## Cleaning interventions

Answer-format repairs applied by the pipeline before evaluation (717 assembled sample(s) with cleaning data). auto_closed is an intervention on the measured object; the rest describe the answer format and double as an instruction-following signal.

| model | samples | auto_closed | used_fence | signature_suspect | dropped_leading | relocated_includes |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 57 | 0.0% (0/57) | 0.0% (0/57) | 0.0% (0/57) | 0.0% (0/57) | 3.5% (2/57) |
| claude_opus_5 | 61 | 1.6% (1/61) | 29.5% (18/61) | 0.0% (0/61) | 0.0% (0/61) | 0.0% (0/61) |
| deepseek_v4_flash | 68 | 7.4% (5/68) | 80.9% (55/68) | 0.0% (0/68) | 0.0% (0/68) | 32.4% (22/68) |
| deepseek_v4_pro | 70 | 11.4% (8/70) | 32.9% (23/70) | 0.0% (0/70) | 1.4% (1/70) | 15.7% (11/70) |
| gemini_31_pro | 65 | 13.8% (9/65) | 3.1% (2/65) | 0.0% (0/65) | 0.0% (0/65) | 0.0% (0/65) |
| gemini_36_flash | 68 | 0.0% (0/68) | 10.3% (7/68) | 0.0% (0/68) | 0.0% (0/68) | 25.0% (17/68) |
| openai_gpt55 | 63 | 6.3% (4/63) | 0.0% (0/63) | 0.0% (0/63) | 0.0% (0/63) | 0.0% (0/63) |
| openai_gpt56_sol | 58 | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/58) |
| qwen36_35b_a3b | 68 | 2.9% (2/68) | 1.5% (1/68) | 0.0% (0/68) | 0.0% (0/68) | 0.0% (0/68) |
| qwen37_max | 65 | 9.2% (6/65) | 16.9% (11/65) | 0.0% (0/65) | 0.0% (0/65) | 7.7% (5/65) |
| qwen3_coder_api | 74 | 1.4% (1/74) | 100.0% (74/74) | 0.0% (0/74) | 0.0% (0/74) | 0.0% (0/74) |

By iteration (does the answer format change under repair?):

| iteration | samples | auto_closed | used_fence | signature_suspect |
| --- | --- | --- | --- | --- |
| 0 | 396 | 8.3% (33/396) | 21.7% (86/396) | 0.0% (0/396) |
| 1 | 189 | 0.0% (0/189) | 30.7% (58/189) | 0.0% (0/189) |
| 2 | 132 | 2.3% (3/132) | 35.6% (47/132) | 0.0% (0/132) |

## Data completeness

Rows total: 1903, incomplete: 0

## Effective config snapshot

Frozen at run time (run_manifest.json, created 2026-08-12T12:46:24.983937Z by stage 'generation', git 6846d689fd81).

Enhanced specs pinned: thesis/results/cache/enhanced/specs.jsonl — sha256 0fe9561e1350…, 483 specs.

### stages.repair
```json
{
  "api_mode": "direct",
  "api_mode_overrides": {},
  "enabled": true,
  "external_tool_commands": {
    "llov": "docker run --rm -u 0 -v \"{host_repo}:/workspace\" -w /workspace pareval-llov python3.8 thesis/evaluation/run_static_analysis.py --config {config} --profile {profile} --run-id {run_id} --model-id {model_id} --tools {tools}",
    "parcoach": "docker run --rm -u 0 -v \"{host_repo}:/workspace\" -w /workspace registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1 python3 thesis/evaluation/run_static_analysis.py --config {config} --profile {profile} --run-id {run_id} --model-id {model_id} --tools {tools}"
  },
  "external_tools": [
    "parcoach",
    "llov"
  ],
  "external_tools_mode": "docker",
  "feedback": {
    "history_message_max_chars": 80,
    "include_non_blocking": false,
    "low_confidence_prefix": "Low-confidence hint (tool precision ~0.5 on validation suites) \u2014 verify at the given location before changing code:\n",
    "mismatch_report_max_indices": 3,
    "templates": {
      "current_header": "## Current version (fix this)",
      "driver_error": "error at the call site in the test driver (your function name/signature likely does not match the expected interface): {message}\n",
      "feedback_header": "## Analysis feedback on the current version",
      "history_iteration_header": "## Iteration {n} (previous attempt)",
      "instruction": "Output the complete corrected function. Line numbers in the feedback refer to the current version shown above.\n",
      "non_blocking_header": "Non-blocking quality hints (optional improvements, not errors):\n",
      "task_header": "## Original task"
    }
  },
  "history_mode": "full",
  "host_repo_path": null,
  "low_confidence_stop_mode": "grace_once",
  "max_iterations": 2,
  "strategies": {
    "combined_feedback": {
      "sources": [
        "compiler_errors",
        "static_findings",
        "correctness_verdicts",
        "dynamic_findings"
      ]
    },
    "static_feedback": {
      "sources": [
        "compiler_errors",
        "static_findings"
      ]
    },
    "test_feedback": {
      "sources": [
        "compiler_errors",
        "correctness_verdicts",
        "dynamic_findings"
      ]
    }
  },
  "variants": [
    "static_feedback",
    "test_feedback",
    "combined_feedback"
  ]
}
```

### stages.enhanced_tests
```json
{
  "baseline_prompt_max_chars": 12000,
  "enabled": true,
  "enhanced_launch": {
    "mpi_ranks": 4,
    "omp_threads": 4
  },
  "execution_models": [
    "serial",
    "omp",
    "mpi"
  ],
  "explicit_values_max_size": 64,
  "jobs": {
    "mpi": 1,
    "omp": 1,
    "serial": 2
  },
  "llm_specs_max": 8,
  "llm_specs_min": 5,
  "max_spec_size": 4096,
  "offered_patterns": [
    "random",
    "all_zeros",
    "all_same",
    "ascending",
    "descending",
    "alternating",
    "extreme_values",
    "duplicate_at",
    "sorted_except_one",
    "spike_at",
    "explicit_values"
  ],
  "output_file_name": "enhanced_tests.jsonl",
  "run_timeout_seconds": 60,
  "spec_model": "glm_5_2",
  "spec_system_prompt": "You are an expert in software testing and C++ numerical code.\nYou design minimal, high-value edge-case test inputs.\nYou respond with STRICT JSON only: a single JSON array, no markdown\nfences, no prose. Every element must follow the schema given by the\nuser exactly.\n",
  "specs_file": "thesis/results/cache/enhanced/specs.jsonl",
  "static_base_sizes": [
    0,
    1,
    2,
    7
  ],
  "target_cases_per_benchmark": 20
}
```
