# Consolidated overview — run smoke_002

Generated 2026-08-06T09:46:06.259773Z. Source: stage JSONLs joined on (sample_id, variant, iteration); see overview.csv for the flat table. Trajectories are CARRY-FORWARD: a stopped sample keeps contributing its final artifact to later iterations (the population stays constant). Enhanced rates count pass over all non-gated specs (gated = baseline_incompatible + numerically_unstable).

## Pass-rate trajectories (ParEval vs. enhanced — overfitting view)

### static_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 33 | 78.8% (26/33) | 99.6% (235/236) |
| 1 | 33 | 75.8% (25/33) | 100.0% (228/228) |
| 2 | 33 | 75.8% (25/33) | 100.0% (228/228) |
| 3 | 33 | 75.8% (25/33) | 100.0% (228/228) |

### test_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 33 | 78.8% (26/33) | 99.6% (235/236) |
| 1 | 33 | 84.8% (28/33) | 100.0% (228/228) |
| 2 | 33 | 93.9% (31/33) | 100.0% (228/228) |
| 3 | 33 | 93.9% (31/33) | 100.0% (228/228) |

### combined_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 33 | 78.8% (26/33) | 99.6% (235/236) |
| 1 | 33 | 84.8% (28/33) | 100.0% (228/228) |
| 2 | 33 | 84.8% (28/33) | 100.0% (228/228) |
| 3 | 33 | 90.9% (30/33) | 100.0% (228/228) |

## Stop-reason distribution

### static_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 1 |
| stopped_clean | 32 |

### test_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 2 |
| stopped_tests_pass | 31 |

### combined_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 7 |
| stopped_clean | 26 |

## Blocking findings per tool over iterations (convergence)

Counts are per produced artifact at that iteration (no carry-forward — this shows what the loop's artifacts still contain). ALL enabled tools are listed, not just those with findings.

### static_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 0 | 5 | 26 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 1 |
| 1 | 15 | 3 | 3 | 7 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 1 |
| 2 | 7 | 0 | 3 | 3 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 |
| 3 | 4 | 0 | 1 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### test_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 0 | 5 | 26 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 1 |
| 1 | 7 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 2 | 6 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 3 | 2 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 0 | n/a | 0 | n/a |

### combined_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 0 | 5 | 26 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 1 |
| 1 | 21 | 1 | 3 | 5 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 1 |
| 2 | 12 | 1 | 1 | 1 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| 3 | 9 | 0 | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 |

## Blocking findings by error class

Cells are `findings (samples)`: finding sums double-count when several tools report the same defect (redundancy by design); the sample count deduplicates across tools and is the citable number. Classes: thesis/evaluation/finding_classes.py.

**static_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 1 (1) | 4 (2) | 25 (6) | 8 (7) | 1 (1) | 0 (0) | 1 (1) |
| 1 | 15 | 0 (0) | 3 (2) | 4 (1) | 4 (4) | 1 (1) | 6 (1) | 0 (0) |
| 2 | 7 | 0 (0) | 3 (3) | 3 (1) | 2 (2) | 1 (1) | 0 (0) | 0 (0) |
| 3 | 4 | 0 (0) | 1 (1) | 5 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**test_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 1 (1) | 4 (2) | 25 (6) | 8 (7) | 1 (1) | 0 (0) | 1 (1) |
| 1 | 7 | 0 (0) | 1 (1) | 1 (1) | 0 (0) | 1 (1) | 0 (0) | 0 (0) |
| 2 | 6 | 0 (0) | 1 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| 3 | 2 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**combined_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 1 (1) | 4 (2) | 25 (6) | 8 (7) | 1 (1) | 0 (0) | 1 (1) |
| 1 | 21 | 0 (0) | 3 (2) | 4 (3) | 5 (5) | 1 (1) | 2 (1) | 0 (0) |
| 2 | 12 | 0 (0) | 1 (1) | 0 (0) | 3 (3) | 0 (0) | 2 (1) | 0 (0) |
| 3 | 9 | 0 (0) | 2 (2) | 0 (0) | 2 (2) | 1 (1) | 0 (0) | 0 (0) |

**static_feedback — class x model (final state, carry-forward):**

| model | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 3 | 0 (0) | 1 (1) | 5 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_31_pro | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_36_flash | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt56_sol | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**test_feedback — class x model (final state, carry-forward):**

| model | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 3 | 0 (0) | 0 (0) | 5 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 3 | 0 (0) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 3 | 1 (1) | 3 (1) | 13 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 3 | 0 (0) | 1 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_31_pro | 3 | 0 (0) | 0 (0) | 2 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| gemini_36_flash | 3 | 0 (0) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 3 | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 1 (1) |
| openai_gpt56_sol | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 3 | 0 (0) | 0 (0) | 2 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 3 | 0 (0) | 0 (0) | 2 (1) | 2 (1) | 0 (0) | 0 (0) | 0 (0) |

**combined_feedback — class x model (final state, carry-forward):**

| model | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 3 | 0 (0) | 1 (1) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 3 | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) |
| gemini_31_pro | 3 | 0 (0) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| gemini_36_flash | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt56_sol | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**class x execution model at iteration 0 (initial generations):**

