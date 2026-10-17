# study_closure_001 - global verification of the study (PASS)

Scope `STUDY_GLOBAL_VERIFICATION_SEVEN_RUNS_READ_ONLY`; schema `study_global_verification.v1`; closure sha256 `c880da4144dc980ea8b6fc9ce66c3dbc04c2fa4f37be71b9dfeae81216c825c5`.
Mode: formal closure (worktree clean, artifacts persisted). Git HEAD `69ee4f390134ba78e3a332bebcea54202de1feba` (thesis-static-analysis, clean).

## Flags

- `MEASUREMENTS_COMPLETE = YES`
- `COMPOSITE_VERIFICATION_COMPLETE = YES`
- `FORMAL_GLOBAL_VERIFICATION_COMPLETE = YES`
- `PILOT_ACCEPTANCE_COMPLETE = NO`
- `PUBLICATION_READY = NO`
- `READY_FOR_SCIENTIFIC_ANALYSIS = YES`

## Sections

| section | status | checks | failing |
| --- | --- | --- | --- |
| identity | PASS | 3 | - |
| runs | PASS | 51 | - |
| tree | PASS | 5 | - |
| history | PASS | 4 | - |
| population | PASS | 8 | - |
| phase2 | PASS | 7 | - |
| coverage | PASS | 10 | - |
| acceptance | PASS | 6 | - |
| disclosures | PASS | 5 | - |

## The seven runs

