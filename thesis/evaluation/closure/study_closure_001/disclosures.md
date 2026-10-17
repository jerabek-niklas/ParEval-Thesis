# Disclosure register - study_closure_001

schema `study_disclosure_register.v1`; register_sha256 `ed677f7c49cd0ba1d5aaab3c846ba497f91c2e956917c862930c46c50c1d81f5`; runs: pilot_002, full_ext_001, full_ext_recovery_001, full_ext_recovery_002, full_ext_recovery_003, full_ext_recovery_004, full_ext_phase2_001

| # | id | title | applies to | status |
|---|---|---|---|---|
| 1 | `policy_mandatory_sources` | Mandatory disclosure sources of the pilot publication policy | pilot | ARTIFACT_BOUND |
| 2 | `pilot_label` | Pilot label | pilot | ARTIFACT_BOUND |
| 3 | `max_two_repair_iterations` | At most two repair iterations | both | COMPUTED |
| 4 | `reasoning_policy_differences` | Reasoning settings differ between models | both | COMPUTED |
| 5 | `cleaning_and_pipeline_interventions` | Cleaning and pipeline interventions | both | COMPUTED |
| 6 | `baseline_incompatibilities` | Baseline-incompatible enhanced tests | both | COMPUTED |
| 7 | `static_analysis_gaps` | Static analysis gaps | both | COMPUTED |
| 8 | `dynamic_analysis_gaps` | Dynamic analysis gaps | both | COMPUTED |
| 9 | `tool_timeouts_and_errors` | Tool timeouts, tool errors and non-pass verdicts | both | COMPUTED |
| 10 | `single_tool_finding_validity` | Validity of single-tool findings | both | ARTIFACT_BOUND |
| 11 | `numerical_tolerance` | Numerical tolerance of the enhanced oracle | both | COMPUTED |
| 12 | `frozen_thread_rank_configuration` | Frozen thread/rank and timeout configuration | both | ARTIFACT_BOUND |
| 13 | `infer_runtime_outlier` | Infer runtime outlier | both | COMPUTED |
| 14 | `one_generation_per_base_cell` | One generation per base cell | both | COMPUTED |
| 15 | `excluded_aborted_parent_repair` | Excluded aborted parent repair | full_ext | COMPUTED |
| 16 | `phase2_operational_incidents` | Phase-2 operational incidents | full_ext | COMPUTED |
| 17 | `verification_scopes` | Verification scopes | both | ARTIFACT_BOUND |

## 1. Mandatory disclosure sources of the pilot publication policy

- id: `policy_mandatory_sources`
- requirement: Every disclosure the pilot_002 publication policy declares as mandatory is carried by its artifact and must accompany any published pilot result.
- applies to: pilot
- status: ARTIFACT_BOUND

| source | raw sha256 |
|---|---|
| `thesis/evaluation/pilot_002_publication_policy.json` | 113df11de62b8df1cb3edb8bd7236951bdcc235db6572d9cc8385133e6c2d892 |
| `thesis/evaluation/semantic_decisions_pilot002.json` | f33a2b4b2ca655da585aaded05f89dfa7419cf5bca787c4023b9b68771b549c4 |
| `thesis/evaluation/prompt_oracle_interlock.json` | fd54ee12c1298ac9c7edad478c21c07ecdb2da2c70fd442098185ec5f60ed3e2 |
| `thesis/evaluation/e3_2_author_confirmation.json` | 3b5b41d0002d60b6fdcc8b6cabd16e1860ff33c716b2cdf4f6db28ac0001a9dd |
| `thesis/evaluation/cross_pilot_comparability.json` | fa23a971d0522bb7e8ee62e02eaef2b181bb78757b1e47f2c2379baa3d0cf72d |