| exec | n | uninitialized | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 11 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| omp | 11 | 0 (0) | 0 (0) | 1 (1) | 8 (7) | 0 (0) | 0 (0) | 0 (0) |
| mpi | 11 | 1 (1) | 4 (2) | 24 (5) | 0 (0) | 1 (1) | 0 (0) | 1 (1) |

## Breakdown by problem type and execution model (final state)

### static_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 75.8% (25/33) | 100.0% (228/228) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 11 | 90.9% (10/11) | NA |
| omp | 11 | 81.8% (9/11) | 100.0% (8/8) |
| serial | 11 | 54.5% (6/11) | 100.0% (220/220) |

### test_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 93.9% (31/33) | 100.0% (228/228) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 11 | 100.0% (11/11) | NA |
| omp | 11 | 100.0% (11/11) | 100.0% (8/8) |
| serial | 11 | 81.8% (9/11) | 100.0% (220/220) |

### combined_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 90.9% (30/33) | 100.0% (228/228) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 11 | 100.0% (11/11) | NA |
| omp | 11 | 81.8% (9/11) | 100.0% (8/8) |
| serial | 11 | 90.9% (10/11) | 100.0% (220/220) |

## "Statically clean but incorrect" (static_feedback, design §9)

Samples stopping clean (no blocking static findings): 32

- ParEval-incorrect among them: 25.0% (8/32)
- enhanced-failing among them: 0.0% (0/12)

## Enhanced tests by execution model

Spec-run verdicts per execution model (gates are SERIAL: sight omp/mpi crash/timeout manually for driver divergence, and expect rounding signatures in fail — see docs/enhanced-tests-parallel.md).

| exec | samples | pass | fail | crash | timeout | build_failed | runtime_error | gated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 32 | 640 | 0 | 0 | 0 | 0 | 0 | 0 |
| omp | 1 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| mpi | 1 | 7 | 1 | 0 | 0 | 0 | 0 | 0 |

## Runtime cost per tool

Median and p95 of the per-sample tool runtime, split by execution model (medians because the distributions are skewed). n = runs with a recorded duration; timeouts are excluded from median/p95 and reported as their own share.

