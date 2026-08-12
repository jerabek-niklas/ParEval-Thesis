# Consolidated overview — run smoke_004

Generated 2026-08-12T11:11:53.820207Z. Source: stage JSONLs joined on (sample_id, variant, iteration); see overview.csv for the flat table. Trajectories are CARRY-FORWARD: a stopped sample keeps contributing its final artifact to later iterations (the population stays constant). Enhanced rates count pass over all non-gated specs (gated = baseline_incompatible + numerically_unstable).

## Pass-rate trajectories (ParEval vs. enhanced — overfitting view)

### static_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 3 | 100.0% (3/3) | 100.0% (60/60) |
| 1 | 3 | 100.0% (3/3) | 100.0% (60/60) |
| 2 | 3 | 100.0% (3/3) | 100.0% (60/60) |

### test_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 3 | 100.0% (3/3) | 100.0% (60/60) |

### combined_feedback
| iteration | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| 0 | 3 | 100.0% (3/3) | 100.0% (60/60) |
| 1 | 3 | 100.0% (3/3) | 100.0% (60/60) |
| 2 | 3 | 100.0% (3/3) | 100.0% (60/60) |

## Stop-reason distribution

### static_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 1 |
| stopped_clean | 2 |

### test_feedback
| final status | samples |
| --- | --- |
| stopped_tests_pass | 3 |

### combined_feedback
| final status | samples |
| --- | --- |
| stopped_budget | 1 |
| stopped_clean | 2 |

## Blocking findings per tool over iterations (convergence)