| evidence | value | source |
|---|---|---|
| sources_declared | 11 | thesis/evaluation/pilot_002_publication_policy.json mandatory_disclosure_sources |
| sources_satisfied | 11 | pilot_freeze.disclosure_sources_state(policy, root) |
| entries | [{"id": "semantic_disclosure_dense_la_00", "artifact": "thesis/evaluation/semantic_decisions_pilot002.json", "field": "decisions[benchmark=dense_la/00_dense_la_lu_decomp].reporting_requirement", "artifact_readable": true, "field_present": true, "problems": [], "satisfied": true}, {"id": "prompt_oracle_interlock", "artifact": "thesis/evaluation/prompt_oracle_interlock.json", "field": "interlocks[] (enforcement = disclosure_required)", "artifact_readable": true, "field_present": true, "problems": [], "satisfied": true}, {"id": "semantic_decisions_all_disclosure_states", "artifact": "thesis/evalu ... | pilot_freeze.disclosure_sources_state(policy, root) |

## 2. Pilot label

- id: `pilot_label`
- requirement: Every pilot_002 result is presented under the pilot label and never as the full 60-benchmark study.
- applies to: pilot
- status: ARTIFACT_BOUND

| source | raw sha256 |
|---|---|
| `thesis/evaluation/pilot_002_publication_policy.json` | 113df11de62b8df1cb3edb8bd7236951bdcc235db6572d9cc8385133e6c2d892 |

| evidence | value | source |
|---|---|---|
| pilot_label | pilot_002 / Pilotexperiment (12 benchmarks x 3 execution models x 11 models, 1 sample per prompt) | thesis/evaluation/pilot_002_publication_policy.json pilot_label |
| may_be_presented_as_full_60_benchmark_study | false | thesis/evaluation/pilot_002_publication_policy.json may_be_presented_as_full_60_benchmark_study |
| pilot_results_must_be_labelled_as_pilot | true | thesis/evaluation/pilot_002_publication_policy.json pilot_results_must_be_labelled_as_pilot |
| policy_state | FRESH | pilot_freeze.verify_publication_policy |
| publication_policy_sha256 | 3f384ac76533e6c82389f376623af2fe34d7364d92b49fea47d896db09761d4e | thesis/evaluation/pilot_002_publication_policy.json publication_policy_sha256 |

## 3. At most two repair iterations

- id: `max_two_repair_iterations`
- requirement: Repair loops stop after at most max_iterations iterations; stopped_budget samples are unresolved by construction, not by evidence.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/config/recovery_successor_005.yaml` | ae6f11d63fa161e0bab95fb74c72739089b092b313d7f7232d1509357e428046 |
| `thesis/evaluation/pilot_002_methodology_freeze.json` | 26d111e98493b2dd423db0ebbc2f464ed2d44c45eee39123046cf9fa2988a427 |
| `thesis/recovery_successor_005/lineage.py` | eb30e2e3f84f11be150ac1f88d1cd548d23da894f858d4745c8e961affd34b46 |
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| configured_max_iterations | 2 | thesis/config/recovery_successor_005.yaml stages.repair.max_iterations |
| frozen_max_iterations | 2 | thesis/evaluation/pilot_002_methodology_freeze.json repair.max_iterations |
| package_constant | 2 | thesis/recovery_successor_005/lineage.py MAX_ITERATIONS |
| observed_max_iteration | 2 | composite cells: max(iteration) |
| cells_per_iteration | {"pilot": {"iter0": 396, "iter1": 358, "iter2": 189}, "full_ext": {"iter0": 1584, "iter1": 1879, "iter2": 1054}} | composite cells: count by block and iteration (iter0 = base) |
| repair_sample_states | {"pilot": {"stopped_analysis_incomplete": 357, "stopped_budget": 123, "stopped_clean": 324, "stopped_tests_pass": 384}, "full_ext": {"stopped_analysis_incomplete": 1539, "stopped_budget": 725, "stopped_clean": 959, "stopped_tests_pass": 1529}} | census summary: blocks.<block>.sample_states (thesis.recovery_successor_004.census.summary) |
| stopped_budget | {"pilot": 123, "full_ext": 725} | census summary: blocks.<block>.sample_states.stopped_budget |
| loops_done | 66/66 | census summary: total_repair_loops_done |

## 4. Reasoning settings differ between models

- id: `reasoning_policy_differences`
- requirement: The models run with provider-specific reasoning settings (effort, thinking levels, budgets) that are not equalised; comparisons across models carry this difference.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/config/recovery_successor_005.yaml` | ae6f11d63fa161e0bab95fb74c72739089b092b313d7f7232d1509357e428046 |
| `thesis/evaluation/pilot_002_methodology_freeze.json` | 26d111e98493b2dd423db0ebbc2f464ed2d44c45eee39123046cf9fa2988a427 |

| evidence | value | source |
|---|---|---|
| per_model | {"claude_fable_5": {"provider": "anthropic", "model_name": "claude-fable-5", "enabled": true, "reasoning": {"thinking": "adaptive", "effort": "medium"}}, "claude_opus_5": {"provider": "anthropic", "model_name": "claude-opus-5", "enabled": true, "reasoning": {"thinking": "adaptive", "effort": "medium"}}, "deepseek_v4_flash": {"provider": "openai_compatible", "model_name": "deepseek-v4-flash", "enabled": true, "reasoning": {"extra_body.enable_thinking": true, "extra_body.reasoning_effort": "high", "extra_body.thinking_budget": 8192}}, "deepseek_v4_pro": {"provider": "openai_compatible", "model_n ... | thesis/config/recovery_successor_005.yaml models[] (keys reasoning_effort, thinking_level, thinking, effort, enable_thinking, thinking_budget at their exact paths) |
| distinct_reasoning_profiles | 6 | thesis/config/recovery_successor_005.yaml models[]: distinct reasoning settings |
| models_without_reasoning_setting | ["qwen3_coder_api"] | thesis/config/recovery_successor_005.yaml models[] |
| freeze_effective_reasoning | {"claude_fable_5": {"effort": "medium", "thinking": "adaptive"}, "claude_opus_5": {"effort": "medium", "thinking": "adaptive"}, "deepseek_v4_flash": {"extra_body.enable_thinking": true, "extra_body.reasoning_effort": "high", "extra_body.thinking_budget": 8192}, "deepseek_v4_pro": {"extra_body.enable_thinking": true, "extra_body.reasoning_effort": "high", "extra_body.thinking_budget": 8192}, "gemini_31_pro": {"thinking_level": "medium"}, "gemini_36_flash": {"thinking_level": "medium"}, "openai_gpt55": {"reasoning_effort": "medium"}, "openai_gpt56_sol": {"reasoning_effort": "medium"}, "qwen36_35 ... | thesis/evaluation/pilot_002_methodology_freeze.json generation.effective_provider_plan.<model>.reasoning_configuration |
| config_equals_freeze | {"claude_fable_5": true, "claude_opus_5": true, "deepseek_v4_flash": true, "deepseek_v4_pro": true, "gemini_31_pro": true, "gemini_36_flash": true, "openai_gpt55": true, "openai_gpt56_sol": true, "qwen36_35b_a3b": true, "qwen37_max": true, "qwen3_coder_api": true} | comparison config models[] vs freeze effective_provider_plan |
| generation_defaults | {"temperature": 0, "max_output_tokens": 16384, "top_p": null, "timeout_seconds": 300, "retry_attempts": 2, "api_mode": "batch"} | thesis/config/recovery_successor_005.yaml generation_defaults |
| frozen_generation_settings | {"temperature": 0.0, "max_output_tokens": 16384, "top_p": null, "timeout_seconds": 300, "retry_attempts": 2, "api_mode": "batch"} | thesis/evaluation/pilot_002_methodology_freeze.json generation.settings |
| generation_defaults_equal_freeze | true | comparison config generation_defaults vs freeze generation.settings |

## 5. Cleaning and pipeline interventions

- id: `cleaning_and_pipeline_interventions`
- requirement: Generated text passed a deterministic cleaning/assembly condition and the technical provenance cleanup wave before measurement; the interventions are counted, not hidden.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/evaluation/technical_provenance_cleanup.json` | 4047d2b9ef6ffb522bdaf198963709b1ab4192ba07e756cec8d4a9100565d5fc |
| `thesis/results/intermediate/pilot_002/run_contract.json` | c332b9174f81de0e29ef5828239ee5b656b7c78a0a7b7e24cd6127a76d477322 |
| `thesis/results/intermediate/full_ext_001/run_contract.json` | bbd62f01a191805011b206495a542d37fe143986a27092e09226b995bf48cf8f |

| evidence | value | source |
|---|---|---|
| technical_provenance_cleanup | {"schema_version": "technical_provenance_cleanup.v1", "wave": "FINAL TECHNICAL PROVENANCE CLEANUP - split-container invocation coverage + iteration-0 correctness/dynamic writer attribution", "date": "2026-09-13", "all_tests_pass": true, "next_step": "PILOT_002 POPULATION + FINAL METHODOLOGY/RUN FREEZE (not the final environment gate, not the pilot start)", "artifact_sha256": "a71ee6580b837b3877c0d9f8a2a51c121032fdf15dfb68f9768a87f2f1c306ce"} | thesis/evaluation/technical_provenance_cleanup.json |
| contract_pins_cleanup | {"technical_provenance_cleanup_sha256": "a71ee6580b837b3877c0d9f8a2a51c121032fdf15dfb68f9768a87f2f1c306ce", "technical_provenance_cleanup_status": "COMPLETE", "pin_matches_artifact": true} | thesis/results/intermediate/pilot_002/run_contract.json conditions |
| cleaning_conditions | {"pilot": {"generation_cleaning_condition_sha256": "1e29649f3052e73af627923718c970453c8e8337795f1b8be7a44e083988e325", "assembly_condition_version": "assembly_condition.v1", "assembly_condition_sha256": "a2a76e899414dea5a81830d02eb67b4e444ec6ce901a4e6f4cd4211ebd083718"}, "full_ext": {"generation_cleaning_condition_sha256": "1e29649f3052e73af627923718c970453c8e8337795f1b8be7a44e083988e325", "assembly_condition_version": "assembly_condition.v1", "assembly_condition_sha256": "a2a76e899414dea5a81830d02eb67b4e444ec6ce901a4e6f4cd4211ebd083718"}} | thesis/results/intermediate/pilot_002/run_contract.json / thesis/results/intermediate/full_ext_001/run_contract.json conditions |
| assembly_rows | {"pilot": 943, "full_ext": 4517} | study assembly.jsonl files (streamed) |
| assembly_files | {"pilot": 70, "full_ext": 77} | study assembly.jsonl files |
| assembled | {"pilot": {"true": 943}, "full_ext": {"true": 4517}} | assembly rows: assembled |
| generation_truncated | {"pilot": {"false": 943}, "full_ext": {"false": 4515, "true": 2}} | assembly rows: generation_truncated |
| assembly_conditions_observed | {"pilot": {"a2a76e899414dea5a81830d02eb67b4e444ec6ce901a4e6f4cd4211ebd083718": 943}, "full_ext": {"a2a76e899414dea5a81830d02eb67b4e444ec6ce901a4e6f4cd4211ebd083718": 4517}} | assembly rows: assembly_condition_sha256 |
| assembly_condition_pins | {"pilot": "a2a76e899414dea5a81830d02eb67b4e444ec6ce901a4e6f4cd4211ebd083718", "full_ext": "a2a76e899414dea5a81830d02eb67b4e444ec6ce901a4e6f4cd4211ebd083718"} | thesis/results/intermediate/pilot_002/run_contract.json (pilot) / thesis/results/intermediate/full_ext_001/run_contract.json (full_ext) conditions.assembly_condition_sha256 |
| assembly_condition_uniform_and_pinned | {"pilot": true, "full_ext": true} | assembly rows vs the block's own contract pin (pilot: thesis/results/intermediate/pilot_002/run_contract.json, full_ext: thesis/results/intermediate/full_ext_001/run_contract.json) |
| cleaning_interventions | {"pilot": {"auto_closed": 30, "dropped_duplicated_prompt_lines": 180, "dropped_leading_lines": 1, "kept_pre_signature_lines": 105, "relocated_includes": 96, "signature_matched_patched": 428, "used_fence": 242}, "full_ext": {"auto_closed": 277, "dropped_duplicated_prompt_lines": 703, "dropped_leading_lines": 5, "kept_pre_signature_lines": 490, "relocated_includes": 369, "signature_matched_patched": 2229, "signature_suspect": 97, "used_fence": 1074}} | assembly rows: cleaning.<flag> truthy (used_fence, dropped_leading_lines, dropped_trailing_lines, signature_matched_patched, dropped_duplicated_prompt_lines, kept_pre_signature_lines, relocated_includes, auto_closed, signature_suspect) |
| cleaning_anomalies | {"pilot": {"braces_balanced": 7, "signature_found_in_output": 182}, "full_ext": {"braces_balanced": 10, "signature_found_in_output": 880}} | assembly rows: cleaning.<flag> false (braces_balanced, signature_found_in_output) |
| composite_cells_per_block | {"pilot": 943, "full_ext": 4517} | composite cells (None when unavailable) |
| runs_scanned | ["pilot_002", "full_ext_001", "pilot_002__static_feedback__iter1", "pilot_002__static_feedback__iter2", "pilot_002__test_feedback__iter1", "pilot_002__test_feedback__iter2", "pilot_002__combined_feedback__iter1", "pilot_002__combined_feedback__iter2", "full_ext_recovery_001__static_feedback__iter1", "full_ext_recovery_001__test_feedback__iter1", "full_ext_recovery_001__test_feedback__iter2", "full_ext_recovery_001__combined_feedback__iter1", "full_ext_recovery_002__static_feedback__iter2", "full_ext_recovery_002__combined_feedback__iter2", "full_ext_recovery_003__static_feedback__iter2", "full ... | study_run_dirs(root) |

## 6. Baseline-incompatible enhanced tests

- id: `baseline_incompatibilities`
- requirement: Enhanced test pairs whose serial oracle is incompatible with the input are baseline_incompatible and never counted against a model.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| enhanced_statuses | {"pilot": {"baseline_incompatible": 807, "build_failed": 614, "crash": 577, "fail": 576, "pass": 16152, "timeout": 134}, "full_ext": {"baseline_incompatible": 483, "build_failed": 5940, "crash": 383, "fail": 3244, "pass": 79998, "timeout": 292}} | composite stage_coverage.<block>.enhanced.statuses |
| enhanced_pairs | {"pilot": 18860, "full_ext": 90340} | composite stage_coverage.<block>.enhanced.pairs |
| baseline_incompatible | {"pilot": 807, "full_ext": 483} | composite stage_coverage.<block>.enhanced.statuses.baseline_incompatible |
| repair_stopped_baseline_incompatible | {"pilot": 0, "full_ext": 0} | census summary: blocks.<block>.sample_states.stopped_baseline_incompatible (0 when absent) |
| non_model_terminal_statuses | ["stopped_baseline_incompatible", "stopped_analysis_incomplete", "stopped_api_exhausted"] | census result: non_model_terminal_statuses |

## 7. Static analysis gaps

- id: `static_analysis_gaps`
- requirement: Static tool entries in a gap state (PARTIAL, NOT_ANALYZED, TOOL_ERROR, TIMEOUT) carry no trustworthy verdict and are reported per tool and block.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| states | {"pilot": {"compiler": {"COMPLETED": 943}, "gcc_analyzer": {"COMPLETED": 357, "PARTIAL": 555, "TOOL_ERROR": 31}, "clang_tidy": {"COMPLETED": 912, "TOOL_ERROR": 31}, "cppcheck": {"COMPLETED": 934, "PARTIAL": 9}, "infer": {"COMPLETED": 595, "NOT_APPLICABLE": 312, "TOOL_ERROR": 36}, "parcoach": {"COMPLETED": 307, "NOT_APPLICABLE": 518, "TIMEOUT": 100, "TOOL_ERROR": 10}, "llov": {"COMPLETED": 92, "NOT_ANALYZED": 147, "NOT_APPLICABLE": 625, "PARTIAL": 29, "TOOL_ERROR": 44}}, "full_ext": {"compiler": {"COMPLETED": 4517}, "gcc_analyzer": {"COMPLETED": 1734, "PARTIAL": 2433, "TOOL_ERROR": 350}, "clang ... | composite cells: static.tools.<tool> state per block |
| gap_states | {"pilot": {"gcc_analyzer": {"PARTIAL": 555, "TOOL_ERROR": 31}, "clang_tidy": {"TOOL_ERROR": 31}, "cppcheck": {"PARTIAL": 9}, "infer": {"TOOL_ERROR": 36}, "parcoach": {"TIMEOUT": 100, "TOOL_ERROR": 10}, "llov": {"NOT_ANALYZED": 147, "PARTIAL": 29, "TOOL_ERROR": 44}}, "full_ext": {"gcc_analyzer": {"PARTIAL": 2433, "TOOL_ERROR": 350}, "clang_tidy": {"TOOL_ERROR": 295}, "cppcheck": {"PARTIAL": 17}, "infer": {"TOOL_ERROR": 172}, "parcoach": {"TIMEOUT": 328, "TOOL_ERROR": 133}, "llov": {"NOT_ANALYZED": 647, "PARTIAL": 239, "TOOL_ERROR": 355}}} | composite cells: static.tools states in PARTIAL, NOT_ANALYZED, TOOL_ERROR, TIMEOUT |
| cells_without_static | {"pilot": 0, "full_ext": 0} | composite cells: static is null |
| analysis_states | ["NOT_APPLICABLE", "COMPLETED", "PARTIAL", "NOT_ANALYZED", "TOOL_ERROR", "TIMEOUT"] | thesis/evaluation/framework.py ANALYSIS_STATES |

## 8. Dynamic analysis gaps

- id: `dynamic_analysis_gaps`
- requirement: Dynamic tool entries that did not run or ended in a gap state are reported per tool and block.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| states | {"pilot": {"asan_ubsan": {"analysis_state": {"COMPLETED": 905, "TIMEOUT": 4, "TOOL_ERROR": 34}, "ran": {"true": 943}}, "tsan": {"analysis_state": {"COMPLETED": 291, "NOT_APPLICABLE": 631, "PARTIAL": 1, "TOOL_ERROR": 20}, "ran": {"false": 631, "true": 312}}, "memcheck": {"analysis_state": {"COMPLETED": 502, "NOT_APPLICABLE": 417, "PARTIAL": 1, "TIMEOUT": 1, "TOOL_ERROR": 22}, "ran": {"false": 417, "true": 526}}, "must": {"analysis_state": {"COMPLETED": 408, "NOT_APPLICABLE": 526, "TOOL_ERROR": 9}, "ran": {"false": 526, "true": 417}}}, "full_ext": {"asan_ubsan": {"analysis_state": {"COMPLETED":  ... | composite cells: dynamic.tools.<tool>.analysis_state / ran per block |
| cells_without_dynamic | {"pilot": 0, "full_ext": 0} | composite cells: dynamic is null |

## 9. Tool timeouts, tool errors and non-pass verdicts

- id: `tool_timeouts_and_errors`
- requirement: Timeouts and tool errors of the analysis tools and the non-pass correctness verdicts are measurement limits, not model findings.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| static_timeouts_and_errors | {"pilot": {"gcc_analyzer": {"TOOL_ERROR": 31}, "clang_tidy": {"TOOL_ERROR": 31}, "infer": {"TOOL_ERROR": 36}, "parcoach": {"TIMEOUT": 100, "TOOL_ERROR": 10}, "llov": {"TOOL_ERROR": 44}}, "full_ext": {"gcc_analyzer": {"TOOL_ERROR": 350}, "clang_tidy": {"TOOL_ERROR": 295}, "infer": {"TOOL_ERROR": 172}, "parcoach": {"TIMEOUT": 328, "TOOL_ERROR": 133}, "llov": {"TOOL_ERROR": 355}}} | composite cells: static.tools states TIMEOUT/TOOL_ERROR |
| dynamic_timeouts_and_errors | {"pilot": {"asan_ubsan": {"TIMEOUT": 4, "TOOL_ERROR": 34}, "tsan": {"TOOL_ERROR": 20}, "memcheck": {"TIMEOUT": 1, "TOOL_ERROR": 22}, "must": {"TOOL_ERROR": 9}}, "full_ext": {"asan_ubsan": {"TIMEOUT": 15, "TOOL_ERROR": 302}, "tsan": {"TIMEOUT": 7, "TOOL_ERROR": 123}, "memcheck": {"TIMEOUT": 7, "TOOL_ERROR": 207}, "must": {"TOOL_ERROR": 90}}} | composite cells: dynamic.tools analysis_state TIMEOUT/TOOL_ERROR |
| correctness_verdicts | {"pilot": {"build_failed": 31, "pass": 864, "runtime_error": 4, "timeout": 4, "validation_failed": 40}, "full_ext": {"build_failed": 297, "pass": 3947, "runtime_error": 6, "timeout": 19, "validation_failed": 248}} | composite cells: correctness.verdict per block |
| cells_without_correctness | {"pilot": 0, "full_ext": 0} | composite cells: correctness is null |

## 10. Validity of single-tool findings

- id: `single_tool_finding_validity`
- requirement: Findings of a single low-precision tool are fed back as low-confidence hints only; the tool validation artifacts bound the precision.
- applies to: both
- status: ARTIFACT_BOUND

| source | raw sha256 |
|---|---|
| `thesis/config/recovery_successor_005.yaml` | ae6f11d63fa161e0bab95fb74c72739089b092b313d7f7232d1509357e428046 |
| `thesis/evaluation/pilot_002_methodology_freeze.json` | 26d111e98493b2dd423db0ebbc2f464ed2d44c45eee39123046cf9fa2988a427 |
| `thesis/tool_validation/results/metrics.csv` | aa45d77ef361551b1aa70c804ddffbb9026f3aa74d7daf3e481e9f190e0f05c8 |
| `thesis/tool_validation/results/summary.md` | ddc73604809fc7ecd3fb5d7ed61ff4fe2da431f1c3f64612857d752d82c6bd51 |
| `thesis/tool_validation/results/metrics_by_language.csv` | 18538622bad0ba354be0d56cf5ce68538ec5c006eaa2cd816e86b223f4236686 |

| evidence | value | source |
|---|---|---|
| low_confidence_prefix | Low-confidence hint (tool precision ~0.5 on validation suites) — verify at the given location before changing code:  | thesis/config/recovery_successor_005.yaml stages.repair.feedback.low_confidence_prefix |
| low_confidence_stop_mode | grace_once | thesis/config/recovery_successor_005.yaml stages.repair.low_confidence_stop_mode |
| frozen_low_confidence_prefix | Low-confidence hint (tool precision ~0.5 on validation suites) — verify at the given location before changing code:  | thesis/evaluation/pilot_002_methodology_freeze.json repair.feedback.low_confidence_prefix |
| frozen_low_confidence_stop_mode | grace_once | thesis/evaluation/pilot_002_methodology_freeze.json repair.low_confidence_stop_mode |
| config_equals_freeze | true | comparison config stages.repair vs freeze repair |
| tool_precision_settings | {"compiler": {"low_precision_warning": false, "low_precision_families": []}, "gcc_analyzer": {"low_precision_warning": false, "low_precision_families": []}, "clang_tidy": {"low_precision_warning": false, "low_precision_families": ["clang-analyzer-optin.mpi"]}, "cppcheck": {"low_precision_warning": false, "low_precision_families": []}, "infer": {"low_precision_warning": false, "low_precision_families": []}, "parcoach": {"low_precision_warning": true, "low_precision_families": []}, "llov": {"low_precision_warning": false, "low_precision_families": []}} | thesis/config/recovery_successor_005.yaml stages.static_analysis.tools.<tool> |
| tool_validation_artifacts | ["thesis/tool_validation/results/metrics.csv", "thesis/tool_validation/results/summary.md", "thesis/tool_validation/results/metrics_by_language.csv"] | thesis/tool_validation/results (not parsed) |

## 11. Numerical tolerance of the enhanced oracle

- id: `numerical_tolerance`
- requirement: Enhanced pairs whose serial oracle is numerically unstable under the fast-math probe are numerically_unstable and never counted against a model; the enhanced policy fixes the input domains.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/enhanced_tests/enhanced_policy.json` | 1173ac98200e65f4ae6e0995b9ea41db60d3851dc7d048151f8f89e91c1619b4 |
| `thesis/evaluation/pilot_002_methodology_freeze.json` | 26d111e98493b2dd423db0ebbc2f464ed2d44c45eee39123046cf9fa2988a427 |
| `thesis/evaluation/run_enhanced_tests.py` | 3eb45647c885bac713eaa3c165a9f733540d7473ba3058bfda19df69bc5b5631 |
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| numerically_unstable | {"pilot": 0, "full_ext": 0} | composite stage_coverage.<block>.enhanced.statuses.numerically_unstable (0 when absent) |
| enhanced_statuses | {"pilot": {"baseline_incompatible": 807, "build_failed": 614, "crash": 577, "fail": 576, "pass": 16152, "timeout": 134}, "full_ext": {"baseline_incompatible": 483, "build_failed": 5940, "crash": 383, "fail": 3244, "pass": 79998, "timeout": 292}} | composite stage_coverage.<block>.enhanced.statuses |
| enhanced_policy | {"status": "ENFORCED", "derivation_version": "e2b.1", "benchmarks": 60, "lf_sha256": "992efd1a7edddda824618417247bf95f38cbbbc70d056d52ec33e268d2ac16c0", "contract_pin_lf_sha256": "992efd1a7edddda824618417247bf95f38cbbbc70d056d52ec33e268d2ac16c0", "pin_matches": true, "contract_pin_status": "ENFORCED"} | thesis/enhanced_tests/enhanced_policy.json / pilot contract conditions |
| frozen_enhanced_block | {"enabled": true, "frozen_specs_path": "thesis/enhanced_tests/frozen/e3_final_specs.jsonl", "frozen_specs_sha256": "49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292", "enhanced_policy_sha256_lf_normalized": "992efd1a7edddda824618417247bf95f38cbbbc70d056d52ec33e268d2ac16c0", "enhanced_policy_status": "ENFORCED", "run_timeout_seconds": 60, "build_timeout_seconds_constant": 120.0, "jobs_cli_override_planned": false, "target_cases_per_benchmark": 20, "max_spec_size": 4096} | thesis/evaluation/pilot_002_methodology_freeze.json enhanced (scalar fields; no tolerance field is frozen) |
| gate_semantics | the serial baseline self-test and the fast-math stability probe decide per spec: baseline_incompatible (oracle crash/hang/self-fail or non-finite reference) and numerically_unstable (perturbed oracle diverges) are oracle properties, never counted against a model | thesis/evaluation/run_enhanced_tests.py (module docstring, gate) |

## 12. Frozen thread/rank and timeout configuration

- id: `frozen_thread_rank_configuration`
- requirement: Parallel samples run at the frozen thread/rank grid and timeouts of the methodology freeze; performance is not measured.
- applies to: both
- status: ARTIFACT_BOUND

| source | raw sha256 |
|---|---|
| `thesis/config/recovery_successor_005.yaml` | ae6f11d63fa161e0bab95fb74c72739089b092b313d7f7232d1509357e428046 |
| `thesis/evaluation/pilot_002_methodology_freeze.json` | 26d111e98493b2dd423db0ebbc2f464ed2d44c45eee39123046cf9fa2988a427 |
| `thesis/results/intermediate/pilot_002/run_contract.json` | c332b9174f81de0e29ef5828239ee5b656b7c78a0a7b7e24cd6127a76d477322 |
| `thesis/results/intermediate/full_ext_001/run_contract.json` | bbd62f01a191805011b206495a542d37fe143986a27092e09226b995bf48cf8f |

| evidence | value | source |
|---|---|---|
| enhanced_launch | {"enhanced_launch": {"omp_threads": 4, "mpi_ranks": 4}, "run_timeout_seconds": 60, "jobs": {"serial": 2, "omp": 1, "mpi": 1}, "execution_models": ["serial", "omp", "mpi"]} | thesis/config/recovery_successor_005.yaml stages.enhanced_tests |
| frozen_enhanced_launch | {"enhanced_launch": {"mpi_ranks": 4, "omp_threads": 4}, "run_timeout_seconds": 60, "jobs": {"serial": 2, "omp": 1, "mpi": 1}, "execution_models": ["serial", "omp", "mpi"], "build_timeout_seconds_constant": 120.0} | thesis/evaluation/pilot_002_methodology_freeze.json enhanced |
| enhanced_launch_equals_freeze | true | comparison config stages.enhanced_tests vs freeze enhanced |
| correctness_launch | {"niter": 1, "run_timeout_seconds": 120} | thesis/config/recovery_successor_005.yaml stages.correctness_tests |
| frozen_correctness_launch | {"niter": 1, "build_timeout_seconds": 120.0, "run_timeout_seconds": 120.0, "launch_defaults": {"mpi": [{"num_procs": 1}, {"num_procs": 2}, {"num_procs": 4}, {"num_procs": 8}], "omp": [{"num_threads": 1}, {"num_threads": 2}, {"num_threads": 4}, {"num_threads": 8}], "serial": [{}]}, "launch_overrides": null} | thesis/evaluation/pilot_002_methodology_freeze.json correctness |
| dynamic_toolset | {"asan_ubsan": {"enabled": true, "execution_models": ["serial", "omp", "mpi"]}, "tsan": {"enabled": true, "execution_models": ["omp"]}, "memcheck": {"enabled": true, "execution_models": ["serial", "omp"]}, "must": {"enabled": true, "execution_models": ["mpi"]}, "helgrind": {"enabled": false, "execution_models": ["omp"]}, "drd": {"enabled": false, "execution_models": ["omp"]}} | thesis/config/recovery_successor_005.yaml stages.dynamic_analysis.tools |
| dynamic_toolset_equals_freeze | true | comparison config stages.dynamic_analysis.tools vs freeze dynamic.toolset |
| contract_timeouts | {"pilot_002": {"run_timeout_seconds": 120, "enhanced_run_timeout_seconds": 60}, "full_ext_001": {"run_timeout_seconds": 120, "enhanced_run_timeout_seconds": 60}} | frozen contracts of pilot_002 / full_ext_001 |

## 13. Infer runtime outlier

- id: `infer_runtime_outlier`
- requirement: One Infer run exceeded the one-hour reporting threshold by far; the recorded duration is wall-clock time and the tool completed.
- applies to: both
- status: COMPUTED
- narrative: operator note (thesis text, not a measurement): the longest Infer run coincided with a laptop standby on the day its static record carries as recorded_date (created_at_utc, see longest_entry_recorded_date); the recorded duration is wall-clock time including the standby and the tool completed - the numbers and the date come from the scan, the standby from the run log

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/full_ext_recovery_003__combined_feedback__iter2/claude_opus_5/static_analysis.jsonl` | 55b67735ea7718c5b8b5b4bec5dec2e390529f2ba2bc429a51dcfef7e1fac576 |
| `thesis/results/intermediate/full_ext_recovery_003__combined_feedback__iter2/gemini_31_pro/static_analysis.jsonl` | 3a58a28866ca47105e369acab3e9fd139a0c93d120fb8ce9260ee7d2d2f59376 |
| `thesis/results/intermediate/full_ext_recovery_004__combined_feedback__iter2/gemini_36_flash/static_analysis.jsonl` | e7b6f599ba1ea1a9be385877da5b77e1f8a653443b6a9b7c57baacfa89e88d2c |
| `thesis/results/intermediate/pilot_002__combined_feedback__iter1/claude_opus_5/static_analysis.jsonl` | 96cf4cef09caa1e573b745e194068ed71716ffe6c8d0eb60aa384b699c0b42d5 |
| `thesis/results/intermediate/full_ext_recovery_003__static_feedback__iter2/gemini_31_pro/static_analysis.jsonl` | 8c0f509dac803542930ed6857b25116574e7ffc72ca780e3c582647c5d9649bf |

| evidence | value | source |
|---|---|---|
| duration_key | duration_seconds | static records: tools.infer / supplement entry (keys seen: {"duration_seconds": 5460}) |
| wall_seconds_entries | 0 | infer scan: entries carrying wall_seconds |
| files_scanned | 299 | infer scan: static_analysis.jsonl + static.*.jsonl supplement ledgers |
| records_scanned | 8859 | infer scan |
| infer_entries | 5460 | infer scan: entries with tool infer |
| infer_entries_ran | 3572 | infer scan: entries with ran = true |
| non_numeric_durations | 0 | infer scan |
| threshold_seconds | 3600 | thesis/study_closure/disclosures.py OUTLIER_SECONDS (reporting convention) |
| max_seconds | 27672.433 | infer scan: max duration_seconds |
| top_entries | [{"seconds": 27672.433, "run": "full_ext_recovery_003__combined_feedback__iter2", "source_run": "full_ext_recovery_003__combined_feedback__iter2", "model": "claude_opus_5", "sample_id": "claude_opus_5__sparse_la__47_sparse_la_spmv__serial__sample_0", "analysis_state": "COMPLETED", "recorded_date": "2026-10-11", "relative": "thesis/results/intermediate/full_ext_recovery_003__combined_feedback__iter2/claude_opus_5/static_analysis.jsonl"}, {"seconds": 173.36, "run": "full_ext_recovery_003__combined_feedback__iter2", "source_run": "full_ext_recovery_003__combined_feedback__iter2", "model": "gemini ... | infer scan: the 5 longest Infer entries |
| longest_entry_recorded_date | 2026-10-11 | infer scan: created_at_utc (date part) of the longest Infer entry |
| above_threshold | 1 | infer scan: entries with duration_seconds > threshold |
| above_threshold_entries | [{"seconds": 27672.433, "run": "full_ext_recovery_003__combined_feedback__iter2", "source_run": "full_ext_recovery_003__combined_feedback__iter2", "model": "claude_opus_5", "sample_id": "claude_opus_5__sparse_la__47_sparse_la_spmv__serial__sample_0", "analysis_state": "COMPLETED", "recorded_date": "2026-10-11", "relative": "thesis/results/intermediate/full_ext_recovery_003__combined_feedback__iter2/claude_opus_5/static_analysis.jsonl"}] | infer scan (<= 10 examples) |
| runs_scanned | ["pilot_002", "full_ext_001", "pilot_002__static_feedback__iter1", "pilot_002__static_feedback__iter2", "pilot_002__test_feedback__iter1", "pilot_002__test_feedback__iter2", "pilot_002__combined_feedback__iter1", "pilot_002__combined_feedback__iter2", "full_ext_recovery_001__static_feedback__iter1", "full_ext_recovery_001__test_feedback__iter1", "full_ext_recovery_001__test_feedback__iter2", "full_ext_recovery_001__combined_feedback__iter1", "full_ext_recovery_002__static_feedback__iter2", "full_ext_recovery_002__combined_feedback__iter2", "full_ext_recovery_003__static_feedback__iter2", "full ... | study_run_dirs(root) |
| supplement_owners_scanned | ["full_ext_recovery_002", "full_ext_recovery_003", "full_ext_phase2_001"] | targets.SUPPLEMENT_OWNERS + phase 2 |

## 14. One generation per base cell

- id: `one_generation_per_base_cell`
- requirement: Every base cell holds exactly one generated sample per prompt (num_samples_per_prompt = 1); there is no sampling distribution per prompt.
- applies to: both
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/pilot_002/run_contract.json` | c332b9174f81de0e29ef5828239ee5b656b7c78a0a7b7e24cd6127a76d477322 |
| `thesis/results/intermediate/full_ext_001/run_contract.json` | bbd62f01a191805011b206495a542d37fe143986a27092e09226b995bf48cf8f |
| `thesis/evaluation/pilot_002_methodology_freeze.json` | 26d111e98493b2dd423db0ebbc2f464ed2d44c45eee39123046cf9fa2988a427 |
| `thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json` | 4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45 |

| evidence | value | source |
|---|---|---|
| num_samples_per_prompt | {"pilot_002": 1, "full_ext_001": 1} | thesis/results/intermediate/pilot_002/run_contract.json / thesis/results/intermediate/full_ext_001/run_contract.json population.num_samples_per_prompt |
| prompt_count | {"pilot_002": 180, "full_ext_001": 180} | thesis/results/intermediate/pilot_002/run_contract.json / thesis/results/intermediate/full_ext_001/run_contract.json population.prompt_count |
| frozen_samples_per_prompt | 1 | thesis/evaluation/pilot_002_methodology_freeze.json population.samples_per_prompt |
| frozen_total_base_cells | 396 | thesis/evaluation/pilot_002_methodology_freeze.json population.total_base_cells |
| composite_base_per_block | {"pilot": 396, "full_ext": 1584} | composite cells.base_per_block |
| expected_population | {"pilot_002": 396, "full_ext_001": 1584} | thesis/recovery_successor_005/composite.py EXPECTED_POPULATION |
| composite_base_equals_expected_population | {"pilot": true, "full_ext": true} | comparison composite cells.base_per_block vs composite.py EXPECTED_POPULATION (the population section fails the closure on a mismatch) |
| composite_population | {"base_cells": 1980, "per_run": {"full_ext_001": 1584, "pilot_002": 396}} | composite population |
| reuse_policies | {"pilot_002": "NO_PILOT001_MEASUREMENT_REUSE", "full_ext_001": "NO_MEASUREMENT_REUSE_INSIDE_EXTENSION"} | thesis/results/intermediate/pilot_002/run_contract.json / thesis/results/intermediate/full_ext_001/run_contract.json reuse_policy.policy |

## 15. Excluded aborted parent repair

- id: `excluded_aborted_parent_repair`
- requirement: The aborted repair iteration of the parent run is excluded from the study: it is never a phase-2 target and no study candidate derives from it.
- applies to: full_ext
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/raw/full_ext_001__static_feedback__iter1/openai_gpt55/generations.jsonl` | 552e5ef64838b44dd1502cddd42c0b5a18ea8ea676454cc456296b7eff90ff34 |

| evidence | value | source |
|---|---|---|
| excluded_runs | ["full_ext_001__static_feedback__iter1"] | thesis/recovery_successor_005/lineage.py EXCLUDED_HISTORICAL_RUNS |
| per_run | {"full_ext_001__static_feedback__iter1": {"raw_dir_exists": true, "intermediate_dir_exists": true, "model_files": 1, "answers": 62, "phase2_targets_with_this_source_run": 0, "in_study_run_dirs": false}} | raw/<run>/*/generations.jsonl rows; frozen target table source_run; results tree directories |
| answers_per_run | {"full_ext_001__static_feedback__iter1": 62} | raw/<run>/*/generations.jsonl rows |
| phase2_targets_with_excluded_source | {"full_ext_001__static_feedback__iter1": 0} | frozen target table source_run |
| answers_total | 62 | raw/<run>/*/generations.jsonl rows |
| targets_sha256 | c836011f34ad8961aaf5ed46b325d9542bc6c22e5b01c6818e40fd216feacec7 | frozen phase-2 target table |
| statement | the excluded run is never a phase-2 target source and never a study results directory | frozen target table + study_run_dirs(root) |

## 16. Phase-2 operational incidents

- id: `phase2_operational_incidents`
- requirement: Interrupted stage invocations, archived torn ledger tails and repeated build groups of the phase-2 run are operational incidents without effect on the measurements.
- applies to: full_ext
- status: COMPUTED

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/full_ext_phase2_001/phase2_stage_invocations.jsonl` | f47a51dd039f6bb556eddfb0e56de59fd2ca8ed0b115dd46667cd2fefa3df298 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/claude_fable_5.phase2_verification.json` | 463875f777d7aff8f7dfc287ed043c7ecb71a9a8395b41a0d8e64cb6760e23fb |
| `thesis/results/intermediate/full_ext_phase2_001/verification/claude_opus_5.phase2_verification.json` | 898fba17523256472a3ab10bfe31872261cd003d89a3628db4b71811ca07e8ba |
| `thesis/results/intermediate/full_ext_phase2_001/verification/deepseek_v4_flash.phase2_verification.json` | e99193d3e1b77386b563475163a8e286aaee7c503e740fa7e497b830b05d4dfc |
| `thesis/results/intermediate/full_ext_phase2_001/verification/deepseek_v4_pro.phase2_verification.json` | 7f53f47bcf1f21d8252227f7de333f955f5e7e0a6894a7a5e4c4b24533b32cca |
| `thesis/results/intermediate/full_ext_phase2_001/verification/gemini_31_pro.phase2_verification.json` | 17236759b27b0580998b61fc8a512e9e75988cafdc185794f685186f5aec0e15 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/gemini_36_flash.phase2_verification.json` | 41990b5f1b99dc85a2c637ae266644330671f4cc787ad072bf1ec29024afd06a |
| `thesis/results/intermediate/full_ext_phase2_001/verification/openai_gpt55.phase2_verification.json` | dc0cbf3d3751b33ab1ee65a5dde810f425d75969e66c82bfa3952880022cde35 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/openai_gpt56_sol.phase2_verification.json` | f4eee88be53901d65cb970dcf129dc5ca609c930f099f5307df2cabf44587965 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/qwen36_35b_a3b.phase2_verification.json` | 7fe086af1715c5fc2ca2200cab163701a0f70938ba29c1aa84db556852e22dcc |
| `thesis/results/intermediate/full_ext_phase2_001/verification/qwen37_max.phase2_verification.json` | e940227929a104e784d1a47e6dec9b630c89899f50c0779f093f6d8819a932f7 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/qwen3_coder_api.phase2_verification.json` | 8cd2e597c77f237f5208e01804408b2b00784cd05dec2ccf643fd71a0cde4072 |

| evidence | value | source |
|---|---|---|
| incident_totals | {"archived_torn_tails": 0, "repeated_build_groups": 0, "stray": 0, "temporary_files": 0} | phase-2 reports: full_ext:phase2_ledgers_bound_to_targets detail + *:phase2_provenance repeated_build_groups |
| incidents_per_model | {"claude_fable_5": {"archived_torn_tails": 0, "temporary_files": 0, "stray": 0, "repeated_build_groups": 0, "provenance_checks": 7, "ledger_check_status": "PASS"}, "claude_opus_5": {"archived_torn_tails": 0, "temporary_files": 0, "stray": 0, "repeated_build_groups": 0, "provenance_checks": 7, "ledger_check_status": "PASS"}, "deepseek_v4_flash": {"archived_torn_tails": 0, "temporary_files": 0, "stray": 0, "repeated_build_groups": 0, "provenance_checks": 7, "ledger_check_status": "PASS"}, "deepseek_v4_pro": {"archived_torn_tails": 0, "temporary_files": 0, "stray": 0, "repeated_build_groups": 0,  ... | phase-2 reports per model |
| stage_invocations | {"static.main": {"invoked": 2, "completed": 2, "other": 0, "interrupted": 0}, "static.parcoach": {"invoked": 2, "completed": 2, "other": 0, "interrupted": 0}, "static.llov": {"invoked": 2, "completed": 2, "other": 0, "interrupted": 0}, "correctness": {"invoked": 2, "completed": 2, "other": 0, "interrupted": 0}, "dynamic": {"invoked": 2, "completed": 1, "other": 0, "interrupted": 1}, "enhanced": {"invoked": 1, "completed": 1, "other": 0, "interrupted": 0}} | thesis/results/intermediate/full_ext_phase2_001/phase2_stage_invocations.jsonl |
| stage_last_status | {"static.main": "completed", "static.parcoach": "completed", "static.llov": "completed", "correctness": "completed", "dynamic": "completed", "enhanced": "completed"} | thesis/results/intermediate/full_ext_phase2_001/phase2_stage_invocations.jsonl |
| stage_last_open_items | {"static.main": [], "static.parcoach": [], "static.llov": [], "correctness": [], "dynamic": [], "enhanced": []} | thesis/results/intermediate/full_ext_phase2_001/phase2_stage_invocations.jsonl |
| interrupted_invocations | 1 | thesis/results/intermediate/full_ext_phase2_001/phase2_stage_invocations.jsonl: invoked without completed |
| history_rows | 21 | thesis/results/intermediate/full_ext_phase2_001/phase2_stage_invocations.jsonl |
| models_reported | 11 | ctx.cache phase2_reports |

## 17. Verification scopes

- id: `verification_scopes`
- requirement: Every verification artifact of the study has its own scope; none of them is a publication decision.
- applies to: both
- status: ARTIFACT_BOUND

| source | raw sha256 |
|---|---|
| `thesis/results/intermediate/pilot_002/post_run_verification.json` | 55fdb6351ee3d1ba1c4adf713590186cef2015622acde715f5afc86e3b014bf9 |
| `thesis/evaluation/recovery/full_ext_recovery_001/parent_report.json` | 8985731d5e6ea9bb2972de6c42284326c6030ab39129a5f39d3e559d28f09adc |
| `thesis/results/intermediate/full_ext_recovery_003/verification/claude_fable_5.successor_verification.json` | ac27be98ac07690e503077d414d224ac9646badda6372b707e7dc3ce59291120 |
| `thesis/results/intermediate/full_ext_recovery_003/verification/claude_opus_5.successor_verification.json` | 928ed4e49f767bd46a8b2a20a1bf69201299f09d264c2f5d4a3ff331816c7a8a |
| `thesis/results/intermediate/full_ext_recovery_003/verification/gemini_31_pro.successor_verification.json` | afacc6b2a71c826982aacc7cb80ae4428582c3c72db5897099e94d3a9ed01e76 |
| `thesis/results/intermediate/full_ext_recovery_003/verification/openai_gpt55.successor_verification.json` | da1b44ad6e03d9943e7088cbe50fc5ef55bea4bc7d96dfd934cf84155ebda0ab |
| `thesis/results/intermediate/full_ext_recovery_004/verification/deepseek_v4_pro.successor_verification.json` | 7c9a0f891bedb3c9ce092d3d13721bfafa8c9a4d7962e298a8ff598e0869571b |
| `thesis/results/intermediate/full_ext_recovery_004/verification/gemini_36_flash.successor_verification.json` | ceebcee58a00a299783cb760ce60b980534eb89ac7aa2dc8f5fe0951b6991e99 |
| `thesis/results/intermediate/full_ext_recovery_004/verification/openai_gpt56_sol.successor_verification.json` | fed44fe1fb97379dc304b788babb11a28719fd4e4e4645bff2f70eb688d05d52 |
| `thesis/results/intermediate/full_ext_recovery_004/verification/qwen36_35b_a3b.successor_verification.json` | 2d08c9c83a3e5c2963639e9e4260fe6f38bede11bb2110784a200fd018e5d488 |
| `thesis/results/intermediate/full_ext_recovery_004/verification/qwen37_max.successor_verification.json` | d76f557dd173096a06138c209d30bfa97ad87b089abd5a4c1bfa7c7ff44e99e8 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/claude_fable_5.phase2_verification.json` | 463875f777d7aff8f7dfc287ed043c7ecb71a9a8395b41a0d8e64cb6760e23fb |
| `thesis/results/intermediate/full_ext_phase2_001/verification/claude_opus_5.phase2_verification.json` | 898fba17523256472a3ab10bfe31872261cd003d89a3628db4b71811ca07e8ba |
| `thesis/results/intermediate/full_ext_phase2_001/verification/deepseek_v4_flash.phase2_verification.json` | e99193d3e1b77386b563475163a8e286aaee7c503e740fa7e497b830b05d4dfc |
| `thesis/results/intermediate/full_ext_phase2_001/verification/deepseek_v4_pro.phase2_verification.json` | 7f53f47bcf1f21d8252227f7de333f955f5e7e0a6894a7a5e4c4b24533b32cca |
| `thesis/results/intermediate/full_ext_phase2_001/verification/gemini_31_pro.phase2_verification.json` | 17236759b27b0580998b61fc8a512e9e75988cafdc185794f685186f5aec0e15 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/gemini_36_flash.phase2_verification.json` | 41990b5f1b99dc85a2c637ae266644330671f4cc787ad072bf1ec29024afd06a |
| `thesis/results/intermediate/full_ext_phase2_001/verification/openai_gpt55.phase2_verification.json` | dc0cbf3d3751b33ab1ee65a5dde810f425d75969e66c82bfa3952880022cde35 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/openai_gpt56_sol.phase2_verification.json` | f4eee88be53901d65cb970dcf129dc5ca609c930f099f5307df2cabf44587965 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/qwen36_35b_a3b.phase2_verification.json` | 7fe086af1715c5fc2ca2200cab163701a0f70938ba29c1aa84db556852e22dcc |
| `thesis/results/intermediate/full_ext_phase2_001/verification/qwen37_max.phase2_verification.json` | e940227929a104e784d1a47e6dec9b630c89899f50c0779f093f6d8819a932f7 |
| `thesis/results/intermediate/full_ext_phase2_001/verification/qwen3_coder_api.phase2_verification.json` | 8cd2e597c77f237f5208e01804408b2b00784cd05dec2ccf643fd71a0cde4072 |

| evidence | value | source |
|---|---|---|
| scopes | [{"run_ids": ["pilot_002"], "artifacts": ["thesis/results/intermediate/pilot_002/post_run_verification.json"], "schema_version": "post_run_verification.v1", "scope": null, "verifier_version": "verify_pilot_run.v1", "proves": "the pilot run's contract, runtime, config, stages and repair scope after the run", "does_not_prove": "the result acceptance of the author"}, {"run_ids": ["full_ext_001"], "artifacts": ["thesis/evaluation/recovery/full_ext_recovery_001/parent_report.json"], "schema_version": "parent_base_evidence_report.v1", "scope": "BASE_ONLY_NOT_FULL_RUN_ACCEPTANCE", "verifier_version": ... | one persisted report per kind + closure constants |
| scopes_distinct | true | verification_scopes |
| retrospective_reverification | {"full_ext_recovery_002": {"models": 2, "statuses": {"PASS_WITH_SUBSTITUTED_AUTHORITY_CHECK": 2}, "deep": {"false": 1, "true": 1}}, "full_ext_recovery_003": {"models": 4, "statuses": {"PASS_WITH_SUBSTITUTED_AUTHORITY_CHECK": 4}, "deep": {"false": 3, "true": 1}}, "full_ext_recovery_004": {"models": 5, "statuses": {"PASS_WITH_SUBSTITUTED_AUTHORITY_CHECK": 5}, "deep": {"false": 4, "true": 1}}} | ctx.cache successor_reverification |

