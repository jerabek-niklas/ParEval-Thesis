# Consolidated overview — run smoke_003

Generated 2026-08-07T19:43:41.465899Z. Source: stage JSONLs joined on (sample_id, variant, iteration); see overview.csv for the flat table. Trajectories are CARRY-FORWARD: a stopped sample keeps contributing its final artifact to later iterations (the population stays constant). Enhanced rates count pass over all non-gated specs (gated = baseline_incompatible + numerically_unstable).

## Pass-rate trajectories (ParEval vs. enhanced — overfitting view)

### static_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 33 | 72.7% (24/33) | 97.9% (646/660) |
| 1 | 33 | 72.7% (24/33) | 97.9% (646/660) |
| 2 | 33 | 69.7% (23/33) | 95.9% (633/660) |

### test_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 33 | 72.7% (24/33) | 97.9% (646/660) |
| 1 | 33 | 84.8% (28/33) | 94.4% (623/660) |
| 2 | 33 | 87.9% (29/33) | 97.4% (643/660) |

### combined_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 33 | 72.7% (24/33) | 97.9% (646/660) |
| 1 | 33 | 81.8% (27/33) | 94.8% (626/660) |
| 2 | 33 | 84.8% (28/33) | 97.9% (646/660) |

## Stop-reason distribution

### static_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 4 |
| stopped_clean | 29 |

### test_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 4 |
| stopped_tests_pass | 29 |

### combined_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 10 |
| stopped_clean | 23 |

## Blocking findings per tool over iterations (convergence)

Counts are per produced artifact at that iteration (no carry-forward — this shows what the loop's artifacts still contain). ALL enabled tools are listed, not just those with findings.

### static_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 0 | 12 | 21 | 0 | 0 | 0 | 3 | 0 | n/a | 0 | 0 |
| 1 | 8 | 0 | 16 | 2 | 0 | 0 | 0 | 2 | 0 | n/a | 0 | 1 |
| 2 | 5 | 0 | 13 | 3 | 0 | 0 | 0 | 1 | 0 | n/a | 0 | 1 |

### test_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 0 | 12 | 21 | 0 | 0 | 0 | 3 | 0 | n/a | 0 | 0 |
| 1 | 9 | 7 | 0 | 8 | 1 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 2 | 5 | 0 | 0 | 6 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |

### combined_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 0 | 12 | 21 | 0 | 0 | 0 | 3 | 0 | n/a | 0 | 0 |
| 1 | 16 | 64 | 14 | 20 | 1 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| 2 | 12 | 0 | 12 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

## Blocking findings by error class

Cells are `findings (samples)`: finding sums double-count when several tools report the same defect (redundancy by design); the sample count deduplicates across tools and is the citable number. Classes: thesis/evaluation/finding_classes.py.

**static_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 12 (3) | 21 (5) | 3 (3) | 0 (0) | 0 (0) | 0 (0) |
| 1 | 8 | 16 (3) | 2 (2) | 2 (2) | 1 (1) | 0 (0) | 0 (0) |
| 2 | 5 | 13 (3) | 3 (1) | 1 (1) | 1 (1) | 0 (0) | 0 (0) |

**test_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 12 (3) | 21 (5) | 3 (3) | 0 (0) | 0 (0) | 0 (0) |
| 1 | 9 | 0 (0) | 8 (2) | 2 (1) | 0 (0) | 7 (1) | 1 (1) |
| 2 | 5 | 0 (0) | 6 (1) | 2 (1) | 0 (0) | 0 (0) | 0 (0) |

**combined_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 33 | 12 (3) | 21 (5) | 3 (3) | 0 (0) | 0 (0) | 0 (0) |
| 1 | 16 | 14 (3) | 2 (2) | 4 (3) | 0 (0) | 82 (1) | 1 (1) |
| 2 | 12 | 12 (4) | 1 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |

**static_feedback — class x model (final state, carry-forward):**

| model | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 3 | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 3 | 7 (1) | 3 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 3 | 1 (1) | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) |
| gemini_31_pro | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_36_flash | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt56_sol | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 3 | 5 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**test_feedback — class x model (final state, carry-forward):**

| model | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 3 | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 3 | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 3 | 5 (1) | 3 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 3 | 1 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_31_pro | 3 | 0 (0) | 5 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_36_flash | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 3 | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt56_sol | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 3 | 0 (0) | 0 (0) | 2 (1) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 3 | 6 (1) | 4 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 3 | 0 (0) | 6 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**combined_feedback — class x model (final state, carry-forward):**

| model | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 3 | 0 (0) | 0 (0) | 1 (1) | 0 (0) | 0 (0) | 0 (0) |
| claude_opus_5 | 3 | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_flash | 3 | 5 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| deepseek_v4_pro | 3 | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_31_pro | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| gemini_36_flash | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt55 | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| openai_gpt56_sol | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen36_35b_a3b | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen37_max | 3 | 5 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| qwen3_coder_api | 3 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**class x execution model at iteration 0 (initial generations):**

