# study_analysis_001 - validation report (PASS)

Schema `study_analysis_validation.v1`; validation sha256 `70050c1e94f31b564a45d16f1d9218ca00afc9d66ba2a0b2bf6de8f7858a6a3c`.

| check | status | detail |
| --- | --- | --- |
| dataset_index | PASS | {"counts": {"base_cells": 1980, "artifacts": 5460, "tool_entries": 60060, "findings": 57263, "enhanced_pairs": 109200, "trajectories": 5940, "generations": 5460}} |
| addendum_bound | PASS | {"addendum_id": "study_analysis_001.addendum_1", "status": "DECLARED_AFTER_DRY_RUN", "canonical_sha256": "348b1516b8c194012323b1fcc9b5fbd94604e9866a1b6fd5dcd8ea30af002486", "metrics": ["X01", "X02", "X03", "X04", "X05", "X06"], "methodology_canonical_sha256": "cb34143728ceaa08befe91100c741a6d95df9b39ebb8b44c4274a9d12acb20dc"} |
| inputs_bound | PASS | {"composite_sha256": "953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0", "composite_raw_sha256": "4553fa16c71d176d03dca3e56041462e72f96d04c3f615aaa64b42d2e4c56f45", "targets_sha256": "c836011f34ad8961aaf5ed46b325d9542bc6c22e5b01c6818e40fd216feacec7", "lineage_sha256": "81a5a18350cfd76c2b4b18a15cb97fabfa9594230729741c8a4b32b9c4317bb6", "census_digest": "f9dfa256ee18f70912680845a5... |
| counts_composite | PASS | {"cells": {"total": 5460, "per_block": {"pilot": 943, "full_ext": 4517}, "base_per_block": {"pilot": 396, "full_ext": 1584}, "candidates": {"pilot": {"static_feedback": {"iter1": 157, "iter2": 79}, "test_feedback": {"iter1": 35, "iter2": 17}, "combined_feedback": {"iter1": 166, "iter2": 93}}, "full_ext": {"static_feedback": {"iter1": 800, "iter2": 449}, "test_feedback": {"iter1": 224, "iter2": ... |
| counts_stage_coverage | PASS | {"problems": [], "problem_count": 0} |
| counts_census | PASS | {"repair_loops": "66/66", "problems": [], "problem_count": 0} |
| trajectories_ledger | PASS | {"ledger_samples": 5940, "problems": [], "problem_count": 0} |
| composite_binding | PASS | {"cells": 5460, "reproduced_sha256": "953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0", "subsumed_rejections": 1102, "problems": [], "problem_count": 0} |
| uniqueness | PASS | {"problems": [], "problem_count": 0} |
| ownership | PASS | {"problems": [], "problem_count": 0} |
| excluded_runs | PASS | {"files_checked": 4516, "problems": [], "problem_count": 0} |
| block_separation | PASS | {"benchmarks": {"pilot": 12, "full_ext": 48}, "problems": [], "problem_count": 0} |
| table_targets | PASS | {"targets": 77, "problems": [], "problem_count": 0} |
| dataset_consistency | PASS | {"problems": [], "problem_count": 0} |
| applicability | PASS | {"inapplicable_tools_in_gap_states": 0, "problems": [], "problem_count": 0} |
| enhanced_gates | PASS | {"groups": 3600, "gated_groups": 48, "gated_groups_per_block": {"pilot": 27, "full_ext": 21}, "problems": [], "problem_count": 0} |
| trajectory_structure | PASS | {"problems": [], "problem_count": 0} |
| estimates_schema | PASS | {"problems": [], "problem_count": 0} |
| metric_coverage | PASS | {"metrics": 50, "estimates": 29418, "post_freeze_estimates": 447, "problems": [], "problem_count": 0} |
| estimate_bounds | PASS | {"problems": [], "problem_count": 0} |
| estimate_recompute | PASS | {"recomputed": 29418, "not_recomputed": 0, "recomputed_per_metric": {"C01": 432, "C02": 423, "C03": 105, "C04": 204, "C05": 216, "D01": 420, "D02": 240, "D03": 60, "E01": 2352, "E02": 2352, "E03": 48, "E04": 147, "E05": 180, "F01": 1755, "F02": 1755, "F03": 585, "F04": 180, "F05": 1110, "F06": 12, "G01": 216, "G02": 81, "Q01": 156, "Q02": 156, "Q03": 156, "Q04": 1560, "Q05": 696, "Q06": 2364, "... |
| final_equals_step2 | PASS | {"pairs": 2934, "problems": [], "problem_count": 0} |
| distribution_sums | PASS | {"groups": 2427, "problems": [], "problem_count": 0} |
| block_additivity | PASS | {"checked": 9451, "partial_counterparts": 9, "problems": [], "problem_count": 0} |
| primary_family | PASS | {"hypotheses": 12, "alpha": 0.05, "problems": [], "problem_count": 0} |
| tables | PASS | {"tables": 26, "degenerate_cells": 98, "bl01_tables": 14, "degenerate_unshown_cells": 307, "post_freeze_tables": 5, "problems": [], "problem_count": 0} |
| figures | PASS | {"figures": 5, "bl01_figures": 4, "reasoning_figures": 2, "effective_states_figures": 1, "problems": [], "problem_count": 0} |
| input_stability | PASS | {"files": 2258, "manifest_sha256": "01f753ec45dc476224069edcee7b8c4c3139d0adbf0d0deb2bb02cc8b641d306", "start_manifest_sha256": "20f309707ba7cf8f94a6728f34496d182e15ae21cc5f20ef88547773306cf058", "write_mode": true, "problems": [], "problem_count": 0} |
| reproducibility | PASS | {"problems": [], "problem_count": 0} |

## Summary

```json
{
 "checks": 29,
 "passed": 29,
 "failing": [],
 "dataset_counts": {
  "base_cells": 1980,
  "artifacts": 5460,
  "tool_entries": 60060,
  "findings": 57263,
  "enhanced_pairs": 109200,
  "trajectories": 5940,
  "generations": 5460
 },
 "estimates": 29418,
 "tables": 26,
 "figures": 5,
 "composite_sha256": "953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0",
 "addendum_canonical_sha256": "348b1516b8c194012323b1fcc9b5fbd94604e9866a1b6fd5dcd8ea30af002486",
 "census_digest": "f9dfa256ee18f70912680845a50415fffd71e8c6a0d4198cd7d0584c60054472",
 "manifest_sha256": "01f753ec45dc476224069edcee7b8c4c3139d0adbf0d0deb2bb02cc8b641d306"
}
```