| tool | exec | n | median s | p95 s | timeouts |
| --- | --- | --- | --- | --- | --- |
| compiler | serial | 32 | 8.82 | 11.36 | 0.0% (0/32) |
| compiler | omp | 49 | 9.35 | 10.11 | 0.0% (0/49) |
| compiler | mpi | 35 | 13.21 | 53.15 | 0.0% (0/35) |
| gcc_analyzer | serial | 32 | 4.82 | 6.08 | 0.0% (0/32) |
| gcc_analyzer | omp | 49 | 5.45 | 6.04 | 0.0% (0/49) |
| gcc_analyzer | mpi | 35 | 7.34 | 24.68 | 0.0% (0/35) |
| clang_tidy | serial | 32 | 6.00 | 7.10 | 0.0% (0/32) |
| clang_tidy | omp | 49 | 6.35 | 7.33 | 0.0% (0/49) |
| clang_tidy | mpi | 35 | 7.38 | 36.99 | 0.0% (0/35) |
| cppcheck | serial | 32 | 0.93 | 1.27 | 0.0% (0/32) |
| cppcheck | omp | 49 | 1.11 | 1.28 | 0.0% (0/49) |
| cppcheck | mpi | 35 | 2.43 | 10.05 | 0.0% (0/35) |
| infer | serial | 32 | 29.50 | 37.93 | 0.0% (0/32) |
| infer | omp | 49 | 29.38 | 33.41 | 0.0% (0/49) |
| infer | mpi | 35 | 43.40 | 224.16 | 0.0% (0/35) |
| parcoach | mpi | 35 | 0.03 | 1.91 | 8.6% (3/35) |
| llov | omp | 49 | 2.09 | 4.54 | 0.0% (0/49) |
| asan_ubsan | serial | 32 | 10.65 | 17.09 | 0.0% (0/32) |
| asan_ubsan | omp | 49 | 12.89 | 14.95 | 0.0% (0/49) |
| asan_ubsan | mpi | 35 | 42.41 | 45.64 | 0.0% (0/35) |
| tsan | omp | 49 | 14.75 | 18.56 | 0.0% (0/49) |
| memcheck | serial | 32 | 15.72 | 27.61 | 0.0% (0/32) |
| memcheck | omp | 49 | 35.43 | 67.48 | 4.1% (2/49) |
| must | mpi | 35 | 74.14 | 89.13 | 0.0% (0/35) |

## Generation effort and direct latency

Measurement semantics: thesis/docs/timing-and-effort.md (why batch wall time is not latency, why reasoning tokens are the primary effort metric).

Effort = tokens spent per generation (median over samples, plus the run total). reasoning median NA means the provider reports no reasoning-token field for this model.

| model | iteration | n | input med | output med | reasoning med | reasoning sum |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 0 | 3 | 270 | 183 | 0 | 160 |
| claude_fable_5 | 1 | 4 | 1083 | 478 | 31 | 159 |
| claude_fable_5 | 2 | 2 | 1148 | 407 | 79 | 159 |
| claude_fable_5 | 3 | 2 | 1711 | 904 | 502 | 1005 |
| claude_opus_5 | 0 | 3 | 270 | 298 | 102 | 471 |
| claude_opus_5 | 1 | 2 | 723 | 352 | 74 | 148 |
| claude_opus_5 | 2 | 1 | 1266 | 293 | 0 | 0 |
| deepseek_v4_flash | 0 | 3 | 182 | 612 | 387 | 4036 |
| deepseek_v4_flash | 1 | 6 | 651 | 4398 | 3887 | 23635 |
| deepseek_v4_flash | 2 | 5 | 1019 | 3949 | 3185 | 15092 |
| deepseek_v4_flash | 3 | 5 | 1387 | 3120 | 2108 | 13293 |
| deepseek_v4_pro | 0 | 3 | 182 | 1534 | 1369 | 8100 |
| deepseek_v4_pro | 1 | 5 | 1067 | 5059 | 4378 | 24759 |
| deepseek_v4_pro | 2 | 5 | 1886 | 4052 | 3115 | 21768 |
| deepseek_v4_pro | 3 | 2 | 3157 | 5031 | 4231 | 8462 |
| gemini_31_pro | 0 | 3 | 194 | 136 | 1377 | 4242 |
| gemini_31_pro | 1 | 4 | 722 | 315 | 1732 | 9128 |
| gemini_31_pro | 2 | 1 | 915 | 191 | 1227 | 1227 |
| gemini_31_pro | 3 | 1 | 1284 | 198 | 1811 | 1811 |
| gemini_36_flash | 0 | 3 | 194 | 202 | 1788 | 6330 |
| gemini_36_flash | 1 | 2 | 588 | 173 | 1848 | 3697 |
| gemini_36_flash | 2 | 2 | 916 | 198 | 2231 | 4462 |
| openai_gpt55 | 0 | 3 | 185 | 687 | 516 | 1944 |
| openai_gpt55 | 1 | 4 | 685 | 770 | 494 | 1743 |
| openai_gpt56_sol | 0 | 3 | 185 | 608 | 456 | 1621 |
| qwen36_35b_a3b | 0 | 3 | 201 | 6057 | 5921 | 17370 |
| qwen36_35b_a3b | 1 | 4 | 944 | 6478 | 6238 | 24815 |
| qwen36_35b_a3b | 2 | 3 | 1549 | 8436 | 8192 | 24576 |
| qwen36_35b_a3b | 3 | 2 | 1681 | 8438 | 8192 | 16384 |
| qwen37_max | 0 | 3 | 201 | 2428 | 2231 | 10537 |
| qwen37_max | 1 | 6 | 704 | 4240 | 3956 | 23906 |
| qwen37_max | 2 | 2 | 958 | 3583 | 3425 | 6851 |
| qwen3_coder_api | 0 | 3 | 188 | 242 | NA | NA |
| qwen3_coder_api | 1 | 6 | 688 | 378 | NA | NA |
| qwen3_coder_api | 2 | 4 | 1051 | 347 | NA | NA |
| qwen3_coder_api | 3 | 3 | 1436 | 387 | NA | NA |