| exec | n | null_deref | arithmetic | race | mpi_usage | build | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 11 | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| omp | 11 | 0 (0) | 0 (0) | 3 (3) | 0 (0) | 0 (0) | 0 (0) |
| mpi | 11 | 12 (3) | 21 (5) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

## Breakdown by problem type and execution model (final state)

### static_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 69.7% (23/33) | 95.9% (633/660) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 11 | 72.7% (8/11) | 87.7% (193/220) |
| omp | 11 | 63.6% (7/11) | 100.0% (220/220) |
| serial | 11 | 72.7% (8/11) | 100.0% (220/220) |

### test_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 87.9% (29/33) | 97.4% (643/660) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 11 | 90.9% (10/11) | 92.3% (203/220) |
| omp | 11 | 81.8% (9/11) | 100.0% (220/220) |
| serial | 11 | 90.9% (10/11) | 100.0% (220/220) |

### combined_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 33 | 84.8% (28/33) | 97.9% (646/660) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 11 | 90.9% (10/11) | 93.6% (206/220) |
| omp | 11 | 72.7% (8/11) | 100.0% (220/220) |
| serial | 11 | 90.9% (10/11) | 100.0% (220/220) |

## "Statically clean but incorrect" (static_feedback, design §9)

Samples stopping clean (no blocking static findings): 29

- ParEval-incorrect among them: 31.0% (9/29)
- enhanced-failing among them: 3.4% (1/29)

## Enhanced tests by execution model

Spec-run verdicts per execution model (gates are SERIAL: sight omp/mpi crash/timeout manually for driver divergence, and expect rounding signatures in fail — see docs/enhanced-tests-parallel.md).

| exec | samples | pass | fail | crash | timeout | build_failed | runtime_error | gated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 19 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| omp | 36 | 677 | 3 | 0 | 0 | 40 | 0 | 0 |
| mpi | 33 | 560 | 100 | 0 | 0 | 0 | 0 | 0 |

## Runtime cost per tool

Median and p95 of the per-sample tool runtime, split by execution model (medians because the distributions are skewed). n = runs with a recorded duration; timeouts are excluded from median/p95 and reported as their own share.

| tool | exec | n | median s | p95 s | timeouts |
| --- | --- | --- | --- | --- | --- |
| compiler | serial | 19 | 2.15 | 3.74 | 0.0% (0/19) |
| compiler | omp | 36 | 2.06 | 3.41 | 0.0% (0/36) |
| compiler | mpi | 33 | 3.58 | 4.66 | 0.0% (0/33) |
| gcc_analyzer | serial | 19 | 1.48 | 3.02 | 0.0% (0/19) |
| gcc_analyzer | omp | 36 | 1.19 | 2.62 | 0.0% (0/36) |
| gcc_analyzer | mpi | 33 | 2.19 | 2.82 | 0.0% (0/33) |
| clang_tidy | serial | 19 | 3.00 | 4.79 | 0.0% (0/19) |
| clang_tidy | omp | 36 | 2.94 | 3.64 | 0.0% (0/36) |
| clang_tidy | mpi | 33 | 3.23 | 4.28 | 0.0% (0/33) |
| cppcheck | serial | 19 | 0.23 | 0.31 | 0.0% (0/19) |
| cppcheck | omp | 36 | 0.25 | 0.34 | 0.0% (0/36) |
| cppcheck | mpi | 33 | 0.63 | 0.90 | 0.0% (0/33) |
| infer | serial | 19 | 16.35 | 27.58 | 0.0% (0/19) |
| infer | omp | 36 | 15.86 | 20.95 | 0.0% (0/36) |
| infer | mpi | 33 | 23.57 | 34.81 | 0.0% (0/33) |
| parcoach | mpi | 33 | 0.02 | 0.03 | 45.5% (15/33) |
| llov | omp | 36 | 0.68 | 1.82 | 0.0% (0/36) |
| asan_ubsan | serial | 19 | 3.12 | 5.90 | 0.0% (0/19) |
| asan_ubsan | omp | 36 | 5.04 | 8.32 | 0.0% (0/36) |
| asan_ubsan | mpi | 33 | 23.37 | 42.88 | 6.1% (2/33) |
| tsan | omp | 20 | 2.44 | 4.06 | 0.0% (0/20) |
| memcheck | serial | 19 | 7.17 | 11.21 | 0.0% (0/19) |
| memcheck | omp | 36 | 28.12 | 54.15 | 0.0% (0/36) |
| must | mpi | 33 | 65.62 | 125.16 | 0.0% (0/33) |

## Generation effort and direct latency

Measurement semantics: thesis/docs/timing-and-effort.md (why batch wall time is not latency, why reasoning tokens are the primary effort metric).

Effort = tokens spent per generation (median over samples, plus the run total). reasoning median NA means the provider reports no reasoning-token field for this model.