Counts are per produced artifact at that iteration (no carry-forward — this shows what the loop's artifacts still contain). ALL enabled tools are listed, not just those with findings.

### static_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| 1 | 1 | 0 | 0 | 0 | 0 | 0 | n/a | 1 | 0 | 0 | 0 | n/a |
| 2 | 1 | 0 | 0 | 0 | 0 | 0 | n/a | 1 | 0 | 0 | 0 | n/a |

### test_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

### combined_feedback
Cell semantics: a NUMBER means the tool ran on at least one artifact at that iteration (0 = ran and found nothing — a result); n/a means the tool was not applicable on this iteration's execution-model mix (or its records are not merged yet, e.g. external containers).

| iteration | artifacts | compiler | gcc_analyzer | clang_tidy | cppcheck | infer | parcoach | llov | asan_ubsan | tsan | memcheck | must |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| 1 | 1 | 0 | 0 | 0 | 0 | 0 | n/a | 1 | 0 | 0 | 0 | n/a |
| 2 | 1 | 0 | 0 | 0 | 0 | 0 | n/a | 1 | 0 | 0 | 0 | n/a |

## Blocking findings by error class

Cells are `findings (samples)`: finding sums double-count when several tools report the same defect (redundancy by design); the sample count deduplicates across tools and is the citable number. Classes: thesis/evaluation/finding_classes.py.

**static_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | race |
| --- | --- | --- |
| 0 | 3 | 1 (1) |
| 1 | 1 | 1 (1) |
| 2 | 1 | 1 (1) |

**test_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | race |
| --- | --- | --- |
| 0 | 3 | 1 (1) |

**combined_feedback — class x iteration (per-iteration artifacts):**

| iteration | n | race |
| --- | --- | --- |
| 0 | 3 | 1 (1) |
| 1 | 1 | 1 (1) |
| 2 | 1 | 1 (1) |

**static_feedback — class x model (final state, carry-forward):**

| model | n | race |
| --- | --- | --- |
| claude_fable_5 | 3 | 1 (1) |

**test_feedback — class x model (final state, carry-forward):**

| model | n | race |
| --- | --- | --- |
| claude_fable_5 | 3 | 1 (1) |

**combined_feedback — class x model (final state, carry-forward):**

| model | n | race |
| --- | --- | --- |
| claude_fable_5 | 3 | 1 (1) |

**class x execution model at iteration 0 (initial generations):**

| exec | n | race |
| --- | --- | --- |
| serial | 1 | 0 (0) |
| omp | 1 | 1 (1) |
| mpi | 1 | 0 (0) |

## Breakdown by problem type and execution model (final state)

### static_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 3 | 100.0% (3/3) | 100.0% (60/60) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 1 | 100.0% (1/1) | 100.0% (20/20) |
| omp | 1 | 100.0% (1/1) | 100.0% (20/20) |
| serial | 1 | 100.0% (1/1) | 100.0% (20/20) |

### test_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 3 | 100.0% (3/3) | 100.0% (60/60) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 1 | 100.0% (1/1) | 100.0% (20/20) |
| omp | 1 | 100.0% (1/1) | 100.0% (20/20) |
| serial | 1 | 100.0% (1/1) | 100.0% (20/20) |

### combined_feedback
| problem_type | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| dense_la | 3 | 100.0% (3/3) | 100.0% (60/60) |

| execution_model | n | ParEval pass | enhanced pass (specs) |
| --- | --- | --- | --- |
| mpi | 1 | 100.0% (1/1) | 100.0% (20/20) |
| omp | 1 | 100.0% (1/1) | 100.0% (20/20) |
| serial | 1 | 100.0% (1/1) | 100.0% (20/20) |

## "Statically clean but incorrect" (static_feedback, design §9)

Samples stopping clean (no blocking static findings): 2

- ParEval-incorrect among them: 0.0% (0/2)
- enhanced-failing among them: 0.0% (0/2)

## Enhanced tests by execution model

Spec-run verdicts per execution model (gates are SERIAL: sight omp/mpi crash/timeout manually for driver divergence, and expect rounding signatures in fail — see docs/enhanced-tests-parallel.md).

| exec | samples | pass | fail | crash | timeout | build_failed | runtime_error | gated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 1 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |
| omp | 5 | 100 | 0 | 0 | 0 | 0 | 0 | 0 |
| mpi | 1 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |

## Race corroboration (omp)

Per deduplicated omp artifact: does the static race report (LLOV) have a dynamic witness (TSan)? `None` cells mean the tool did not run on that artifact — that is missing data, never a clean result.

| corroboration | artifacts |
| --- | --- |
| both report (corroborated) | 0 |
| LLOV only (static, dynamically unconfirmed) | 5 |
| TSan only (LLOV blind/not analyzable) | 0 |
| neither | 0 |

Artifacts with at least one race report (5 of 5 omp artifacts listed; the 0 without any report are only counted above):

| model | variant | iter | llov | tsan | ParEval | enhanced |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | static_feedback | 0 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | static_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | combined_feedback | 1 | 1 | 0 | pass 4/4 | 20p/0f |
| claude_fable_5 | combined_feedback | 2 | 1 | 0 | pass 4/4 | 20p/0f |

**stopped_budget attribution (omp):** 2 of 2 stopped_budget outcomes end on an iteration whose ONLY blocker is an LLOV race finding (TSan 0/not run) — budget burned without a dynamic witness.

## Runtime cost per tool

Median and p95 of the per-sample tool runtime, split by execution model (medians because the distributions are skewed). n = runs with a recorded duration; timeouts are excluded from median/p95 and reported as their own share.

| tool | exec | n | median s | p95 s | timeouts |
| --- | --- | --- | --- | --- | --- |
| compiler | serial | 1 | 11.53 | 11.53 | 0.0% (0/1) |
| compiler | omp | 5 | 10.89 | 11.21 | 0.0% (0/5) |
| compiler | mpi | 1 | 12.53 | 12.53 | 0.0% (0/1) |
| gcc_analyzer | serial | 1 | 4.65 | 4.65 | 0.0% (0/1) |
| gcc_analyzer | omp | 5 | 6.44 | 6.74 | 0.0% (0/5) |
| gcc_analyzer | mpi | 1 | 6.62 | 6.62 | 0.0% (0/1) |
| clang_tidy | serial | 1 | 7.22 | 7.22 | 0.0% (0/1) |
| clang_tidy | omp | 5 | 6.71 | 7.29 | 0.0% (0/5) |
| clang_tidy | mpi | 1 | 7.40 | 7.40 | 0.0% (0/1) |
| cppcheck | serial | 1 | 1.44 | 1.44 | 0.0% (0/1) |
| cppcheck | omp | 5 | 1.67 | 1.83 | 0.0% (0/5) |
| cppcheck | mpi | 1 | 2.60 | 2.60 | 0.0% (0/1) |
| infer | serial | 1 | 30.17 | 30.17 | 0.0% (0/1) |
| infer | omp | 5 | 29.80 | 31.85 | 0.0% (0/5) |
| infer | mpi | 1 | 47.66 | 47.66 | 0.0% (0/1) |
| parcoach | mpi | 1 | 0.05 | 0.05 | 0.0% (0/1) |
| llov | omp | 5 | 1.73 | 2.63 | 0.0% (0/5) |
| asan_ubsan | serial | 1 | 6.72 | 6.72 | 0.0% (0/1) |
| asan_ubsan | omp | 5 | 6.60 | 9.78 | 0.0% (0/5) |
| asan_ubsan | mpi | 1 | 39.60 | 39.60 | 0.0% (0/1) |
| tsan | omp | 5 | 9.29 | 16.21 | 0.0% (0/5) |
| memcheck | serial | 1 | 14.83 | 14.83 | 0.0% (0/1) |
| memcheck | omp | 5 | 51.80 | 57.01 | 0.0% (0/5) |
| must | mpi | 1 | 93.10 | 93.10 | 0.0% (0/1) |

## Generation effort and direct latency

Measurement semantics: thesis/docs/timing-and-effort.md (why batch wall time is not latency, why reasoning tokens are the primary effort metric).

Effort = tokens spent per generation (median over samples, plus the run total). reasoning median NA means the provider reports no reasoning-token field for this model.

| model | iteration | n | input med | output med | reasoning med | reasoning sum |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 0 | 3 | 272 | 186 | 0 | 89 |
| claude_fable_5 | 1 | 2 | 722 | 321 | 85 | 170 |
| claude_fable_5 | 2 | 2 | 1172 | 501 | 73 | 146 |

Direct request latency (timing_mode == "direct" records ONLY — batch records carry no latency by design, their wall time is provider queue time). Latency additionally includes network and provider load; comparable numbers require one contiguous direct run.

| model | n (direct) | median s | p95 s |
| --- | --- | --- | --- |
| claude_fable_5 | 7 | 7.87 | 10.59 |

## Cleaning interventions

Answer-format repairs applied by the pipeline before evaluation (5 assembled sample(s) with cleaning data). auto_closed is an intervention on the measured object; the rest describe the answer format and double as an instruction-following signal.

| model | samples | auto_closed | used_fence | signature_suspect | dropped_leading | relocated_includes |
| --- | --- | --- | --- | --- | --- | --- |
| claude_fable_5 | 5 | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) | 0.0% (0/5) |

By iteration (does the answer format change under repair?):

| iteration | samples | auto_closed | used_fence | signature_suspect |
| --- | --- | --- | --- | --- |
| 0 | 3 | 0.0% (0/3) | 0.0% (0/3) | 0.0% (0/3) |
| 1 | 1 | 0.0% (0/1) | 0.0% (0/1) | 0.0% (0/1) |
| 2 | 1 | 0.0% (0/1) | 0.0% (0/1) | 0.0% (0/1) |

## Data completeness

Rows total: 13, incomplete: 0

## Effective config snapshot

Frozen at run time (run_manifest.json, created 2026-08-08T16:39:18.550485Z by stage 'generation', git 368e4f020118 DIRTY).

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
