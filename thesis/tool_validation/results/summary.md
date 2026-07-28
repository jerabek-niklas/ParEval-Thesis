# Tool-Validation Summary

## Definitions

**Row unit.** One row of the underlying data is one (kernel, tool) run.
A *kernel* is one labeled testcase variant (Juliet: bad/good compile of one
testcase file; DRB: one `-yes`/`-no` micro-benchmark; MBI: one generated
program).

**Confusion counts.** `tp`/`fn` are counted over bad-labeled kernels,
`fp`/`tn` over good-labeled kernels. What makes a finding count ("the tool
detected it") is suite-specific:

- *Juliet*: a finding counts only if its check_id is mapped to the
  testcase's CWE class (type-aware matching, `cwe_map.py`) — unrelated
  findings on a bad kernel do NOT count.
- *DRB*: a race-family finding (`tsan-data-race`, `llov-data-race`,
  `helgrind-race`, `drd-conflicting-access`, `parcoach-*`) on the kernel
  counts; DRB has a single defect category, so this is equivalent to
  category-aware matching.
- *MBI*: any defect-identifying finding of the tool's family counts
  (capability markers like `must-unsupported` never count). This lax view
  is category-BLIND: a tool reporting e.g. a request leak on a kernel
  labeled `callmatching` still counts as tp. See `tp_strict` below.

**Metrics.**
- `recall = tp / (tp + fn)` — share of known-bad kernels the tool flags.
- `fp_rate = fp / (fp + tn)` — alarm rate on known-clean kernels.
- `precision = tp / (tp + fp)` — trustworthiness of a single report.
- `f1` — harmonic mean of precision and recall.
- `tp_strict`, `recall_strict` — ADDITIVE category-aware view: the finding
  must identify the kernel's labeled defect category (mapping justified
  per check_id in `cwe_map.py`). For Juliet and DRB strict == lax by
  construction; the columns differ only on MBI. Both views are reportable:
  lax = "tool raises a defect report on a defective kernel", strict =
  "tool identifies the labeled defect class".

**skipped / errors.** `skipped` = kernel does not compile in this
environment; `errors` = the tool itself failed (timeout, crash, missing
report). Both are excluded from every metric — a tool failure is not a
negative result.

**Overlap table.** Computed over bad-labeled kernels that BOTH tools
processed without error (`common_kernels`), using the lax detection view:
`both` / `only_a` / `only_b` / `neither`, and
`jaccard = both / (both + only_a + only_b)`.
IMPORTANT: overlap is KERNEL-level — "both tools flagged something
class-relevant on the same kernel", NOT "both tools reported the same
defect at the same location". On Juliet (one CWE per kernel) kernel-level
closely approximates bug-level; on DRB a line-level sample shows the tools
report the same code region (same or ±2 lines), so the approximation holds
there too; on MBI tools may report different manifestations of the same
labeled defect.

**Footnotes.**
- Dynamic tools (asan_ubsan, memcheck, tsan*, must) only detect a bug if
  the test execution triggers it; their recall is not directly comparable
  to static tools.
- `clang_sa` and `clang_tidy_ast` are VIRTUAL tools: one clang-tidy run,
  findings partitioned by check_id prefix (`clang-analyzer-*` = symbolic
  execution vs. AST matchers) — redundancy is defined over detection
  methods, and clang-tidy bundles two.
- `tsan_noarcher`, `helgrind`, `drd`, `compiler_fanalyzer`, `infer_bo`,
  `infer_bo_l1l2` are inclusion/exclusion-justification measurements, NOT
  pipeline tools. The last three are VARIANT measurements: the pipeline
  tool plus one extra analysis component (`-fanalyzer`, `--bufferoverrun`),
  measured so the inclusion decision rests on numbers — see the
  "Variant deltas" section.
- `infer_bo_l1l2` is a VIRTUAL variant of `infer_bo` (same run, InferBO
  findings kept only at confidence levels L1/L2).
- `runtime_mean_s` / `runtime_median_s` are per-kernel analysis wall-clock
  seconds over the kernels that entered the metrics (skipped/error rows
  excluded). CAVEAT: tools measured in DIFFERENT run sessions are not
  comparable on this column (machine load, warm caches) — a cross-tool
  cost comparison needs a same-session measurement; see the runtime note
  in the "Variant deltas" section.