| model | iteration | n | input med | output med | reasoning med | reasoning sum |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 0 | 3 | 272 | 183 | 0 | 29 |
| claude_fable_5 | 1 | 2 | 719 | 285 | 57 | 115 |
| claude_fable_5 | 2 | 2 | 1161 | 448 | 71 | 143 |
| claude_opus_5 | 0 | 3 | 272 | 241 | 81 | 490 |
| claude_opus_5 | 1 | 2 | 725 | 313 | 51 | 103 |
| claude_opus_5 | 2 | 2 | 1201 | 542 | 113 | 227 |
| deepseek_v4_flash | 0 | 3 | 183 | 1821 | 1587 | 6489 |
| deepseek_v4_flash | 1 | 2 | 1499 | 2123 | 1355 | 2710 |
| deepseek_v4_flash | 2 | 2 | 2838 | 4143 | 3223 | 6446 |
| deepseek_v4_pro | 0 | 3 | 183 | 2541 | 2282 | 10693 |
| deepseek_v4_pro | 1 | 4 | 1166 | 7989 | 6060 | 24170 |
| deepseek_v4_pro | 2 | 4 | 2066 | 7631 | 6651 | 22200 |
| gemini_31_pro | 0 | 3 | 195 | 158 | 1505 | 4918 |
| gemini_31_pro | 1 | 2 | 1029 | 468 | 1456 | 2912 |
| gemini_36_flash | 0 | 3 | 195 | 139 | 1274 | 5667 |
| openai_gpt55 | 0 | 3 | 186 | 767 | 516 | 1982 |
| openai_gpt55 | 1 | 2 | 626 | 3539 | 3273 | 6547 |
| openai_gpt56_sol | 0 | 3 | 186 | 416 | 239 | 860 |
| qwen36_35b_a3b | 0 | 3 | 202 | 5590 | 5342 | 16176 |
| qwen36_35b_a3b | 1 | 6 | 854 | 7054 | 6765 | 38384 |
| qwen36_35b_a3b | 2 | 3 | 2132 | 4961 | 4737 | 16415 |
| qwen37_max | 0 | 3 | 202 | 3841 | 3585 | 13916 |
| qwen37_max | 1 | 6 | 1733 | 5426 | 4818 | 29272 |
| qwen37_max | 2 | 3 | 3654 | 6752 | 5611 | 16135 |
| qwen3_coder_api | 0 | 3 | 189 | 256 | NA | NA |
| qwen3_coder_api | 1 | 7 | 1695 | 378 | NA | NA |
| qwen3_coder_api | 2 | 6 | 2136 | 366 | NA | NA |

Direct request latency (timing_mode == "direct" records ONLY — batch records carry no latency by design, their wall time is provider queue time). Latency additionally includes network and provider load; comparable numbers require one contiguous direct run.

| model | n (direct) | median s | p95 s |
| --- | --- | --- | --- |
| claude_fable_5 | 7 | 9.46 | 11.38 |
| claude_opus_5 | 7 | 4.78 | 11.00 |
| deepseek_v4_flash | 7 | 35.10 | 53.79 |
| deepseek_v4_pro | 11 | 95.53 | 277.45 |
| gemini_31_pro | 5 | 25.87 | 46.87 |
| gemini_36_flash | 3 | 7.64 | 19.12 |
| openai_gpt55 | 5 | 23.44 | 136.19 |
| openai_gpt56_sol | 3 | 8.43 | 26.65 |
| qwen36_35b_a3b | 12 | 47.79 | 77.31 |
| qwen37_max | 12 | 83.86 | 155.13 |
| qwen3_coder_api | 16 | 6.30 | 46.38 |

## Cleaning interventions

Answer-format repairs applied by the pipeline before evaluation (61 assembled sample(s) with cleaning data). auto_closed is an intervention on the measured object; the rest describe the answer format and double as an instruction-following signal.

| model | samples | auto_closed | used_fence | signature_suspect | dropped_leading | relocated_includes |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 5 | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) |
| claude_opus_5 | 5 | 0.0% (0/5) | 40.0% (2/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) |
| deepseek_v4_flash | 5 | 0.0% (0/5) | 80.0% (4/5) | 0.0% (0/5) | 0.0% (0/5) | 20.0% (1/5) |
| deepseek_v4_pro | 7 | 0.0% (0/7) | 57.1% (4/7) | 0.0% (0/7) | 0.0% (0/7) | 42.9% (3/7) |
| gemini_31_pro | 4 | 25.0% (1/4) | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) |
| gemini_36_flash | 3 | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) | 33.3% (1/3) |
| openai_gpt55 | 4 | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) |
| openai_gpt56_sol | 3 | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) |
| qwen36_35b_a3b | 8 | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) |
| qwen37_max | 8 | 0.0% (0/8) | 37.5% (3/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) |
| qwen3_coder_api | 9 | 0.0% (0/9) | 100.0% (9/9) | 0.0% (0/9) | 0.0% (0/9) | 0.0% (0/9) |

By iteration (does the answer format change under repair?):

| iteration | samples | auto_closed | used_fence | signature_suspect |
| --- | --- | --- | --- | --- |
| 0 | 33 | 3.0% (1/33) | 24.2% (8/33) | 0.0% (0/33) |
| 1 | 16 | 0.0% (0/16) | 37.5% (6/16) | 0.0% (0/16) |
| 2 | 12 | 0.0% (0/12) | 66.7% (8/12) | 0.0% (0/12) |

## Data completeness

Rows total: 154, incomplete: 0

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
