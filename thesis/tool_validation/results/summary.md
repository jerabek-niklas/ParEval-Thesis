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
- `tsan_noarcher`, `helgrind`, `drd` are inclusion/exclusion-justification
  measurements, not pipeline tools.


## Metrics (per suite and tool)

| suite | tool | tp | fn | fp | tn | recall | fp_rate | precision | f1 | tp_strict | recall_strict | skipped | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| drb | drd | 19 | 77 | 13 | 80 | 0.198 | 0.14 | 0.594 | 0.297 | 19 | 0.198 | 2 | 13 |
| drb | helgrind | 91 | 7 | 83 | 10 | 0.929 | 0.892 | 0.523 | 0.669 | 91 | 0.929 | 2 | 11 |
| drb | llov | 43 | 53 | 6 | 87 | 0.448 | 0.065 | 0.878 | 0.593 | 43 | 0.448 | 9 | 6 |
| drb | parcoach | 0 | 101 | 0 | 96 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 2 | 5 |
| drb | tsan | 80 | 18 | 19 | 73 | 0.816 | 0.207 | 0.808 | 0.812 | 80 | 0.816 | 2 | 12 |
| drb | tsan_noarcher | 88 | 9 | 56 | 35 | 0.907 | 0.615 | 0.611 | 0.73 | 88 | 0.907 | 2 | 14 |
| juliet | asan_ubsan | 244 | 392 | 0 | 591 | 0.384 | 0.0 | 1.0 | 0.555 | 244 | 0.384 | 0 | 73 |
| juliet | clang_sa | 249 | 401 | 54 | 596 | 0.383 | 0.083 | 0.822 | 0.523 | 249 | 0.383 | 0 | 0 |
| juliet | clang_tidy_ast | 0 | 650 | 0 | 650 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 |
| juliet | compiler | 152 | 498 | 11 | 639 | 0.234 | 0.017 | 0.933 | 0.374 | 152 | 0.234 | 0 | 0 |
| juliet | cppcheck | 139 | 511 | 0 | 650 | 0.214 | 0.0 | 1.0 | 0.352 | 139 | 0.214 | 0 | 0 |
| juliet | infer | 62 | 588 | 15 | 635 | 0.095 | 0.023 | 0.805 | 0.171 | 62 | 0.095 | 0 | 0 |
| juliet | memcheck | 230 | 406 | 0 | 591 | 0.362 | 0.0 | 1.0 | 0.531 | 230 | 0.362 | 0 | 73 |
| mbi | clang_sa | 317 | 789 | 240 | 525 | 0.287 | 0.314 | 0.569 | 0.381 | 12 | 0.011 | 0 | 0 |
| mbi | clang_tidy_ast | 0 | 1106 | 0 | 765 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0 |
| mbi | must | 926 | 180 | 16 | 749 | 0.837 | 0.021 | 0.983 | 0.904 | 923 | 0.835 | 0 | 0 |
| mbi | parcoach | 664 | 442 | 648 | 117 | 0.6 | 0.847 | 0.506 | 0.549 | 636 | 0.575 | 0 | 0 |


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
| juliet | asan_ubsan | cppcheck | 636 | 75 | 169 | 64 | 328 | 0.244 |
| juliet | asan_ubsan | infer | 636 | 25 | 219 | 37 | 355 | 0.089 |
| juliet | asan_ubsan | memcheck | 636 | 167 | 77 | 63 | 329 | 0.544 |
| juliet | clang_sa | clang_tidy_ast | 650 | 0 | 249 | 0 | 401 | 0.0 |
| juliet | clang_sa | compiler | 650 | 129 | 120 | 23 | 378 | 0.474 |
| juliet | clang_sa | cppcheck | 650 | 119 | 130 | 20 | 381 | 0.442 |
| juliet | clang_sa | infer | 650 | 62 | 187 | 0 | 401 | 0.249 |
| juliet | clang_sa | memcheck | 636 | 163 | 86 | 67 | 320 | 0.516 |
| juliet | clang_tidy_ast | compiler | 650 | 0 | 0 | 152 | 498 | 0.0 |
| juliet | clang_tidy_ast | cppcheck | 650 | 0 | 0 | 139 | 511 | 0.0 |
| juliet | clang_tidy_ast | infer | 650 | 0 | 0 | 62 | 588 | 0.0 |
| juliet | clang_tidy_ast | memcheck | 636 | 0 | 0 | 230 | 406 | 0.0 |
| juliet | compiler | cppcheck | 650 | 65 | 87 | 74 | 424 | 0.288 |
| juliet | compiler | infer | 650 | 17 | 135 | 45 | 453 | 0.086 |
| juliet | compiler | memcheck | 636 | 116 | 36 | 114 | 370 | 0.436 |
| juliet | cppcheck | infer | 650 | 52 | 87 | 10 | 501 | 0.349 |
| juliet | cppcheck | memcheck | 636 | 46 | 93 | 184 | 313 | 0.142 |
| juliet | infer | memcheck | 636 | 2 | 60 | 228 | 346 | 0.007 |
| mbi | clang_sa | clang_tidy_ast | 1106 | 0 | 317 | 0 | 789 | 0.0 |
| mbi | clang_sa | must | 1106 | 291 | 26 | 635 | 154 | 0.306 |
| mbi | clang_sa | parcoach | 1106 | 215 | 102 | 449 | 340 | 0.281 |
| mbi | clang_tidy_ast | must | 1106 | 0 | 0 | 926 | 180 | 0.0 |
| mbi | clang_tidy_ast | parcoach | 1106 | 0 | 0 | 664 | 442 | 0.0 |
| mbi | must | parcoach | 1106 | 606 | 320 | 58 | 122 | 0.616 |


_See the Definitions section above for metric semantics, the kernel-level overlap caveat, and the dynamic-tool / virtual-tool footnotes. Measurement methodology: docs/measurement-definitions.md._