## Metrics (per suite and tool)

| suite | tool | tp | fn | fp | tn | recall | fp_rate | precision | f1 | tp_strict | recall_strict | skipped | errors | runtime_mean_s | runtime_median_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| drb | drd | 19 | 77 | 13 | 80 | 0.198 | 0.14 | 0.594 | 0.297 | 19 | 0.198 | 2 | 13 | 3.0 | 1.27 |
| drb | helgrind | 91 | 7 | 83 | 10 | 0.929 | 0.892 | 0.523 | 0.669 | 91 | 0.929 | 2 | 11 | 2.26 | 1.13 |
| drb | llov | 43 | 53 | 6 | 87 | 0.448 | 0.065 | 0.878 | 0.593 | 43 | 0.448 | 9 | 6 | 0.83 | 0.18 |
| drb | parcoach | 0 | 101 | 0 | 96 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 2 | 5 | 0.15 | 0.15 |
| drb | tsan | 80 | 18 | 19 | 73 | 0.816 | 0.207 | 0.808 | 0.812 | 80 | 0.816 | 2 | 12 | 1.24 | 0.94 |
| drb | tsan_noarcher | 88 | 9 | 56 | 35 | 0.907 | 0.615 | 0.611 | 0.73 | 88 | 0.907 | 2 | 14 | 1.13 | 0.78 |
| juliet | asan_ubsan | 244 | 392 | 0 | 591 | 0.384 | 0.0 | 1.0 | 0.555 | 244 | 0.384 | 0 | 73 | 2.15 | 1.96 |
| juliet | clang_sa | 249 | 401 | 54 | 596 | 0.383 | 0.083 | 0.822 | 0.523 | 249 | 0.383 | 0 | 0 | 0.64 | 0.57 |
| juliet | clang_tidy_ast | 0 | 650 | 0 | 650 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 | 0.64 | 0.57 |
| juliet | compiler | 152 | 498 | 11 | 639 | 0.234 | 0.017 | 0.933 | 0.374 | 152 | 0.234 | 0 | 0 | 0.75 | 0.62 |
| juliet | compiler_fanalyzer | 310 | 340 | 21 | 629 | 0.477 | 0.032 | 0.937 | 0.632 | 310 | 0.477 | 0 | 0 | 0.38 | 0.35 |
| juliet | cppcheck | 139 | 511 | 0 | 650 | 0.214 | 0.0 | 1.0 | 0.352 | 139 | 0.214 | 0 | 0 | 0.44 | 0.38 |
| juliet | infer | 62 | 588 | 15 | 635 | 0.095 | 0.023 | 0.805 | 0.171 | 62 | 0.095 | 0 | 0 | 1.17 | 1.02 |
| juliet | infer_bo | 98 | 552 | 73 | 577 | 0.151 | 0.112 | 0.573 | 0.239 | 98 | 0.151 | 0 | 0 | 0.52 | 0.49 |
| juliet | infer_bo_l1l2 | 98 | 552 | 15 | 635 | 0.151 | 0.023 | 0.867 | 0.257 | 98 | 0.151 | 0 | 0 | 0.52 | 0.49 |
| juliet | memcheck | 230 | 406 | 0 | 591 | 0.362 | 0.0 | 1.0 | 0.531 | 230 | 0.362 | 0 | 73 | 2.68 | 2.5 |
| mbi | clang_sa | 317 | 789 | 240 | 525 | 0.287 | 0.314 | 0.569 | 0.381 | 12 | 0.011 | 0 | 0 | 0.23 | 0.21 |
| mbi | clang_tidy_ast | 0 | 1106 | 0 | 765 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 | 0.23 | 0.21 |
| mbi | must | 926 | 180 | 16 | 749 | 0.837 | 0.021 | 0.983 | 0.904 | 923 | 0.835 | 0 | 0 | 43.74 | 2.54 |
| mbi | parcoach | 664 | 442 | 648 | 117 | 0.6 | 0.847 | 0.506 | 0.549 | 636 | 0.575 | 0 | 0 | 0.13 | 0.1 |


## Pairwise overlap (bad kernels processed by both tools)

