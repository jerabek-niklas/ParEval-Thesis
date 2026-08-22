# Benchmark worked-example vs. oracle consistency — all 60 benchmarks

- **Question answered:** for every benchmark, is the worked example shown to the models consistent with the oracle that grades them? (Phase 0, Task 1 — the bug class behind pilot_001's stencil result.)
- **Result: 6 of 60 benchmarks are inconsistent** — `50_stencil_xor_kernel` (the known calibration case) plus **five newly found**: `06_fft_dft`, `07_fft_fft_conjugate`, `09_fft_fft_out_of_place`, `41_sort_k-th_smallest_element`, `42_sort_sorted_ranks`. All six are proven by executing the committed oracle on the prompt's own example input, not by reading. All 60 prompts carry a worked example (none is example-free); 54 of 60 reproduce exactly under execution.
- **None of the five new cases is in the pilot's 12-benchmark subset** — pilot_001's numbers are unaffected — but all five would have entered the full 60-benchmark run. Three of five sit in `fft`, two in `sort`.
- **Date:** 2026-08-22.

## Method

- **Stage A — triage (60 independent reads).** For each benchmark: all three prompt entries (serial/omp/mpi), `baseline.hpp`, and `cpu.cc::validate()` were read side by side, and the oracle was hand-simulated step by step on the example input. Verdicts: 53 consistent, 7 suspect, 0 no-worked-example, 0 cannot-tell. Calibration: the known-broken `50_stencil_xor_kernel` was flagged with exactly the known 7/16 disagreeing cells.
- **Stage B — execution (all 60, not just suspects).** For every benchmark a minimal fixture was built: the example input transcribed into a small `main()` that calls the baseline (`correct*`) directly, compiled with `g++ -std=c++17 -O2 -I <benchmark_dir> -I drivers/cpp` inside the `pareval-thesis` container, its output compared against the prompt's example output. Each fixture mirrors the comparison semantics of that benchmark's own `validate()` (element order, canonicalisation such as hull-rotation or sorting, float tolerance), so benign ordering/rounding differences are not reported as inconsistencies.
- **Stage C — control sample: superseded by full coverage.** The brief asked for ~8 executed controls from the Stage-A-consistent set to estimate Stage A's false-negative rate. Instead, *every* benchmark was executed. Measured on all 53 Stage-A-consistent benchmarks: **0 execution-detected inconsistencies — false-negative rate 0/53**. Stage A's one over-flag: `43_sort_sort_an_array_of_structs_by_key` (suspect for tie-order ambiguity) executes consistent on the example itself; the tie hazard remains a note, not an inconsistency.
- **Deviation from the brief (and why):** the brief suggested reusing the `thesis/enhanced_tests/` machinery to run the baselines. That machinery drives *pattern-based* fills (`ENHANCED_FILL_*`) and cannot feed an arbitrary explicit example — explicit values exist only for benchmarks with fill sites and never for struct/complex/COO-typed inputs. Direct per-benchmark fixtures against `baseline.hpp` are the only mechanism that works for all 60; the enhanced compile/run conventions were reused where they apply (include layout, container, comparison-epsilon choices).

## Re-running the check

The check is committed and re-runnable; it exits 0 = all fixtured benchmarks consistent, 1 = at least one inconsistency, 2 = infrastructure failure:

```bash
docker run --rm -u 0 -v "<host_repo>:/workspace:ro" -w /workspace pareval-thesis python3 thesis/evaluation/check_prompt_oracle_consistency.py
```

Fixtures live in `thesis/evaluation/prompt_oracle_fixtures.json` (per benchmark: the harness source, the expected output as JSON, the leaf tolerances, the example quoted verbatim from the prompt, and the canonicalisation note). After any prompt or oracle fix, re-run; the affected row must flip to `consistent`. The current committed state reproduces: **54 consistent, 6 INCONSISTENT, exit 1**.

## The six inconsistencies — executed evidence

Every case below: oracle = the committed `baseline.hpp` function, executed on the example input exactly as printed in the prompt; grading epsilon = the benchmark's own `validate()` epsilon.

### 06_fft_dft — example uses the opposite DFT sign convention
Oracle output at k=1: `-8+12i`; prompt says `-8-12i`. At k=3: oracle `-8-12i`, prompt `-8+12i` (imaginary parts differ by 24; k=0/k=2 agree). The prompt's example is the elementwise conjugate of the oracle's output — the example encodes the positive-exponent convention `sum x[n]*e^{+2πink/N}` while `correctDft()` implements the negative-exponent convention. A model faithfully implementing the example's convention is graded wrong on every input with a nonzero imaginary spectrum. The wrong example also appears verbatim in the driver header comment. Grading epsilon 1e-4; the disagreement is 2.4e5× larger.

### 07_fft_fft_conjugate — example's re/im values are transposed at every odd index
4 of 8 cells disagree: idx 1 oracle `[2.41421, -1]` vs prompt `[1, -2.41421]`; idx 3 oracle `[-0.41421, 1]` vs prompt `[1, -0.41421]`; idx 5, 7 analogous. The prompt's values look like the components were swapped/reordered relative to any correct FFT of the example input; differences are O(1) — ~1000× the 1e-3 grading epsilon. Even index cells agree.

### 09_fft_fft_out_of_place — single-value typo in the example
One cell: prompt prints `{1, -2.42421}` where the oracle (and mathematics: `-(1+√2)`) gives `-2.41421356…`. |diff| ≈ 1.0e-2 = 100× the 1e-4 grading epsilon. The printed example additionally violates conjugate symmetry (X[7] should equal conj(X[1])), confirming the typo is in the example, not the oracle. Least severe of the six — a model computing a correct FFT still matches 7 of 8 cells, and validate() compares driver-generated inputs, not the example — but any model that hard-learns the example value is being taught a wrong number, and the example contradicts the oracle it is graded by.

### 41_sort_k-th_smallest_element — example output matches no reading of the oracle's semantics
Oracle: `correctFindKthSmallest([1,7,6,0,2,2,10,6], k=4)` returns **2** (1-indexed over the sorted array with duplicates: sorted = [0,1,2,2,6,6,7,10], element k−1 = 2). Prompt says **6** — which equals sorted[4] under 0-indexed k, or the 4th *distinct* smallest under distinct-value semantics; it matches the oracle under neither. Every model must guess among ≥3 semantics, and the only worked disambiguation teaches one the oracle rejects. The same contradictory example sits as a comment in `baseline.hpp` directly above the code that violates it.

### 42_sort_sorted_ranks — second example's output is unreachable under any tie ordering
Example 1 reproduces exactly. Example 2 (`[100, 7.6, 16.1, 18, 7.6]`, tied values): oracle produces `[4,0,2,3,1]` (libstdc++ `std::sort` keeps tied indices in encounter order at n=5); prompt says `[4,0,1,2,3]`. Decisive: the prompt's output is not merely a different tie-break — inverting it implies the sorted order `[7.6, 16.1, 18, 7.6, 100]`, which is not ascending, so **no** tie ordering can produce it. The example output is wrong for the stated input. `validate()` grades with exact equality on rank vectors, so on tied inputs a model can only pass by replicating libstdc++'s incidental stability behaviour — which the (wrong) example cannot teach.

### 50_stencil_xor_kernel — the known calibration case, reproduced
Full-grid execution: oracle (4-neighbour von Neumann) vs prompt example (8-neighbour Moore) disagree on 7/16 cells — exactly the pilot_001 finding. Within `validate()`'s interior-only comparison scope, 3/4 compared cells disagree. The check's canonical fixture uses the interior scope (mirroring the grader); the full-grid result is recorded as supplementary evidence.

## Consequences for the fix list and the re-pilot

1. **The fix list grows by five prompt/oracle alignments** (06, 07, 09, 41, 42) beyond the already-decided 50/45/46/49 fixes. In four of the five the *example* is the defective side (07 transposed values, 09 typo, 41 mismatched semantics, 42 arithmetically impossible output) — prompt-side fixes that do not touch grading and do not invalidate upstream comparability. 06 is a genuine convention conflict where either side could be aligned; that decision is not Phase 0's to make.
2. **The pilot's 12 benchmarks need no re-cut**: 05, and the other 10 non-stencil/sparse benchmarks, execute consistent; the pilot subset contained exactly the 2 defects already known.
3. **The full run must not start before the five fixes land**, or it would grade 6/60 benchmarks (10%) against oracles that contradict their own prompts — the stencil scenario, five more times.
4. **This check is now a pre-run gate**: exit code 1 blocks; after prompt/oracle fixes, the affected fixture's `expected_json` must be updated to the corrected example and the check re-run to `consistent` (the fixture then locks the fix in place).

## The 60-row table

Stage A = hand-simulation verdict; Executed = machine verdict of the committed check (2026-08-22 run).

| # | benchmark | worked example | Stage A | executed | note |
|---|---|---|---|---|---|
| 00 | `00_dense_la_lu_decomp` | yes | consistent | consistent |  |
| 01 | `01_dense_la_solve` | yes | consistent | consistent |  |
| 02 | `02_dense_la_gemm` | yes | consistent | consistent |  |
| 03 | `03_dense_la_axpy` | yes | consistent | consistent |  |
| 04 | `04_dense_la_gemv` | yes | consistent | consistent |  |
| 05 | `05_fft_inverse_fft` | yes | consistent | consistent |  |
| 06 | `06_fft_dft` | yes | suspect | **INCONSISTENT** | imag sign flipped at k=1,3 (conjugate/DFT-convention conflict) |
| 07 | `07_fft_fft_conjugate` | yes | suspect | **INCONSISTENT** | 4/8 cells: example re/im values transposed at odd indices |
| 08 | `08_fft_split_fft` | yes | consistent | consistent |  |
| 09 | `09_fft_fft_out_of_place` | yes | suspect | **INCONSISTENT** | one-cell example typo: -2.42421 vs -(1+sqrt(2)) = -2.41421 |
| 10 | `10_geometry_convex_hull` | yes | consistent | consistent | consistent up to cyclic rotation, which validate() canonicalises |
| 11 | `11_geometry_convex_hull_perimeter` | yes | consistent | consistent |  |
| 12 | `12_geometry_smallest_triangle` | yes | consistent | consistent |  |
| 13 | `13_geometry_closest_pair_2d` | yes | consistent | consistent |  |
| 14 | `14_geometry_closest_pair_1d` | yes | consistent | consistent |  |
| 15 | `15_graph_edge_count` | yes | consistent | consistent |  |
| 16 | `16_graph_largest_component` | yes | consistent | consistent |  |
| 17 | `17_graph_highest_degree` | yes | consistent | consistent |  |
| 18 | `18_graph_count_components` | yes | consistent | consistent |  |
| 19 | `19_graph_shortest_path` | yes | consistent | consistent |  |
| 20 | `20_histogram_pixel_histogram` | yes | consistent | consistent |  |
| 21 | `21_histogram_bin_0-100` | yes | consistent | consistent |  |
| 22 | `22_histogram_count_quadrants` | yes | consistent | consistent |  |
| 23 | `23_histogram_first_letter_counts` | yes | consistent | consistent |  |
| 24 | `24_histogram_count_quartile` | yes | consistent | consistent |  |
| 25 | `25_reduce_xor` | yes | consistent | consistent |  |
| 26 | `26_reduce_product_of_inverses` | yes | consistent | consistent |  |
| 27 | `27_reduce_average` | yes | consistent | consistent |  |
| 28 | `28_reduce_smallest_odd_number` | yes | consistent | consistent |  |
| 29 | `29_reduce_sum_of_min_of_pairs` | yes | consistent | consistent |  |
| 30 | `30_scan_prefix_sum` | yes | consistent | consistent |  |
| 31 | `31_scan_scan_with_min_function` | yes | consistent | consistent |  |
| 32 | `32_scan_sum_of_prefix_sum_array` | yes | consistent | consistent |  |
| 33 | `33_scan_reverse_prefix_sum` | yes | consistent | consistent |  |
| 34 | `34_scan_largest_contiguous_subarray_sum` | yes | consistent | consistent |  |
| 35 | `35_search_search_for_last_struct_by_key` | yes | consistent | consistent |  |
| 36 | `36_search_check_if_array_contains_value` | yes | consistent | consistent |  |
| 37 | `37_search_find_the_closest_number_to_pi` | yes | consistent | consistent |  |
| 38 | `38_search_find_the_first_even_number` | yes | consistent | consistent |  |
| 39 | `39_search_xor_contains` | yes | consistent | consistent |  |
| 40 | `40_sort_sort_an_array_of_complex_numbers_by_magnitude` | yes | consistent | consistent |  |
| 41 | `41_sort_k-th_smallest_element` | yes | suspect | **INCONSISTENT** | oracle 2 vs example 6; example matches no reading of the oracle semantics |
| 42 | `42_sort_sorted_ranks` | yes | suspect | **INCONSISTENT** | example 2 output unreachable under any tie ordering |
| 43 | `43_sort_sort_an_array_of_structs_by_key` | yes | suspect | consistent | Stage A suspect (tie-order ambiguity) -> executes consistent; hazard noted |
| 44 | `44_sort_sort_non-zero_elements` | yes | consistent | consistent |  |
| 45 | `45_sparse_la_sparse_solve` | yes | consistent | consistent |  |
| 46 | `46_sparse_la_spmm` | yes | consistent | consistent |  |
| 47 | `47_sparse_la_spmv` | yes | consistent | consistent |  |
| 48 | `48_sparse_la_sparse_axpy` | yes | consistent | consistent |  |
| 49 | `49_sparse_la_sparse_lu_decomp` | yes | consistent | consistent |  |
| 50 | `50_stencil_xor_kernel` | yes | suspect | **INCONSISTENT** | 7/16 cells (4- vs 8-neighbour); known calibration case |
| 51 | `51_stencil_edge_kernel` | yes | consistent | consistent |  |
| 52 | `52_stencil_1d_jacobi_3-point_stencil` | yes | consistent | consistent |  |
| 53 | `53_stencil_2d_jacobi_5-point_stencil` | yes | consistent | consistent |  |
| 54 | `54_stencil_game_of_life` | yes | consistent | consistent |  |
| 55 | `55_transform_relu` | yes | consistent | consistent |  |
| 56 | `56_transform_negate_odds` | yes | consistent | consistent |  |
| 57 | `57_transform_inverse_offset` | yes | consistent | consistent |  |
| 58 | `58_transform_squaring` | yes | consistent | consistent |  |
| 59 | `59_transform_map_function` | yes | consistent | consistent |  |


## Notable secondary observations (verdict-neutral, feed the fix list)

Collected across the 60 triage reads; the pilot-relevant ones are quantified in `thesis/docs/pilot-001-corrected-numbers.md`:

- **NaN-blind comparator interactions** (`utilities.hpp` predicate) recur wherever an oracle can produce NaN: unpivoted LU/solve on zero pivots (00, 01, 45, 49), divergent iteratives, fft overflow specs. Known decided fix; the triage confirms the breadth.
- **Degenerate-size hazards**: unsigned `TEST_SIZE-1` underflow / interior-only comparison scopes in the stencil family (50-54) and empty-input crash/hang oracles (35, 50) - already visible in pilot gating.
- **fft oracle domain limit**: the radix-2 `fftCooleyTookey` baselines are only valid for power-of-two N; non-power-of-two enhanced sizes make the oracle wrong silently (N=3) or corrupt memory (N=5/7). New defect class, quantified in the corrected-numbers document (Task 2, probe 5).
- **Tie-ordering underspecification** in sort benchmarks (42, 43): exact-equality rank/struct grading makes libstdc++'s incidental stability part of the spec; only 42's example is *wrong*, but 43 passes on luck of tie-free examples.

## Provenance

- Stage A: 60 independent triage analyses (hand-simulation with quoted oracle lines per benchmark); Stage B: 60 execution fixtures, each compiled and run in `pareval-thesis` (GCC 13.3) with the repo mounted read-only; final verification: one complete run of the committed check reproducing 54/6/0. Per-benchmark analyses and fixture build logs are preserved as session audit artifacts outside the repo.
- Committed artifacts: `thesis/evaluation/check_prompt_oracle_consistency.py` (runner), `thesis/evaluation/prompt_oracle_fixtures.json` (60 fixtures). Companion: `thesis/docs/pilot-001-corrected-numbers.md` (Phase 0 Tasks 2-5).