Direct request latency (timing_mode == "direct" records ONLY — batch records carry no latency by design, their wall time is provider queue time). Latency additionally includes network and provider load; comparable numbers require one contiguous direct run.

| model | n (direct) | median s | p95 s |
| --- | --- | --- | --- |
| claude_fable_5 | 11 | 7.24 | 15.93 |
| claude_opus_5 | 6 | 6.75 | 11.88 |
| deepseek_v4_flash | 19 | 39.64 | 166.81 |
| deepseek_v4_pro | 15 | 113.72 | 27587.46 |
| gemini_31_pro | 9 | 23.64 | 36.67 |
| gemini_36_flash | 7 | 11.81 | 19.59 |
| openai_gpt55 | 7 | 12.39 | 26.57 |
| openai_gpt56_sol | 3 | 13.18 | 28.00 |
| qwen36_35b_a3b | 12 | 65.12 | 85.18 |
| qwen37_max | 11 | 70.26 | 116.55 |
| qwen3_coder_api | 16 | 5.27 | 47.72 |

## Cleaning interventions

Answer-format repairs applied by the pipeline before evaluation (79 assembled sample(s) with cleaning data). auto_closed is an intervention on the measured object; the rest describe the answer format and double as an instruction-following signal.

| model | samples | auto_closed | used_fence | signature_suspect | dropped_leading | relocated_includes |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 7 | 0.0% (0/7) | 42.9% (3/7) | 0.0% (0/7) | 0.0% (0/7) | 0.0% (0/7) |
| claude_opus_5 | 5 | 0.0% (0/5) | 80.0% (4/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) |
| deepseek_v4_flash | 12 | 0.0% (0/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) | 0.0% (0/12) |
| deepseek_v4_pro | 8 | 0.0% (0/8) | 62.5% (5/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) |
| gemini_31_pro | 7 | 14.3% (1/7) | 0.0% (0/7) | 0.0% (0/7) | 0.0% (0/7) | 0.0% (0/7) |
| gemini_36_flash | 5 | 0.0% (0/5) | 40.0% (2/5) | 0.0% (0/5) | 0.0% (0/5) | 20.0% (1/5) |
| openai_gpt55 | 5 | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) |
| openai_gpt56_sol | 3 | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) |
| qwen36_35b_a3b | 9 | 0.0% (0/9) | 0.0% (0/9) | 0.0% (0/9) | 0.0% (0/9) | 0.0% (0/9) |
| qwen37_max | 8 | 0.0% (0/8) | 12.5% (1/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) |
| qwen3_coder_api | 10 | 0.0% (0/10) | 100.0% (10/10) | 0.0% (0/10) | 0.0% (0/10) | 0.0% (0/10) |

By iteration (does the answer format change under repair?):

| iteration | samples | auto_closed | used_fence | signature_suspect |
| --- | --- | --- | --- | --- |
| 0 | 33 | 3.0% (1/33) | 36.4% (12/33) | 0.0% (0/33) |
| 1 | 21 | 0.0% (0/21) | 52.4% (11/21) | 0.0% (0/21) |
| 2 | 15 | 0.0% (0/15) | 46.7% (7/15) | 0.0% (0/15) |
| 3 | 10 | 0.0% (0/10) | 70.0% (7/10) | 0.0% (0/10) |

## Data completeness

Rows total: 182, incomplete: 0

## Effective config snapshot

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
  "external_tools_mode": "manual",
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
    "serial"
  ],
  "explicit_values_max_size": 64,
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
  "run_timeout_seconds": 30,
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