| suite | tool_a | tool_b | common_kernels | both | only_a | only_b | neither | jaccard |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| drb | drd | helgrind | 96 | 19 | 0 | 70 | 7 | 0.213 |
| drb | drd | llov | 91 | 3 | 16 | 40 | 32 | 0.051 |
| drb | drd | parcoach | 96 | 0 | 19 | 0 | 77 | 0.0 |
| drb | drd | tsan | 96 | 15 | 4 | 64 | 13 | 0.181 |
| drb | drd | tsan_noarcher | 96 | 19 | 0 | 68 | 9 | 0.218 |
| drb | helgrind | llov | 93 | 40 | 46 | 3 | 4 | 0.449 |
| drb | helgrind | parcoach | 98 | 0 | 91 | 0 | 7 | 0.0 |
| drb | helgrind | tsan | 97 | 79 | 11 | 1 | 6 | 0.868 |
| drb | helgrind | tsan_noarcher | 97 | 87 | 3 | 1 | 6 | 0.956 |
| drb | llov | parcoach | 96 | 0 | 43 | 0 | 53 | 0.0 |
| drb | llov | tsan | 93 | 38 | 5 | 38 | 12 | 0.469 |
| drb | llov | tsan_noarcher | 92 | 39 | 4 | 44 | 5 | 0.448 |
| drb | parcoach | tsan | 98 | 0 | 0 | 80 | 18 | 0.0 |
| drb | parcoach | tsan_noarcher | 97 | 0 | 0 | 88 | 9 | 0.0 |
| drb | tsan | tsan_noarcher | 97 | 78 | 2 | 10 | 7 | 0.867 |
| juliet | asan_ubsan | clang_sa | 636 | 127 | 117 | 122 | 270 | 0.347 |
| juliet | asan_ubsan | clang_tidy_ast | 636 | 0 | 244 | 0 | 392 | 0.0 |
| juliet | asan_ubsan | compiler | 636 | 104 | 140 | 48 | 344 | 0.356 |
| juliet | asan_ubsan | compiler_fanalyzer | 636 | 209 | 35 | 99 | 293 | 0.609 |
| juliet | asan_ubsan | cppcheck | 636 | 75 | 169 | 64 | 328 | 0.244 |
| juliet | asan_ubsan | infer | 636 | 25 | 219 | 37 | 355 | 0.089 |
| juliet | asan_ubsan | infer_bo | 636 | 60 | 184 | 38 | 354 | 0.213 |
| juliet | asan_ubsan | infer_bo_l1l2 | 636 | 60 | 184 | 38 | 354 | 0.213 |
| juliet | asan_ubsan | memcheck | 636 | 167 | 77 | 63 | 329 | 0.544 |
| juliet | clang_sa | clang_tidy_ast | 650 | 0 | 249 | 0 | 401 | 0.0 |
| juliet | clang_sa | compiler | 650 | 129 | 120 | 23 | 378 | 0.474 |
| juliet | clang_sa | compiler_fanalyzer | 650 | 222 | 27 | 88 | 313 | 0.659 |
| juliet | clang_sa | cppcheck | 650 | 119 | 130 | 20 | 381 | 0.442 |
| juliet | clang_sa | infer | 650 | 62 | 187 | 0 | 401 | 0.249 |
| juliet | clang_sa | infer_bo | 650 | 62 | 187 | 36 | 365 | 0.218 |
| juliet | clang_sa | infer_bo_l1l2 | 650 | 62 | 187 | 36 | 365 | 0.218 |
| juliet | clang_sa | memcheck | 636 | 163 | 86 | 67 | 320 | 0.516 |
| juliet | clang_tidy_ast | compiler | 650 | 0 | 0 | 152 | 498 | 0.0 |
| juliet | clang_tidy_ast | compiler_fanalyzer | 650 | 0 | 0 | 310 | 340 | 0.0 |
| juliet | clang_tidy_ast | cppcheck | 650 | 0 | 0 | 139 | 511 | 0.0 |
| juliet | clang_tidy_ast | infer | 650 | 0 | 0 | 62 | 588 | 0.0 |
| juliet | clang_tidy_ast | infer_bo | 650 | 0 | 0 | 98 | 552 | 0.0 |
| juliet | clang_tidy_ast | infer_bo_l1l2 | 650 | 0 | 0 | 98 | 552 | 0.0 |
| juliet | clang_tidy_ast | memcheck | 636 | 0 | 0 | 230 | 406 | 0.0 |
| juliet | compiler | compiler_fanalyzer | 650 | 152 | 0 | 158 | 340 | 0.49 |
| juliet | compiler | cppcheck | 650 | 65 | 87 | 74 | 424 | 0.288 |
| juliet | compiler | infer | 650 | 17 | 135 | 45 | 453 | 0.086 |
| juliet | compiler | infer_bo | 650 | 17 | 135 | 81 | 417 | 0.073 |
| juliet | compiler | infer_bo_l1l2 | 650 | 17 | 135 | 81 | 417 | 0.073 |
| juliet | compiler | memcheck | 636 | 116 | 36 | 114 | 370 | 0.436 |
| juliet | compiler_fanalyzer | cppcheck | 650 | 109 | 201 | 30 | 310 | 0.321 |
| juliet | compiler_fanalyzer | infer | 650 | 43 | 267 | 19 | 321 | 0.131 |
| juliet | compiler_fanalyzer | infer_bo | 650 | 43 | 267 | 55 | 285 | 0.118 |
| juliet | compiler_fanalyzer | infer_bo_l1l2 | 650 | 43 | 267 | 55 | 285 | 0.118 |
| juliet | compiler_fanalyzer | memcheck | 636 | 188 | 120 | 42 | 286 | 0.537 |
| juliet | cppcheck | infer | 650 | 52 | 87 | 10 | 501 | 0.349 |
| juliet | cppcheck | infer_bo | 650 | 52 | 87 | 46 | 465 | 0.281 |
| juliet | cppcheck | infer_bo_l1l2 | 650 | 52 | 87 | 46 | 465 | 0.281 |
| juliet | cppcheck | memcheck | 636 | 46 | 93 | 184 | 313 | 0.142 |
| juliet | infer | infer_bo | 650 | 62 | 0 | 36 | 552 | 0.633 |
| juliet | infer | infer_bo_l1l2 | 650 | 62 | 0 | 36 | 552 | 0.633 |
| juliet | infer | memcheck | 636 | 2 | 60 | 228 | 346 | 0.007 |
| juliet | infer_bo | infer_bo_l1l2 | 650 | 98 | 0 | 0 | 552 | 1.0 |
| juliet | infer_bo | memcheck | 636 | 36 | 62 | 194 | 344 | 0.123 |
| juliet | infer_bo_l1l2 | memcheck | 636 | 36 | 62 | 194 | 344 | 0.123 |
| mbi | clang_sa | clang_tidy_ast | 1106 | 0 | 317 | 0 | 789 | 0.0 |
| mbi | clang_sa | must | 1106 | 291 | 26 | 635 | 154 | 0.306 |
| mbi | clang_sa | parcoach | 1106 | 215 | 102 | 449 | 340 | 0.281 |
| mbi | clang_tidy_ast | must | 1106 | 0 | 0 | 926 | 180 | 0.0 |
| mbi | clang_tidy_ast | parcoach | 1106 | 0 | 0 | 664 | 442 | 0.0 |
| mbi | must | parcoach | 1106 | 606 | 320 | 58 | 122 | 0.616 |