| run | block | models | contract | authorization | manifest | verification evidence |
| --- | --- | --- | --- | --- | --- | --- |
| pilot_002 | pilot | 11 | 4aaa00c265ee14a8 | 5797edfe37cf6ef9 | complete | {"verification": "thesis/results/intermediate/pilot_002/post_run_verification.json", "verifier": "thesis/evaluation/verify_pilot_run.py (post_run_verificatio... |
| full_ext_001 | full_ext | 11 | e3843f81f79638b2 | 45bdf8edf131edc5 | complete | {"verification": "thesis/evaluation/recovery/full_ext_recovery_001/parent_report.json", "verifier": "thesis/evaluation/verify_parent_base_evidence.py (parent... |
| full_ext_recovery_001 | full_ext | 11 | 884ad0fb4b407117 | 446a437098d2cf11 | complete | {"verification": null, "verifier": "thesis/evaluation/verify_recovery_run.py (never persisted; acceptance predicate 33/33 within recovery_001 unsatisfiable a... |
| full_ext_recovery_002 | full_ext | 2 | f00b6bbadc105320 | c15a4bf028c6effb | complete | {"verification": null, "verifier": "thesis/evaluation/verify_successor_run.py (in-process PASS, no persisted report)", "persisted": false, "native_verifier_s... |
| full_ext_recovery_003 | full_ext | 4 | e7becfe7d5a2228c | 7104b1298754b1b0 | complete | {"verification": "thesis/results/intermediate/full_ext_recovery_003/verification", "verifier": "thesis/recovery_successor_003/verify.py (successor_model_veri... |
| full_ext_recovery_004 | full_ext | 5 | f2e77c2cd31a07f6 | 8916689a17dd54d4 | complete | {"verification": "thesis/results/intermediate/full_ext_recovery_004/verification", "verifier": "thesis/recovery_successor_004/verify.py (successor_model_veri... |
| full_ext_phase2_001 | full_ext | 11 | 1fd28309588a328d | ad9f4778755bd823 | complete | {"verification": "thesis/results/intermediate/full_ext_phase2_001/verification", "verifier": "thesis/recovery_successor_005/verify.py (phase2_model_verificat... |

## Population and candidates

- base population: {"source": "thesis/evaluation/full_001_composite.json", "source_raw_sha256": "a623cbf72b2c4373af7799318bec6247e93626b9c490d85e344c5635c0671be0", "study_manif...
- composite cells: {"total": 5460, "per_block": {"pilot": 943, "full_ext": 4517}, "base_per_block": {"pilot": 396, "full_ext": 1584}, "candidates": {"pilot": {"static_feedback"...
- repair loops terminal: 66/66 (owners {"pilot": {"pilot_002": 33}, "full_ext": {"full_ext_recovery_001": 6, "full_ext_recovery_002": 4, "full_ext_recovery_003": 8, "full_ext_recovery_004": 15}})
- enhanced (sample, spec) pairs: {"pilot": 18860, "full_ext": 90340, "total": 109200}
- composite artifact: {"relative": "thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json", "persisted": true, "raw_sha256": "4553fa16c71d176d03dca3e56041462e72f96...
- phase-2 incidents: {"archived_torn_tails": 0, "repeated_build_groups": 0, "interrupted_invocations": 1}

## Pilot publication gate

- publication_allowed: False; result acceptance: None
- reason: result acceptance pending (no pilot_002_result_acceptance.v1 artifact)
- label required: pilot_002 / Pilotexperiment (12 benchmarks x 3 execution models x 11 models, 1 sample per prompt)

## Verification scopes

- {"scope": "verify_pilot_run.v1 / post_run_verification.v1", "runs": ["pilot_002"], "verifier": "thesis/evaluation/verify_pilot_run.py (post_run_verification....
- {"scope": "BASE_ONLY_NOT_FULL_RUN_ACCEPTANCE", "runs": ["full_ext_001"], "verifier": "thesis/evaluation/verify_parent_base_evidence.py (parent_base_evidence_...
- {"scope": "SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE", "runs": ["full_ext_recovery_003", "full_ext_recovery_004", "full_ext_recovery_002 (in-...
- {"scope": "PHASE2_MEASUREMENT_COMPLETENESS_PILOT_AND_FULL_EXT", "runs": ["full_ext_phase2_001"], "verifier": "thesis/recovery_successor_005/verify.py (phase2...
- {"scope": "STUDY_GLOBAL_VERIFICATION_SEVEN_RUNS_READ_ONLY", "runs": ["pilot_002", "full_ext_001", "full_ext_recovery_001", "full_ext_recovery_002", "full_ext...
- {"scope": "RETROSPECTIVE_READONLY_COVERAGE_OF_RECOVERY_001_002_BY_STUDY_CLOSURE_001", "runs": ["full_ext_recovery_001", "full_ext_recovery_002"], "verifier":...

## Checks

### identity (PASS)

| check | status | detail |
| --- | --- | --- |
| identity:git_state | PASS | {"head": "69ee4f390134ba78e3a332bebcea54202de1feba", "branch": "thesis-static-analysis", "clean": true, "uncommitted_paths": [], "uncommitted_count": 0, "mod... |
| identity:closure_source_pins | PASS | {"closure_modules": 16, "reused_modules": 18, "missing": []} |
| identity:provider_isolation | PASS | {"package": "thesis/study_closure", "modules_scanned": ["__init__.py", "acceptance.py", "composite_closure.py", "core.py", "coverage.py", "disclosures.py", "... |

### runs (PASS)

| check | status | detail |
| --- | --- | --- |
| runs:pilot_002:manifest_complete | PASS | {"git_commit": "bdb6ac14bd1691422ff643d53f2d4ac6e1ff664c", "created_at_utc": "2026-09-17T17:29:33.869334Z", "fragments": 135, "config_drift_records": 1, "pro... |
| runs:pilot_002:frozen_contract | PASS | {"contract_sha256": "4aaa00c265ee14a8ea5389c2191e9be568122154b74976325b911afd536b1d48", "profile": "pilot", "model_ids": 11, "problems": []} |
| runs:pilot_002:authorization | PASS | {"authorization_sha256": "5797edfe37cf6ef9b1d4b2c056fa24f46b7866635f76bcee8bda39517803c4de", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:pilot_002:fragment_integrity | PASS | {"fragments": 135, "snapshot_fragments": 135, "stray_files": [], "history_entries": 683, "history_outcomes": {"created": 134, "idempotent": 549}, "refused_hi... |
| runs:pilot_002:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:pilot_002:stage_runtime_stamps | PASS | {"stages": ["correctness", "dynamic", "enhanced", "repair_evaluation", "static.llov", "static.main", "static.parcoach"], "count": 7, "problems": []} |
| runs:pilot_002:models | PASS | {"model_ids": ["claude_fable_5", "claude_opus_5", "deepseek_v4_flash", "deepseek_v4_pro", "gemini_31_pro", "gemini_36_flash", "openai_gpt55", "openai_gpt56_s... |
| runs:full_ext_001:manifest_complete | PASS | {"git_commit": "b22ecba74f06f74f0e52700358830d47e15f586e", "created_at_utc": "2026-09-23T17:42:49.687671Z", "fragments": 27, "config_drift_records": 0, "prob... |
| runs:full_ext_001:frozen_contract | PASS | {"contract_sha256": "e3843f81f79638b2de180a1cdb0cc0b16ba1f9fd42bca3ba1e0d5c02abe059e4", "profile": "full_extension", "model_ids": 11, "problems": []} |
| runs:full_ext_001:authorization | PASS | {"authorization_sha256": "45bdf8edf131edc5e9f735554ec5000cc7eedc55ed6a9875d3b2e32e31303943", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:full_ext_001:fragment_integrity | PASS | {"fragments": 27, "snapshot_fragments": 27, "stray_files": [], "history_entries": 30, "history_outcomes": {"created": 27, "idempotent": 3}, "refused_history_... |
| runs:full_ext_001:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:full_ext_001:stage_runtime_stamps | PASS | {"stages": ["correctness", "dynamic", "static.llov", "static.main", "static.parcoach"], "count": 5, "problems": []} |
| runs:full_ext_001:models | PASS | {"model_ids": ["claude_fable_5", "claude_opus_5", "deepseek_v4_flash", "deepseek_v4_pro", "gemini_31_pro", "gemini_36_flash", "openai_gpt55", "openai_gpt56_s... |
| runs:full_ext_recovery_001:manifest_complete | PASS | {"git_commit": "8d88ebc69ecf24a685dfbd67579dc4fefd79208c", "created_at_utc": "2026-09-29T21:21:42.962541Z", "fragments": 26, "config_drift_records": 0, "prob... |
| runs:full_ext_recovery_001:frozen_contract | PASS | {"contract_sha256": "884ad0fb4b40711756f1ff6f74591f8be87f79e4625f64484c13b415f6307d07", "profile": "recovery", "model_ids": 11, "problems": []} |
| runs:full_ext_recovery_001:authorization | PASS | {"authorization_sha256": "446a437098d2cf1143a31d471c4579aa2990e9f7bfc27a0150cb5bea9ebe11e2", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:full_ext_recovery_001:fragment_integrity | PASS | {"fragments": 26, "snapshot_fragments": 26, "stray_files": [], "history_entries": 60, "history_outcomes": {"created": 26, "idempotent": 34}, "refused_history... |
| runs:full_ext_recovery_001:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:full_ext_recovery_001:stage_runtime_stamps | PASS | {"stages": ["repair_evaluation", "static.parcoach"], "count": 2, "problems": []} |
| runs:full_ext_recovery_001:models | PASS | {"model_ids": ["claude_fable_5", "claude_opus_5", "deepseek_v4_flash", "deepseek_v4_pro", "gemini_31_pro", "gemini_36_flash", "openai_gpt55", "openai_gpt56_s... |
| runs:full_ext_recovery_002:manifest_complete | PASS | {"git_commit": "196b262b2b10a16a180dd8c40d477bc4abbbb865", "created_at_utc": "2026-10-09T17:51:25.486045Z", "fragments": 15, "config_drift_records": 0, "prob... |
| runs:full_ext_recovery_002:frozen_contract | PASS | {"contract_sha256": "f00b6bbadc105320a6c7e42d04188f14440503989c5a96f5a21fba972d2dfde9", "profile": "recovery_successor", "model_ids": 2, "problems": []} |
| runs:full_ext_recovery_002:authorization | PASS | {"authorization_sha256": "c15a4bf028c6effb9d1616492d3814df25ad1a986319df74a38a0a6446a5892d", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:full_ext_recovery_002:fragment_integrity | PASS | {"fragments": 15, "snapshot_fragments": 15, "stray_files": [], "history_entries": 36, "history_outcomes": {"created": 15, "idempotent": 21}, "refused_history... |
| runs:full_ext_recovery_002:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:full_ext_recovery_002:stage_runtime_stamps | PASS | {"stages": ["repair_evaluation", "static.llov", "static.parcoach"], "count": 3, "problems": []} |
| runs:full_ext_recovery_002:models | PASS | {"model_ids": ["deepseek_v4_flash", "qwen3_coder_api"], "count": 2, "full_set_required": false, "problems": []} |
| runs:full_ext_recovery_003:manifest_complete | PASS | {"git_commit": "9170197a1b9fd30651582e8e7bcdc4ac53dd3b47", "created_at_utc": "2026-10-10T14:22:30.457330Z", "fragments": 23, "config_drift_records": 0, "prob... |
| runs:full_ext_recovery_003:frozen_contract | PASS | {"contract_sha256": "e7becfe7d5a2228c2cd13d2b5782f47ce0a99a3fd9bfe03b4fa83762681ed0a7", "profile": "recovery_successor_003", "model_ids": 4, "problems": []} |
| runs:full_ext_recovery_003:authorization | PASS | {"authorization_sha256": "7104b1298754b1b06b3956db40dd78cbe26222058a93c8af3437e57c74704038", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:full_ext_recovery_003:fragment_integrity | PASS | {"fragments": 23, "snapshot_fragments": 23, "stray_files": [], "history_entries": 84, "history_outcomes": {"created": 23, "idempotent": 61}, "refused_history... |
| runs:full_ext_recovery_003:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:full_ext_recovery_003:stage_runtime_stamps | PASS | {"stages": ["repair_evaluation", "static.llov", "static.parcoach"], "count": 3, "problems": []} |
| runs:full_ext_recovery_003:models | PASS | {"model_ids": ["claude_fable_5", "claude_opus_5", "gemini_31_pro", "openai_gpt55"], "count": 4, "full_set_required": false, "problems": []} |
| runs:full_ext_recovery_004:manifest_complete | PASS | {"git_commit": "7b748ca09950d99e42412d3b7872a3c8ae6743cc", "created_at_utc": "2026-10-11T14:09:26.164401Z", "fragments": 32, "config_drift_records": 0, "prob... |
| runs:full_ext_recovery_004:frozen_contract | PASS | {"contract_sha256": "f2e77c2cd31a07f654129ebf1f3651a43917059c054fe18efa947b7d8d4198ab", "profile": "recovery_successor_004", "model_ids": 5, "problems": []} |
| runs:full_ext_recovery_004:authorization | PASS | {"authorization_sha256": "8916689a17dd54d47e13922890c3cf2c94743b9fa5112a7d265f6b30b2807b1d", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:full_ext_recovery_004:fragment_integrity | PASS | {"fragments": 32, "snapshot_fragments": 32, "stray_files": [], "history_entries": 144, "history_outcomes": {"created": 32, "idempotent": 112}, "refused_histo... |
| runs:full_ext_recovery_004:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:full_ext_recovery_004:stage_runtime_stamps | PASS | {"stages": ["repair_evaluation", "static.llov", "static.parcoach"], "count": 3, "problems": []} |
| runs:full_ext_recovery_004:models | PASS | {"model_ids": ["deepseek_v4_pro", "qwen36_35b_a3b", "qwen37_max", "gemini_36_flash", "openai_gpt56_sol"], "count": 5, "full_set_required": false, "problems":... |
| runs:full_ext_phase2_001:manifest_complete | PASS | {"git_commit": "19ad88b351ae9dd1bde079d2629e9bfbdc61b6e8", "created_at_utc": "2026-10-13T17:31:23.585928Z", "fragments": 76, "config_drift_records": 0, "prob... |
| runs:full_ext_phase2_001:frozen_contract | PASS | {"contract_sha256": "1fd28309588a328d2459cbdf56cc95110492e15a84bd9afd2c0074e2135cdbc0", "profile": "recovery_successor_005", "model_ids": 11, "problems": []} |
| runs:full_ext_phase2_001:authorization | PASS | {"authorization_sha256": "ad9f4778755bd8230d3bac11d438da2b4affec5dadcaab28636c60bbb43cf1ba", "decision": "START_ALLOWED", "schema_version": "run_start_author... |
| runs:full_ext_phase2_001:fragment_integrity | PASS | {"fragments": 76, "snapshot_fragments": 76, "stray_files": [], "history_entries": 204, "history_outcomes": {"created": 76, "idempotent": 128}, "refused_histo... |
| runs:full_ext_phase2_001:runtime_t0 | PASS | {"probe_status": "OK", "fresh_runtime_condition_sha256": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "readiness_runtime_condition_sha... |
| runs:full_ext_phase2_001:stage_runtime_stamps | PASS | {"stages": ["correctness", "dynamic", "enhanced", "static.llov", "static.main", "static.parcoach"], "count": 6, "problems": []} |
| runs:full_ext_phase2_001:models | PASS | {"model_ids": ["claude_fable_5", "claude_opus_5", "deepseek_v4_flash", "deepseek_v4_pro", "gemini_31_pro", "gemini_36_flash", "openai_gpt55", "openai_gpt56_s... |
| runs:runtime_identity_uniform | PASS | {"values": {"readiness_rt": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41dd0e944ae657510a", "fresh_rt": "0d5f4889334dea26ab74a39df493b7d861eefba49fb7bf41... |
| runs:enhanced_specs_uniform | PASS | {"sha256": "49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292", "recorded_paths": ["thesis/results/cache/enhanced/specs.jsonl"], "spec_counts"... |

### tree (PASS)

| check | status | detail |
| --- | --- | --- |
| tree:intermediate_scope | PASS | {"area": "thesis/results/intermediate", "directories": 35, "counts": {"study": 27, "excluded": 1, "out_of_study": 7, "forbidden": 0, "unexplained": 0}, "stud... |
| tree:raw_scope | PASS | {"area": "thesis/results/raw", "directories": 59, "counts": {"study": 22, "excluded": 1, "out_of_study": 36, "forbidden": 0, "unexplained": 0}, "study": ["fu... |
| tree:no_successor_locks | PASS | {"directory": "thesis/results/intermediate/.successor_locks", "present": true, "lock_files": [], "other_entries": ["full_ext_phase2_001.writer.lock.interrupt... |
| tree:phase2_results_inventory | PASS | {"relative": "thesis/results/intermediate/full_ext_phase2_001", "file_count": 789, "total_bytes": 224821838, "inventory_sha256": "3fb738ea4ad45b1b0f319cd2e38... |
| tree:excluded_parent_repair_present_not_adopted | PASS | {"excluded_runs": ["full_ext_001__static_feedback__iter1"], "excluded_answers": {"full_ext_001__static_feedback__iter1": 62}, "target_source_runs": 15, "asse... |

### history (PASS)

| check | status | detail |
| --- | --- | --- |
| history:phase2_lineage_verify | PASS | {"lineage_sha256": "81a5a18350cfd76c2b4b18a15cb97fabfa9594230729741c8a4b32b9c4317bb6", "protected_file_counts": {"pilot_002": 3258, "full_ext_001": 1832, "fu... |
| history:custody_chain | PASS | {"protected_history": {"path": "thesis/evaluation/recovery/full_ext_recovery_001/protected_history.json", "result_files": 5090}, "full_ext_recovery_004_linea... |
| history:phase2_definitions_bound | PASS | {"definitions": {"lineage_sha256": "81a5a18350cfd76c2b4b18a15cb97fabfa9594230729741c8a4b32b9c4317bb6", "targets_sha256": "c836011f34ad8961aaf5ed46b325d9542bc... |
| history:target_table_rederives | PASS | {"frozen_table_sha256": "c836011f34ad8961aaf5ed46b325d9542bc6c22e5b01c6818e40fd216feacec7", "rebuilt_table_sha256": "c836011f34ad8961aaf5ed46b325d9542bc6c22e... |

### population (PASS)

| check | status | detail |
| --- | --- | --- |
| population:census_66_66 | PASS | {"summary": {"total_repair_loops_done": "66/66", "blocks": {"pilot": {"terminal": 33, "loops": 33, "open": [], "not_started": [], "owners": {"pilot_002": 33}... |
| population:census_digest_frozen | PASS | {"rule": "canonical_sha256(census.summary(census.census(root, MODELS)))", "computed": "f9dfa256ee18f70912680845a50415fffd71e8c6a0d4198cd7d0584c60054472", "li... |
| population:base_cells_1980 | PASS | {"population": {"source": "thesis/evaluation/full_001_composite.json", "source_raw_sha256": "a623cbf72b2c4373af7799318bec6247e93626b9c490d85e344c5635c0671be0... |
| population:derived_lineages_own_no_base_cells | PASS | {"lineages": [{"run_id": "full_ext_recovery_001", "role": "repair_candidates", "base_cells": 0, "contract_path": "thesis/evaluation/recovery/full_ext_recover... |
| population:composite_reconstruction | PASS | {"composite_sha256": "953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0", "cells": {"total": 5460, "per_block": {"pilot": 943, "full_ext": 451... |
| population:composite_cells_partition | PASS | {"cells_total": 5460, "base_per_block": {"pilot": 396, "full_ext": 1584}, "candidates_per_block": {"pilot": 547, "full_ext": 2933}, "candidates_per_owner_run... |
| population:composite_owners | PASS | {"coverage": {"pilot": {"static": {"cells": 943, "with_evidence": 943, "owners": {"pilot_002": 943}, "supplemented_by": {}}, "correctness": {"cells": 943, "w... |
| population:composite_persisted | PASS | {"persisted": true, "relative": "thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json", "raw_sha256": "4553fa16c71d176d03dca3e56041462e72f96... |

### phase2 (PASS)

| check | status | detail |
| --- | --- | --- |
| phase2:plan_empty | PASS | {"totals": {"enhanced": {"expected_pairs": 90340, "expected_samples": 4517, "items": 0, "samples": 0, "targets_open": 0}, "correctness": {"items": 0, "sample... |
| phase2:reports_present | PASS | {"models": {"claude_fable_5": {"status": "PASS", "model_complete": true, "raw_sha256": "463875f777d7aff8f7dfc287ed043c7ecb71a9a8395b41a0d8e64cb6760e23fb", "p... |
| phase2:reports_reproduce | PASS | {"models": {"claude_fable_5": {"status": "PASS", "model_complete": true, "persisted_status": "PASS", "persisted_model_complete": true, "checks": 104, "checks... |
| phase2:enhanced_pairs_total | PASS | {"pilot_pairs": 18860, "full_ext_pairs": 90340, "total": 109200, "rows": {"pilot": 18860, "full_ext": 90340}, "composite_pairs": {"pilot": 18860, "full_ext":... |
| phase2:stage_history | PASS | {"stages": {"static.main": {"invoked": 2, "completed": 2, "other": 0, "interrupted_invocations": 0, "last_status": "completed", "last_open_items": [], "invoc... |
| phase2:ledger_hygiene | PASS | {"per_model": {"claude_fable_5": {"stray": 0, "temporary_files": 0, "archived_torn_tails": [], "repeated_build_groups": 0}, "claude_opus_5": {"stray": 0, "te... |
| phase2:manifest_invocations_registered | PASS | {"invocations_per_stage": {"static.main": 11, "static.parcoach": 11, "static.llov": 11, "correctness": 11, "dynamic": 11, "enhanced": 11}, "reports": 11, "pr... |

### coverage (PASS)

| check | status | detail |
| --- | --- | --- |
| coverage:pilot_report | PASS | {"relative": "thesis/results/intermediate/pilot_002/post_run_verification.json", "raw_sha256": "55fdb6351ee3d1ba1c4adf713590186cef2015622acde715f5afc86e3b014... |
| coverage:parent_report | PASS | {"relative": "thesis/evaluation/recovery/full_ext_recovery_001/parent_report.json", "raw_sha256": "8985731d5e6ea9bb2972de6c42284326c6030ab39129a5f39d3e559d28... |
| coverage:successor_reports:full_ext_recovery_003 | PASS | {"directory": "thesis/results/intermediate/full_ext_recovery_003/verification", "models": ["claude_fable_5", "claude_opus_5", "gemini_31_pro", "openai_gpt55"... |
| coverage:successor_reports:full_ext_recovery_004 | PASS | {"directory": "thesis/results/intermediate/full_ext_recovery_004/verification", "models": ["deepseek_v4_pro", "qwen36_35b_a3b", "qwen37_max", "gemini_36_flas... |
| coverage:retrospective_reverification:full_ext_recovery_002 | PASS | {"models": ["deepseek_v4_flash", "qwen3_coder_api"], "per_model": {"deepseek_v4_flash": {"retrospective_status": "PASS_WITH_SUBSTITUTED_AUTHORITY_CHECK", "na... |
| coverage:retrospective_reverification:full_ext_recovery_003 | PASS | {"models": ["claude_fable_5", "claude_opus_5", "gemini_31_pro", "openai_gpt55"], "per_model": {"claude_fable_5": {"retrospective_status": "PASS_WITH_SUBSTITU... |
| coverage:retrospective_reverification:full_ext_recovery_004 | PASS | {"models": ["deepseek_v4_pro", "qwen36_35b_a3b", "qwen37_max", "gemini_36_flash", "openai_gpt56_sol"], "per_model": {"deepseek_v4_pro": {"retrospective_statu... |
| coverage:recovery_001_map | PASS | {"run_id": "full_ext_recovery_001", "status": "PASS", "native_verifier_status": "NOT_APPLICABLE_AFTER_HANDOFF", "owned_loops": 6, "covered_by": [{"evidence":... |
| coverage:recovery_002_map | PASS | {"run_id": "full_ext_recovery_002", "status": "PASS", "native_verifier_status": "NOT_PERSISTED_INPROCESS_PASS", "owned_loops": 4, "covered_by": [{"evidence":... |
| coverage:scopes_unique | PASS | {"scopes": ["verify_pilot_run.v1 / post_run_verification.v1", "BASE_ONLY_NOT_FULL_RUN_ACCEPTANCE", "SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE... |

### acceptance (PASS)

| check | status | detail |
| --- | --- | --- |
| acceptance:pilot_post_run_report | PASS | {"verifier_version": "verify_pilot_run.v1", "schema_version": "post_run_verification.v1", "counts": {"PASS": 269, "FAIL": 0, "UNRESOLVED": 0}, "digest": "53d... |
| acceptance:publication_policy_fresh | PASS | {"status": "FRESH", "run_id": "pilot_002", "publication_policy_sha256": "3f384ac76533e6c82389f376623af2fe34d7364d92b49fea47d896db09761d4e", "contract_bound_s... |
| acceptance:mandatory_disclosure_sources | PASS | {"sources": 11, "satisfied": 11, "entries": [{"id": "semantic_disclosure_dense_la_00", "artifact": "thesis/evaluation/semantic_decisions_pilot002.json", "fie... |
| acceptance:publication_gate_now | PASS | {"publication_allowed": false, "result_acceptance_status": null, "acceptance_file_present": false, "reasons": ["result acceptance pending (no pilot_002_resul... |
| acceptance:template_valid | PASS | {"status": "PENDING", "reasons": ["result acceptance lacks required field(s): decided_by, decided_on", "result acceptance status is PENDING, not ACCEPTED"], ... |
| acceptance:readiness_document | PASS | {"status": "AUTHOR_DECISION_REQUIRED", "readiness_sha256": "10706829c751e359092adaa56e22e8c03bcaff7bf8c8fb733c1acc6b36a8ee54"} |

### disclosures (PASS)

| check | status | detail |
| --- | --- | --- |
| disclosures:inputs_available | PASS | {"missing": [], "note": null} |
| disclosures:register_built | PASS | {"items": 17, "statuses": {"ARTIFACT_BOUND": 5, "COMPUTED": 12}, "register_sha256": "ed677f7c49cd0ba1d5aaab3c846ba497f91c2e956917c862930c46c50c1d81f5", "prob... |
| disclosures:policy_sources_ok | PASS | {"sources": 11, "unsatisfied": []} |
| disclosures:infer_outlier_found | PASS | {"above_threshold": 1, "max_seconds": 27672.433, "threshold_seconds": 3600, "top": [{"seconds": 27672.433, "run": "full_ext_recovery_003__combined_feedback__... |
| disclosures:no_numbers_from_memory | PASS | {"evidence_entries": 115, "problems": [], "problem_count": 0} |

## Closure-protected bytes

- `full_ext_phase2_001`: 789 files, 224821838 bytes, inventory sha256 `3fb738ea4ad45b1b0f319cd2e38e3d6213173d8bb55f7ed0aa2a40475252711f`

## Source pins

- closure:
  - `thesis/study_closure/__init__.py` `cc8aed2785ba340ab3611e3eefae975326cdaaa46d6fb2284725b56579d71643`
  - `thesis/study_closure/acceptance.py` `2b24774ddeb713bf31205a377d0fc8d671549edebcc2e50df5720adebc79cb07`
  - `thesis/study_closure/composite_closure.py` `7c71d1aacf208c39476c2da110b919dbe278b1e06b5c64dd4185573d7997edf0`
  - `thesis/study_closure/core.py` `d683e29298fbee7b5a694970094c8b0760f879d6d3e0cb404c1b808cc61b8ff2`
  - `thesis/study_closure/coverage.py` `79eeb0cfa7b55a0c2592f908510a78436376eacaf0cc39e4b4402055ec318ba0`
  - `thesis/study_closure/disclosures.py` `4da87efe7259f401c87ed5b8efecf894e8ba1be5af40d915fc93a51f942bfe7e`
  - `thesis/study_closure/report.py` `4c54e6aaded57fa2c7ee50b365c2ec6020f8e50b25dfb9c8087f9577ab90e2bc`
  - `thesis/study_closure/run.py` `990a60ec632c9d6f7f719deff20601523728418b7c5ecc66a67c182e3e5108dc`
  - `thesis/study_closure/runs.py` `309e93ceb8f882d6ef1469f96a9db31a6aa44f27a57161005c8bd0744f9872a3`
  - `thesis/study_closure/study.py` `466d04864aed163f0087d9c1c7317c8ae8f1e3e34db36804e145bd289384b327`
  - `thesis/study_closure/test_acceptance.py` `f8c3ed0f6aadf490a25c986f9337b568d276612b7337b2c58db62d94009f2b84`
  - `thesis/study_closure/test_coverage.py` `018a55701b98850a1f627cbcc6222accbb0a27767114fd881ce67733ea080586`
  - `thesis/study_closure/test_disclosures.py` `c55e30d15f8176319792602ec037f5231ef920d54a1c52895ee277382345eb89`
  - `thesis/study_closure/test_report.py` `a45f8cb84ac5f0709617b5e3da42f40cd59a2b7049fd581613e4afb6d7178ae4`
  - `thesis/study_closure/test_runs.py` `f9d94b01877e8d99b88d9f8719f16d2d3202542d9b02f9b5f5e80ed9ede34fa8`
  - `thesis/study_closure/test_study.py` `a41be807750c0c04f1b17652d8d25425ce8a14e6844fab20e586deebec404dfb`
- reused:
  - `thesis/recovery_successor_005/composite.py` `bab685c53d3fc4aba165149827b59567082adb29ae2b124c87e3cee4afc05ef0`
  - `thesis/recovery_successor_005/verify.py` `dc26e3085dc35193256fda337062a052f8fe3eaf8cb6b78ae563c554593a087f`
  - `thesis/recovery_successor_005/plan.py` `fe92a62ee15b20b5e01dc06aa47345ab3a64aa7987b10fcfc4066be75fe8d883`
  - `thesis/recovery_successor_005/ledger.py` `4313da1fabf9d1c7c4fe18dbf6adb5d44e02f4217dbfa652a583d6e5bb8191b5`
  - `thesis/recovery_successor_005/targets.py` `223d9fc4cd0ebe4614d36980e7eaec8f60c7f466f1a058011f69231a89878bc8`
  - `thesis/recovery_successor_005/lineage.py` `eb30e2e3f84f11be150ac1f88d1cd548d23da894f858d4745c8e961affd34b46`
  - `thesis/recovery_successor_004/census.py` `954141ba11e18d8dd55a9d3a88e93c17abb4d8f7ecf9b6d25e9a22483e432957`
  - `thesis/recovery_successor_004/verify.py` `2d097820171799c94345c2372122fd6df87a79d392165ba57659b568375666e2`
  - `thesis/recovery_successor_003/verify.py` `3891be6f5354e3dde630fe61178e2dc03bea18a87d7246e2aea3f4093969556b`
  - `thesis/evaluation/verify_successor_run.py` `7a47f2ceb171e34e5825f4e22031bb02c00b7f9b80cd2eaed597af3481c3e8f7`
  - `thesis/evaluation/verify_pilot_run.py` `2c7b4a645d147ea9b42d0aff64d014ed3728d49956d5a40dda07179cfd68f0ff`
  - `thesis/evaluation/pilot_freeze.py` `406b0a19cbfd9c422c3dd35b0edcc29f6807d238d8f29b99685439aedbdb10c1`
  - `thesis/evaluation/pilot_run_contract.py` `9dd2845daa58336118802d9c833db56c4ff0678f174c3b9bde9b942847fa105e`
  - `thesis/evaluation/run_authorization.py` `da3dfff68ae015fe45130ee149b9cfdaf27101a548b764eb0fe291cc094b29f3`
  - `thesis/evaluation/manifest_fragments.py` `4a68597d17def75874cab628da2a62da4a760fd2fc41eb58edee80fad3f52c39`
  - `thesis/evaluation/stage_runtime.py` `baf95e0c2555dbca1431b8af952bf53d6610a0f37ea98134967d711bc9b31ea3`
  - `thesis/evaluation/composite_study.py` `cfa77248d200ab9cb54ddf59a0db834d4862e3f320b95db751cbd0900885f3ec`
  - `thesis/evaluation/condition_hashing.py` `1f8eb71bc9550845697e6de5dd5cfbe3057e751401dd19d38b7a57edef2b84db`

Generated 2026-10-17T13:53:21Z (started 2026-10-17T13:09:43Z).