## Variant deltas (justification measurements)

Each row compares a base tool with the same tool plus one extra analysis component. `only_variant` — bad kernels that ONLY the extended variant detects, over kernels both processed — is the decisive number: it is the variant's unique contribution, independent of metric arithmetic.

**Do not read `runtime_factor` as the cost of the extra analysis.** Base and variant were measured in separate run sessions, so the column mixes in machine load and cache state (it can even come out below 1). A same-session back-to-back measurement over 60 Juliet kernels (2026-07-21) gives the real per-kernel surcharge: compiler 0.29s -> compiler_fanalyzer 0.30s (1.03x), infer 0.43s -> infer_bo 0.47s (1.09x). On these small single-file kernels both extra analyses are nearly free; that does not extrapolate to large translation units.

| suite | base | variant | recall_base | recall_variant | d_recall | precision_base | precision_variant | d_precision | fp_rate_base | fp_rate_variant | d_fp_rate | runtime_mean_base_s | runtime_mean_variant_s | runtime_factor | common_bad_kernels | only_variant | only_base |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| juliet | compiler | compiler_fanalyzer | 0.234 | 0.477 | 0.243 | 0.933 | 0.937 | 0.004 | 0.017 | 0.032 | 0.015 | 0.75 | 0.38 | 0.5 | 650 | 158 | 0 |
| juliet | infer | infer_bo | 0.095 | 0.151 | 0.056 | 0.805 | 0.573 | -0.232 | 0.023 | 0.112 | 0.089 | 1.17 | 0.52 | 0.4 | 650 | 36 | 0 |
| juliet | infer | infer_bo_l1l2 | 0.095 | 0.151 | 0.056 | 0.805 | 0.867 | 0.062 | 0.023 | 0.023 | 0.0 | 1.17 | 0.52 | 0.4 | 650 | 36 | 0 |
| drb | tsan | tsan_noarcher | 0.816 | 0.907 | 0.091 | 0.808 | 0.611 | -0.197 | 0.207 | 0.615 | 0.408 | 1.24 | 1.13 | 0.9 | 97 | 10 | 2 |


### InferBO confidence levels

InferBO encodes its certainty in the bug_type suffix (`BUFFER_OVERRUN_L1` .. `_L5`, L1 = most reliable). Per level: on how many bad / good kernels it produces a class-relevant finding. `infer_bo_l1l2` in the tables above is the virtual variant restricted to L1/L2 (same run, findings filtered).

| level | bad_kernels_flagged | good_kernels_flagged | precision_of_level |
| --- | --- | --- | --- |
| L1 | 36 | 0 | 1.0 |
| L3 | 0 | 58 | 0.0 |


## Metrics by kernel language (additive view)

Juliet ships C and C++ testcases. GCC documents `-fanalyzer` as targeting C, so the C/C++ split is the empirical answer to how viable it is on C++ — the open question behind its exclusion. Reported for every tool as a comparison baseline.

| suite | tool | tp | fn | fp | tn | recall | fp_rate | precision | f1 | tp_strict | recall_strict | skipped | errors | runtime_mean_s | runtime_median_s | language |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| drb | drd | 19 | 77 | 13 | 80 | 0.198 | 0.14 | 0.594 | 0.297 | 19 | 0.198 | 2 | 13 | 3.0 | 1.27 | c |
| drb | helgrind | 91 | 7 | 83 | 10 | 0.929 | 0.892 | 0.523 | 0.669 | 91 | 0.929 | 2 | 11 | 2.26 | 1.13 | c |
| drb | llov | 43 | 53 | 6 | 87 | 0.448 | 0.065 | 0.878 | 0.593 | 43 | 0.448 | 9 | 6 | 0.83 | 0.18 | c |
| drb | parcoach | 0 | 101 | 0 | 96 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 2 | 5 | 0.15 | 0.15 | c |
| drb | tsan | 80 | 18 | 19 | 73 | 0.816 | 0.207 | 0.808 | 0.812 | 80 | 0.816 | 2 | 12 | 1.24 | 0.94 | c |
| drb | tsan_noarcher | 88 | 9 | 56 | 35 | 0.907 | 0.615 | 0.611 | 0.73 | 88 | 0.907 | 2 | 14 | 1.13 | 0.78 | c |
| juliet | asan_ubsan | 179 | 358 | 0 | 492 | 0.333 | 0.0 | 1.0 | 0.5 | 179 | 0.333 | 0 | 73 | 1.96 | 1.72 | c |
| juliet | clang_sa | 185 | 366 | 50 | 501 | 0.336 | 0.091 | 0.787 | 0.471 | 185 | 0.336 | 0 | 0 | 0.6 | 0.54 | c |
| juliet | clang_tidy_ast | 0 | 551 | 0 | 551 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 | 0.6 | 0.54 | c |
| juliet | compiler | 97 | 454 | 11 | 540 | 0.176 | 0.02 | 0.898 | 0.294 | 97 | 0.176 | 0 | 0 | 0.68 | 0.58 | c |
| juliet | compiler_fanalyzer | 239 | 312 | 21 | 530 | 0.434 | 0.038 | 0.919 | 0.589 | 239 | 0.434 | 0 | 0 | 0.36 | 0.33 | c |
| juliet | cppcheck | 111 | 440 | 0 | 551 | 0.201 | 0.0 | 1.0 | 0.335 | 111 | 0.201 | 0 | 0 | 0.43 | 0.35 | c |
| juliet | infer | 56 | 495 | 15 | 536 | 0.102 | 0.027 | 0.789 | 0.18 | 56 | 0.102 | 0 | 0 | 1.11 | 0.93 | c |
| juliet | infer_bo | 92 | 459 | 73 | 478 | 0.167 | 0.132 | 0.558 | 0.257 | 92 | 0.167 | 0 | 0 | 0.51 | 0.47 | c |
| juliet | infer_bo_l1l2 | 92 | 459 | 15 | 536 | 0.167 | 0.027 | 0.86 | 0.28 | 92 | 0.167 | 0 | 0 | 0.51 | 0.47 | c |
| juliet | memcheck | 173 | 364 | 0 | 492 | 0.322 | 0.0 | 1.0 | 0.487 | 173 | 0.322 | 0 | 73 | 2.55 | 2.42 | c |
| mbi | clang_sa | 317 | 789 | 240 | 525 | 0.287 | 0.314 | 0.569 | 0.381 | 12 | 0.011 | 0 | 0 | 0.23 | 0.21 | c |
| mbi | clang_tidy_ast | 0 | 1106 | 0 | 765 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 | 0.23 | 0.21 | c |
| mbi | must | 926 | 180 | 16 | 749 | 0.837 | 0.021 | 0.983 | 0.904 | 923 | 0.835 | 0 | 0 | 43.74 | 2.54 | c |
| mbi | parcoach | 664 | 442 | 648 | 117 | 0.6 | 0.847 | 0.506 | 0.549 | 636 | 0.575 | 0 | 0 | 0.13 | 0.1 | c |
| juliet | asan_ubsan | 65 | 34 | 0 | 99 | 0.657 | 0.0 | 1.0 | 0.793 | 65 | 0.657 | 0 | 0 | 3.1 | 3.1 | cpp |
| juliet | clang_sa | 64 | 35 | 4 | 95 | 0.646 | 0.04 | 0.941 | 0.766 | 64 | 0.646 | 0 | 0 | 0.87 | 0.76 | cpp |
| juliet | clang_tidy_ast | 0 | 99 | 0 | 99 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 | 0.87 | 0.76 | cpp |
| juliet | compiler | 55 | 44 | 0 | 99 | 0.556 | 0.0 | 1.0 | 0.714 | 55 | 0.556 | 0 | 0 | 1.13 | 0.97 | cpp |
| juliet | compiler_fanalyzer | 71 | 28 | 0 | 99 | 0.717 | 0.0 | 1.0 | 0.835 | 71 | 0.717 | 0 | 0 | 0.48 | 0.45 | cpp |
| juliet | cppcheck | 28 | 71 | 0 | 99 | 0.283 | 0.0 | 1.0 | 0.441 | 28 | 0.283 | 0 | 0 | 0.5 | 0.49 | cpp |
| juliet | infer | 6 | 93 | 0 | 99 | 0.061 | 0.0 | 1.0 | 0.114 | 6 | 0.061 | 0 | 0 | 1.51 | 1.41 | cpp |
| juliet | infer_bo | 6 | 93 | 0 | 99 | 0.061 | 0.0 | 1.0 | 0.114 | 6 | 0.061 | 0 | 0 | 0.61 | 0.55 | cpp |
| juliet | infer_bo_l1l2 | 6 | 93 | 0 | 99 | 0.061 | 0.0 | 1.0 | 0.114 | 6 | 0.061 | 0 | 0 | 0.61 | 0.55 | cpp |
| juliet | memcheck | 57 | 42 | 0 | 99 | 0.576 | 0.0 | 1.0 | 0.731 | 57 | 0.576 | 0 | 0 | 3.32 | 2.56 | cpp |


_See the Definitions section above for metric semantics, the kernel-level overlap caveat, and the dynamic-tool / virtual-tool footnotes. Measurement methodology: docs/measurement-definitions.md._
